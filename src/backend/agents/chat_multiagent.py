import re
import sys
import json
import pickle
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Annotated, Literal, List, TypedDict, Dict
from pydantic import BaseModel, Field, ConfigDict

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

# Import ThinkingRouter and utilities from agents
try:
    from .utils import extract_text_from_content
    from .context import trim_to_fit
    from .llm_retry import invoke_with_timeout, LLM_RETRY_POLICY
    from ..providers.base import get_model_name
    from ..prompts.system_prompts import (
        generate_multiagent_expert_prompt,
        generate_multiagent_synthesizer_prompt,
        format_expert_responses_message,
        generate_multiagent_overseer_prompt,
        generate_multiagent_overseer_final_prompt,
    )
    from ..schemas import to_langchain_messages
except ImportError:
    from agents.utils import extract_text_from_content
    from agents.context import trim_to_fit
    from agents.llm_retry import invoke_with_timeout, LLM_RETRY_POLICY
    from providers.base import get_model_name
    from prompts.system_prompts import (
        generate_multiagent_expert_prompt,
        generate_multiagent_synthesizer_prompt,
        format_expert_responses_message,
        generate_multiagent_overseer_prompt,
        generate_multiagent_overseer_final_prompt,
    )
    from schemas import to_langchain_messages

# Max retries when an expert LLM returns empty content (transient provider quirk)
MAX_EMPTY_RETRIES = 2

def _parse_expert_tags(text: str) -> "ExpertOutput | None":
    """Try to parse <public>...</public> and <private>...</private> tags from text.

    Returns ExpertOutput if both tags are found and public is non-empty, None otherwise.
    """
    public_match = re.search(r'<public>(.*?)</public>', text, re.DOTALL)
    private_match = re.search(r'<private>(.*?)</private>', text, re.DOTALL)
    if not public_match or not private_match:
        return None
    public_response = public_match.group(1).strip()
    private_memory = private_match.group(1).strip()
    if not public_response:
        return None
    return ExpertOutput(public_response=public_response, private_memory=private_memory)

def _needs_strict(model) -> bool:
    """OpenAI requires strict=True for tool schemas; other providers don't."""
    from langchain_openai import ChatOpenAI
    return isinstance(model, ChatOpenAI)

def merge_parallel_responses(existing: Dict[str, str], updates: Dict[str, str]) -> Dict[str, str]:
    """Merge expert responses instead of replacing the entire dict."""
    return {**existing, **updates}

# --- Provider-aware combined tools + structured output binding ---

def _strip_additional_properties(schema: dict) -> dict:
    """Recursively remove `additionalProperties` and `title` from a JSON schema.

    Gemini's SDK rejects these fields in client-side validation.
    """
    schema = schema.copy()
    schema.pop("additionalProperties", None)
    schema.pop("title", None)
    if "properties" in schema:
        schema["properties"] = {
            k: _strip_additional_properties(v) if isinstance(v, dict) else v
            for k, v in schema["properties"].items()
        }
    for container_key in ("$defs", "items"):
        if container_key in schema and isinstance(schema[container_key], dict):
            schema[container_key] = _strip_additional_properties(schema[container_key])
    return schema


def _dump_empty_content_debug(messages, response, model, tools, label: str):
    """Save a pickle file with full LLM call context when empty content is received.

    The pickle contains everything needed to reproduce the call:
    messages, response, model class/name, tool names, and metadata.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dump_dir = Path(__file__).resolve().parent.parent / "data" / "debug_dumps"
    dump_dir.mkdir(parents=True, exist_ok=True)
    path = dump_dir / f"empty_content_{label}_{ts}.pkl"
    model_name = get_model_name(model)
    payload = {
        "timestamp": datetime.now().isoformat(),
        "label": label,
        "model_class": model.__class__.__name__,
        "model_name": model_name,
        "tool_names": [t.name for t in tools],
        "messages": messages,
        "response": response,
        "response_content": response.content,
        "response_metadata": getattr(response, 'response_metadata', {}),
        "stop_reason": _get_stop_reason(response),
    }
    try:
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        print(f"[MultiAgent:CollabExpert]   Debug dump saved: {path}")
    except Exception as exc:
        print(f"[MultiAgent:CollabExpert]   Failed to save debug dump: {exc}")


def _get_stop_reason(response) -> str:
    """Extract stop/finish reason from response metadata (provider-agnostic).

    Anthropic uses 'stop_reason', OpenAI/Gemini/Groq use 'finish_reason'.
    Returns 'unknown' if metadata is missing or has no recognized key.
    """
    try:
        meta = getattr(response, 'response_metadata', None)
        if not isinstance(meta, dict):
            return 'unknown'
        return meta.get('stop_reason') or meta.get('finish_reason') or 'unknown'
    except Exception:
        return 'unknown'


def bind_tools_and_schema(model: BaseChatModel, tools: list, schema: type[BaseModel]):
    """Bind both tools AND structured output to a model in a single call.

    When the model makes tool calls, the structured output constraint doesn't apply.
    When the model responds with text (no tool calls), the response is constrained
    to the JSON schema. Uses provider-specific API parameters detected via isinstance().
    """
    from langchain_openai import ChatOpenAI
    from langchain_anthropic import ChatAnthropic
    from langchain_google_genai import ChatGoogleGenerativeAI

    json_schema = schema.model_json_schema()

    strict = isinstance(model, ChatOpenAI)

    if isinstance(model, ChatAnthropic):
        from anthropic import transform_schema
        return model.bind_tools(tools).bind(
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": transform_schema(schema),
                }
            }
        )
    elif isinstance(model, ChatGoogleGenerativeAI):
        gemini_schema = _strip_additional_properties(json_schema)
        return model.bind_tools(tools).bind(
            generation_config={
                "response_mime_type": "application/json",
                "response_json_schema": gemini_schema,
            }
        )
    elif isinstance(model, ChatOpenAI):
        # Covers OpenAI, Azure OpenAI (subclass), and LM Studio (uses ChatOpenAI)
        return model.bind_tools(tools, strict=True).bind(
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__.lower(),
                    "schema": json_schema,
                    "strict": True,
                },
            }
        )
    else:
        # ChatGroq, ChatOllama, and any other provider — try OpenAI-style binding
        return model.bind_tools(tools, strict=strict).bind(
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__.lower(),
                    "schema": json_schema,
                    "strict": True,
                },
            }
        )


# --- 1. Schemas ---

class ExpertOutput(BaseModel):
    """Structured output for collaborative experts."""
    model_config = ConfigDict(extra="forbid")

    public_response: str = Field(description="Response to share with the user, other experts and Overseer.")
    private_memory: str = Field(description="Analytical scratchpad: independent doubts, hypotheses, or alternative approaches to recall next round.")

class OverseerDecision(BaseModel):
    """Structured output for the overseer's decision."""
    decision: Literal["CONTINUE", "CONCLUDE"] = Field(description="Whether to continue discussion or provide final answer.")
    reasoning_feedback: str = Field(description="Reasoning for the decision and feedback to the experts.")

# --- 2. State Definition ---

class MultiAgentState(TypedDict):
    # Shared conversation history (visible to all in collaborative)
    messages: Annotated[List[BaseMessage], add_messages]

    # Cross-turn history from ConversationStore (read-only, injected at start)
    # Contains public messages from all past turns. Each node prepends this
    # after system prompt so personas see prior conversation context.
    cross_turn_history: List[BaseMessage]

    # Configuration & Context
    mode: Literal["parallel", "collaborative"]
    max_rounds: int
    current_round: int
    language: str
    additional_system_prompt: str

    # State for Parallel Mode
    parallel_responses: Annotated[Dict[str, str], merge_parallel_responses]  # { "Expert_1": "response text..." }

    # State for Collaborative Mode
    current_expert_index: int  # Pointer to which expert is acting
    expert_memories: Dict[str, str]  # { "0": "memory...", "1": "..." } keys are str(index)

    # Whether experts receive cross-turn conversation history
    expert_full_history: bool

    # Internal routing flag
    next_node: str | None

    # Track which node called tools (for routing tool results back correctly)
    last_tool_caller: str | None  # "expert" | "synthesizer" | "overseer"

# --- 3. Node Definitions ---

def get_model(config: dict, role: str, index: int = 0) -> BaseChatModel:
    """Helper to retrieve models passed via runtime config."""
    if role == "expert":
        return config["configurable"]["expert_models"][index]
    elif role == "overseer":
        return config["configurable"]["overseer_model"]
    elif role == "synthesizer":
        return config["configurable"]["synthesizer_model"]
    raise ValueError(f"Unknown role {role}")

