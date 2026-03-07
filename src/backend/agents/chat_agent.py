import sys
import re
import uuid
import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, Annotated, Callable, Literal, List, TypedDict

if TYPE_CHECKING:
    from ..conversation_store import ConversationStore
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

try:
    from ..schemas import Message
    from .utils import extract_text_from_content
    from .context import trim_to_fit
    from .llm_retry import invoke_with_timeout, ainvoke_with_timeout, astream_with_timeout, LLM_RETRY_POLICY
    from ..providers.base import get_model_name
except ImportError:
    from schemas import Message
    from utils import extract_text_from_content
    from context import trim_to_fit
    from llm_retry import invoke_with_timeout, ainvoke_with_timeout, astream_with_timeout, LLM_RETRY_POLICY
    from providers.base import get_model_name

def _needs_strict(model) -> bool:
    """OpenAI requires strict=True for tool schemas; other providers don't."""
    from langchain_openai import ChatOpenAI
    return isinstance(model, ChatOpenAI)

# DEBUG: Set to False to disable streaming for easier debugging
ENABLE_STREAM = True

# --- Legacy ThinkingRouter (Preserved & Required for DeepSeek/Open Source) ---
class ThinkingRouter:
    """
    Routes streamed text into ("thinking", ...) and ("text", ...) events.
    Essential for DeepSeek R1 and other models that stream <think> tags.
    """
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.in_think = enabled
        self.buffer = ""
        self.think_start = "<think>"
        self.think_end = "</think>"

    def process(self, chunk: str) -> list[tuple[str, str]]:
        if not self.enabled: return [("text", chunk)]
        self.buffer += chunk
        results = []
        while True:
            if self.in_think:
                end_idx = self.buffer.find(self.think_end)
                if end_idx != -1:
                    content = self.buffer[:end_idx]
                    if content: results.append(("thinking", content))
                    self.in_think = False
                    self.buffer = self.buffer[end_idx + len(self.think_end):]
                else:
                    break # Wait for more data
            else:
                start_idx = self.buffer.find(self.think_start)
                if start_idx != -1:
                    before = self.buffer[:start_idx]
                    if before: results.append(("text", before))
                    self.in_think = True
                    self.buffer = self.buffer[start_idx + len(self.think_start):]
                else:
                    if self.buffer: results.append(("text", self.buffer))
                    self.buffer = ""
                    break
        return results

    def flush(self):
        if self.buffer: return [("thinking" if self.in_think else "text", self.buffer)]
        return []

# --- 1. Define State and Schema ---

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

# --- 2. Define Nodes ---

def agent_node(state: AgentState, config):
    """The generic ReAct agent that CANNOT see the structured output schema."""
    # Retrieve tools and model from config (passed via runtime)
    tools = config["configurable"].get("server_tools", [])
    # We add 'client_tools' just as definitions so the LLM knows they exist
    client_tools = config["configurable"].get("client_tools", [])
    model = config["configurable"]["model"]

    # Log model info
    model_name = get_model_name(model)
    print(f"[Graph:Agent] Using model: {type(model).__name__} (model_name: {model_name})")

    # Trim messages to fit context window before invoking
    max_ctx = config["configurable"].get("max_context_tokens", 128000)
    trimmed = trim_to_fit(state["messages"], model_name, max_ctx)

    # Bind all tools (server + client)
    model_with_tools = model.bind_tools(tools + client_tools, strict=_needs_strict(model))

    llm_timeout = config["configurable"].get("llm_timeout", 60)
    response = invoke_with_timeout(model_with_tools, trimmed, llm_timeout, label="Agent")

    if response.tool_calls:
        print(f"[Graph:Agent] Response has {len(response.tool_calls)} tool call(s): {[tc['name'] for tc in response.tool_calls]}")
    else:
        content = extract_text_from_content(response.content)
        preview = content[:150].replace('\n', ' ') if content else ""
        print(f"[Graph:Agent] Response text ({len(content)} chars): {preview}...")

    return {"messages": [response]}

