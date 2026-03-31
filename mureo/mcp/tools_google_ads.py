"""Google Ads MCP tool definitions

Provides 82 tool definitions (MCP Tool).
Handler implementations are separated into _handlers_google_ads.py /
_handlers_google_ads_extensions.py / _handlers_google_ads_analysis.py.

Tool definitions are split into category sub-modules:
  _tools_google_ads_campaigns.py  -- Campaigns, ad groups, ads, budgets
  _tools_google_ads_keywords.py   -- Keywords, negative keywords
  _tools_google_ads_extensions.py -- Sitelinks, callouts, conversions, targeting
  _tools_google_ads_analysis.py   -- Performance analysis, search terms, monitoring, capture
  _tools_google_ads_assets.py     -- Image assets
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent, Tool

# Expose handler module (allows tests to patch)
from mureo.mcp._handlers_google_ads import (  # noqa: F401
    HANDLERS as _HANDLERS,
)

# Import category-specific tool definitions
from mureo.mcp._tools_google_ads_analysis import TOOLS as _TOOLS_ANALYSIS
from mureo.mcp._tools_google_ads_assets import TOOLS as _TOOLS_ASSETS
from mureo.mcp._tools_google_ads_campaigns import TOOLS as _TOOLS_CAMPAIGNS
from mureo.mcp._tools_google_ads_extensions import TOOLS as _TOOLS_EXTENSIONS
from mureo.mcp._tools_google_ads_keywords import TOOLS as _TOOLS_KEYWORDS

# ---------------------------------------------------------------------------
# Tool definitions (82) -- aggregated from sub-modules
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = (
    _TOOLS_CAMPAIGNS
    + _TOOLS_KEYWORDS
    + _TOOLS_EXTENSIONS
    + _TOOLS_ANALYSIS
    + _TOOLS_ASSETS
)

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