def get_llm_timeout(config: dict) -> int:
    return config["configurable"].get("llm_timeout", 60)

def get_max_context_tokens(config: dict, role: str, index: int = 0) -> int:
    """Helper to retrieve per-role max_context_tokens from runtime config."""
    if role == "expert":
        limits = config["configurable"].get("expert_max_context_tokens", [])
        return limits[index] if index < len(limits) else 128000
    elif role == "overseer":
        return config["configurable"].get("overseer_max_context_tokens", 128000)
    elif role == "synthesizer":
        return config["configurable"].get("synthesizer_max_context_tokens", 128000)
    return 128000

def get_tools_list(config: dict, role: str) -> list:
    """Helper to retrieve tools passed via runtime config."""
    if role == "expert":
        return (config["configurable"]["expert_server_tools"] or []) + (config["configurable"]["expert_client_tools"] or [])
    elif role == "supervisor":
        return (config["configurable"]["supervisor_server_tools"] or []) + (config["configurable"]["supervisor_client_tools"] or [])
    return []


# -- Helper: Message Filtering --

def _get_collab_public_history(messages: List[BaseMessage]) -> List[BaseMessage]:
    """Get collaborative public history: excludes SystemMessages and tool interactions."""
    return [m for m in messages
            if not isinstance(m, SystemMessage)
            and not isinstance(m, ToolMessage)
            and not (isinstance(m, AIMessage) and getattr(m, 'tool_calls', None))]

def _get_current_expert_tool_chain(messages: List[BaseMessage]) -> List[BaseMessage]:
    """Extract the current expert's tool interaction chain from the end of messages.

    Walks backward collecting ToolMessages and AIMessages with tool_calls,
    stopping at an AIMessage without tool_calls (previous expert's final
    response) or a HumanMessage.
    """
    chain = []
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            break
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            break
        chain.insert(0, msg)
    return chain

# def _adapt_collab_history_for_expert(
#         messages: List[BaseMessage], 
#         current_agent_name: str, 
#         convert_own: bool = False) -> List[BaseMessage]:
#     """Convert other agents' AIMessages to HumanMessages for role alternation.

#     LLM APIs (Gemini, Claude) require or expect alternating user/model turns.
#     Consecutive model-role messages degrade tool-calling behavior (Gemini) or
#     cause outright rejection (Claude). This converts other agents' AIMessages
#     to HumanMessages while keeping the current agent's own messages as AIMessages.

#     When convert_own=True, ALL AIMessages are converted (including the current
#     agent's own). Used by Overseer/FinalAnswer nodes whose own prior decisions
#     are feedback context, not assistant continuations.
#     """
#     result = []
#     for msg in messages:
#         if isinstance(msg, AIMessage) and (msg.name != current_agent_name or convert_own):
#             display_name = msg.name
#             content = f"[message from {display_name}]\n{msg.content}"
#             result.append(HumanMessage(content=content, name=msg.name))
#         else:
#             result.append(msg)
#     return result

def _adapt_collab_history_for_expert(
    messages: List[BaseMessage],
    current_agent_name: str,
    convert_own: bool = False,
) -> List[BaseMessage]:
    """Convert other agents' AIMessages to HumanMessages for Anthropic-compliant
    role alternation, with full speaker attribution preserved in message content.

    The Anthropic API requires strictly alternating user/assistant roles. In
    collaborative mode, multiple expert AIMessages appear consecutively in the
    shared public history, which produces invalid consecutive assistant turns.

    This function fixes the sequence in two passes:

    Pass 1 — Role conversion:
        Foreign AIMessages (from agents other than current_agent_name) are
        converted to HumanMessages with a "[SpeakerName]:" prefix so
        participants know who said what. Own AIMessages are kept as AIMessages
        so Claude retains continuity of its own prior reasoning.
        When convert_own=True (Overseer/FinalAnswer nodes), ALL AIMessages are
        converted — the overseer treats prior responses as context, not as its
        own assistant continuations.
        Note: no name= kwarg is set on HumanMessages. The name field is only
        valid on AIMessages in the Anthropic API; passing it on HumanMessages
        triggers silent malformed-message behavior that contributes to empty
        responses with output_config active.

    Pass 2 — Consecutive-role merge:
        After conversion, multiple foreign responses become consecutive
        HumanMessages. These are merged into a single HumanMessage with a
        blank-line separator. Speaker labels in content preserve attribution.
        This guarantees strict H→A→H→A alternation regardless of how many
        agents have spoken or how many rounds have elapsed.

    Important: this function operates on the output of _get_collab_public_history,
    which already strips SystemMessages, ToolMessages, and AIMessages with
    tool_calls. The caller is responsible for ensuring cross_turn_history
    prepended before this output does not itself create a consecutive-HumanMessage
    boundary (merge at the join point if needed).

    Args:
        messages:           Public history from _get_collab_public_history.
        current_agent_name: Name of the calling agent (e.g. "Expert_2", "Overseer").
        convert_own:        If True, convert own AIMessages too. Default False.

    Returns:
        List[BaseMessage] with strict alternating roles and speaker attribution
        preserved inside message content.
    """
    # ── Pass 1: Role conversion ──────────────────────────────────────────────
    adapted: List[BaseMessage] = []

    for msg in messages:
        if isinstance(msg, AIMessage):
            is_own = (not convert_own) and (msg.name == current_agent_name)
            if is_own:
                adapted.append(msg)
            else:
                adapted.append(
                    HumanMessage(content=f"[{msg.name}]:\n{msg.content}")
                )
        else:
            adapted.append(msg)

    # ── Pass 2: Merge consecutive HumanMessages ───────────────────────────────
    merged: List[BaseMessage] = []
    separator = "\n\n" + "─" * 6 + "\n\n"

    for msg in adapted:
        if merged and isinstance(merged[-1], HumanMessage) and isinstance(msg, HumanMessage):
            merged[-1] = HumanMessage(
                content = merged[-1].content + separator + msg.content
            )
        else:
            merged.append(msg)

    return merged


def _format_message_counts(messages: List[BaseMessage]) -> str:
    """Format message list as count with type breakdown."""
    counts = {"system": 0, "human": 0, "ai": 0, "tool_call": 0, "tool_result": 0}
    for m in messages:
        if isinstance(m, SystemMessage):
            counts["system"] += 1
        elif isinstance(m, HumanMessage):
            counts["human"] += 1
        elif isinstance(m, ToolMessage):
            counts["tool_result"] += 1
        elif isinstance(m, AIMessage) and getattr(m, 'tool_calls', None):
            counts["tool_call"] += 1
        elif isinstance(m, AIMessage):
            counts["ai"] += 1
    parts = [f"{v} {k}" for k, v in counts.items() if v > 0]
    return f"{len(messages)} ({', '.join(parts)})"

def _get_synthesizer_context(messages: List[BaseMessage]) -> tuple[List[BaseMessage], List[BaseMessage]]:
    """Build synthesizer's message context for parallel mode.

    Returns (conversation_history, synth_tool_chain) as separate lists so the
    caller can insert expert responses between them.

    conversation_history: everything up to and including the last HumanMessage
        (no SystemMessages). Expert tool interactions excluded.
    synth_tool_chain: synthesizer's own AIMessages + ToolMessages from the
        current round (identified by name='Synthesizer').
    """
    # Find last HumanMessage = boundary of frontend conversation history
    last_human_idx = -1
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            last_human_idx = i

    if last_human_idx < 0:
        return [], []

    # Conversation history (no SystemMessages)
    history = [m for m in messages[:last_human_idx + 1]
               if not isinstance(m, SystemMessage)]

    # Synthesizer's own messages from current round
    synth_chain = []
    synth_started = False
    for msg in messages[last_human_idx + 1:]:
        if isinstance(msg, AIMessage) and getattr(msg, 'name', None) == "Synthesizer":
            synth_started = True
        if synth_started:
            synth_chain.append(msg)

    return history, synth_chain

# -- Shared Tools Nodes --

