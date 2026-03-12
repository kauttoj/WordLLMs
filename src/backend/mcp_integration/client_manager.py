"""MCP Client Manager — manages connections to external MCP servers.

Spawns MCP server subprocesses via stdio transport, discovers their tools,
and wraps them as LangChain StructuredTool objects for agent binding.
Server configs are persisted to a JSON file on disk.
"""

import json
import re
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool as MCPTool

from langchain_core.tools import StructuredTool
from pydantic import Field as PydanticField, create_model


def _sanitize_server_name(name: str) -> str:
    """Convert server name to a safe identifier for tool name prefixing."""
    return re.sub(r"[^a-z0-9]", "_", name.lower()).strip("_")


def _json_type_to_python(json_type: str | list) -> type:
    """Map JSON Schema type to Python type."""
    if isinstance(json_type, list):
        # e.g. ["string", "null"] — use the non-null type
        types = [t for t in json_type if t != "null"]
        json_type = types[0] if types else "string"
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return mapping.get(json_type, str)


@dataclass
class MCPServerConfig:
    id: str
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    auto_connect: bool = False  # Was connected last session → reconnect on startup


@dataclass
class MCPConnection:
    config: MCPServerConfig
    session: ClientSession
    tools: list[MCPTool]
    _stack: AsyncExitStack


