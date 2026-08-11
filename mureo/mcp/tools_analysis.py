"""Cross-platform analysis MCP tool definitions and dispatcher.

Three tools:

- ``analysis_anomalies_check`` — given a current metrics snapshot for a
  campaign and (optionally) STATE.json's action log, returns a
  severity-ordered list of anomalies (zero-spend, CPA spike, CTR drop).
- ``analysis_exclusion_impact_preview`` (#547) — given an exclusion /
  block / negative-keyword batch, returns the share of the account's own
  recent delivery it removes, and whether STRATEGY.md ``## Guardrails``
  would refuse it.
- ``analysis_tracking_consistency_check`` — given ad records from any
  platform, reports ads whose final-URL tracking parameters disagree
  with the campaign they live in (#550).

``analysis_anomalies_check`` and ``analysis_tracking_consistency_check``
are pure: they analyse what the caller passes in and never reach a
platform API, so they work identically for native, plugin, bridged and
hosted-connector platforms. ``analysis_exclusion_impact_preview`` is pure
in the same way only when the caller supplies ``delivery_records``;
otherwise it issues one platform read to fetch them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.mcp._handlers_analysis import handle_anomalies_check
from mureo.mcp._handlers_exclusion_impact import handle_exclusion_impact_preview
from mureo.mcp._handlers_tracking import handle_tracking_consistency_check

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

_ENTITY_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "value": {
            "type": "string",
            "description": "The excluded value — domain, app id, keyword text…",
        },
        "entity_type": {
            "type": "string",
            "description": (
                "Kind of entity: website / mobile_application / "
                "mobile_app_category / search_term, or any string a plugin "
                "surface uses. Must equal the entity_type on the matching "
                "delivery rows."
            ),
        },
        "match_type": {
            "type": "string",
            "description": (
                "Negative keyword match type (EXACT / PHRASE / BROAD). "
                "Ignored for every other entity kind."
            ),
        },
    },
    "required": ["value", "entity_type"],
    "additionalProperties": False,
}

_DELIVERY_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entity": {
            "type": "string",
            "description": "Entity key exactly as the platform's report names it.",
        },
        "entity_type": {"type": "string", "description": "Kind of entity."},
        "impressions": {"type": "number"},
        "clicks": {"type": "number"},
        "cost": {"type": "number"},
        "conversions": {"type": "number"},
    },
    "required": ["entity", "entity_type"],
    "additionalProperties": False,
}

_AD_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_id": {
            "type": "string",
            "description": "Platform ad id. Required; must be non-empty.",
        },
        "campaign_id": {
            "type": "string",
            "description": (
                "Campaign the ad lives in. Ads are grouped by this value, so "
                "an omitted campaign_id lumps every ad into one campaign."
            ),
        },
        "final_urls": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Destination URL(s) with their query string intact. Pass an "
                "empty list when the platform's read surface does not expose "
                "the URL — the ad is then reported as unchecked, never clean."
            ),
        },
        "platform": {
            "type": "string",
            "description": (
                "Canonical platform key — 'google_ads', 'meta_ads', or "
                "'plugin:<distribution>:<provider>'. Comparisons never cross "
                "platforms."
            ),
        },
        "campaign_name": {
            "type": "string",
            "description": "Optional; used to name campaigns in the findings.",
        },
        "status": {"type": "string", "description": "Optional ad status, verbatim."},
        "impressions": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Impressions over the audited window. Omit when unknown — "
                "omitted is NOT 0. 0 grades a mis-tagged ad as a cheap fix, "
                ">0 grades it as a data-integrity incident (severity "
                "critical), omitted leaves delivery_state=unknown."
            ),
        },
    },
    "required": ["ad_id"],
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
        name="analysis_exclusion_impact_preview",
        description=(
            "Before applying a batch of exclusions / blocks / negative "
            "keywords, report how much of the account's OWN recent delivery "
            "(impressions, clicks, cost, conversions) it removes — both for "
            "this batch and cumulatively for every standing exclusion once "
            "it lands. Call it with 'tool' + 'arguments' to size the exact "
            "call you are about to make on a surface mureo models (Google "
            "Ads negative placements / negative keywords, Meta excluded "
            "placements, plus any surface a plugin registered), or with "
            "'excluded_entities' + 'delivery_records' to size a batch on any "
            "other platform from a report you fetched yourself — that form "
            "reaches no platform API. Returns coverage 'measured', 'partial' "
            "or 'unknown'; 'unknown' is an honest answer and never means "
            "'no impact'. 'would_block' is computed by the same rule the "
            "dispatcher enforces from STRATEGY.md ## Guardrails, so it "
            "cannot disagree with what will actually happen. "
            "'unevaluated_rules' names any guardrail the operator wrote that "
            "cannot be evaluated for this call — an inert rule is not a "
            "satisfied one, so surface it to the operator."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tool": {
                    "type": "string",
                    "description": (
                        "MCP tool name of the exclusion call being previewed, "
                        "e.g. google_ads_negative_placements_add."
                    ),
                },
                "arguments": {
                    "type": "object",
                    "description": (
                        "The arguments that call would be made with. Required "
                        "when 'tool' is given."
                    ),
                    "additionalProperties": True,
                },
                "excluded_entities": {
                    "type": "array",
                    "description": (
                        "Entities being excluded, when no modelled 'tool' " "applies."
                    ),
                    "items": _ENTITY_ITEM,
                },
                "standing_exclusions": {
                    "type": "array",
                    "description": (
                        "Entities already excluded on this scope, for the "
                        "cumulative figure. Omit rather than pass an empty "
                        "list when they are unknown — an empty list means "
                        "'there are none'."
                    ),
                    "items": _ENTITY_ITEM,
                },
                "delivery_records": {
                    "type": "array",
                    "description": (
                        "The account's own delivery over the window, one row "
                        "per entity. Supplying this suppresses every platform "
                        "read."
                    ),
                    "items": _DELIVERY_ITEM,
                },
                "window_days": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Recent window in days. Defaults to STRATEGY.md's "
                        "exclusion_impact_window_days, else 30."
                    ),
                },
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="analysis_tracking_consistency_check",
        description=(
            "Audit final-URL tracking parameters across ad records you pass "
            "in, on any platform. Returns findings with severity, "
            "delivery_state (served / not_served / unknown), the ad ids "
            "involved and the evidence — ads carrying a utm scheme that "
            "belongs to exactly one other campaign, ads sending one landing "
            "page to two different schemes, ads missing a parameter the rest "
            "of their campaign carries, and violations of a "
            "'## Tracking Convention' declared in STRATEGY.md. Read-only; "
            "reaches no platform API. Pass planned_ads to pre-flight ads "
            "before creating them — then only the new ads are reported. "
            "Recognises utm_* parameters unless the convention declares more; "
            "ads with no readable URL are listed in ads_without_readable_url "
            "rather than reported clean."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ads": {
                    "type": "array",
                    "description": (
                        "Existing ads to audit. Assemble from "
                        "google_ads_ads_list (final_urls), meta_ads_ads_list "
                        "(creative.object_story_spec link + url_tags), a "
                        "plugin platform's own list tool, or a bridged MCP. "
                        "Ads are only ever compared with ads carrying the "
                        "same 'platform' value."
                    ),
                    "items": _AD_RECORD_SCHEMA,
                },
                "planned_ads": {
                    "type": "array",
                    "description": (
                        "Ads about to be created. When present the tool runs "
                        "in pre-flight mode and reports only findings the "
                        "planned ads are responsible for; use any stable "
                        "placeholder string as ad_id."
                    ),
                    "items": _AD_RECORD_SCHEMA,
                },
                "convention_markdown": {
                    "type": "string",
                    "description": (
                        "STRATEGY.md text (whole file or just the section) "
                        "containing '## Tracking Convention'. mureo parses it "
                        "— do not pre-interpret it. Omit when the account has "
                        "declared no convention; the zero-config checks still "
                        "run."
                    ),
                },
            },
            "required": ["ads"],
            "additionalProperties": False,
        },
    ),
]

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)

_HANDLERS: dict[str, Any] = {
    "analysis_anomalies_check": handle_anomalies_check,
    "analysis_exclusion_impact_preview": handle_exclusion_impact_preview,
    "analysis_tracking_consistency_check": handle_tracking_consistency_check,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch an analysis.* tool call to its handler."""
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)  # type: ignore[no-any-return]