def tool_node(state: MultiAgentState, config):
    """Handles ALL tool calls from the last AI message.

    Server tools execute inline. Client tools interrupt for frontend
    execution via Office.js.
    """
    last_msg = state["messages"][-1]

    all_server_tools = (
        (config["configurable"]["expert_server_tools"] or []) +
        (config["configurable"]["supervisor_server_tools"] or [])
    )
    server_tool_map = {t.name: t for t in all_server_tools}

    all_client_tool_names = {
        t.name for t in (config["configurable"]["expert_client_tools"] or [])
    } | {
        t.name for t in (config["configurable"]["supervisor_client_tools"] or [])
    }

    print(f"[MultiAgent:Tools] Processing {len(last_msg.tool_calls)} tool call(s)")
    print(f"[MultiAgent:Tools]   Mode: {state['mode']}, Caller: {state.get('last_tool_caller', 'unknown')}")

    results = []
    for tc in last_msg.tool_calls:
        if tc["name"] in server_tool_map:
            print(f"[MultiAgent:Tools]   Server Tool: {tc['name']}")
            try:
                res = server_tool_map[tc["name"]].invoke(tc["args"])
                print(f"[MultiAgent:Tools]   Result: {str(res)[:100]}...")
                results.append(ToolMessage(tool_call_id=tc["id"], content=str(res)))
            except Exception as e:
                print(f"[MultiAgent:Tools]   ERROR: {str(e)}")
                results.append(ToolMessage(tool_call_id=tc["id"], content=f"Error: {str(e)}"))
        elif tc["name"] in all_client_tool_names:
            print(f"[MultiAgent:Tools]   Client Tool PAUSE: {tc['name']}")
            tool_result_data = interrupt({
                "type": "client_tool_call",
                "name": tc["name"],
                "args": tc["args"],
                "id": tc["id"]
            })
            print(f"[MultiAgent:Tools]   Client Tool RESUME: {tc['name']} -> {str(tool_result_data)[:100]}...")
            results.append(ToolMessage(tool_call_id=tc["id"], content=str(tool_result_data)))
        else:
            available = sorted(set(server_tool_map) | all_client_tool_names)
            print(f"[MultiAgent:Tools]   WARNING: Unknown tool '{tc['name']}'")
            results.append(ToolMessage(tool_call_id=tc["id"],
                content=f"Error: Unknown tool '{tc['name']}'. Available tools: {', '.join(available)}"))

    return {"messages": results}

# -- Parallel Mode Nodes --

def parallel_expert_node(state: MultiAgentState, config):
    """Runs a single expert for parallel mode."""
    idx = state["current_expert_index"]
    model = get_model(config, "expert", idx)
    tools = get_tools_list(config, "expert")

    expert_name = f"Expert_{idx+1}"
    total_experts = len(config["configurable"]["expert_models"])

    model_name = get_model_name(model)
    print(f"[MultiAgent:ParallelExpert] Starting {expert_name} ({idx+1}/{total_experts})")
    print(f"[MultiAgent:ParallelExpert]   Model: {model.__class__.__name__} (model_name: {model_name})")
    print(f"[MultiAgent:ParallelExpert]   Tools: {[t.name for t in tools]}")

    # Experts are stateless across tasks: only see current user query
    user_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    print(f"[MultiAgent:ParallelExpert]   User messages: {len(user_messages)}")

    system_prompt = generate_multiagent_expert_prompt(
        expert_name, idx, total_experts, 1, False, "", "parallel", state["language"]
    )

    # Inject public-only cross-turn history if enabled
    if state.get("expert_full_history", False):
        cross_turn_public = _get_collab_public_history(state.get("cross_turn_history", []))
        print(f"[MultiAgent:ParallelExpert]   Cross-turn history: {len(cross_turn_public)} messages")
        system_prompt += "\n\nConversation history from prior turns is included for context. The most recent user message is your current task."
        sep = "\n\n" + "─" * 6 + "\n\n"
        if (cross_turn_public and user_messages
                and isinstance(cross_turn_public[-1], HumanMessage)
                and isinstance(user_messages[0], HumanMessage)):
            merged = HumanMessage(content=cross_turn_public[-1].content + sep + user_messages[0].content)
            history = cross_turn_public[:-1] + [merged] + user_messages[1:]
        else:
            history = cross_turn_public + user_messages
    else:
        history = user_messages

    messages = [SystemMessage(content=system_prompt)] + history

    # Trim to fit context window
    max_ctx = get_max_context_tokens(config, "expert", idx)
    messages = trim_to_fit(messages, model_name, max_ctx)

    print(f"[MultiAgent:ParallelExpert]   Invoking model...")
    model_with_tools = model.bind_tools(tools, strict=_needs_strict(model))
    response = invoke_with_timeout(model_with_tools, messages, get_llm_timeout(config), label=expert_name)

    # If tool calls, add to history temporarily for execution
    if response.tool_calls:
        print(f"[MultiAgent:ParallelExpert]   Response has {len(response.tool_calls)} tool call(s): {[tc['name'] for tc in response.tool_calls]}")
        return {
            "messages": [response],
            "last_tool_caller": "expert"
        }

    # Text response: Store in separate dict
    content_text = extract_text_from_content(response.content)
    print(f"[MultiAgent:ParallelExpert]   Response text: {content_text[:100]}...")
    return {
        "parallel_responses": {expert_name: content_text},
        "current_expert_index": idx + 1,
    }

def parallel_tool_post_processing_node(state: MultiAgentState, config):
    """Refines tool output in parallel mode."""
    idx = state["current_expert_index"]
    model = get_model(config, "expert", idx)
    tools = get_tools_list(config, "expert")

    expert_name = f"Expert_{idx+1}"
    total_experts = len(config["configurable"]["expert_models"])

    model_name = get_model_name(model)
    print(f"[MultiAgent:ParallelPostProcess] Post-processing for {expert_name}")
    print(f"[MultiAgent:ParallelPostProcess]   Model: {model.__class__.__name__} (model_name: {model_name})")

    system_prompt = generate_multiagent_expert_prompt(
        expert_name, idx, total_experts, 1, False, "", "parallel", state["language"]
    )

    # Experts are stateless across tasks: user messages + own tool chain only
    user_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    expert_tool_chain = _get_current_expert_tool_chain(state["messages"])

    # Inject public-only cross-turn history if enabled
    if state.get("expert_full_history", False):
        cross_turn_public = _get_collab_public_history(state.get("cross_turn_history", []))
        system_prompt += "\n\nConversation history from prior turns is included for context. The most recent user message is your current task."
        sep = "\n\n" + "─" * 6 + "\n\n"
        if (cross_turn_public and user_messages
                and isinstance(cross_turn_public[-1], HumanMessage)
                and isinstance(user_messages[0], HumanMessage)):
            merged = HumanMessage(content=cross_turn_public[-1].content + sep + user_messages[0].content)
            history = cross_turn_public[:-1] + [merged] + user_messages[1:]
        else:
            history = cross_turn_public + user_messages
    else:
        history = user_messages

    messages = [SystemMessage(content=system_prompt)] + history + expert_tool_chain
    print(f"[MultiAgent:ParallelPostProcess]   Message history: {_format_message_counts(messages)}")

    # Trim to fit context window
    max_ctx = get_max_context_tokens(config, "expert", idx)
    messages = trim_to_fit(messages, model_name, max_ctx)

    print(f"[MultiAgent:ParallelPostProcess]   Invoking model for refinement...")
    model_with_tools = model.bind_tools(tools, strict=_needs_strict(model))
    response = invoke_with_timeout(model_with_tools, messages, get_llm_timeout(config), label=f"{expert_name}:PostProcess")

    # If more tool calls, track caller for routing
    if response.tool_calls:
        print(f"[MultiAgent:ParallelPostProcess]   Response has {len(response.tool_calls)} more tool call(s): {[tc['name'] for tc in response.tool_calls]}")
        return {
            "messages": [response],
            "last_tool_caller": "expert"
        }

    # Text response: finalize expert output
    content_text = extract_text_from_content(response.content)
    print(f"[MultiAgent:ParallelPostProcess]   Final response: {content_text[:100]}...")
    print(f"[MultiAgent:ParallelPostProcess]   Moving to next expert (index {idx+1})")
    return {
        "messages": [response],
        "parallel_responses": {expert_name: content_text},
        "current_expert_index": idx + 1
    }

