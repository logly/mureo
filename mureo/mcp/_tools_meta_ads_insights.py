"""Meta Ads tool definitions — Insights, analysis.

Tool descriptions follow ``docs/tdqs-style-guide.md``. Insights tools
pull raw delivery metrics straight from the Meta Graph API; analysis
tools apply mureo-side heuristics (period comparison, outlier
detection, A/B scoring) on top of those metrics to produce
operator-ready findings.
"""

from __future__ import annotations

from mcp.types import Tool

# Reusable parameter fragments.
_ACCOUNT_ID_PARAM = {
    "type": "string",
    "description": (
        "Meta Ads account ID in the format 'act_XXXXXXXXXX' (e.g. "
        "'act_1234567890'). Optional — falls back to META_ADS_ACCOUNT_ID "
        "from the configured credentials. The leading 'act_' prefix is "
        "required."
    ),
}

_PERIOD_PARAM = {
    "type": "string",
    "description": (
        "Analysis window. Accepts Meta predefined ranges ('today', "
        "'yesterday', 'last_7d', 'last_14d', 'last_30d' (default), "
        "'last_90d') or explicit 'YYYY-MM-DD..YYYY-MM-DD'. Longer "
        "windows cost more Graph API quota."
    ),
}

TOOLS: list[Tool] = [
    # === Insights ===
    Tool(
        name="meta_ads_insights_report",
        description=(
            "Pulls raw delivery metrics from Meta Graph API Insights for "
            "one campaign or the whole account. Returns rows with "
            "impressions, reach, clicks, spend, cpc, cpm, ctr, "
            "conversions, cost_per_conversion, and purchase_roas, "
            "aggregated at the requested level (campaign / adset / ad). "
            "Read-only. Use this when you need raw metrics; for "
            "interpreted findings (period comparison, outlier callouts) "
            "use meta_ads_analysis_performance instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict to a single campaign. Omit to report "
                        "across the whole account."
                    ),
                },
                "period": _PERIOD_PARAM,
                "level": {
                    "type": "string",
                    "enum": ["account", "campaign", "adset", "ad"],
                    "description": (
                        "Aggregation level. Default 'campaign'. Finer "
                        "levels (adset, ad) return more rows and consume "
                        "more Graph quota."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads_insights_breakdown",
        description=(
            "Pulls delivery metrics for a campaign broken down along one "
            "dimension (age, gender, device_platform, placement, country, "
            "region, etc.). Returns rows with the breakdown key plus "
            "impressions, clicks, spend, cpc, ctr, conversions, and "
            "cost_per_conversion. Read-only. Use this for ad-hoc slicing; "
            "for pre-packaged splits use the dedicated "
            "meta_ads_analysis_audience (age/gender) or "
            "meta_ads_analysis_placements tools, which add "
            "interpretation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign to break down.",
                },
                "breakdown": {
                    "type": "string",
                    "enum": [
                        "age",
                        "gender",
                        "age,gender",
                        "country",
                        "region",
                        "device_platform",
                        "publisher_platform",
                        "placement",
                        "impression_device",
                    ],
                    "description": (
                        "Dimension to split by. Meta accepts a single "
                        "breakdown or a small set joined by commas "
                        "(e.g. 'age,gender'). Some combinations are "
                        "rejected by Meta — stick to one breakdown per "
                        "call when unsure."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    # === Performance analysis ===
    Tool(
        name="meta_ads_analysis_performance",
        description=(
            "Produces an operator-ready performance review for a Meta Ads "
            "campaign (or the whole account) with period-over-period "
            "comparison. Returns current-period metrics, prior-period "
            "metrics (same length immediately before current), delta %, "
            "and a ranked list of callouts (e.g. 'CPA up 32% week-over-"
            "week', 'impressions down 45%'). Read-only. Use this at the "
            "start of an audit — it narrows attention before pulling raw "
            "insights via meta_ads.insights.report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict to a single campaign. Omit to analyse "
                        "the whole account."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads_analysis_audience",
        description=(
            "Scores delivery efficiency across age × gender segments and "
            "flags the best and worst performing buckets. Returns rows "
            "per age_range × gender with spend, conversions, CPA, and a "
            "relative_score vs the campaign average, plus a "
            "recommendations array (e.g. 'Pause 55-64 male — 3x CPA, 1 "
            "conversion'). Read-only. Use before adjusting targeting; "
            "for raw breakdown numbers use meta_ads_insights_breakdown "
            "with breakdown='age,gender'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign to analyse.",
                },
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads_analysis_placements",
        description=(
            "Scores delivery efficiency across Meta placements (Facebook "
            "Feed, Instagram Feed, Stories, Reels, Audience Network, "
            "Messenger, etc.) and flags the best and worst. Returns rows "
            "per placement with spend, conversions, CPA, ctr, and a "
            "recommendation (exclude / keep / scale). Read-only. Call "
            "this when CPA drifts on a campaign to find whether a single "
            "placement is dragging the average. For raw numbers use "
            "meta_ads_insights_breakdown with breakdown='placement'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign to analyse.",
                },
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads_analysis_cost",
        description=(
            "Diagnoses root causes of rising spend or degrading CPA on a "
            "Meta Ads campaign. Returns a decomposition that attributes "
            "the cost change to drivers — bid increase, CPM inflation, "
            "CTR drop, CVR drop, audience saturation, or creative "
            "fatigue — with per-driver magnitude and a specific action "
            "hint. Read-only. Use this when the operator reports 'why "
            "did CPA jump'; it separates auction-side from creative-side "
            "causes in one call."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign to diagnose.",
                },
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads_analysis_compare_ads",
        description=(
            "Runs an A/B-style comparison of ads inside a single ad set, "
            "ranking them by efficiency and flagging statistically "
            "meaningful winners. Returns rows per ad with impressions, "
            "spend, conversions, CPA, CTR, and a relative-score vs the "
            "ad set average, plus a verdict (winner / laggard / "
            "insufficient-data). Read-only. Use this to decide which "
            "creatives to pause; pair with meta_ads_ads_pause for "
            "action."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_set_id": {
                    "type": "string",
                    "description": (
                        "Ad set whose ads will be compared. Comparison "
                        "is always within a single ad set (same "
                        "targeting, same budget) so differences reflect "
                        "creative."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": ["ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads_analysis_suggest_creative",
        description=(
            "Generates concrete creative-improvement suggestions for a "
            "Meta Ads campaign based on recent ad performance. Returns a "
            "ranked list of suggestions (e.g. 'add a short-form video — "
            "carousel CTR is 2x static image', 'rotate headlines — "
            "top-3 CTR ads all use question-form headlines'). Read-only "
            "— does not create creatives. Follow up with "
            "meta_ads_creatives_create* to materialize the suggestions "
            "after operator review."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign to analyse.",
                },
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
]