def tool_node(state: AgentState, config):
    """Handles ALL tool calls from the last AI message.

    Server tools execute inline. Client tools interrupt for frontend
    execution via Office.js. Multiple sequential interrupt() calls are
    supported by LangGraph -- each Command(resume=value) continues from
    the last interrupt point.
    """
    server_tools = config["configurable"].get("server_tools", [])
    server_tool_map = {t.name: t for t in server_tools}
    client_tool_names = {t.name for t in config["configurable"].get("client_tools", [])}

    last_msg = state["messages"][-1]
    results = []

    print(f"[Graph:Tools] Processing {len(last_msg.tool_calls)} tool call(s)")

    for tc in last_msg.tool_calls:
        if tc["name"] in server_tool_map:
            print(f"[Graph:Tools]   Server Tool: {tc['name']}")
            tool = server_tool_map[tc["name"]]
            try:
                res = tool.invoke(tc["args"])
                print(f"[Graph:Tools]   Result: {str(res)[:100]}...")
                results.append(ToolMessage(tool_call_id=tc["id"], content=str(res)))
            except Exception as e:
                print(f"[Graph:Tools]   ERROR: {str(e)}")
                results.append(ToolMessage(tool_call_id=tc["id"], content=f"Error: {str(e)}"))
        elif tc["name"] in client_tool_names:
            print(f"[Graph:Tools]   Client Tool PAUSE: {tc['name']}")
            tool_result = interrupt({
                "type": "client_tool_call",
                "name": tc["name"],
                "args": tc["args"],
                "id": tc["id"]
            })
            print(f"[Graph:Tools]   Client Tool RESUME: {tc['name']} -> {str(tool_result)[:100]}...")
            results.append(ToolMessage(tool_call_id=tc["id"], content=str(tool_result)))
        else:
            available = sorted(set(server_tool_map) | client_tool_names)
            results.append(ToolMessage(tool_call_id=tc["id"],
                content=f"Error: Unknown tool '{tc['name']}'. Available tools: {', '.join(available)}"))

    return {"messages": results}

# --- 3. Build Graph ---

def route_agent(state: AgentState, config):
    """Decides where to go after the Agent speaks."""
    last_msg = state["messages"][-1]
    if not last_msg.tool_calls:
        return END
    return "tools"

workflow = StateGraph(AgentState)

workflow.add_node("agent", agent_node, retry_policy=LLM_RETRY_POLICY)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", route_agent)
workflow.add_edge("tools", "agent")

# Global Checkpointer (In-memory for now)
checkpointer = MemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

# Track which AIMessage's text has been emitted per session,
# preventing duplicate text emission during multi-tool resume cycles.
_UNSET = object()  # sentinel: distinguishes "not tracked" from "tracked with id=None"
_emitted_ai_msg_id: dict[str, Any] = {}  # session_id → last emitted AIMessage.id


def _mark_ai_msg_emitted(session_id: str, snapshot) -> None:
    """Record the latest AIMessage's id so _emit_text_if_new skips it next time."""
    for msg in reversed(snapshot.values.get("messages", [])):
        if isinstance(msg, AIMessage):
            _emitted_ai_msg_id[session_id] = msg.id
            break


def _emit_text_if_new(session_id: str, snapshot, filter_thinking: bool):
    """Return a text SSE event from the latest AIMessage, or None if already emitted."""
    all_msgs = snapshot.values.get("messages", [])
    for msg in reversed(all_msgs):
        if isinstance(msg, AIMessage):
            if _emitted_ai_msg_id.get(session_id, _UNSET) == msg.id:
                return None
            content = extract_text_from_content(msg.content)
            if content:
                content = remove_thinking_tags(content, filter_thinking)
            if content:
                _emitted_ai_msg_id[session_id] = msg.id
                return {"event": "text", "data": {"content": content}}
            break
    return None


# --- 4. Helper: Stream Processor ---