def synthesizer_node(state: MultiAgentState, config):
    """Combines parallel outputs."""
    model = get_model(config, "synthesizer")
    tools = get_tools_list(config, "supervisor")

    model_name = get_model_name(model)
    print(f"[MultiAgent:Synthesizer] Starting synthesis")
    print(f"[MultiAgent:Synthesizer]   Model: {model.__class__.__name__} (model_name: {model_name})")
    print(f"[MultiAgent:Synthesizer]   Tools: {[t.name for t in tools]}")
    print(f"[MultiAgent:Synthesizer]   Expert responses to combine: {list(state['parallel_responses'].keys())}")

    prompt = generate_multiagent_synthesizer_prompt(state["language"], tools=tools)

    # Append additional behavioral instructions if provided
    extra = state.get("additional_system_prompt", "")
    if extra:
        prompt += "\n\n# Additional behavior instructions\n" + extra

    # Build expert responses as text for a HumanMessage
    expert_data = [{"expert": k, "response": v} for k, v in state["parallel_responses"].items()]
    expert_text = format_expert_responses_message(expert_data)

    # Conversation history (ends with user HumanMessage) + synthesizer's own tool chain
    cross_turn = state.get("cross_turn_history", [])
    conv_history, synth_tool_chain = _get_synthesizer_context(state["messages"])

    # Merge expert responses into last HumanMessage (the user query)
    # Same pattern as collaborative: consecutive HumanMessages get merged
    sep = "\n\n" + "─" * 6 + "\n\n"
    if conv_history and isinstance(conv_history[-1], HumanMessage):
        conv_history[-1] = HumanMessage(
            content=conv_history[-1].content + sep + expert_text
        )
    else:
        conv_history.append(HumanMessage(content=expert_text))

    # Cross-turn boundary merge (same as overseer_node / final_answer_node)
    if (cross_turn and conv_history
            and isinstance(cross_turn[-1], HumanMessage)
            and isinstance(conv_history[0], HumanMessage)):
        merged = HumanMessage(content=cross_turn[-1].content + sep + conv_history[0].content)
        history = cross_turn[:-1] + [merged] + conv_history[1:]
    else:
        history = cross_turn + conv_history

    messages = [SystemMessage(content=prompt)] + history + synth_tool_chain

    # Trim to fit context window
    max_ctx = get_max_context_tokens(config, "synthesizer")
    messages = trim_to_fit(messages, model_name, max_ctx)

    print(f"[MultiAgent:Synthesizer]   Invoking model...")
    model_with_tools = model.bind_tools(tools, strict=_needs_strict(model))
    response = invoke_with_timeout(model_with_tools, messages, get_llm_timeout(config), label="Synthesizer")

    # Tag the synthesizer response
    response.name = "Synthesizer"

    # Track caller for routing
    if response.tool_calls:
        print(f"[MultiAgent:Synthesizer]   Response has {len(response.tool_calls)} tool call(s): {[tc['name'] for tc in response.tool_calls]}")
        return {
            "messages": [response],
            "last_tool_caller": "synthesizer"
        }

    content_text = extract_text_from_content(response.content)
    print(f"[MultiAgent:Synthesizer]   Final response: {content_text[:100]}...")
    return {"messages": [response]}

# -- Collaborative Mode Nodes --

def collab_expert_node(state: MultiAgentState, config):
    """Runs the current expert in the collaborative cycle.

    Combined mode (default): Binds both tools AND structured output (ExpertOutput)
    on a single LLM call. When the model calls tools, the structured output
    constraint doesn't apply. When the model responds with text (no tool calls),
    the response is JSON conforming to ExpertOutput.

    Legacy mode: Binds tools only (no structured output). Free-text responses
    are parsed inline for <public>/<private> XML tags. If parsing fails, a cheap
    formatter model extracts the structured output.
    """
    idx = state["current_expert_index"]
    model = get_model(config, "expert", idx)
    tools = get_tools_list(config, "expert")
    legacy_mode = config["configurable"].get("legacy_mode", False)

    expert_name = f"Expert_{idx+1}"
    total_experts = len(config["configurable"]["expert_models"])
    memory = state["expert_memories"].get(str(idx), "")

    model_name = get_model_name(model)
    mode_label = "legacy" if legacy_mode else "combined"
    print(f"[MultiAgent:CollabExpert] Starting {expert_name} ({idx+1}/{total_experts}) [{mode_label}]")
    print(f"[MultiAgent:CollabExpert]   Round: {state['current_round']}/{state['max_rounds']}")
    print(f"[MultiAgent:CollabExpert]   Model: {model.__class__.__name__} (model_name: {model_name})")
    print(f"[MultiAgent:CollabExpert]   Tools: {[t.name for t in tools]}")
    print(f"[MultiAgent:CollabExpert]   Memory: {memory[:50] if memory else 'None'}...")

    system_prompt = generate_multiagent_expert_prompt(
        expert_name, idx, total_experts, state["current_round"],
        True, memory, "collaborative", state["language"],
        legacy_mode=legacy_mode,
    )

    # Current task discussion + own tool chain
    public_history = _get_collab_public_history(state["messages"])
    public_history = _adapt_collab_history_for_expert(public_history, expert_name)
    own_tool_chain = _get_current_expert_tool_chain(state["messages"])

    # Inject public-only cross-turn history if enabled
    if state.get("expert_full_history", False):
        cross_turn_public = _get_collab_public_history(state.get("cross_turn_history", []))
        print(f"[MultiAgent:CollabExpert]   Cross-turn history: {len(cross_turn_public)} messages")
        system_prompt += "\n\nConversation history from prior turns is included for context. The most recent user message is your current task."
        sep = "\n\n" + "─" * 6 + "\n\n"
        if (cross_turn_public and public_history
                and isinstance(cross_turn_public[-1], HumanMessage)
                and isinstance(public_history[0], HumanMessage)):
            merged = HumanMessage(content=cross_turn_public[-1].content + sep + public_history[0].content)
            history = cross_turn_public[:-1] + [merged] + public_history[1:]
        else:
            history = cross_turn_public + public_history
    else:
        history = public_history

    messages = [SystemMessage(content=system_prompt)] + history + own_tool_chain
    print(f"[MultiAgent:CollabExpert]   Message history: {_format_message_counts(messages)}")

    # Trim to fit context window
    max_ctx = get_max_context_tokens(config, "expert", idx)
    messages = trim_to_fit(messages, model_name, max_ctx)

    if legacy_mode:
        # Legacy mode Step 1: tools only, no structured output
        print(f"[MultiAgent:CollabExpert]   Invoking model (tools only, legacy mode)...")
        if tools:
            bound_model = model.bind_tools(tools, strict=_needs_strict(model))
        else:
            bound_model = model
        for empty_attempt in range(MAX_EMPTY_RETRIES + 1):
            response = invoke_with_timeout(bound_model, messages, get_llm_timeout(config), label=expert_name)
            print(f"[MultiAgent:CollabExpert]   Stop reason: {_get_stop_reason(response)}")
            response.name = expert_name

            if response.tool_calls:
                print(f"[MultiAgent:CollabExpert]   Response has {len(response.tool_calls)} tool call(s): {[tc['name'] for tc in response.tool_calls]}")
                return {
                    "messages": [response],
                    "last_tool_caller": "expert"
                }

            # Free text: try inline tag parsing, then formatter fallback
            content_text = extract_text_from_content(response.content)
            if content_text:
                print(f"[MultiAgent:CollabExpert]   Free text response (legacy): {content_text[:200]}...")
                break

            # Empty content — retry or raise
            if empty_attempt < MAX_EMPTY_RETRIES:
                print(f"[MultiAgent:CollabExpert]   WARNING: Empty content (attempt {empty_attempt+1}/{MAX_EMPTY_RETRIES+1}), retrying...")
            else:
                _dump_empty_content_debug(messages, response, model, tools, expert_name)
                raise ValueError(f"{expert_name} returned empty content in legacy mode after {MAX_EMPTY_RETRIES+1} attempts. stop_reason={_get_stop_reason(response)}, content type={type(response.content).__name__}, repr={repr(response.content)[:500]}")

        # Step A: Try parsing <public>/<private> XML tags
        output = _parse_expert_tags(content_text)

        if output is None:
            # Step B: Tags not found — use cheap formatter model
            print(f"[MultiAgent:CollabExpert]   Tag parsing failed, using formatter model...")
            formatter_model_obj = config["configurable"].get("formatter_model")
            if formatter_model_obj is None:
                raise ValueError(
                    f"{expert_name} response did not contain valid <public>/<private> tags "
                    f"and no formatter model is configured. Configure a Formatter Model in "
                    f"Settings -> Multi-Agent. Response preview: {content_text[:300]}"
                )
            formatter_model_name = get_model_name(formatter_model_obj)
            print(f"[MultiAgent:CollabExpert]   Formatter: {formatter_model_obj.__class__.__name__} ({formatter_model_name})")

            structured_formatter = formatter_model_obj.with_structured_output(ExpertOutput)
            format_messages = [HumanMessage(content=(
                f"Extract the public response and private memory from the text below.\n"
                f"- public_response: The expert's analysis and recommendations (visible to others)\n"
                f"- private_memory: Analytical scratchpad — independent doubts, hypotheses, or alternative approaches (not shared)\n\n"
                f"---\n\n"
                f"{content_text}\n"
            ))]
            output = invoke_with_timeout(
                structured_formatter, format_messages, get_llm_timeout(config), label=f"{expert_name}_formatter"
            )
            print(f"[MultiAgent:CollabExpert]   Formatter extracted - Public: {output.public_response[:200]}...")
            print(f"[MultiAgent:CollabExpert]   Formatter extracted - Memory: {output.private_memory[:100]}...")
        else:
            print(f"[MultiAgent:CollabExpert]   Tag parsing succeeded")
            print(f"[MultiAgent:CollabExpert]   Public response: {output.public_response[:200]}...")
            print(f"[MultiAgent:CollabExpert]   Private memory: {output.private_memory[:100]}...")

        # Create XML-tagged message for shared history (same as combined mode)
        public_content = f"<{expert_name}>\n{output.public_response}\n</{expert_name}>"
        public_msg = AIMessage(content=public_content, name=expert_name)

        next_idx = idx + 1
        print(f"[MultiAgent:CollabExpert]   Moving to next expert (index {next_idx})")

        return {
            "messages": [public_msg],
            "expert_memories": {str(idx): output.private_memory},
            "current_expert_index": next_idx
        }
    else:
        # Combined mode: bind both tools and structured output schema on a single call
        print(f"[MultiAgent:CollabExpert]   Invoking model (tools + structured output)...")
        bound_model = bind_tools_and_schema(model, tools, ExpertOutput)
        for empty_attempt in range(MAX_EMPTY_RETRIES + 1):
            response = invoke_with_timeout(bound_model, messages, get_llm_timeout(config), label=expert_name)
            print(f"[MultiAgent:CollabExpert]   Stop reason: {_get_stop_reason(response)}")

            # Tag message with expert name
            response.name = expert_name

            # Tool calls: route to tool execution (structured output doesn't apply)
            if response.tool_calls:
                print(f"[MultiAgent:CollabExpert]   Response has {len(response.tool_calls)} tool call(s): {[tc['name'] for tc in response.tool_calls]}")
                return {
                    "messages": [response],
                    "last_tool_caller": "expert"
                }

            # Text response: parse structured JSON output
            raw_json = extract_text_from_content(response.content)
            if raw_json:
                print(f"[MultiAgent:CollabExpert]   Raw JSON response: {raw_json[:200]}...")
                break

            # Empty content — retry or raise
            if empty_attempt < MAX_EMPTY_RETRIES:
                print(f"[MultiAgent:CollabExpert]   WARNING: Empty content (attempt {empty_attempt+1}/{MAX_EMPTY_RETRIES+1}), retrying...")
            else:
                print(f"[MultiAgent:CollabExpert]   ERROR: Empty text extracted from response")
                print(f"[MultiAgent:CollabExpert]   response.content type={type(response.content).__name__}, repr={repr(response.content)[:500]}")
                print(f"[MultiAgent:CollabExpert]   response_metadata: {response.response_metadata}")
                _dump_empty_content_debug(messages, response, model, tools, expert_name)
                raise ValueError(f"{expert_name} returned empty content (no text to parse as JSON) after {MAX_EMPTY_RETRIES+1} attempts. stop_reason={_get_stop_reason(response)}, content type={type(response.content).__name__}, repr={repr(response.content)[:500]}")
        output = ExpertOutput.model_validate_json(raw_json)

        print(f"[MultiAgent:CollabExpert]   Public response: {output.public_response[:200]}...")
        print(f"[MultiAgent:CollabExpert]   Private memory: {output.private_memory[:100]}...")

        # Create XML-tagged message for shared history
        public_content = f"<{expert_name}>\n{output.public_response}\n</{expert_name}>"
        public_msg = AIMessage(content=public_content, name=expert_name)

        next_idx = idx + 1
        print(f"[MultiAgent:CollabExpert]   Moving to next expert (index {next_idx})")

        return {
            "messages": [public_msg],
            "expert_memories": {str(idx): output.private_memory},
            "current_expert_index": next_idx
        }


