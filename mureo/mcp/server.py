"""mureo MCP server

Exposes Google Ads / Meta Ads / Search Console tools via the MCP protocol.
Invoked over stdio by MCP clients such as Claude Code or Cursor.

Tool definitions and handlers are separated into per-service modules
(tools_google_ads.py, tools_meta_ads.py, tools_search_console.py).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.server import Server
from mcp.server.stdio import stdio_server

if TYPE_CHECKING:
    from mcp.types import Tool

from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS
from mureo.mcp.tools_google_ads import handle_tool as handle_google_ads_tool
from mureo.mcp.tools_meta_ads import TOOLS as META_ADS_TOOLS
from mureo.mcp.tools_meta_ads import handle_tool as handle_meta_ads_tool
from mureo.mcp.tools_search_console import TOOLS as SEARCH_CONSOLE_TOOLS
from mureo.mcp.tools_search_console import handle_tool as handle_search_console_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Combined tool list
# ---------------------------------------------------------------------------

_ALL_TOOLS: list[Tool] = [
    *GOOGLE_ADS_TOOLS,
    *META_ADS_TOOLS,
    *SEARCH_CONSOLE_TOOLS,
]
_GOOGLE_ADS_NAMES: frozenset[str] = frozenset(t.name for t in GOOGLE_ADS_TOOLS)
_META_ADS_NAMES: frozenset[str] = frozenset(t.name for t in META_ADS_TOOLS)
_SEARCH_CONSOLE_NAMES: frozenset[str] = frozenset(t.name for t in SEARCH_CONSOLE_TOOLS)


# ---------------------------------------------------------------------------
# Handlers (defined as module-level functions so tests can call them directly)
# ---------------------------------------------------------------------------


async def handle_list_tools() -> list[Any]:
    """Return the list of registered tools."""
    return list(_ALL_TOOLS)


async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """Execute a tool and return the result.

    Raises:
        ValueError: Unknown tool name or missing required parameter
    """
    if name in _GOOGLE_ADS_NAMES:
        return await handle_google_ads_tool(name, arguments)
    if name in _META_ADS_NAMES:
        return await handle_meta_ads_tool(name, arguments)
    if name in _SEARCH_CONSOLE_NAMES:
        return await handle_search_console_tool(name, arguments)
    raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# MCP server setup & entry point
# ---------------------------------------------------------------------------


def _create_server() -> Server:
    """Create an MCP Server instance and register handlers."""
    server = Server("mureo")

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator, unused-ignore]
    async def list_tools() -> list[Any]:
        return await handle_list_tools()

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        return await handle_call_tool(name, arguments)

    return server


async def main() -> None:
    """Start the MCP server over stdio."""
    server = _create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
