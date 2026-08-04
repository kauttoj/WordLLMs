import json
import sys
from contextlib import asynccontextmanager
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
    ThreadSaveRequest, ProfilePathRequest,
    EditMessageRequest, TruncateRequest, ForkRequest,
    MCPServerAddRequest, MCPServerUpdateRequest,
    AttachmentUploadRequest,
)
from .file_processing import compose_user_content
from . import attachment_store
from .image_proxy import ImageProxyError, fetch_image
from .providers import create_model
from .tools import get_tools, CLIENT_TOOLS, SERVER_TOOLS, CLIENT_TOOL_CATEGORY
from .agents import stream_chat, stream_agent, resume_agent
from .agents.chat_multiagent import stream_multiagent, resume_multiagent
from .conversation_store import ConversationStore
from .mcp_integration import MCPClientManager
from .profile_store import ProfileStore, get_browse_root, resolve_initial_profile_dir
from . import pricing
from .providers import effort

import logging

logger = logging.getLogger(__name__)

DIST_DIR = Path(__file__).parent.parent.parent / "dist"

# Local inference providers run on CPU and can be extremely slow.
# Multiply their timeout to avoid premature disconnects.
_LOCAL_PROVIDERS = {"ollama", "lmstudio"}
_LOCAL_TIMEOUT_MULTIPLIER = 10

def adjust_timeout_for_provider(timeout: int, provider: str) -> int:
    if provider in _LOCAL_PROVIDERS:
        adjusted = timeout * _LOCAL_TIMEOUT_MULTIPLIER
        logger.info(f"Local provider '{provider}': timeout {timeout}s -> {adjusted}s")
        return adjusted
    return timeout