def overseer_node(state: MultiAgentState, config):
    """Overseer evaluates the round."""
    model = get_model(config, "overseer")
    total_experts = len(config["configurable"]["expert_models"])

    model_name = get_model_name(model)
    print(f"[MultiAgent:Overseer] Evaluating round {state['current_round']}/{state['max_rounds']}")
    print(f"[MultiAgent:Overseer]   Model: {model.__class__.__name__} (model_name: {model_name})")

    system_prompt = generate_multiagent_overseer_prompt(
        total_experts, state["current_round"], state["max_rounds"], state["language"]
    )

    # Append additional behavioral instructions if provided
    extra = state.get("additional_system_prompt", "")
    if extra:
        system_prompt += "\n\n# Additional behavior instructions\n" + extra

    cross_turn = state.get("cross_turn_history", [])
    public_history = _get_collab_public_history(state["messages"])
    adapted_public = _adapt_collab_history_for_expert(public_history, "Overseer", convert_own=True)
    # Cross-turn history + public history only (no tool interactions)
    if 0:
        messages = [SystemMessage(content=system_prompt)] + cross_turn + adapted_public
    else:
        sep = "\n\n" + "─" * 6 + "\n\n"
        if (cross_turn and adapted_public
                and isinstance(cross_turn[-1], HumanMessage)
                and isinstance(adapted_public[0], HumanMessage)):
            merged_boundary = HumanMessage(content=cross_turn[-1].content + sep + adapted_public[0].content)
            history = cross_turn[:-1] + [merged_boundary] + adapted_public[1:]
            print(f"[MultiAgent:Overseer] adapted cross-turn content")
        else:
            history = cross_turn + adapted_public
        messages = [SystemMessage(content=system_prompt)] + history

    print(f"[MultiAgent:Overseer]   Message history: {_format_message_counts(messages)}")

    # Trim to fit context window
    max_ctx = get_max_context_tokens(config, "overseer")
    messages = trim_to_fit(messages, model_name, max_ctx)

    print(f"[MultiAgent:Overseer]   Invoking decider...")
    decider = model.with_structured_output(OverseerDecision)
    output: OverseerDecision = invoke_with_timeout(decider, messages, get_llm_timeout(config), label="Overseer")

    print(f"[MultiAgent:Overseer]   Decision: {output.decision}")
    print(f"[MultiAgent:Overseer]   Reasoning: {output.reasoning_feedback[:100]}...")

    # Store decision + reasoning so final_answer model has useful context
    decision_content = f"{output.decision}: {output.reasoning_feedback}"
    feedback_msg = AIMessage(content=decision_content, name="Overseer")

    if output.decision == "CONCLUDE" or state["current_round"] >= state["max_rounds"]:
        print(f"[MultiAgent:Overseer]   -> Moving to final_answer")
        return {
            "messages": [feedback_msg],
            "next_node": "final_answer"
        }
    else:
        print(f"[MultiAgent:Overseer]   -> Starting round {state['current_round'] + 1}")
        return {
            "messages": [feedback_msg],
            "next_node": "expert_loop",
            "current_round": state["current_round"] + 1,
            "current_expert_index": 0
        }

def final_answer_node(state: MultiAgentState, config):
    """Produces the final text response."""
    model = get_model(config, "overseer")
    tools = get_tools_list(config, "supervisor")

    model_name = get_model_name(model)
    print(f"[MultiAgent:FinalAnswer] Starting final answer generation")
    print(f"[MultiAgent:FinalAnswer]   Model: {model.__class__.__name__} (model_name: {model_name})")
    print(f"[MultiAgent:FinalAnswer]   Tools: {[t.name for t in tools]}")

    system_prompt = generate_multiagent_overseer_final_prompt(state["language"], tools=tools)

    # Cross-turn history + public history + own tool chain (final_answer uses write tools)
    cross_turn = state.get("cross_turn_history", [])
    public_history = _get_collab_public_history(state["messages"])    
    adapted_public = _adapt_collab_history_for_expert(public_history, "Overseer", convert_own=True)    
    own_tool_chain = _get_current_expert_tool_chain(state["messages"])    
    if 0:
        messages = [SystemMessage(content=system_prompt)] + cross_turn + adapted_public + own_tool_chain
    else:
        sep = "\n\n" + "─" * 6 + "\n\n"
        if (cross_turn and adapted_public
                and isinstance(cross_turn[-1], HumanMessage)
                and isinstance(adapted_public[0], HumanMessage)):
            merged_boundary = HumanMessage(content=cross_turn[-1].content + sep + adapted_public[0].content)
            history = cross_turn[:-1] + [merged_boundary] + adapted_public[1:]
            print(f"[MultiAgent:FinalAnswer]   Adapted cross-turn content")
        else:
            history = cross_turn + adapted_public
        messages = [SystemMessage(content=system_prompt)] + history + own_tool_chain
    print(f"[MultiAgent:FinalAnswer]   Message history: {_format_message_counts(messages)}")

    # Trim to fit context window
    max_ctx = get_max_context_tokens(config, "overseer")
    messages = trim_to_fit(messages, model_name, max_ctx)

    print(f"[MultiAgent:FinalAnswer]   Invoking model...")
    model_with_tools = model.bind_tools(tools, strict=_needs_strict(model))
    response = invoke_with_timeout(model_with_tools, messages, get_llm_timeout(config), label="FinalAnswer")
    response.name = "Overseer"

    # Track caller for routing
    if response.tool_calls:
        print(f"[MultiAgent:FinalAnswer]   Response has {len(response.tool_calls)} tool call(s): {[tc['name'] for tc in response.tool_calls]}")
        return {
            "messages": [response],
            "last_tool_caller": "overseer"
        }

    content_text = extract_text_from_content(response.content)
    print(f"[MultiAgent:FinalAnswer]   Final response: {content_text[:100]}...")
    return {"messages": [response]}