class MCPClientManager:
    """Manages connections to multiple MCP servers."""

    def __init__(self, config_path: Path):
        self._config_path = config_path
        self._configs: dict[str, MCPServerConfig] = {}
        self._connections: dict[str, MCPConnection] = {}
        # tool_full_name → (server_id, LangChain StructuredTool)
        self._langchain_tools: dict[str, tuple[str, StructuredTool]] = {}
        self._load_configs()

    # --- Config Persistence ---

    def _load_configs(self) -> None:
        if not self._config_path.exists():
            return
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            for entry in data:
                cfg = MCPServerConfig(**entry)
                self._configs[cfg.id] = cfg
        except (json.JSONDecodeError, OSError, TypeError) as e:
            print(f"[MCP] Failed to load configs: {e}")

    def _save_configs(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(cfg) for cfg in self._configs.values()]
        self._config_path.write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    # --- Server CRUD ---

    def add_server(self, name: str, command: str, args: list[str] | None = None,
                   env: dict[str, str] | None = None) -> MCPServerConfig:
        server_id = uuid.uuid4().hex[:12]
        cfg = MCPServerConfig(
            id=server_id,
            name=name,
            command=command,
            args=args or [],
            env=env or {},
        )
        self._configs[server_id] = cfg
        self._save_configs()
        print(f"[MCP] Added server '{name}' (id={server_id})")
        return cfg

    async def remove_server(self, server_id: str) -> None:
        if server_id not in self._configs:
            raise ValueError(f"MCP server not found: {server_id}")
        if server_id in self._connections:
            await self.disconnect(server_id)
        del self._configs[server_id]
        self._save_configs()
        print(f"[MCP] Removed server {server_id}")

    def update_server(self, server_id: str, name: str | None = None,
                      command: str | None = None, args: list[str] | None = None,
                      env: dict[str, str] | None = None) -> MCPServerConfig:
        if server_id not in self._configs:
            raise ValueError(f"MCP server not found: {server_id}")
        cfg = self._configs[server_id]
        if name is not None:
            cfg.name = name
        if command is not None:
            cfg.command = command
        if args is not None:
            cfg.args = args
        if env is not None:
            cfg.env = env
        self._save_configs()
        return cfg

    # --- Connection Lifecycle ---

    async def connect(self, server_id: str) -> list[dict[str, Any]]:
        """Connect to an MCP server, discover tools. Returns tool descriptors."""
        if server_id not in self._configs:
            raise ValueError(f"MCP server not found: {server_id}")
        if server_id in self._connections:
            raise ValueError(f"MCP server already connected: {server_id}")

        cfg = self._configs[server_id]
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env if cfg.env else None,
        )

        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(params)
            )
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()

            tools_result = await session.list_tools()
            tools = tools_result.tools

            self._connections[server_id] = MCPConnection(
                config=cfg,
                session=session,
                tools=tools,
                _stack=stack,
            )

            # Mark for auto-reconnect on next startup
            cfg.auto_connect = True
            self._save_configs()

            # Wrap each tool as LangChain StructuredTool
            safe_name = _sanitize_server_name(cfg.name)
            for mcp_tool in tools:
                wrapped = self._wrap_mcp_tool(server_id, safe_name, mcp_tool)
                self._langchain_tools[wrapped.name] = (server_id, wrapped)

            print(f"[MCP] Connected to '{cfg.name}': {len(tools)} tool(s) discovered")
            return [
                {
                    "name": f"mcp_{safe_name}_{t.name}",
                    "original_name": t.name,
                    "description": t.description or "",
                }
                for t in tools
            ]

        except Exception:
            await stack.aclose()
            raise

    async def disconnect(self, server_id: str) -> None:
        if server_id not in self._connections:
            raise ValueError(f"MCP server not connected: {server_id}")

        conn = self._connections.pop(server_id)

        # Remove wrapped tools
        to_remove = [name for name, (sid, _) in self._langchain_tools.items() if sid == server_id]
        for name in to_remove:
            del self._langchain_tools[name]

        # Mark as not auto-connect
        if server_id in self._configs:
            self._configs[server_id].auto_connect = False
            self._save_configs()

        await conn._stack.aclose()
        print(f"[MCP] Disconnected from '{conn.config.name}'")

    async def disconnect_all(self) -> None:
        server_ids = list(self._connections.keys())
        for sid in server_ids:
            try:
                await self.disconnect(sid)
            except Exception as e:
                print(f"[MCP] Error disconnecting {sid}: {e}")

    async def auto_connect_servers(self) -> None:
        """Reconnect servers that were connected last session."""
        for cfg in list(self._configs.values()):
            if cfg.auto_connect and cfg.id not in self._connections:
                try:
                    await self.connect(cfg.id)
                except Exception as e:
                    print(f"[MCP] Auto-connect failed for '{cfg.name}': {e}")
                    cfg.auto_connect = False
                    self._save_configs()

    # --- Tool Wrapping ---

    def _wrap_mcp_tool(self, server_id: str, safe_server_name: str,
                       mcp_tool: MCPTool) -> StructuredTool:
        """Create a LangChain StructuredTool from an MCP tool definition."""
        schema = mcp_tool.inputSchema or {}
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        fields: dict[str, Any] = {}
        for prop_name, prop_def in properties.items():
            python_type = _json_type_to_python(prop_def.get("type", "string"))
            description = prop_def.get("description", "")
            if prop_name in required:
                fields[prop_name] = (python_type, PydanticField(description=description))
            else:
                fields[prop_name] = (python_type | None, PydanticField(default=None, description=description))

        # Create dynamic Pydantic model for the tool's args
        model_name = f"MCP_{safe_server_name}_{mcp_tool.name}_Args"
        if fields:
            ArgsModel = create_model(model_name, **fields)
        else:
            ArgsModel = create_model(model_name)

        tool_name = f"mcp_{safe_server_name}_{mcp_tool.name}"

        # Capture references for the closure
        manager = self
        _server_id = server_id
        _tool_name = mcp_tool.name

        async def _execute(**kwargs: Any) -> str:
            return await manager.call_tool(_server_id, _tool_name, kwargs)

        return StructuredTool.from_function(
            coroutine=_execute,
            name=tool_name,
            description=mcp_tool.description or f"MCP tool: {mcp_tool.name}",
            args_schema=ArgsModel,
        )

    # --- Tool Execution ---

    async def call_tool(self, server_id: str, tool_name: str, args: dict[str, Any]) -> str:
        """Execute an MCP tool and return the result as a string."""
        if server_id not in self._connections:
            raise RuntimeError(f"MCP server not connected: {server_id}")

        conn = self._connections[server_id]
        result = await conn.session.call_tool(tool_name, args)

        if result.isError:
            raise RuntimeError(
                f"MCP tool '{tool_name}' on '{conn.config.name}' returned error: "
                + " ".join(c.text for c in result.content if hasattr(c, "text"))
            )

        # Concatenate text content from the result
        parts = []
        for content_item in result.content:
            if hasattr(content_item, "text"):
                parts.append(content_item.text)
            else:
                parts.append(str(content_item))
        return "\n".join(parts)

    # --- Query Methods ---

    def get_langchain_tools(self, tool_names: list[str]) -> list[StructuredTool]:
        """Resolve MCP tool names to LangChain tool objects."""
        tools = []
        for name in tool_names:
            if name not in self._langchain_tools:
                raise ValueError(f"MCP tool not found or server not connected: {name}")
            tools.append(self._langchain_tools[name][1])
        return tools

    def is_mcp_tool(self, name: str) -> bool:
        return name.startswith("mcp_")

    def is_connected(self, server_id: str) -> bool:
        return server_id in self._connections

    def list_servers(self) -> list[dict[str, Any]]:
        """Return all server configs with connection status and discovered tools."""
        result = []
        for cfg in self._configs.values():
            entry: dict[str, Any] = {
                **asdict(cfg),
                "status": "connected" if cfg.id in self._connections else "disconnected",
            }
            if cfg.id in self._connections:
                conn = self._connections[cfg.id]
                safe_name = _sanitize_server_name(cfg.name)
                entry["tools"] = [
                    {
                        "name": f"mcp_{safe_name}_{t.name}",
                        "original_name": t.name,
                        "description": t.description or "",
                    }
                    for t in conn.tools
                ]
            else:
                entry["tools"] = []
            result.append(entry)
        return result

    def get_server_tools(self, server_id: str) -> list[dict[str, Any]]:
        if server_id not in self._configs:
            raise ValueError(f"MCP server not found: {server_id}")
        if server_id not in self._connections:
            return []
        conn = self._connections[server_id]
        safe_name = _sanitize_server_name(conn.config.name)
        return [
            {
                "name": f"mcp_{safe_name}_{t.name}",
                "original_name": t.name,
                "description": t.description or "",
            }
            for t in conn.tools
        ]
