"""The nine ChatGPT Ads read tools, and the builder every tool uses.

Pure data: building them needs no credentials and no network, so the MCP
server can list them at start. Every tool declares ``readOnlyHint`` and the
same throttle, which the plugin safety layer reads
(:mod:`mureo.mcp.plugin_semantics`) — the provider is served through the
plugin path, not the built-in tool families. The tools that change the
account are in :mod:`mureo.chatgpt_ads.tools_mutations`, built by
:func:`build_tool` here so the two sets cannot drift in shape.
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool, ToolAnnotations

from mureo.chatgpt_ads._api import THROTTLE_BURST, THROTTLE_RATE

#: Default rows for the list tools and the change history.
DEFAULT_LIST_LIMIT = 50
#: Largest tool ``limit``, the bound ``_LIMIT_PARAM`` uses on the Meta tools.
MAX_TOOL_LIMIT = 1000
#: Default rows for an insights report: the largest, still one API page. A
#: 30-day daily report over a handful of campaigns already exceeds 200 rows,
#: and rows past ``limit`` are dropped without notice.
DEFAULT_INSIGHTS_LIMIT = MAX_TOOL_LIMIT
#: Bounds the API puts on the ``name`` filter of the list endpoints.
NAME_MIN_CHARS = 3
NAME_MAX_CHARS = 1000
#: The API's own pattern for a name: at least one character that is not a
#: space, on one line. The schemas carry it as the API states it; the
#: handlers search it too and refuse a line break themselves, because
#: Python's regex dialect lets some line breaks through.
NAME_PATTERN = r"^.*\S.*$"

#: Delivery metrics, sent as ``{level}.{metric}`` (the reference's canonical
#: field names). The Reporting guide's examples use flat names such as
#: ``impressions``; the reference's form is the one it defines.
DELIVERY_METRICS = ("impressions", "clicks", "spend", "ctr", "cpc", "cpm")
#: Conversion and purchase metrics, sent under their bare names as the
#: reference's ``fields[]=conversions`` examples do.
CONVERSION_METRICS = (
    "conversions",
    "cpa",
    "post_click_cvr",
    "order_created_attributed_sales",
    "order_created_roas",
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True)
_THROTTLE = {"throttle": {"rate": THROTTLE_RATE, "burst": THROTTLE_BURST}}

#: Path ids are put into URLs, so they are held to a conservative pattern.
ID_PATTERN = "^[A-Za-z0-9_-]{1,128}$"


def id_param(entity: str, example: str) -> dict[str, Any]:
    return {
        "type": "string",
        "pattern": ID_PATTERN,
        "description": (
            f"{entity} id as the API returns it (e.g. '{example}'). Find it with "
            "the matching list tool."
        ),
    }


def _limit_param(default: int, page_note: str) -> dict[str, Any]:
    return {
        "type": "integer",
        "minimum": 1,
        "maximum": MAX_TOOL_LIMIT,
        "description": (
            f"Maximum rows to return. Default {default}. {page_note} mureo "
            "follows the cursor until this many rows are collected, so no "
            "cursor is returned."
        ),
    }


_NAME_PARAM = {
    "type": "string",
    "minLength": NAME_MIN_CHARS,
    "maxLength": NAME_MAX_CHARS,
    "pattern": NAME_PATTERN,
    "description": (
        "Return only entities whose name matches this text: 3 to 1000 "
        "characters, not all spaces."
    ),
}
_SERVING_ISSUES_PARAM = {
    "type": "boolean",
    "description": (
        "Also return serving_issues, the platform's reasons a campaign is not "
        "delivering. Default false."
    ),
}
#: The ``period`` argument's text, shared by every tool that takes one.
PERIOD_DESCRIPTION = (
    "Window as 'today', 'yesterday', 'last_7d', 'last_14d', 'last_30d', "
    "'last_90d', 'this_month', 'last_month' or explicit "
    "'YYYY-MM-DD..YYYY-MM-DD' (both ends inclusive), resolved in the ad "
    "account's time zone. 'last_Nd' ends yesterday. At most 365 days."
)
#: The ``limit`` of a list tool over an endpoint that pages at 500.
ENTITY_LIMIT = _limit_param(DEFAULT_LIST_LIMIT, "The API serves at most 500 per page.")
#: ``time_granularity`` values of both reports.
TIME_GRANULARITIES = ("none", "daily")
#: Click attribution windows, in days, both reports accept.
ATTRIBUTION_WINDOWS = (7, 14, 30)
TIME_GRANULARITY = {
    "type": "string",
    "enum": list(TIME_GRANULARITIES),
    "description": (
        "'none' (default) returns one row per entity for the whole "
        "window; 'daily' adds one row per day."
    ),
}


def build_tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    *,
    annotations: ToolAnnotations = _READ_ONLY,
    declarations: dict[str, Any] | None = None,
) -> Tool:
    """One tool with a closed schema and the shared throttle.

    ``declarations`` are further ``meta["mureo"]`` keys (``identity``,
    ``budget``, ``bid``), merged over the throttle declaration.
    """
    return Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        annotations=annotations,
        _meta={"mureo": {**_THROTTLE, **(declarations or {})}},
    )


_ACCOUNT_GET = build_tool(
    "chatgpt_ads_account_get",
    "Gets the ChatGPT Ads ad account the configured API key belongs to. "
    "Returns the platform object unchanged: id, name, status, timezone, "
    "currency_code, review state and any field the beta API adds. Read-only. "
    "One key is scoped to one ad account, so there is no account_id argument. "
    "Use this first to confirm which account mureo is reading and in which "
    "currency and time zone its reports are expressed.",
    {},
    [],
)

_CAMPAIGNS_LIST = build_tool(
    "chatgpt_ads_campaigns_list",
    "Lists campaigns in the ChatGPT Ads account. Returns a JSON array of "
    "campaign objects as the platform returns them (id, name, status, "
    "objective, bidding_type, billing_event_type, budget in micros, schedule). "
    "Read-only. Use this to find a campaign_id; for one campaign's full record "
    "use chatgpt_ads_campaigns_get, and for performance use "
    "chatgpt_ads_insights_report.",
    {
        "name": _NAME_PARAM,
        "include_serving_issues": _SERVING_ISSUES_PARAM,
        "limit": ENTITY_LIMIT,
    },
    [],
)

_CAMPAIGNS_GET = build_tool(
    "chatgpt_ads_campaigns_get",
    "Gets one ChatGPT Ads campaign. Returns the platform object unchanged: "
    "status, objective, bidding_type, billing_event_type, targeting, schedule "
    "and budget. Budget amounts are micros of the account currency (1,000,000 "
    "= one unit); do not read them as currency units. Read-only. Set "
    "include_serving_issues to see why a campaign is not delivering. To list "
    "campaigns use chatgpt_ads_campaigns_list.",
    {
        "campaign_id": id_param("Campaign", "cmpn_123"),
        "include_serving_issues": _SERVING_ISSUES_PARAM,
    },
    ["campaign_id"],
)

_AD_GROUPS_LIST = build_tool(
    "chatgpt_ads_ad_groups_list",
    "Lists ChatGPT Ads ad groups, of one campaign when campaign_id is given, "
    "otherwise of the whole ad account. Returns a JSON array of ad group "
    "objects as the platform returns them (id, name, status, bidding_config "
    "with bid amounts in micros, serving_issues). Read-only. For one ad group "
    "use chatgpt_ads_ad_groups_get; for its ads use chatgpt_ads_ads_list.",
    {
        "campaign_id": id_param("Parent campaign", "cmpn_123"),
        "name": _NAME_PARAM,
        "limit": ENTITY_LIMIT,
    },
    [],
)

_AD_GROUPS_GET = build_tool(
    "chatgpt_ads_ad_groups_get",
    "Gets one ChatGPT Ads ad group. Returns the platform object unchanged: "
    "status, bidding_config (bid amounts in micros of the account currency, "
    "1,000,000 = one unit), context hints and serving_issues. Read-only. Use "
    "this to read an ad group's bid settings or why it is not serving before "
    "explaining its results. To list the ad groups of a campaign use "
    "chatgpt_ads_ad_groups_list.",
    {"ad_group_id": id_param("Ad group", "adgrp_123")},
    ["ad_group_id"],
)

_ADS_LIST = build_tool(
    "chatgpt_ads_ads_list",
    "Lists ads in the ChatGPT Ads account, optionally within one ad group. "
    "Returns a JSON array of ad objects as the platform returns them (id, "
    "name, status, review_status, creative, serving_issues). Read-only. Use "
    "this to find an ad_id or check review status across ads; for one ad's "
    "full record use chatgpt_ads_ads_get.",
    {
        "ad_group_id": id_param("Parent ad group", "adgrp_123"),
        "name": _NAME_PARAM,
        "limit": ENTITY_LIMIT,
    },
    [],
)

_ADS_GET = build_tool(
    "chatgpt_ads_ads_get",
    "Gets one ChatGPT Ads ad. Returns the platform object unchanged: status, "
    "review_status and review detail, appeal, creative and serving_issues. "
    "Read-only. Use this to see why one ad was rejected or is not serving and "
    "what its creative says. To list ads use chatgpt_ads_ads_list; for its "
    "performance use chatgpt_ads_insights_report with ad_id.",
    {"ad_id": id_param("Ad", "ad_123")},
    ["ad_id"],
)

_INSIGHTS_REPORT = build_tool(
    "chatgpt_ads_insights_report",
    "Reports ChatGPT Ads performance. Returns a JSON array of rows as the API "
    "returns them: the row entity's id and name, readable_time for daily rows, "
    "and the requested metrics. Read-only. Scope with at most one of "
    "campaign_id / ad_group_id / ad_id (none = the whole account); level picks "
    "the row entity at or below that scope. spend, cpc and cpm are major "
    "currency units (12.50 = 12.50), not micros; ctr is a ratio. Impressions "
    "and clicks arrive within minutes, spend reflects finalized activity and "
    "can update later, conversions take at least one day, so same-day rows are "
    "provisional.",
    {
        "period": {
            "type": "string",
            "description": f"{PERIOD_DESCRIPTION} Default 'last_30d'.",
        },
        "level": {
            "type": "string",
            "enum": ["account", "campaign", "ad_group", "ad"],
            "description": (
                "Row entity. Default 'campaign', or the scope's own level when "
                "scoped to an ad group or ad. Must not be above the scope."
            ),
        },
        "campaign_id": id_param("Campaign to scope the report to", "cmpn_123"),
        "ad_group_id": id_param("Ad group to scope the report to", "adgrp_123"),
        "ad_id": id_param("Ad to scope the report to", "ad_123"),
        "time_granularity": TIME_GRANULARITY,
        "metrics": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [*DELIVERY_METRICS, *CONVERSION_METRICS],
            },
            "minItems": 1,
            "uniqueItems": True,
            "description": (
                "Metrics to return, each at most once. Delivery: impressions, clicks, spend, ctr, "
                "cpc, cpm (the default set). Conversion: conversions, cpa, "
                "post_click_cvr, order_created_attributed_sales, "
                "order_created_roas; these need full days and measured "
                "conversions."
            ),
        },
        "attribution_window_days": {
            "type": "integer",
            "enum": list(ATTRIBUTION_WINDOWS),
            "description": (
                "Click attribution window for conversion metrics. Omit for the "
                "API default (30). Does not change delivery metrics."
            ),
        },
        "limit": _limit_param(
            DEFAULT_INSIGHTS_LIMIT,
            "Rows beyond limit are dropped without notice; daily granularity "
            "returns one row per entity per day, so size limit to entities x "
            "days.",
        ),
    },
    [],
)

_CHANGE_HISTORY_LIST = build_tool(
    "chatgpt_ads_change_history_list",
    "Lists the ChatGPT Ads account's change history (audit log). Returns a "
    "JSON array of entries as the platform returns them: id, ts, actor_id, "
    "actor_type, audit_log_type, obj_type, obj_id, item_name and changes. "
    "Read-only. Optionally narrow to one campaign, ad group or ad. Use this to "
    "see who changed what before explaining a performance shift; for the "
    "performance itself use chatgpt_ads_insights_report.",
    {
        "period": {
            "type": "string",
            "description": (
                f"{PERIOD_DESCRIPTION} Default 'last_7d', which ends "
                "yesterday; pass 'today' for changes made today."
            ),
        },
        "campaign_id": id_param("Campaign whose changes to return", "cmpn_123"),
        "ad_group_id": id_param("Ad group whose changes to return", "adgrp_123"),
        "ad_id": id_param("Ad whose changes to return", "ad_123"),
        "limit": _limit_param(
            DEFAULT_LIST_LIMIT, "The API serves at most 100 entries per page."
        ),
    },
    [],
)

TOOLS: tuple[Tool, ...] = (
    _ACCOUNT_GET,
    _CAMPAIGNS_LIST,
    _CAMPAIGNS_GET,
    _AD_GROUPS_LIST,
    _AD_GROUPS_GET,
    _ADS_LIST,
    _ADS_GET,
    _INSIGHTS_REPORT,
    _CHANGE_HISTORY_LIST,
)

__all__ = [
    "ATTRIBUTION_WINDOWS",
    "CONVERSION_METRICS",
    "DEFAULT_INSIGHTS_LIMIT",
    "DEFAULT_LIST_LIMIT",
    "DELIVERY_METRICS",
    "ENTITY_LIMIT",
    "ID_PATTERN",
    "MAX_TOOL_LIMIT",
    "NAME_MAX_CHARS",
    "NAME_MIN_CHARS",
    "NAME_PATTERN",
    "PERIOD_DESCRIPTION",
    "TIME_GRANULARITIES",
    "TIME_GRANULARITY",
    "TOOLS",
    "build_tool",
    "id_param",
]
