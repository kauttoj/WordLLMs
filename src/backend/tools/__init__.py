import sys
from pathlib import Path
from typing import Any

_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

try:
    from .web import create_web_search_tool, fetch_url_tool
    from .calculator import calculate_tool
    from .date import get_current_date_tool
    from .word_tools import CLIENT_TOOLS as _CLIENT_TOOL_LIST
except ImportError:
    from web import create_web_search_tool, fetch_url_tool
    from calculator import calculate_tool
    from date import get_current_date_tool
    from word_tools import CLIENT_TOOLS as _CLIENT_TOOL_LIST

# Server-side tools that don't require per-request credentials
SERVER_TOOLS = {
    "fetch_url": fetch_url_tool,
    "calculate": calculate_tool,
    "get_current_date": get_current_date_tool,
}

# Client-side Word tools — schemas only, executed via frontend Office.js
CLIENT_TOOLS = {t.name: t for t in _CLIENT_TOOL_LIST}

# Combined lookup for all known tools (excludes dynamic web_search)
ALL_TOOLS = {**SERVER_TOOLS, **CLIENT_TOOLS}

# Tool categorization for multiagent system
# Read-Only Word Tools (safe for experts)
READ_ONLY_WORD_TOOLS = {
    'get_selected_text',
    'get_document_content',
    'get_document_properties',
    'get_range_info',
    'get_table_info',
    'find_text',
    'find_and_select_text',
    'select_between_text',
    'select_text',
    'go_to_bookmark',
}

# Write Word Tools (supervisor only)
WRITE_WORD_TOOLS = {
    'insert_text', 'replace_selected_text', 'append_text',
    'insert_paragraph', 'delete_text',
    'search_and_replace', 'search_and_replace_in_selection',
    'format_text', 'clear_formatting', 'set_font_name',
    'insert_table', 'insert_list', 'insert_page_break', 'insert_image',
    'insert_bookmark', 'insert_content_control',
    'insert_comment',
}

def _build_server_tools(tavily_api_key: str | None = None) -> dict:
    """Build server tools dict, including web_search only if Tavily key is available."""
    tools = dict(SERVER_TOOLS)
    if tavily_api_key:
        tools["web_search"] = create_web_search_tool(tavily_api_key)
    return tools


def get_tools(tool_names: list[str], tavily_api_key: str | None = None,
              mcp_manager: "Any | None" = None) -> tuple[list, list]:
    """Get tool instances by name, separated by execution location.

    MCP tools (names starting with 'mcp_') are resolved via the MCPClientManager
    and treated as server-side tools.

    Returns:
        (server_tools, client_tools) — server tools run in Python,
        client tools are schema-only stubs executed via frontend RPC.
    """
    # Only create the Tavily tool if web_search is actually requested
    need_web_search = "web_search" in tool_names
    all_server = _build_server_tools(tavily_api_key) if need_web_search else dict(SERVER_TOOLS)
    server = []
    client = []
    for name in tool_names:
        if name.startswith("mcp_"):
            # MCP tool — resolve via manager
            if not mcp_manager:
                raise ValueError(f"MCP tool '{name}' requested but no MCP manager available")
            mcp_tools = mcp_manager.get_langchain_tools([name])
            server.extend(mcp_tools)
        elif name in all_server:
            server.append(all_server[name])
        elif name in CLIENT_TOOLS:
            client.append(CLIENT_TOOLS[name])
        elif name == "web_search" and not tavily_api_key:
            print("[tools] Skipping web_search: no Tavily API key configured")
            continue
        else:
            raise ValueError(f"Unknown tool: {name}. Available: {list({**all_server, **CLIENT_TOOLS}.keys())}")
    return server, client


__all__ = [
    "get_tools",
    "SERVER_TOOLS",
    "CLIENT_TOOLS",
    "ALL_TOOLS",
    "READ_ONLY_WORD_TOOLS",
    "WRITE_WORD_TOOLS",
]