# --- 4. Routing Logic ---

def route_parallel(state: MultiAgentState, config):
    last_msg = state["messages"][-1]

    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        print(f"[MultiAgent:Route:Parallel] -> tools ({last_msg.tool_calls[0]['name']})")
        return "tools"

    # No tool calls: check if more experts need to run or move to synthesizer
    current_idx = state["current_expert_index"]
    total_experts = len(config["configurable"]["expert_models"])

    if current_idx < total_experts:
        print(f"[MultiAgent:Route:Parallel] -> parallel_expert (expert {current_idx+1}/{total_experts})")
        return "parallel_expert"
    print(f"[MultiAgent:Route:Parallel] -> synthesizer (all experts done)")
    return "synthesizer"

def route_collaborative(state: MultiAgentState, config):
    """Route after collab_expert: tools, next expert, or overseer."""
    last_msg = state["messages"][-1]

    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        print(f"[MultiAgent:Route:Collaborative] -> tools ({last_msg.tool_calls[0]['name']})")
        return "tools"

    # Both legacy and combined: expert finished. Check if more experts remain.
    current_idx = state["current_expert_index"]
    total_experts = len(config["configurable"]["expert_models"])

    if current_idx < total_experts:
        print(f"[MultiAgent:Route:Collaborative] -> collab_expert (expert {current_idx+1}/{total_experts})")
        return "collab_expert"
    print(f"[MultiAgent:Route:Collaborative] -> overseer (all experts done)")
    return "overseer"

def route_overseer(state: MultiAgentState):
    next_node = state["next_node"]
    print(f"[MultiAgent:Route:Overseer] -> {next_node}")
    return next_node

def route_synthesizer(state: MultiAgentState):
    """Route synthesizer output - check for tool calls or end."""
    last_msg = state["messages"][-1]

    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        print(f"[MultiAgent:Route:Synthesizer] -> tools ({last_msg.tool_calls[0]['name']})")
        return "tools"

    print(f"[MultiAgent:Route:Synthesizer] -> end (no tool calls)")
    return "end"

def route_final_answer(state: MultiAgentState):
    """Route final_answer output - check for tool calls or end."""
    last_msg = state["messages"][-1]

    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        print(f"[MultiAgent:Route:FinalAnswer] -> tools ({last_msg.tool_calls[0]['name']})")
        return "tools"

    print(f"[MultiAgent:Route:FinalAnswer] -> end (no tool calls)")
    return "end"

def route_start(state: MultiAgentState):
    mode = state["mode"]
    print(f"[MultiAgent:Route:Start] Mode: {mode}")
    if mode == "parallel":
        print(f"[MultiAgent:Route:Start] -> parallel_expert")
        return "parallel_router"
    print(f"[MultiAgent:Route:Start] -> collab_expert")
    return "collab_router"


def route_after_tools(state: MultiAgentState):
    """Route tool results back to the correct mode-specific node."""
    caller = state.get("last_tool_caller", "expert")
    mode = state["mode"]

    print(f"[MultiAgent:Route:AfterTools] Caller: {caller}, Mode: {mode}")

    if caller == "synthesizer":
        print(f"[MultiAgent:Route:AfterTools] -> synthesizer")
        return "synthesizer"
    elif caller == "overseer":
        print(f"[MultiAgent:Route:AfterTools] -> final_answer")
        return "final_answer"
    else:  # expert
        if mode == "parallel":
            print(f"[MultiAgent:Route:AfterTools] -> parallel_post_process")
            return "parallel_post_process"
        print(f"[MultiAgent:Route:AfterTools] -> collab_expert")
        return "collab_expert"

# --- 5. Graph Construction ---

def _build_graph():
    """Build and compile the unified multiagent graph.

    Both legacy and combined collaborative modes use the same graph structure.
    The legacy vs combined distinction is handled inside collab_expert_node.
    """
    workflow = StateGraph(MultiAgentState)

    # Nodes
    workflow.add_node("tools", tool_node)

    workflow.add_node("parallel_expert", parallel_expert_node, retry_policy=LLM_RETRY_POLICY)
    workflow.add_node("parallel_post_process", parallel_tool_post_processing_node, retry_policy=LLM_RETRY_POLICY)
    workflow.add_node("synthesizer", synthesizer_node, retry_policy=LLM_RETRY_POLICY)

    workflow.add_node("collab_expert", collab_expert_node, retry_policy=LLM_RETRY_POLICY)
    workflow.add_node("overseer", overseer_node, retry_policy=LLM_RETRY_POLICY)
    workflow.add_node("final_answer", final_answer_node, retry_policy=LLM_RETRY_POLICY)

    # Edges
    workflow.add_conditional_edges(START, route_start, {
        "parallel_router": "parallel_expert",
        "collab_router": "collab_expert"
    })

    # Parallel
    workflow.add_conditional_edges("parallel_expert", route_parallel, {
        "tools": "tools",
        "parallel_post_process": "parallel_post_process",
        "parallel_expert": "parallel_expert",
        "synthesizer": "synthesizer"
    })
    workflow.add_conditional_edges("tools", route_after_tools, {
        "parallel_post_process": "parallel_post_process",
        "collab_expert": "collab_expert",
        "synthesizer": "synthesizer",
        "final_answer": "final_answer"
    })
    workflow.add_conditional_edges("parallel_post_process", route_parallel, {
        "tools": "tools",
        "parallel_expert": "parallel_expert",
        "synthesizer": "synthesizer"
    })
    workflow.add_conditional_edges("synthesizer", route_synthesizer, {
        "tools": "tools",
        "end": END
    })

    # Collaborative (unified for both legacy and combined modes)
    workflow.add_conditional_edges("collab_expert", route_collaborative, {
        "tools": "tools",
        "collab_expert": "collab_expert",
        "overseer": "overseer"
    })

    workflow.add_conditional_edges("overseer", route_overseer, {
        "final_answer": "final_answer",
        "expert_loop": "collab_expert"
    })
    workflow.add_conditional_edges("final_answer", route_final_answer, {
        "tools": "tools",
        "end": END
    })

    return workflow.compile(checkpointer=MemorySaver())


# Single compiled graph (both legacy and combined use same structure)
graph = _build_graph()


def _get_graph(legacy: bool = False):
    """Select the compiled graph. Now unified for both modes."""
    return graph

# --- 6. Helper: Stream Processor ---

