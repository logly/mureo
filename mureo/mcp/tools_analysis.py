"""Cross-platform analysis MCP tool definitions and dispatcher.

Exposes one tool: ``analysis.anomalies.check``. Given a current
metrics snapshot for a campaign and (optionally) STATE.json's action
log, returns a severity-ordered list of anomalies (zero-spend, CPA
spike, CTR drop) the agent should surface to the operator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.mcp._handlers_analysis import handle_anomalies_check

if TYPE_CHECKING:
    from mcp.types import TextContent


_CURRENT_PROPERTIES: dict[str, Any] = {
    "campaign_id": {
        "type": "string",
        "description": "Campaign identifier the metrics apply to.",
    },
    "cost": {"type": "number", "description": "Spend in the current window."},
    "impressions": {"type": "integer", "description": "Impressions served."},
    "clicks": {"type": "integer", "description": "Clicks received."},
    "conversions": {"type": "number", "description": "Conversions recorded."},
    "cpa": {
        "type": "number",
        "description": (
            "Cost per acquisition. Optional — if omitted the handler derives "
            "it from cost/conversions."
        ),
    },
    "ctr": {
        "type": "number",
        "description": (
            "Click-through rate as a decimal (e.g. 0.012 = 1.2%). Optional — "
            "derived from clicks/impressions when omitted."
        ),
    },
}

TOOLS: list[Tool] = [
    Tool(
        name="analysis.anomalies.check",
        description=(
            "Detect anomalies for one campaign by comparing its current "
            "metrics against a median-based baseline built from STATE.json's "
            "action_log history. Returns severity-ordered anomalies — zero "
            "spend (CRITICAL), CPA spike (HIGH/CRITICAL, gated by 30+ "
            "conversions), CTR drop (HIGH/CRITICAL, gated by 1000+ "
            "impressions). No baseline is produced when history < "
            "min_baseline_entries (default 7)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "current": {
                    "type": "object",
                    "description": "Point-in-time metrics for the campaign.",
                    "properties": _CURRENT_PROPERTIES,
                    # cost is required so a zero-spend alert is always an
                    # intentional zero rather than an omitted field.
                    "required": ["campaign_id", "cost"],
                },
                "state_file": {
                    "type": "string",
                    "description": (
                        "Path to STATE.json. Resolved inside the server's "
                        "current working directory; traversal or symlink "
                        "escape is rejected. Defaults to 'STATE.json'."
                    ),
                },
                "had_prior_spend": {
                    "type": "boolean",
                    "description": (
                        "Set false for fresh campaigns that have never spent. "
                        "Suppresses the zero-spend alert in that case."
                    ),
                },
                "min_baseline_entries": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Minimum action_log entries required to build a "
                        "baseline. Default 7 (one week). Below this the tool "
                        "returns baseline=null and evaluates only zero-spend."
                    ),
                },
            },
            "required": ["current"],
        },
    ),
]

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)

_HANDLERS: dict[str, Any] = {
    "analysis.anomalies.check": handle_anomalies_check,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch an analysis.* tool call to its handler."""
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)  # type: ignore[no-any-return]
