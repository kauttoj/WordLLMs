import json
import sys
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

# Support running from both project root and backend directory
_BACKEND_DIR = Path(__file__).parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from .schemas import (
    ChatRequest, AgentRequest, AgentContinueRequest,
    MultiAgentRequest, MultiAgentContinueRequest,
    ThreadSaveRequest, HistoryPathRequest,
    EditMessageRequest, TruncateRequest, ForkRequest,
)
from .file_processing import format_attachments_for_message
from .providers import create_model
from .tools import get_tools, ALL_TOOLS
from .agents import stream_chat, stream_agent, resume_agent, get_session_info
from .agents.chat_multiagent import stream_multiagent, resume_multiagent
from .conversation_store import ConversationStore, DEFAULT_DB_PATH, _DATA_DIR

DIST_DIR = Path(__file__).parent.parent.parent / "dist"
CONFIG_PATH = _DATA_DIR / "config.json"


def _read_db_path_from_config() -> str:
    """Read the last-used DB path from config.json, falling back to default."""
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            path = cfg.get("db_path", "")
            if path:
                return path
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_DB_PATH


def _write_db_path_to_config(db_path: str) -> None:
    """Persist the current DB path to config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"db_path": db_path}, indent=2),
        encoding="utf-8",
    )


# Unified conversation history store (SQLite-backed, shared across all endpoints)
conversation_store = ConversationStore(db_path=_read_db_path_from_config())

app = FastAPI(
    title="WordLLMs Backend (LangGraph)",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_ATTACHMENTS_BYTES = 50 * 1024 * 1024  # 50 MB total

def inject_attachments(request: ChatRequest | AgentRequest | MultiAgentRequest) -> None:
    """Parse file attachments and inject their content into the last user message.

    Mutates request.messages in-place. For text files, appends parsed content
    to the message. For images, converts to multimodal content format.
    """
    if not request.attachments:
        return

    # Enforce total size limit
    total_bytes = sum(len(a.data) for a in request.attachments)
    if total_bytes > MAX_ATTACHMENTS_BYTES:
        raise ValueError(f"Total attachment size ({total_bytes} bytes) exceeds 50MB limit")

    att_dicts = [{"filename": a.filename, "data": a.data} for a in request.attachments]
    text_block, image_parts = format_attachments_for_message(att_dicts, request.attachment_char_limit)

    # Find last user message
    user_msg = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_msg = msg
            break
    if user_msg is None:
        raise ValueError("No user message found to attach files to")

    if image_parts:
        # Convert to multimodal content list
        original = user_msg.content if isinstance(user_msg.content, str) else ""
        user_msg.content = [
            {"type": "text", "text": original + text_block},
            *image_parts,
        ]
    elif text_block:
        if isinstance(user_msg.content, str):
            user_msg.content += text_block
        else:
            # Already a list (shouldn't happen without images, but handle gracefully)
            user_msg.content.insert(0, {"type": "text", "text": text_block})


def sse_response(event_generator: AsyncGenerator[dict, None]) -> StreamingResponse:
    async def encode_sse():
        async for event in event_generator:
            event_type = event["event"]
            data = event["data"] if isinstance(event["data"], str) else json.dumps(event["data"])
            yield f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")
    return StreamingResponse(encode_sse(), media_type="text/event-stream")

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "word-gpt-plus-backend-langgraph"}

@app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {"name": name, "description": tool.description}
            for name, tool in ALL_TOOLS.items()
        ]
    }

@app.get("/api/context-stats/{conversation_id}")
async def context_stats(conversation_id: str):
    chars, tokens = conversation_store.get_context_stats(conversation_id)
    return {"chars": chars, "tokens": tokens}

# --- Chat Endpoint (Standard Stream) ---
@app.post("/api/chat")
async def chat_completion(request: ChatRequest):
    inject_attachments(request)
    async def generate():
        try:
            model = create_model(
                provider=request.provider,
                model=request.model,
                credentials=request.credentials,
                temperature=request.temperature,
                timeout=request.llm_timeout,
            )
            async for event in stream_chat(
                model=model,
                messages=request.messages,
                filter_thinking=request.filter_thinking,
                language=request.language,
                additional_system_prompt=request.additional_system_prompt,
                conversation_id=request.conversation_id,
                conversation_store=conversation_store,
                max_context_tokens=request.max_context_tokens,
                llm_timeout=request.llm_timeout,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}
    return sse_response(generate())

# --- Agent Endpoint (LangGraph Start) ---
@app.post("/api/agent")
async def agent_completion(request: AgentRequest):
    inject_attachments(request)
    async def generate():
        try:
            model = create_model(
                provider=request.provider,
                model=request.model,
                credentials=request.credentials,
                temperature=request.temperature,
                timeout=request.llm_timeout,
            )

            if not request.tools:
                raise ValueError("No tools provided — frontend must send the active tool list")
            server_tools, client_tools = get_tools(request.tools, tavily_api_key=request.tavily_api_key)

            async for event in stream_agent(
                model=model,
                messages=request.messages,
                tools=server_tools,
                client_tools=client_tools,
                tool_names=request.tools,
                recursion_limit=request.recursion_limit,
                filter_thinking=request.filter_thinking,
                language=request.language,
                additional_system_prompt=request.additional_system_prompt,
                thread_id=request.thread_id,
                conversation_id=request.conversation_id,
                conversation_store=conversation_store,
                max_context_tokens=request.max_context_tokens,
                llm_timeout=request.llm_timeout,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}
        except Exception as e:
             yield {"event": "error", "data": json.dumps({"error": str(e)})}
             
    return sse_response(generate())

# --- Agent Continue Endpoint (LangGraph Resume) ---
@app.post("/api/agent/continue")
async def agent_continue(request: AgentContinueRequest):
    async def generate():
        try:
            # Reconstruct model for the resume step
            model = create_model(
                provider=request.provider,
                model=request.model,
                credentials=request.credentials,
                temperature=request.temperature,
                timeout=request.llm_timeout,
            )

            # Use the same filtered tool list as the original /api/agent call
            if not request.tools:
                raise ValueError("No tools in continue request — frontend must send the original tool list")
            server_tools, client_tools = get_tools(request.tools, tavily_api_key=request.tavily_api_key)

            async for event in resume_agent(
                model=model,
                session_id=request.session_id,
                tool_results=[tr.model_dump() for tr in request.tool_results],
                server_tools=server_tools,
                client_tools=client_tools,
                filter_thinking=request.filter_thinking,
                conversation_store=conversation_store,
                max_context_tokens=request.max_context_tokens,
                llm_timeout=request.llm_timeout,
                recursion_limit=request.recursion_limit,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return sse_response(generate())

@app.post("/api/multiagent")
async def multiagent_completion(request: MultiAgentRequest):
    inject_attachments(request)
    async def generate():
        try:
            # 1. Instantiate all Expert models
            expert_models = []
            expert_max_context_tokens = []
            for cfg in request.experts:
                expert_models.append(create_model(
                    provider=cfg.provider,
                    model=cfg.model,
                    credentials=cfg.credentials,
                    temperature=cfg.temperature,
                    timeout=request.llm_timeout,
                ))
                expert_max_context_tokens.append(cfg.max_context_tokens)

            # 2. Instantiate Overseer model
            overseer_model = create_model(
                provider=request.overseer.provider,
                model=request.overseer.model,
                credentials=request.overseer.credentials,
                temperature=request.overseer.temperature,
                timeout=request.llm_timeout,
            )
            overseer_max_context_tokens = request.overseer.max_context_tokens

            # 3. Instantiate Synthesizer model (Parallel mode only)
            if request.synthesizer:
                synthesizer_model = create_model(
                    provider=request.synthesizer.provider,
                    model=request.synthesizer.model,
                    credentials=request.synthesizer.credentials,
                    temperature=request.synthesizer.temperature,
                    timeout=request.llm_timeout,
                )
                synthesizer_max_context_tokens = request.synthesizer.max_context_tokens
            else:
                synthesizer_model = overseer_model
                synthesizer_max_context_tokens = overseer_max_context_tokens

            # 4. Instantiate Formatter model (Legacy collaborative mode fallback)
            formatter_model = None
            if request.formatter:
                formatter_model = create_model(
                    provider=request.formatter.provider,
                    model=request.formatter.model,
                    credentials=request.formatter.credentials,
                    temperature=request.formatter.temperature,
                    timeout=request.llm_timeout,
                )

            # 5. Resolve Tools
            expert_server_tools, expert_client_tools = get_tools(request.expert_tools, tavily_api_key=request.tavily_api_key)
            supervisor_server_tools, supervisor_client_tools = get_tools(request.supervisor_tools, tavily_api_key=request.tavily_api_key)

            # 5. Start the LangGraph Multi-Agent Stream
            async for event in stream_multiagent(
                mode=request.mode,
                expert_models=expert_models,
                overseer_model=overseer_model,
                synthesizer_model=synthesizer_model,
                messages=request.messages,
                max_rounds=request.max_rounds,
                use_expert_memory=request.use_expert_memory,
                expert_server_tools=expert_server_tools,
                expert_client_tools=expert_client_tools,
                supervisor_server_tools=supervisor_server_tools,
                supervisor_client_tools=supervisor_client_tools,
                recursion_limit=request.recursion_limit,
                language=request.language,
                additional_system_prompt=request.additional_system_prompt,
                conversation_id=request.conversation_id,
                conversation_store=conversation_store,
                expert_max_context_tokens=expert_max_context_tokens,
                overseer_max_context_tokens=overseer_max_context_tokens,
                synthesizer_max_context_tokens=synthesizer_max_context_tokens,
                llm_timeout=request.llm_timeout,
                legacy_mode=(request.operating_mode == "legacy"),
                formatter_model=formatter_model,
                expert_full_history=request.expert_full_history,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}
    
    return sse_response(generate())


@app.post("/api/multiagent/continue")
async def multiagent_continue(request: MultiAgentContinueRequest):
    async def generate():
        try:
            # We don't need to reconstruct models here because chat_multiagent.py
            # handles the session restoration via its internal cache.
            async for event in resume_multiagent(
                multiagent_session_id=request.session_id,
                tool_results=[tr.model_dump() for tr in request.tool_results],
                conversation_store=conversation_store,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return sse_response(generate())


# --- Thread CRUD Endpoints (GUI display history) ---

@app.get("/api/threads")
async def list_threads(limit: int = 50):
    threads = conversation_store.list_threads(limit=limit)
    return {"threads": threads}


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str):
    thread = conversation_store.get_thread(thread_id)
    if thread is None:
        return {"thread": None}
    return {"thread": thread}


@app.post("/api/threads")
async def save_thread(request: ThreadSaveRequest):
    thread_data = {
        "id": request.id,
        "title": request.title,
        "messages": [m.model_dump(exclude_none=True) for m in request.messages],
        "mode": request.mode,
        "provider": request.provider or "",
        "model": request.model or "",
        "messageCount": request.messageCount,
        "createdAt": request.createdAt or "",
        "updatedAt": request.updatedAt or "",
    }
    conversation_store.save_thread(thread_data)
    return {"ok": True}


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str):
    deleted = conversation_store.delete_thread(thread_id)
    return {"deleted": deleted}


# --- Conversation Edit/Fork Endpoints ---

@app.post("/api/conversation/edit")
async def edit_message(request: EditMessageRequest):
    conversation_store.edit_user_message(
        request.conversation_id, request.turn, request.new_content,
    )
    return {"ok": True}


@app.post("/api/conversation/truncate")
async def truncate_conversation(request: TruncateRequest):
    conversation_store.truncate_from_turn(request.conversation_id, request.from_turn)
    return {"ok": True}


@app.post("/api/conversation/fork")
async def fork_conversation(request: ForkRequest):
    conversation_store.fork_conversation(
        request.source_conversation_id,
        request.target_conversation_id,
        request.up_to_turn,
    )
    return {"ok": True}


# --- History Path Endpoints ---

@app.get("/api/history/path")
async def get_history_path():
    return {"path": conversation_store.db_path}


@app.post("/api/history/path")
async def set_history_path(request: HistoryPathRequest):
    new_path = request.path.strip()
    if not new_path:
        new_path = DEFAULT_DB_PATH

    # Validate that the parent directory exists or can be created
    parent = Path(new_path).parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"Cannot create directory {parent}: {e}")

    conversation_store.switch_database(new_path)
    _write_db_path_to_config(new_path)
    return {"path": new_path}


@app.get("/api/history/browse-dir")
async def browse_directory(path: str = ""):
    """List directory contents for the web-based file browser."""
    target = Path(path) if path else Path(conversation_store.db_path).parent
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {target}")
    try:
        entries = []
        for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.is_dir() or item.suffix == ".db":
                entries.append({"name": item.name, "path": str(item), "is_dir": item.is_dir()})
        parent = str(target.parent) if target.parent != target else None
        return {"current_path": str(target), "parent_path": parent, "entries": entries}
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")


# Serve static files
if DIST_DIR.exists():
    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @app.get("/{path:path}")
    async def serve_static(path: str):
        file_path = DIST_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path, headers=_NO_CACHE)
        # Only serve index.html for SPA navigation routes, not missing asset files
        if "." in path.split("/")[-1]:
            raise HTTPException(status_code=404, detail=f"Not found: {path}")
        return FileResponse(DIST_DIR / "index.html", headers=_NO_CACHE)

    @app.get("/")
    async def serve_index():
        return FileResponse(DIST_DIR / "index.html", headers=_NO_CACHE)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)