async def _process_multiagent_stream(event_stream, valid_tool_names: set[str] | None = None):
    """Process LangGraph events and yield complete message/tool_call events.

    No token-by-token streaming: each 'message' event is a complete, self-contained
    text bubble. Each 'tool_call' event is a complete tool invocation. The frontend
    creates one GUI bubble per event with no accumulation logic.
    """
    current_speaker = None
    current_round = None  # Track round number for collaborative mode

    async for event in event_stream:
        # Track speaker changes on chain start
        if event["event"] == "on_chain_start":
            node = event.get("metadata", {}).get("langgraph_node", "")
            input_data = event["data"].get("input")

            if node == "parallel_expert":
                expert_idx = input_data.get("current_expert_index", 0) if isinstance(input_data, dict) else 0
                current_speaker = f"Expert_{expert_idx + 1}"
            elif node == "parallel_post_process":
                if isinstance(input_data, dict):
                    expert_idx = input_data.get("current_expert_index", 0)
                    current_speaker = f"Expert_{expert_idx + 1}"
            elif node == "tools":
                if isinstance(input_data, dict):
                    caller = input_data.get("last_tool_caller", "expert")
                    if caller == "expert":
                        expert_idx = input_data.get("current_expert_index", 0)
                        current_speaker = f"Expert_{expert_idx + 1}"
                    elif caller == "synthesizer":
                        current_speaker = "Synthesizer"
                    elif caller == "overseer":
                        current_speaker = "Overseer"
            elif node == "synthesizer":
                current_speaker = "Synthesizer"
            elif node == "collab_expert":
                expert_idx = input_data.get("current_expert_index", 0) if isinstance(input_data, dict) else 0
                current_speaker = f"Expert_{expert_idx + 1}"
                current_round = input_data.get("current_round", 1) if isinstance(input_data, dict) else 1
            elif node == "overseer":
                current_speaker = "Overseer"
            elif node == "final_answer":
                current_speaker = "Overseer"

        elif event["event"] == "on_tool_start":
            tool_name = event.get("name", "?")
            if valid_tool_names is not None and tool_name not in valid_tool_names:
                print(f"[MultiAgentStream] SKIP unknown tool_call: {tool_name}")
                continue
            if not current_speaker:
                raise ValueError(f"[MultiAgentStream] BUG: Emitting tool_call with speaker=None (tool={tool_name}). Every multiagent event must have a valid speaker.")
            yield {"event": "tool_call", "data": {"name": tool_name, "args": event.get("data", {}).get("input"), "speaker": current_speaker}}

        elif event["event"] == "on_chain_end":
            node = event.get("metadata", {}).get("langgraph_node", "")
            output = event["data"].get("output")

            # Only process dict outputs (node-level), skip string outputs (model-level)
            if not isinstance(output, dict):
                continue

            msgs = output.get("messages", [])
            parallel_resp = output.get("parallel_responses", {})

            if node == "parallel_expert":
                if parallel_resp:
                    # No tool calls — emit complete expert response from parallel_responses
                    expert_name = list(parallel_resp.keys())[0]
                    content_text = list(parallel_resp.values())[0]
                    if content_text:
                        yield {"event": "message", "data": {"content": content_text, "speaker": expert_name}}
                elif msgs:
                    # Has tool calls — emit pre-tool text if any (e.g. "Let me search...")
                    content = extract_text_from_content(msgs[0].content)
                    if content:
                        if not current_speaker:
                            raise ValueError(f"[MultiAgentStream] BUG: Emitting message with speaker=None (node=parallel_expert). Every multiagent event must have a valid speaker.")
                        yield {"event": "message", "data": {"content": content, "speaker": current_speaker}}

            elif node == "parallel_post_process":
                if parallel_resp:
                    # Final response (no more tools) — emit from messages
                    expert_name = list(parallel_resp.keys())[0]
                    content_text = extract_text_from_content(msgs[0].content) if msgs else ""
                    if content_text:
                        yield {"event": "message", "data": {"content": content_text, "speaker": expert_name}}
                elif msgs:
                    # Has tool calls — emit pre-tool text if any
                    content = extract_text_from_content(msgs[0].content)
                    if content:
                        if not current_speaker:
                            raise ValueError(f"[MultiAgentStream] BUG: Emitting message with speaker=None (node=parallel_post_process). Every multiagent event must have a valid speaker.")
                        yield {"event": "message", "data": {"content": content, "speaker": current_speaker}}

            elif node == "collab_expert":
                if msgs:
                    last_output_msg = msgs[0]
                    if isinstance(last_output_msg, AIMessage) and not getattr(last_output_msg, 'tool_calls', None):
                        speaker = getattr(last_output_msg, 'name', None) or current_speaker or "Expert"
                        content_text = extract_text_from_content(last_output_msg.content)
                        # Strip XML expert tags used for LLM context (not for GUI display)
                        for tag in [f"<{speaker}>", f"</{speaker}>"]:
                            content_text = content_text.replace(tag, "")
                        content_text = content_text.strip()
                        if content_text:
                            yield {"event": "message", "data": {"content": content_text, "speaker": speaker, "round": current_round}}

            elif node == "overseer":
                if msgs:
                    full_content = extract_text_from_content(msgs[0].content)
                    if full_content:
                        # Extract just the decision word (before colon) for the GUI
                        decision = full_content.split(":")[0].strip()
                        yield {"event": "overseer_decision", "data": {"decision": decision, "speaker": "Overseer"}}

            elif node == "synthesizer":
                if msgs and msgs[0].content:
                    content_text = extract_text_from_content(msgs[0].content)
                    if content_text:
                        yield {"event": "message", "data": {"content": content_text, "speaker": "Synthesizer"}}

            elif node == "final_answer":
                if msgs:
                    content = extract_text_from_content(msgs[0].content)
                    if content:
                        yield {"event": "message", "data": {"content": content, "speaker": "Overseer"}}


# --- 7. Result Extraction Helper ---

def _extract_multiagent_public_response(config, mode: str, active_graph=None) -> AIMessage | None:
    """Extract the public response from a completed multiagent graph execution.

    Parallel mode: last AIMessage from Synthesizer with no tool_calls.
    Collaborative mode: last AIMessage from Overseer with no tool_calls.
    """
    g = active_graph or graph
    snapshot = g.get_state(config)
    all_msgs = snapshot.values.get("messages", [])

    target_name = "Synthesizer" if mode == "parallel" else "Overseer"

    for msg in reversed(all_msgs):
        if (isinstance(msg, AIMessage)
                and getattr(msg, 'name', None) == target_name
                and not msg.tool_calls):
            return msg

    return None


def _extract_consigliere_tool_interactions(config, mode: str, active_graph=None) -> list[BaseMessage]:
    """Extract overseer/synthesizer tool interactions from a completed graph.

    Returns AIMessages with tool_calls and their ToolMessage results that
    belong to the consigliere persona (synthesizer in parallel mode, overseer
    in collaborative mode).  Expert tool interactions are excluded.
    """
    g = active_graph or graph
    snapshot = g.get_state(config)
    all_msgs = snapshot.values.get("messages", [])
    target_name = "Synthesizer" if mode == "parallel" else "Overseer"

    # Collect tool_call IDs belonging to the consigliere persona
    consigliere_call_ids: set[str] = set()
    result: list[BaseMessage] = []

    for msg in all_msgs:
        if isinstance(msg, AIMessage) and msg.tool_calls and getattr(msg, 'name', None) == target_name:
            result.append(msg)
            for tc in msg.tool_calls:
                if tc["id"]:
                    consigliere_call_ids.add(tc["id"])
        elif isinstance(msg, ToolMessage) and msg.tool_call_id in consigliere_call_ids:
            result.append(msg)

    return result


# --- 8. Exported Functions (API) ---

_session_config_cache = {}
_session_graph_cache = {}  # Maps thread_id -> compiled graph reference