async def _process_graph_stream(
    event_stream,
    think_router: ThinkingRouter,
    valid_tool_names: set[str] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Consumes graph events and yields SSE-compatible chunks."""

    text_chars = 0  # accumulate text chunk sizes for summary logging
    accumulated_text = ""  # accumulate full text for preview logging

    async for event in event_stream:
        evt_type = event.get("event", "?")
        node = event.get("metadata", {}).get("langgraph_node", "?")

        # 1. Stream Agent Text (The "Thinking" or "Drafting" phase)
        # We look for output from the 'agent' node specifically.
        if evt_type == "on_chat_model_stream" and node == "agent":
            chunk = event["data"]["chunk"]
            if hasattr(chunk, "content") and chunk.content:
                # Extract text before passing to ThinkingRouter (handles both string and list content)
                text_chunk = extract_text_from_content(chunk.content)
                text_chars += len(text_chunk)
                accumulated_text += text_chunk
                # Route through thinking filter
                for type_, content in think_router.process(text_chunk):
                    yield {"event": type_, "data": {"content": content}}

        elif evt_type == "on_chat_model_end" and node == "agent":
            # Summary with preview: one line per agent turn instead of per-chunk
            preview = accumulated_text[:150].replace('\n', ' ') if accumulated_text else ""
            print(f"[GraphStream] agent text done ({text_chars} chars, preview: {preview}...)")
            text_chars = 0
            accumulated_text = ""

        # 2. Handle Server Tool Execution Events (Optional: UI feedback)
        elif evt_type == "on_tool_start":
            tool_name = event.get("name", "?")
            if valid_tool_names is not None and tool_name not in valid_tool_names:
                print(f"[GraphStream] SKIP unknown tool_call: {tool_name}")
                continue
            print(f"[GraphStream] EMIT tool_call: {tool_name}")
            yield {"event": "tool_call", "data": {"name": tool_name, "args": event.get("data", {}).get("input")}}

    # Flush thinking buffer
    for type_, content in think_router.flush():
        yield {"event": type_, "data": {"content": content}}

# --- 5. Shared Helpers (Message Conversion & System Prompt) ---

def remove_thinking_tags(text: str, enabled: bool = True) -> str:
    """Remove <think>...</think> tags from a complete string."""
    if not enabled:
        return text
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'^.*?</think>', '', text, flags=re.DOTALL)
    return text.strip()


def convert_messages(messages: list[Message]) -> list[BaseMessage]:
    """Convert API messages to LangChain message format."""
    result = []
    for msg in messages:
        if msg.role == "system":
            result.append(SystemMessage(content=msg.content))
        elif msg.role == "user":
            result.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            result.append(AIMessage(content=msg.content))
    return result


def _log_conversation_length(messages: list[BaseMessage], prefix: str = "[agent]") -> None:
    """Log a breakdown of message types in the conversation."""
    counts: dict[str, int] = {}
    for m in messages:
        counts[m.type] = counts.get(m.type, 0) + 1
    parts = [f"{v} {k}" for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    print(f"{prefix} conversation length is {len(messages)} ({', '.join(parts)})")


def inject_system_prompt_if_needed(
    messages: list[Message],
    language: str | None,
    prompt_generator: Callable
) -> list[Message]:
    """Inject system prompt if language provided and no existing system message."""
    if language is None:
        print("[prompt] No language provided, using custom prompt from frontend")
        return messages

    # Skip injection if this is a continuation (has assistant messages)
    if has_assistant_messages(messages):
        print("[prompt] Continuation turn detected (has assistant messages)")
        # Remove any system messages from history to avoid duplicates
        filtered = [msg for msg in messages if msg.role != "system"]
        if len(filtered) < len(messages):
            print(f"[prompt] Filtered {len(messages) - len(filtered)} system messages from history")
        return filtered

    if messages and messages[0].role == "system":
        print("[prompt] System message already present, not injecting")
        return messages

    system_content = prompt_generator(language)
    print(f"[prompt] Injecting system prompt for language: {language}")
    print(f"[prompt] Prompt preview: {system_content[:100]}...")
    system_message = Message(role="system", content=system_content)
    return [system_message] + messages


def has_assistant_messages(messages: list[Message]) -> bool:
    """Check if message history contains any assistant responses.

    This indicates a continuation turn rather than the first turn.
    """
    return any(msg.role == "assistant" for msg in messages)


# --- 6. stream_chat (Simple Chat, No Tools) ---

async def chat_complete(
    model: BaseChatModel,
    messages: list[Message],
    filter_thinking: bool = True,
    llm_timeout: int = 60,
) -> dict[str, Any]:
    """Non-streaming chat - returns complete response at once."""
    lc_messages = convert_messages(messages)
    response = await ainvoke_with_timeout(model, lc_messages, llm_timeout, label="Chat")
    text = extract_text_from_content(response.content)
    content = remove_thinking_tags(text, enabled=filter_thinking)
    return {"content": content, "finish_reason": "stop"}


async def stream_chat(
    model: BaseChatModel,
    messages: list[Message],
    filter_thinking: bool = True,
    language: str | None = None,
    additional_system_prompt: str | None = None,
    conversation_id: str | None = None,
    conversation_store: "ConversationStore | None" = None,
    max_context_tokens: int = 128000,
    llm_timeout: int = 60,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream a simple chat response (no tools).

    Uses ConversationStore for cross-mode history when conversation_id is
    provided.  Chat and agent share the same consigliere history — the only
    difference is chat doesn't bind tools.
    """
    print(f"[stream_chat] Starting with model: {type(model).__name__}, filter_thinking: {filter_thinking}, messages: {len(messages)}, language: {language}")

    from ..prompts.system_prompts import generate_chat_system_prompt, inject_behavior

    use_store = bool(conversation_id and conversation_store)
    turn = None

    if use_store:
        assert conversation_id is not None and conversation_store is not None
        turn = conversation_store.start_turn(conversation_id)
        history = conversation_store.get_history_for_consigliere(conversation_id)
        print(f"[stream_chat] Conversation store turn {turn}, consigliere history: {len(history)} messages")

        # Determine system prompt
        system_content = None
        if language:
            system_content = generate_chat_system_prompt(language)
            conversation_store.set_system_prompt(conversation_id, system_content)
        elif messages and messages[0].role == "system":
            system_content = messages[0].content
            conversation_store.set_system_prompt(conversation_id, system_content)
            messages = messages[1:]
        else:
            system_content = conversation_store.get_system_prompt(conversation_id)

        # Inject behavioral instructions after identity paragraph
        if system_content and isinstance(system_content, str):
            system_content = inject_behavior(system_content, additional_system_prompt)

        # Build: system prompt + consigliere history + new user message
        lc_messages = []
        if system_content:
            lc_messages.append(SystemMessage(content=system_content))
        lc_messages += history
        new_user_msgs = convert_messages(messages)
        lc_messages += new_user_msgs

        # Store user message(s)
        for msg in new_user_msgs:
            if isinstance(msg, HumanMessage):
                conversation_store.add_user_message(conversation_id, turn, msg, "chat")
    else:
        # Fallback: no store, use messages as-is (legacy / dev mode)
        messages_to_use = inject_system_prompt_if_needed(
            messages, language, generate_chat_system_prompt
        )
        lc_messages = convert_messages(messages_to_use)

    _log_conversation_length(lc_messages, prefix="[stream_chat]")

    # Trim to fit context window
    model_name = get_model_name(model)
    lc_messages = trim_to_fit(lc_messages, model_name, max_context_tokens)

    if not ENABLE_STREAM:
        print("[stream_chat] Non-streaming mode enabled")
        response = await ainvoke_with_timeout(model, lc_messages, llm_timeout, label="Chat")
        text = extract_text_from_content(response.content)
        content = remove_thinking_tags(text, enabled=filter_thinking)
        if use_store:
            conversation_store.add_public_response(
                conversation_id, turn, "chat", "chat",
                AIMessage(content=content),
            )
        yield {"event": "text", "data": {"content": content}}
        yield {"event": "done", "data": {"finish_reason": "stop"}}
        return

    think_router = ThinkingRouter(enabled=filter_thinking)
    accumulated_content = ""
    chunk_count = 0

    print("[stream_chat] Starting to stream chunks from model.astream()...")
    try:
        async for chunk in astream_with_timeout(model, lc_messages, llm_timeout, label="Chat"):
            chunk_count += 1
            if chunk_count <= 3 or chunk_count % 10 == 0:
                print(f"[stream_chat] Chunk {chunk_count} received")

            if hasattr(chunk, "content") and chunk.content:
                text_chunk = extract_text_from_content(chunk.content)

                if text_chunk:
                    if accumulated_content and text_chunk.startswith(accumulated_content):
                        delta = text_chunk[len(accumulated_content):]
                    else:
                        delta = text_chunk
                    accumulated_content = text_chunk

                    for event_type, content in think_router.process(delta):
                        if content:
                            yield {"event": event_type, "data": {"content": content}}

        content_preview = accumulated_content[:200].replace('\n', ' ') if accumulated_content else ""
        print(f"[stream_chat] Stream completed. Total chunks: {chunk_count}, accumulated length: {len(accumulated_content)} (preview: {content_preview}...)")

    except Exception as e:
        print(f"[stream_chat] ERROR during streaming: {type(e).__name__}: {e}")
        if use_store:
            conversation_store.rollback_response(conversation_id, turn)
        import traceback
        traceback.print_exc()
        raise

    for event_type, content in think_router.flush():
        if content:
            yield {"event": event_type, "data": {"content": content}}

    # Store the final chat response
    if use_store and accumulated_content:
        final_text = remove_thinking_tags(accumulated_content, enabled=filter_thinking)
        conversation_store.add_public_response(
            conversation_id, turn, "chat", "chat",
            AIMessage(content=final_text),
        )

    yield {"event": "done", "data": {"finish_reason": "stop"}}


# --- 7. Result Extraction Helper ---

def _store_single_agent_results(store, conversation_id, turn, config, pre_turn_count):
    """Extract and store results from a completed single agent turn.

    Consigliere tool interactions: AIMessages with tool_calls + ToolMessages.
    Public: The agent's final AIMessage (no tool_calls).
    """
    snapshot = graph.get_state(config)
    all_msgs = snapshot.values.get("messages", [])
    new_msgs = all_msgs[pre_turn_count:]

    tool_interactions = [
        msg for msg in new_msgs
        if isinstance(msg, ToolMessage)
        or (isinstance(msg, AIMessage) and msg.tool_calls)
    ]
    if tool_interactions:
        store.add_consigliere_messages(
            conversation_id, turn, "agent", "agent", tool_interactions
        )

    # Last AIMessage without tool_calls is the agent's final response
    final_msg = None
    for msg in reversed(new_msgs):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            final_msg = msg
            break

    if final_msg is None:
        raise RuntimeError(
            f"No final AIMessage found in single agent turn {turn} "
            f"for conversation {conversation_id}. "
            f"new_msgs types: {[type(m).__name__ for m in new_msgs]}"
        )

    store.add_public_response(
        conversation_id, turn, "agent", "agent", final_msg,
    )


# --- 8. Exported Functions (API Hooks) ---

async def stream_agent(
    model: BaseChatModel,
    messages: list[Message],
    tools: list,
    client_tools: list | None = None,
    tool_names: list[str] | None = None,
    recursion_limit: int = 25,
    filter_thinking: bool = True,
    language: str | None = None,
    additional_system_prompt: str | None = None,
    thread_id: str | None = None,
    conversation_id: str | None = None,
    conversation_store: "ConversationStore | None" = None,
    max_context_tokens: int = 128000,
    llm_timeout: int = 60,
) -> AsyncGenerator[dict[str, Any], None]:
    """Entry point for new agent request.

    Uses ConversationStore for cross-mode consigliere history.
    Agent is part of the consigliere persona (same history as chat,
    overseer, synthesizer).
    """
    from ..prompts.system_prompts import generate_agent_system_prompt, inject_behavior

    # Log model info at entry point
    model_name = get_model_name(model)
    print(f"[stream_agent] Starting with model: {type(model).__name__} (model_name: {model_name})")

    all_tools = list(tools) + list(client_tools or [])

    use_store = bool(conversation_id and conversation_store)
    turn = None
    pre_turn_count = 0

    if use_store:
        assert conversation_id is not None and conversation_store is not None
        turn = conversation_store.start_turn(conversation_id)
        session_id = str(uuid.uuid4())
        print(f"[agent] Conversation store turn {turn}, internal thread: {session_id}")

        # Get consigliere history (public + consigliere tool interactions)
        history = conversation_store.get_history_for_consigliere(conversation_id)

        # Determine system prompt
        system_content = None
        if language:
            system_content = generate_agent_system_prompt(language, tools=all_tools)
            conversation_store.set_system_prompt(conversation_id, system_content)
        elif messages and messages[0].role == "system":
            system_content = messages[0].content
            conversation_store.set_system_prompt(conversation_id, system_content)
            messages = messages[1:]
        else:
            system_content = conversation_store.get_system_prompt(conversation_id)

        # Inject behavioral instructions after identity paragraph
        if system_content and isinstance(system_content, str):
            system_content = inject_behavior(system_content, additional_system_prompt)

        # Build message list: system prompt + consigliere history + new user message
        lc_messages = []
        if system_content:
            lc_messages.append(SystemMessage(content=system_content))
        lc_messages += history
        new_user_msgs = convert_messages(messages)
        lc_messages += new_user_msgs

        # Store user message(s)
        for msg in new_user_msgs:
            if isinstance(msg, HumanMessage):
                conversation_store.add_user_message(conversation_id, turn, msg, "agent")

        pre_turn_count = len(lc_messages)
        conversation_store.register_thread(session_id, conversation_id, turn, pre_turn_count)
    else:
        # Fallback: no store (dev / standalone mode)
        session_id = thread_id or str(uuid.uuid4())
        _gen = lambda lang: generate_agent_system_prompt(lang, tools=all_tools)
        messages_to_use = inject_system_prompt_if_needed(
            messages, language, _gen
        )
        lc_messages = convert_messages(messages_to_use)

    _log_conversation_length(lc_messages, prefix="[agent] Sending")

    config = {
        "configurable": {
            "thread_id": session_id,
            "model": model,
            "server_tools": tools,
            "client_tools": client_tools or [],
            "max_context_tokens": max_context_tokens,
            "llm_timeout": llm_timeout,
        },
        "recursion_limit": recursion_limit
    }

    print(f"[stream_agent] Tools: {len(tools)} server + {len(client_tools or [])} client = {len(tools) + len(client_tools or [])} total | server: {[t.name for t in tools]} | client: {[t.name for t in (client_tools or [])]}")

    think_router = ThinkingRouter(enabled=filter_thinking)
    all_tool_names = {t.name for t in tools} | {t.name for t in (client_tools or [])}

    try:
        event_stream = graph.astream_events(
            {"messages": lc_messages},
            config=config,
            version="v2"
        )

        text_emitted = False
        async for sse_event in _process_graph_stream(event_stream, think_router, all_tool_names):
            if sse_event.get("event") == "text":
                text_emitted = True
            yield sse_event

        # Check for Interrupts (Client Tool Calls)
        snapshot = graph.get_state(config)
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            interrupt_data = snapshot.tasks[0].interrupts[0].value

            # Emit agent text before tool_call (non-streaming fallback)
            if not text_emitted:
                text_event = _emit_text_if_new(session_id, snapshot, filter_thinking)
                if text_event:
                    yield text_event
            else:
                # Text was already streamed — record the AIMessage id so
                # resume_agent() won't re-emit it on subsequent resumes.
                _mark_ai_msg_emitted(session_id, snapshot)

            yield {
                "event": "tool_call",
                "data": {
                    "name": interrupt_data["name"],
                    "args": interrupt_data["args"]
                }
            }

            yield {
                "event": "client_tool_call",
                "data": {
                    "session_id": session_id,
                    "tool_calls": [{
                        "name": interrupt_data["name"],
                        "args": interrupt_data["args"],
                        "call_id": interrupt_data["id"]
                    }]
                }
            }
        else:
            # NO interrupt = agent is done
            # Emit final response if streaming didn't already
            if not text_emitted:
                all_msgs = snapshot.values.get("messages", [])
                final_msg = None
                for msg in reversed(all_msgs):
                    if isinstance(msg, AIMessage) and not msg.tool_calls:
                        final_msg = msg
                        break

                if final_msg:
                    content = extract_text_from_content(final_msg.content)
                    if content:
                        content = remove_thinking_tags(content, filter_thinking)
                    if content:
                        yield {"event": "text", "data": {"content": content}}

            if use_store:
                _store_single_agent_results(
                    conversation_store, conversation_id, turn, config, pre_turn_count
                )
                conversation_store.unregister_thread(session_id)
            _emitted_ai_msg_id.pop(session_id, None)
            yield {"event": "done", "data": {"finish_reason": "stop"}}

    except Exception as e:
        if use_store:
            assert conversation_id is not None and conversation_store is not None and turn is not None
            conversation_store.rollback_response(conversation_id, turn)
            conversation_store.unregister_thread(session_id)
        _emitted_ai_msg_id.pop(session_id, None)
        yield {"event": "error", "data": {"error": str(e)}}


async def resume_agent(
    model: BaseChatModel,
    session_id: str,
    tool_results: list[dict],
    server_tools: list,
    client_tools: list,
    filter_thinking: bool = True,
    conversation_store=None,
    max_context_tokens: int = 128000,
    llm_timeout: int = 60,
    recursion_limit: int = 25,
) -> AsyncGenerator[dict[str, Any], None]:
    """Entry point for resuming a paused agent."""

    config = {
        "configurable": {
            "thread_id": session_id,
            "model": model,
            "server_tools": server_tools,
            "client_tools": client_tools,
            "max_context_tokens": max_context_tokens,
            "llm_timeout": llm_timeout,
        },
        "recursion_limit": recursion_limit
    }

    think_router = ThinkingRouter(enabled=filter_thinking)
    all_tool_names = {t.name for t in server_tools} | {t.name for t in client_tools}
    result_str = tool_results[0]["result"]

    try:
        event_stream = graph.astream_events(
            Command(resume=result_str),
            config=config,
            version="v2"
        )

        text_emitted = False
        async for sse_event in _process_graph_stream(event_stream, think_router, all_tool_names):
            if sse_event.get("event") == "text":
                text_emitted = True
            yield sse_event

        snapshot = graph.get_state(config)
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            interrupt_data = snapshot.tasks[0].interrupts[0].value

            # Emit agent text before tool_call — de-duplicated so the same
            # AIMessage text is never sent twice across resume cycles.
            if not text_emitted:
                text_event = _emit_text_if_new(session_id, snapshot, filter_thinking)
                if text_event:
                    yield text_event
            else:
                _mark_ai_msg_emitted(session_id, snapshot)

            yield {
                "event": "tool_call",
                "data": {
                    "name": interrupt_data["name"],
                    "args": interrupt_data["args"]
                }
            }

            yield {
                "event": "client_tool_call",
                "data": {
                    "session_id": session_id,
                    "tool_calls": [{
                        "name": interrupt_data["name"],
                        "args": interrupt_data["args"],
                        "call_id": interrupt_data["id"]
                    }]
                }
            }
        else:
            # NO interrupt = agent is done
            # Emit final response explicitly if streaming didn't
            if not text_emitted:
                all_msgs = snapshot.values.get("messages", [])
                final_msg = None
                for msg in reversed(all_msgs):
                    if isinstance(msg, AIMessage) and not msg.tool_calls:
                        final_msg = msg
                        break

                if final_msg:
                    content = extract_text_from_content(final_msg.content)
                    if content:
                        content = remove_thinking_tags(content, filter_thinking)
                    if content:
                        yield {"event": "text", "data": {"content": content}}

            # Store results if conversation store is active
            if conversation_store:
                mapping = conversation_store.lookup_thread(session_id)
                if mapping:
                    _store_single_agent_results(
                        conversation_store, mapping.conversation_id,
                        mapping.turn, config, mapping.pre_turn_message_count,
                    )
                    conversation_store.unregister_thread(session_id)
            _emitted_ai_msg_id.pop(session_id, None)
            yield {"event": "done", "data": {"finish_reason": "stop"}}

    except Exception as e:
        if conversation_store:
            mapping = conversation_store.lookup_thread(session_id)
            if mapping:
                conversation_store.rollback_response(mapping.conversation_id, mapping.turn)
                conversation_store.unregister_thread(session_id)
        _emitted_ai_msg_id.pop(session_id, None)
        yield {"event": "error", "data": {"error": str(e)}}

def get_session_info(session_id: str):
    """Stub to satisfy legacy main.py calls if needed."""
    # In LangGraph, we don't need to look up tool names separately 
    # as we re-pass them from main.py, but this prevents import errors.
    return type('obj', (object,), {'tool_names': []})