"""Cross-platform analysis MCP tool definitions and dispatcher.

Three tools, all platform-agnostic:

- ``analysis_anomalies_check`` — given a current metrics snapshot for a
  campaign and (optionally) STATE.json's action log, returns a
  severity-ordered list of anomalies (zero-spend, CPA spike, CTR drop).
- ``analysis_delivery_collapse_check`` (#546) — given a day-grain
  delivery report for any platform, flags campaigns whose delivery fell
  off a cliff while their status still says they should be serving. Its
  baseline comes from the delivery rows themselves, so it works on
  accounts with an empty ``action_log``.
- ``analysis_delivery_collapse_diagnose`` (#546) — overlays a change
  feed on the same rows and walks the elimination ladder, reporting what
  was ruled out AND what remains unknown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.analysis.collapse_diagnosis import ELIMINATION_LADDER, CheckOutcome
from mureo.mcp._handlers_analysis import handle_anomalies_check
from mureo.mcp._handlers_delivery_collapse import (
    handle_delivery_collapse_check,
    handle_delivery_collapse_diagnose,
)

if TYPE_CHECKING:
    from mcp.types import TextContent


_DELIVERY_ROW_PROPERTIES: dict[str, Any] = {
    "campaign_id": {"type": "string", "description": "Campaign identifier."},
    "campaign_name": {"type": "string", "description": "Campaign name (optional)."},
    "status": {
        "type": "string",
        "description": (
            "The platform's own status spelling (ENABLED / ACTIVE / PAUSED / …). "
            "A campaign that is not set to serve is never flagged — the "
            "status-says-serving contradiction IS the signal."
        ),
    },
    "end_date": {
        "type": "string",
        "description": (
            "Flight end date, YYYY-MM-DD, when the platform reports one. A "
            "finished flight stops serving while its status stays ENABLED and "
            "is not reported as a fault."
        ),
    },
    "date": {"type": "string", "description": "Delivery day, YYYY-MM-DD."},
    "impressions": {"type": "integer", "description": "Impressions that day."},
    "clicks": {"type": "integer", "description": "Clicks that day."},
    "cost": {"type": "number", "description": "Spend that day."},
}

_DELIVERY_ROWS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "description": (
        "Day-grain delivery rows, one per (campaign, day), covering at least "
        "the last ~30 days. Any platform that can produce this shape gets the "
        "same detection: hosted connectors (tiktok_ads), official-MCP bridges "
        "(Amazon), and plugin platforms alike."
    ),
    "items": {
        "type": "object",
        "properties": _DELIVERY_ROW_PROPERTIES,
        "required": ["campaign_id", "date", "impressions"],
    },
}


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
        name="analysis_anomalies_check",
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
            "additionalProperties": False,
        },
    ),
    Tool(
        name="analysis_delivery_collapse_check",
        description=(
            "Detect delivery collapse: campaigns whose impressions fell off a "
            "cliff while their status still says they should be serving. The "
            "inverse of google_ads_cost_increase_investigate, and the scheduled "
            "detector /daily-check runs. Feed it a day-grain delivery report "
            "(one row per campaign per day, ~30+ days) for ANY platform — "
            "hosted connectors, bridges and plugins included. The baseline is "
            "the median of the SAME WEEKDAY from those rows, so weekend dips do "
            "not fire, and it never reads action_log, so it works on accounts "
            "operated partly by hand. The current (partial) day is always "
            "excluded. Thresholds come from STRATEGY.md ## Guardrails "
            "(delivery_collapse_drop_pct, delivery_collapse_consecutive_days, "
            "delivery_collapse_min_baseline_impressions, "
            "delivery_collapse_baseline_days) and default to a 90% drop against "
            "a 28-day baseline. Read-only."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": (
                        "Platform key the rows came from (google_ads, meta_ads, "
                        "tiktok_ads, plugin:<distribution>:<name>, …). Reported "
                        "back on every signal."
                    ),
                },
                "rows": _DELIVERY_ROWS_SCHEMA,
                "as_of": {
                    "type": "string",
                    "description": (
                        "Treat this YYYY-MM-DD date as 'today'; days on or after "
                        "it are partial and are not evaluated. Defaults to the "
                        "server's current date."
                    ),
                },
                "reported_through": {
                    "type": "string",
                    "description": (
                        "YYYY-MM-DD: the last date the platform has actually "
                        "REPORTED delivery for. Optional. Without it the tool "
                        "infers the frontier as the latest date appearing "
                        "anywhere in `rows`, which assumes every campaign in "
                        "`rows` was fetched in one request and finalises at the "
                        "same time. Set it when that does not hold — rows "
                        "stitched together from several fetches, or a connector "
                        "whose campaigns finalise at different times — using the "
                        "OLDEST per-campaign last date you trust. Do NOT pass the "
                        "end of the range you requested: that asserts coverage "
                        "the platform never confirmed and turns reporting lag "
                        "into a false collapse."
                    ),
                },
            },
            "required": ["platform", "rows"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="analysis_delivery_collapse_diagnose",
        description=(
            "Diagnose one collapsed campaign: overlay a change feed on its daily "
            "delivery to answer 'what changed immediately before the cliff?', "
            "then fold in whatever elimination-ladder evidence you have already "
            "gathered ("
            + ", ".join(ELIMINATION_LADDER)
            + "). Returns the timeline, the changes in the days before the "
            "cliff, the checks that passed, the most likely cause WITH its "
            "evidence when one is implicated, and — always — the questions that "
            "remain open plus the standing limitations of what any read API can "
            "answer. It reports most_likely_cause=null / "
            "confidence=undetermined rather than guessing: in the incident this "
            "was built from, every check passed and the cause was still never "
            "identified. Read-only; gather evidence with the per-platform tools "
            "it names in next_checks and call it again."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "Platform key the rows came from.",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Which campaign in `rows` to diagnose.",
                },
                "rows": _DELIVERY_ROWS_SCHEMA,
                "as_of": {
                    "type": "string",
                    "description": "Treat this YYYY-MM-DD date as 'today'.",
                },
                "change_lookback_days": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 90,
                    "description": (
                        "How many days before the cliff count as 'immediately "
                        "before' for changes_before_cliff (default 3). Widen it "
                        "for a cause with a delayed effect — a billing hold or "
                        "a policy review can stop delivery days after the "
                        "change that caused it. Changes outside the window "
                        "still appear on the timeline."
                    ),
                },
                "timeline_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 180,
                    "description": (
                        "How many trailing days of delivery the timeline "
                        "covers (default 21)."
                    ),
                },
                "changes": {
                    "type": "array",
                    "description": (
                        "Change events to overlay — from "
                        "google_ads_change_history_list, STATE.json's "
                        "action_log, or a platform's own feed."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "occurred_at": {
                                "type": "string",
                                "description": "ISO date or datetime.",
                            },
                            "source": {"type": "string"},
                            "resource_type": {"type": "string"},
                            "summary": {"type": "string"},
                            "actor": {"type": "string"},
                        },
                        "required": ["occurred_at", "summary"],
                    },
                },
                "evidence": {
                    "type": "array",
                    "description": (
                        "Elimination-ladder results you already gathered. Only "
                        "report what you actually checked: an unsupplied step is "
                        "returned as an open question, which is the honest state."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "check": {
                                "type": "string",
                                "enum": list(ELIMINATION_LADDER),
                            },
                            "outcome": {
                                "type": "string",
                                "enum": [o.value for o in CheckOutcome],
                            },
                            "detail": {
                                "type": "string",
                                "description": "The evidence, in one line.",
                            },
                        },
                        "required": ["check", "outcome"],
                    },
                },
            },
            "required": ["platform", "campaign_id", "rows"],
            "additionalProperties": False,
        },
    ),
]

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)

_HANDLERS: dict[str, Any] = {
    "analysis_anomalies_check": handle_anomalies_check,
    "analysis_delivery_collapse_check": handle_delivery_collapse_check,
    "analysis_delivery_collapse_diagnose": handle_delivery_collapse_diagnose,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch an analysis.* tool call to its handler."""
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)  # type: ignore[no-any-return]