# Profile store — owns the active profile folder and its JSON files.
# It runs the per-profile data-version compatibility check and writes the
# active-profile pointer file. ConversationStore and MCPClientManager open
# their files inside the profile folder it manages.
profile_store = ProfileStore(resolve_initial_profile_dir())
# Before ConversationStore: its delete_thread() removes the thread's attachment
# folder, so the store must be pointed at the right profile from the outset.
attachment_store.configure_attachments_dir(profile_store.attachments_path)
conversation_store = ConversationStore(db_path=str(profile_store.db_path))
mcp_manager = MCPClientManager(config_path=profile_store.mcp_config_path)
pricing.configure_model_costs_path(profile_store.model_costs_path)
effort.configure_model_efforts_path(profile_store.model_efforts_path)
effort.log_override_status()
# Drop attachment folders for conversations that no longer exist.
attachment_store.sweep_orphans(conversation_store.list_known_ids())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Auto-connect MCP servers on startup, clean disconnect on shutdown."""
    await mcp_manager.auto_connect_servers()
    yield
    await mcp_manager.disconnect_all()


app = FastAPI(
    title="WordLLMs Backend (LangGraph)",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def inject_attachments(request: ChatRequest | AgentRequest | MultiAgentRequest) -> list[dict]:
    """Resolve attachment refs to server-stored content and inject into the last user message.

    Attachments are id references only (see POST /api/attachments) — base64
    already crossed the wire at upload time. Mutates request.messages in-place
    via `compose_user_content`, the single code path shared with the
    /api/conversation/edit handler, so a message restored from history is
    byte-identical to a freshly sent one.

    Raises HTTPException(400) — never sends silently — if conversation_id is
    missing, if any referenced attachment is missing on server, or if the
    target user message isn't plain text.

    Returns list of truncation warnings (empty if none).
    """
    if not request.attachments:
        return []

    if not request.conversation_id:
        raise HTTPException(
            status_code=400,
            detail="conversation_id is required when attachments are present",
        )

    refs = [{"id": a.id, "filename": a.filename} for a in request.attachments]
    items, missing_ids = attachment_store.load_for_injection(request.conversation_id, refs)
    if missing_ids:
        missing_filenames = [a.filename for a in request.attachments if a.id in missing_ids]
        raise HTTPException(
            status_code=400,
            detail=f"Attachment content missing on server: {', '.join(missing_filenames)}",
        )

    # Find last user message
    user_msg = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_msg = msg
            break
    if user_msg is None:
        raise HTTPException(status_code=400, detail="No user message found to attach files to")
    if not isinstance(user_msg.content, str):
        raise HTTPException(
            status_code=400,
            detail="User message content must be plain text before attachments are injected",
        )

    user_msg.content, truncation_warnings = compose_user_content(
        user_msg.content, items, request.attachment_char_limit,
    )
    return truncation_warnings


def sse_response(event_generator: AsyncGenerator[dict, None]) -> StreamingResponse:
    async def encode_sse():
        async for event in event_generator:
            event_type = event["event"]
            data = event["data"] if isinstance(event["data"], str) else json.dumps(event["data"])
            yield f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")
    return StreamingResponse(encode_sse(), media_type="text/event-stream")


async def _tracked(gen: AsyncGenerator[dict, None]) -> AsyncGenerator[dict, None]:
    """Wrap an SSE generator so the active-streams counter is bumped while it runs.

    The counter is read by GET /api/profile and gates POST /api/profile/path.
    Increment happens on first iteration; decrement runs in finally so it fires
    even on client disconnect or generator-close.
    """
    profile_store.increment_active_streams()
    try:
        async for ev in gen:
            yield ev
    finally:
        profile_store.decrement_active_streams()

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "wordllms-backend-langgraph"}

@app.get("/api/tools")
async def list_tools():
    tools = [
        {"name": n, "description": t.description, "kind": "client",
         "category": CLIENT_TOOL_CATEGORY[n]}
        for n, t in CLIENT_TOOLS.items()
    ] + [
        {"name": n, "description": t.description, "kind": "server",
         "category": "server"}
        for n, t in SERVER_TOOLS.items()
    ]
    tools.append({"name": "web_search", "kind": "server", "category": "server",
                  "description": "Search the web for current information."})
    return {"tools": tools}

@app.get("/api/model-capabilities")
async def model_capabilities(provider: str, model: str = ""):
    """What reasoning-effort tiers does (provider, model) support?

    Pure capability lookup: takes no credentials and makes no upstream call.
    Backs the Settings reasoning-effort dropdown so it only offers tiers the
    selected model actually supports.
    """
    return effort.supported_ladder(provider, model)

@app.get("/api/proxy/image")
async def proxy_image(url: str):
    """Fetch a remote image server-side for the `insert_image` Word tool.

    The add-in cannot fetch most image URLs itself (CORS, hotlink protection),
    and Word cannot decode every format the web serves. See image_proxy.py.
    """
    try:
        image = await fetch_image(url)
    except ImageProxyError as exc:
        # A bad URL is the caller's problem, not a server fault — 400 keeps the
        # message intact for the LLM instead of surfacing as a generic 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "base64": image.base64,
        "contentType": image.content_type,
        "sourceContentType": image.source_content_type,
        "converted": image.converted,
        "byteSize": image.byte_size,
    }

@app.get("/api/context-stats/{conversation_id}")
async def context_stats(conversation_id: str):
    chars, tokens = conversation_store.get_context_stats(conversation_id)
    return {"chars": chars, "tokens": tokens}

@app.post("/api/attachments")
def upload_attachments(request: AttachmentUploadRequest):
    """Upload attachment files once; returns ids to reference from /api/chat,
    /api/agent, /api/multiagent, and /api/conversation/edit.

    Sync `def` (not `async def`) so FastAPI runs it in its threadpool — parsing
    (MarkItDown, base64 decode) must never block the event loop.
    """
    try:
        files = [{"filename": f.filename, "data": f.data} for f in request.files]
        results = attachment_store.save_attachments(request.conversation_id, files)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"attachments": results}

# --- Chat Endpoint (Standard Stream) ---
@app.post("/api/chat")
async def chat_completion(request: ChatRequest):
    truncation_warnings = inject_attachments(request)
    llm_timeout = adjust_timeout_for_provider(request.llm_timeout, request.provider)
    async def generate():
        if truncation_warnings:
            yield {"event": "warning", "data": json.dumps({"warnings": truncation_warnings})}
        try:
            model = create_model(
                provider=request.provider,
                model=request.model,
                credentials=request.credentials,
                temperature=request.temperature,
                timeout=llm_timeout,
                reasoning_effort=request.reasoning_effort,
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
                llm_timeout=llm_timeout,
                document_content=request.document_content,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}
    return sse_response(_tracked(generate()))

# --- Agent Endpoint (LangGraph Start) ---
@app.post("/api/agent")
async def agent_completion(request: AgentRequest):
    truncation_warnings = inject_attachments(request)
    llm_timeout = adjust_timeout_for_provider(request.llm_timeout, request.provider)
    async def generate():
        if truncation_warnings:
            yield {"event": "warning", "data": json.dumps({"warnings": truncation_warnings})}
        try:
            model = create_model(
                provider=request.provider,
                model=request.model,
                credentials=request.credentials,
                temperature=request.temperature,
                timeout=llm_timeout,
                reasoning_effort=request.reasoning_effort,
            )

            if not request.tools:
                raise ValueError("No tools provided — frontend must send the active tool list")
            server_tools, client_tools = get_tools(request.tools, tavily_api_key=request.tavily_api_key, mcp_manager=mcp_manager)

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
                llm_timeout=llm_timeout,
                enable_todos=request.enable_todos,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}
        except Exception as e:
             yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return sse_response(_tracked(generate()))

# --- Agent Continue Endpoint (LangGraph Resume) ---
@app.post("/api/agent/continue")
async def agent_continue(request: AgentContinueRequest):
    llm_timeout = adjust_timeout_for_provider(request.llm_timeout, request.provider)
    async def generate():
        try:
            # Reconstruct model for the resume step
            model = create_model(
                provider=request.provider,
                model=request.model,
                credentials=request.credentials,
                temperature=request.temperature,
                timeout=llm_timeout,
                reasoning_effort=request.reasoning_effort,
            )

            # Use the same filtered tool list as the original /api/agent call
            if not request.tools:
                raise ValueError("No tools in continue request — frontend must send the original tool list")
            server_tools, client_tools = get_tools(request.tools, tavily_api_key=request.tavily_api_key, mcp_manager=mcp_manager)

            async for event in resume_agent(
                model=model,
                session_id=request.session_id,
                tool_results=[tr.model_dump() for tr in request.tool_results],
                server_tools=server_tools,
                client_tools=client_tools,
                filter_thinking=request.filter_thinking,
                conversation_store=conversation_store,
                max_context_tokens=request.max_context_tokens,
                llm_timeout=llm_timeout,
                recursion_limit=request.recursion_limit,
                enable_todos=request.enable_todos,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return sse_response(_tracked(generate()))

@app.post("/api/multiagent")
async def multiagent_completion(request: MultiAgentRequest):
    truncation_warnings = inject_attachments(request)
    # If any provider in the request is local, apply the timeout multiplier
    all_providers = [cfg.provider for cfg in request.experts] + [request.overseer.provider]
    if request.synthesizer:
        all_providers.append(request.synthesizer.provider)
    if request.formatter:
        all_providers.append(request.formatter.provider)
    llm_timeout = request.llm_timeout
    if any(p in _LOCAL_PROVIDERS for p in all_providers):
        llm_timeout = adjust_timeout_for_provider(request.llm_timeout, next(p for p in all_providers if p in _LOCAL_PROVIDERS))
    async def generate():
        if truncation_warnings:
            yield {"event": "warning", "data": json.dumps({"warnings": truncation_warnings})}
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
                    timeout=llm_timeout,
                    reasoning_effort=cfg.reasoning_effort,
                ))
                expert_max_context_tokens.append(cfg.max_context_tokens)

            # 2. Instantiate Overseer model
            overseer_model = create_model(
                provider=request.overseer.provider,
                model=request.overseer.model,
                credentials=request.overseer.credentials,
                temperature=request.overseer.temperature,
                timeout=llm_timeout,
                reasoning_effort=request.overseer.reasoning_effort,
            )
            overseer_max_context_tokens = request.overseer.max_context_tokens

            # 3. Instantiate Synthesizer model (Parallel mode only)
            if request.synthesizer:
                synthesizer_model = create_model(
                    provider=request.synthesizer.provider,
                    model=request.synthesizer.model,
                    credentials=request.synthesizer.credentials,
                    temperature=request.synthesizer.temperature,
                    timeout=llm_timeout,
                    reasoning_effort=request.synthesizer.reasoning_effort,
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
                    timeout=llm_timeout,
                    reasoning_effort=request.formatter.reasoning_effort,
                )

            # 5. Resolve Tools — backend derives the expert/supervisor split from
            # the single flat tool list the frontend sends (read + select tools
            # go to experts; the full list goes to supervisors).
            supervisor_names = list(request.tools)
            expert_names = [n for n in request.tools
                            if n not in CLIENT_TOOLS
                            or CLIENT_TOOL_CATEGORY[n] != "write"]
            expert_server_tools, expert_client_tools = get_tools(expert_names, tavily_api_key=request.tavily_api_key, mcp_manager=mcp_manager)
            supervisor_server_tools, supervisor_client_tools = get_tools(supervisor_names, tavily_api_key=request.tavily_api_key, mcp_manager=mcp_manager)

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
                llm_timeout=llm_timeout,
                legacy_mode=(request.operating_mode == "legacy"),
                formatter_model=formatter_model,
                expert_full_history=request.expert_full_history,
                use_expert_parallelization=request.use_expert_parallelization,
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"])}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return sse_response(_tracked(generate()))


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

    return sse_response(_tracked(generate()))


# --- MCP Server Management Endpoints ---

@app.get("/api/mcp/servers")
async def list_mcp_servers():
    """List all configured MCP servers with status and discovered tools."""
    return {"servers": mcp_manager.list_servers()}


@app.post("/api/mcp/servers")
async def add_mcp_server(request: MCPServerAddRequest):
    """Add a new MCP server configuration."""
    cfg = mcp_manager.add_server(
        name=request.name,
        command=request.command,
        args=request.args,
        env=request.env,
    )
    return {"server": {**cfg.__dict__, "status": "disconnected", "tools": []}}


@app.put("/api/mcp/servers/{server_id}")
async def update_mcp_server(server_id: str, request: MCPServerUpdateRequest):
    """Update an existing MCP server configuration."""
    cfg = mcp_manager.update_server(
        server_id,
        name=request.name,
        command=request.command,
        args=request.args,
        env=request.env,
    )
    return {"server": {**cfg.__dict__, "status": "connected" if mcp_manager.is_connected(server_id) else "disconnected"}}


@app.delete("/api/mcp/servers/{server_id}")
async def delete_mcp_server(server_id: str):
    """Remove an MCP server configuration (disconnects if connected)."""
    await mcp_manager.remove_server(server_id)
    return {"ok": True}


@app.post("/api/mcp/servers/{server_id}/connect")
async def connect_mcp_server(server_id: str):
    """Connect to an MCP server and discover its tools."""
    tools = await mcp_manager.connect(server_id)
    return {"tools": tools}


@app.post("/api/mcp/servers/{server_id}/disconnect")
async def disconnect_mcp_server(server_id: str):
    """Disconnect from an MCP server."""
    await mcp_manager.disconnect(server_id)
    return {"ok": True}


@app.get("/api/mcp/servers/{server_id}/tools")
async def list_mcp_server_tools(server_id: str):
    """List tools discovered from a connected MCP server."""
    tools = mcp_manager.get_server_tools(server_id)
    return {"tools": tools}


# --- Thread CRUD Endpoints (GUI display history) ---

def _annotate_attachments(thread: dict) -> dict:
    """Mark each message attachment ref with whether its content still resolves on disk.

    Operates on the freshly-deserialized dict returned by ConversationStore
    (json.loads per call), not the stored DB row, so this never mutates what's
    persisted — only the response.
    """
    available = attachment_store.available_ids(thread["id"])
    for msg in thread.get("messages", []):
        atts = msg.get("attachments")
        if not atts:
            continue
        for att in atts:
            att["available"] = att.get("id") in available if "id" in att else False
    return thread


@app.get("/api/threads")
async def list_threads(limit: int = 50):
    threads = conversation_store.list_threads(limit=limit)
    threads = [_annotate_attachments(t) for t in threads]
    return {"threads": threads}


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str):
    thread = conversation_store.get_thread(thread_id)
    if thread is None:
        return {"thread": None}
    thread = _annotate_attachments(thread)
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
    refs = [{"id": a.id, "filename": a.filename} for a in request.attachments]
    items, missing_ids = attachment_store.load_for_injection(request.conversation_id, refs)
    if missing_ids:
        missing_filenames = [a.filename for a in request.attachments if a.id in missing_ids]
        raise HTTPException(
            status_code=400,
            detail=f"Attachment content missing on server: {', '.join(missing_filenames)}",
        )
    content, _truncation_warnings = compose_user_content(
        request.new_content, items, request.attachment_char_limit,
    )
    conversation_store.edit_user_message(
        request.conversation_id, request.turn, content,
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
    # So the forked thread's attachment refs still resolve to content.
    attachment_store.copy_conversation(request.source_conversation_id, request.target_conversation_id)
    return {"ok": True}


# --- Profile Endpoints ---

@app.get("/api/profile")
async def get_profile():
    """Full snapshot: path + settings + prompts + active_streams.

    Called once at app startup by the frontend to hydrate the profile store,
    and again after a profile switch.
    """
    return profile_store.snapshot()


def _enforce_browse_root(target: Path) -> Path:
    """Reject paths that escape the volume mount when running in Docker."""
    root = get_browse_root()
    if root is None:
        return target
    try:
        target.resolve().relative_to(root)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Profile must live under the mounted volume {root}. "
                "Pick a subfolder of the host directory you mounted."
            ),
        )
    return target


@app.post("/api/profile/path")
async def set_profile_path(request: ProfilePathRequest):
    """Switch the active profile folder.

    Refuses with 409 if any SSE stream is currently active — the user must
    wait for ongoing work to finish before switching.
    """
    new_path = request.path.strip()
    if not new_path:
        raise HTTPException(status_code=400, detail="Profile path is required")
    target = Path(new_path).expanduser()
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="Profile path must be absolute")
    _enforce_browse_root(target)

    try:
        profile_store.rebind(target)
    except RuntimeError as e:
        # Active streams — frontend should have disabled the UI, but enforce here too.
        raise HTTPException(status_code=409, detail=str(e))

    # Repoint the attachment store first: ConversationStore.delete_thread deletes
    # the matching attachment folder, so the two must never point at different
    # profiles, not even briefly.
    attachment_store.configure_attachments_dir(profile_store.attachments_path)

    # Reopen conversation DB and reload MCP servers against the new folder.
    conversation_store.switch_database(str(profile_store.db_path))
    await mcp_manager.reload_from(profile_store.mcp_config_path)
    pricing.configure_model_costs_path(profile_store.model_costs_path)
    effort.configure_model_efforts_path(profile_store.model_efforts_path)
    effort.log_override_status()
    # Sweep only after the new DB is open — known_ids must come from it.
    attachment_store.sweep_orphans(conversation_store.list_known_ids())

    return profile_store.snapshot()


@app.put("/api/profile/settings")
async def save_profile_settings(payload: dict):
    """Replace settings.json with the given dict. Frontend owns the schema."""
    profile_store.save_settings(payload)
    return {"ok": True}


@app.put("/api/profile/prompts")
async def save_profile_prompts(payload: dict):
    """Replace prompts.json with the given dict. Frontend owns the schema."""
    profile_store.save_prompts(payload)
    return {"ok": True}


@app.get("/api/profile/browse-dir")
async def browse_directory(path: str = ""):
    """Directory listing for the profile-folder picker. Folders only.

    In Docker, browsing is clamped to the volume mount so the user can't
    pick a container-only path.
    """
    root = get_browse_root()
    target = Path(path).expanduser() if path else (root or profile_store.path)
    _enforce_browse_root(target)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {target}")
    try:
        entries = [
            {"name": item.name, "path": str(item), "is_dir": True}
            for item in sorted(target.iterdir(), key=lambda x: x.name.lower())
            if item.is_dir()
        ]
        # Suppress 'parent_path' once we hit the browse root so the UI can't
        # navigate above it.
        at_root = root is not None and target.resolve() == root
        parent = None if (at_root or target.parent == target) else str(target.parent)
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