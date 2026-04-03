"""Search Console MCP tool definitions and handler mapping.

Provides tool definitions (MCP Tool) and handler dispatch.
Handler implementations are in _handlers_search_console.py.
Dispatched from server.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent, Tool

from mureo.mcp._handlers_search_console import (
    handle_analytics_compare_periods,
    handle_analytics_device_breakdown,
    handle_analytics_query,
    handle_analytics_top_pages,
    handle_analytics_top_queries,
    handle_sitemaps_list,
    handle_sitemaps_submit,
    handle_sites_get,
    handle_sites_list,
    handle_url_inspection_inspect,
)
from mureo.mcp._tools_search_console import TOOLS as _TOOLS_SC

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definitions -- from sub-module
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = list(_TOOLS_SC)

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute the handler corresponding to the tool name.

    Raises:
        ValueError: Unknown tool name or missing required parameter
    """
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")

    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Handler mapping
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    # Sites
    "search_console.sites.list": handle_sites_list,
    "search_console.sites.get": handle_sites_get,
    # Analytics
    "search_console.analytics.query": handle_analytics_query,
    "search_console.analytics.top_queries": handle_analytics_top_queries,
    "search_console.analytics.top_pages": handle_analytics_top_pages,
    "search_console.analytics.device_breakdown": handle_analytics_device_breakdown,
    "search_console.analytics.compare_periods": handle_analytics_compare_periods,
    # Sitemaps
    "search_console.sitemaps.list": handle_sitemaps_list,
    "search_console.sitemaps.submit": handle_sitemaps_submit,
    # URL Inspection
    "search_console.url_inspection.inspect": handle_url_inspection_inspect,
}