async def stream_multiagent(
    mode: Literal["parallel", "collaborative"],
    expert_models: list[BaseChatModel],
    overseer_model: BaseChatModel,
    synthesizer_model: BaseChatModel,
    messages: list,
    max_rounds: int,
    use_expert_memory: bool,
    expert_server_tools: list,
    expert_client_tools: list,
    supervisor_server_tools: list,
    supervisor_client_tools: list,
    recursion_limit: int,
    language: str = "English",
    additional_system_prompt: str | None = None,
    conversation_id: str | None = None,
    conversation_store: Any = None,
    expert_max_context_tokens: list[int] | None = None,
    overseer_max_context_tokens: int = 128000,
    synthesizer_max_context_tokens: int = 128000,
    llm_timeout: int = 60,
    legacy_mode: bool = False,
    formatter_model: BaseChatModel | None = None,
    expert_full_history: bool = False,
) -> AsyncGenerator[dict[str, Any], None]:

    # Log model configuration at entry point
    expert_model_names = [get_model_name(m) for m in expert_models]
    overseer_model_name = get_model_name(overseer_model)
    synthesizer_model_name = get_model_name(synthesizer_model)
    active_graph = _get_graph(legacy_mode)
    print(f"[stream_multiagent] Starting {mode} mode (legacy={legacy_mode})")
    print(f"[stream_multiagent]   Expert models: {[f'{type(m).__name__} ({n})' for m, n in zip(expert_models, expert_model_names)]}")
    print(f"[stream_multiagent]   Overseer: {type(overseer_model).__name__} ({overseer_model_name})")
    print(f"[stream_multiagent]   Synthesizer: {type(synthesizer_model).__name__} ({synthesizer_model_name})")
    if formatter_model:
        print(f"[stream_multiagent]   Formatter: {type(formatter_model).__name__} ({get_model_name(formatter_model)})")

    use_store = bool(conversation_id and conversation_store)
    turn = None
    cross_turn_history: list[BaseMessage] = []

    if use_store:
        turn = conversation_store.start_turn(conversation_id)
        cross_turn_history = conversation_store.get_history_for_consigliere(conversation_id)
        print(f"[MultiAgent] Conversation store turn {turn}, consigliere history: {len(cross_turn_history)}")

        # Store user message(s)
        for msg in to_langchain_messages(messages):
            if isinstance(msg, HumanMessage):
                conversation_store.add_user_message(
                    conversation_id, turn, msg,
                    "parallel" if mode == "parallel" else "collaborative",
                )

    thread_id = str(uuid.uuid4())

    config = {
        "configurable": {
            "thread_id": thread_id,
            "expert_models": expert_models,
            "overseer_model": overseer_model,
            "synthesizer_model": synthesizer_model,
            "expert_server_tools": expert_server_tools,
            "expert_client_tools": expert_client_tools,
            "supervisor_server_tools": supervisor_server_tools,
            "supervisor_client_tools": supervisor_client_tools,
            "expert_max_context_tokens": expert_max_context_tokens or [128000] * len(expert_models),
            "overseer_max_context_tokens": overseer_max_context_tokens,
            "synthesizer_max_context_tokens": synthesizer_max_context_tokens,
            "llm_timeout": llm_timeout,
            "legacy_mode": legacy_mode,
            "formatter_model": formatter_model,
        },
        "recursion_limit": recursion_limit
    }
    _session_config_cache[thread_id] = config
    _session_graph_cache[thread_id] = active_graph

    print(f"[stream_multiagent] Expert tools: {len(expert_server_tools)} server + {len(expert_client_tools)} client = {len(expert_server_tools) + len(expert_client_tools)} total | server: {[t.name for t in expert_server_tools]} | client: {[t.name for t in expert_client_tools]}")
    print(f"[stream_multiagent] Supervisor tools: {len(supervisor_server_tools)} server + {len(supervisor_client_tools)} client = {len(supervisor_server_tools) + len(supervisor_client_tools)} total | server: {[t.name for t in supervisor_server_tools]} | client: {[t.name for t in supervisor_client_tools]}")

    if use_store:
        conversation_store.register_thread(thread_id, conversation_id, turn, 0)

    initial_state = {
        "messages": to_langchain_messages(messages),
        "cross_turn_history": cross_turn_history,
        "mode": mode,
        "max_rounds": max_rounds,
        "current_round": 1,
        "language": language,
        "additional_system_prompt": additional_system_prompt or "",
        "parallel_responses": {},
        "current_expert_index": 0,
        "expert_memories": {},
        "expert_full_history": expert_full_history,
        "next_node": None,
        "last_tool_caller": None
    }

    all_tool_names = (
        {t.name for t in expert_server_tools} | {t.name for t in expert_client_tools}
        | {t.name for t in supervisor_server_tools} | {t.name for t in supervisor_client_tools}
    )

    try:
        event_stream = active_graph.astream_events(initial_state, config=config, version="v2")

        async for sse_event in _process_multiagent_stream(event_stream, all_tool_names):
            yield sse_event

        snapshot = active_graph.get_state(config)
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            interrupt_data = snapshot.tasks[0].interrupts[0].value

            # Determine speaker from state for GUI display
            state_values = snapshot.values
            caller = state_values.get("last_tool_caller")
            if caller == "expert":
                idx = state_values.get("current_expert_index", 0)
                speaker = f"Expert_{idx + 1}"
            elif caller == "synthesizer":
                speaker = "Synthesizer"
            elif caller == "overseer":
                speaker = "Overseer"
            else:
                speaker = None

            yield {
                "event": "tool_call",
                "data": {
                    "name": interrupt_data["name"],
                    "args": interrupt_data["args"],
                    "speaker": speaker
                }
            }

            yield {
                "event": "client_tool_call",
                "data": {
                    "session_id": thread_id,
                    "tool_calls": [{
                        "name": interrupt_data["name"],
                        "args": interrupt_data["args"],
                        "call_id": interrupt_data["id"]
                    }]
                }
            }
        else:
            # Store consigliere results if conversation store is active
            if use_store:
                persona = "synthesizer" if mode == "parallel" else "overseer"

                # Store consigliere tool interactions (AIMessage+tool_calls, ToolMessage)
                tool_msgs = _extract_consigliere_tool_interactions(config, mode, active_graph)
                if tool_msgs:
                    conversation_store.add_consigliere_messages(
                        conversation_id, turn, persona, mode, tool_msgs,
                    )

                # Store final public response
                public_response = _extract_multiagent_public_response(config, mode, active_graph)
                if public_response:
                    conversation_store.add_public_response(
                        conversation_id, turn, persona, mode, public_response,
                    )
                conversation_store.unregister_thread(thread_id)
            yield {"event": "done", "data": {"finish_reason": "stop"}}
            _session_config_cache.pop(thread_id, None)
            _session_graph_cache.pop(thread_id, None)

    except Exception as e:
        if use_store:
            conversation_store.rollback_response(conversation_id, turn)
            conversation_store.unregister_thread(thread_id)
        yield {"event": "error", "data": {"error": str(e)}}
        _session_config_cache.pop(thread_id, None)
        _session_graph_cache.pop(thread_id, None)


async def resume_multiagent(
    multiagent_session_id: str,
    tool_results: list[dict],
    conversation_store: Any = None,
) -> AsyncGenerator[dict[str, Any], None]:

    config = _session_config_cache.get(multiagent_session_id)
    active_graph = _session_graph_cache.get(multiagent_session_id)
    if not config or not active_graph:
        yield {"event": "error", "data": {"error": "Session context lost (server restart?)"}}
        return

    cfg = config["configurable"]
    all_tool_names = {t.name for t in
        cfg.get("expert_server_tools", []) + cfg.get("expert_client_tools", [])
        + cfg.get("supervisor_server_tools", []) + cfg.get("supervisor_client_tools", [])}

    result_str = tool_results[0]["result"]

    try:
        event_stream = active_graph.astream_events(
            Command(resume=result_str),
            config=config,
            version="v2"
        )

        async for sse_event in _process_multiagent_stream(event_stream, all_tool_names):
            yield sse_event

        snapshot = active_graph.get_state(config)
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            interrupt_data = snapshot.tasks[0].interrupts[0].value

            state_values = snapshot.values
            caller = state_values.get("last_tool_caller")
            if caller == "expert":
                idx = state_values.get("current_expert_index", 0)
                speaker = f"Expert_{idx + 1}"
            elif caller == "synthesizer":
                speaker = "Synthesizer"
            elif caller == "overseer":
                speaker = "Overseer"
            else:
                speaker = None

            yield {
                "event": "tool_call",
                "data": {
                    "name": interrupt_data["name"],
                    "args": interrupt_data["args"],
                    "speaker": speaker
                }
            }

            yield {
                "event": "client_tool_call",
                "data": {
                    "session_id": multiagent_session_id,
                    "tool_calls": [{
                        "name": interrupt_data["name"],
                        "args": interrupt_data["args"],
                        "call_id": interrupt_data["id"]
                    }]
                }
            }
        else:
            # Store consigliere results if conversation store is active
            if conversation_store:
                mapping = conversation_store.lookup_thread(multiagent_session_id)
                if mapping:
                    state_mode = snapshot.values.get("mode", "parallel")
                    persona = "synthesizer" if state_mode == "parallel" else "overseer"

                    # Store consigliere tool interactions
                    tool_msgs = _extract_consigliere_tool_interactions(config, state_mode, active_graph)
                    if tool_msgs:
                        conversation_store.add_consigliere_messages(
                            mapping.conversation_id, mapping.turn,
                            persona, state_mode, tool_msgs,
                        )

                    # Store final public response
                    public_response = _extract_multiagent_public_response(config, state_mode, active_graph)
                    if public_response:
                        conversation_store.add_public_response(
                            mapping.conversation_id, mapping.turn,
                            persona, state_mode, public_response,
                        )
                    conversation_store.unregister_thread(multiagent_session_id)
            yield {"event": "done", "data": {"finish_reason": "stop"}}
            _session_config_cache.pop(multiagent_session_id, None)
            _session_graph_cache.pop(multiagent_session_id, None)

    except Exception as e:
        if conversation_store:
            mapping = conversation_store.lookup_thread(multiagent_session_id)
            if mapping:
                conversation_store.rollback_response(mapping.conversation_id, mapping.turn)
                conversation_store.unregister_thread(multiagent_session_id)
        yield {"event": "error", "data": {"error": str(e)}}
        _session_config_cache.pop(multiagent_session_id, None)
        _session_graph_cache.pop(multiagent_session_id, None)