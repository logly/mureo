"""Google Ads tool definitions — Performance analysis, search terms, auctions, monitoring, capture.

Tool descriptions follow ``docs/tdqs-style-guide.md``: specific verb, returned
fields, side effects, and differentiation from sibling tools. See the guide
before adding a new tool or rewriting an existing one.
"""

from __future__ import annotations

from mcp.types import Tool

# Reusable parameter fragments — keep descriptions consistent across tools.
_CUSTOMER_ID_PARAM = {
    "type": "string",
    "description": (
        "Google Ads customer ID as a 10-digit string without dashes "
        "(e.g. '1234567890'). Optional — falls back to "
        "GOOGLE_ADS_CUSTOMER_ID / GOOGLE_ADS_LOGIN_CUSTOMER_ID from the "
        "configured credentials when omitted."
    ),
}

_PERIOD_PARAM = {
    "type": "string",
    "enum": [
        "TODAY",
        "YESTERDAY",
        "LAST_7_DAYS",
        "LAST_14_DAYS",
        "LAST_30_DAYS",
        "LAST_90_DAYS",
        "THIS_MONTH",
        "LAST_MONTH",
    ],
    "description": (
        "Reporting window for the metrics. Default 'LAST_30_DAYS'. Use a "
        "shorter window (LAST_7_DAYS / LAST_14_DAYS) when diagnosing recent "
        "changes; use LAST_90_DAYS for trend baselines."
    ),
}

TOOLS: list[Tool] = [
    # === Analysis ===
    Tool(
        name="google_ads.performance.report",
        description=(
            "Aggregate campaign-level performance metrics for a Google Ads "
            "account over a reporting window. Returns one row per campaign "
            "with id, name, status, impressions, clicks, cost_micros, "
            "conversions, conversion_value, ctr, average_cpc, "
            "cost_per_conversion, and conversion_rate. Read-only; no "
            "mutation. Use this for campaign-level totals. For per-ad "
            "breakdowns use google_ads.ad_performance.report; for Google "
            "Search vs. Search Partners splits use "
            "google_ads.network_performance.report; for query-level detail "
            "use google_ads.search_terms.report; for conversion-action "
            "slicing use google_ads.conversions.performance."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict the report to a single campaign by numeric "
                        "ID (e.g. '23743184133'). Omit to aggregate across "
                        "every campaign in the account."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.search_terms.report",
        description=(
            "List actual user search queries that triggered ads in the "
            "account over a reporting window. Returns one row per "
            "(search_term, keyword, match_type) with impressions, clicks, "
            "cost_micros, conversions, conversion_value, and the triggering "
            "ad group. Read-only. Use this for raw query logs when you need "
            "to eyeball the terms yourself. For rule-based add/exclude "
            "candidates use google_ads.search_terms.review; for intent-class "
            "distribution use google_ads.search_terms.analyze; for "
            "campaign-level aggregates without query breakdown use "
            "google_ads.performance.report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict results to a single campaign by numeric "
                        "ID. Omit to include all campaigns."
                    ),
                },
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Restrict results to a single ad group by numeric "
                        "ID. Omit to include all ad groups under the "
                        "campaign filter (or the entire account if "
                        "campaign_id is also omitted)."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.search_terms.review",
        description="Review Google Ads search terms with multi-stage rules and suggest addition/exclusion candidates",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {
                    "type": "string",
                    "description": "Period (default: LAST_7_DAYS)",
                },
                "target_cpa": {"type": "number", "description": "Target CPA"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.auction_insights.analyze",
        description="Analyze Google Ads auction insights",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.cpc.detect_trend",
        description="Detect Google Ads CPC increase trends",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.device.analyze",
        description="Analyze Google Ads performance by device",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    # === Network performance report ===
    Tool(
        name="google_ads.network_performance.report",
        description="Get Google Ads network performance report (Google Search vs Search Partners)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Filter by campaign ID",
                },
                "period": {"type": "string", "description": "Period"},
            },
            "required": [],
        },
    ),
    # === Per-ad report ===
    Tool(
        name="google_ads.ad_performance.report",
        description="Get Google Ads per-ad performance report",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {
                    "type": "string",
                    "description": "Filter by ad group ID",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Filter by campaign ID",
                },
                "period": {"type": "string", "description": "Period"},
            },
            "required": [],
        },
    ),
    # === Search Term Analysis ===
    Tool(
        name="google_ads.search_terms.analyze",
        description="Analyze Google Ads search term and keyword overlap and N-gram distribution",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    # === Performance analysis ===
    Tool(
        name="google_ads.performance.analyze",
        description="Comprehensively analyze Google Ads campaign performance",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.cost_increase.investigate",
        description="Investigate causes of Google Ads cost increase or CPA degradation",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.health_check.all",
        description="Run a health check on all active Google Ads campaigns",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.ad_performance.compare",
        description="Compare ad performance within a Google Ads ad group",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["ad_group_id"],
        },
    ),
    # === Budget analysis ===
    Tool(
        name="google_ads.budget.efficiency",
        description="Analyze budget allocation efficiency across all active Google Ads campaigns",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "period": {"type": "string", "description": "Period"},
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.budget.reallocation",
        description="Generate budget reallocation suggestions for all Google Ads campaigns",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "period": {"type": "string", "description": "Period"},
            },
            "required": [],
        },
    ),
    # === Auction insights ===
    Tool(
        name="google_ads.auction_insights.get",
        description="Get Google Ads campaign auction insights data",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    # === RSA analysis ===
    Tool(
        name="google_ads.rsa_assets.analyze",
        description="Analyze Google Ads RSA per-asset performance",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.rsa_assets.audit",
        description="Audit Google Ads RSA assets and generate replacement/addition recommendations",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    # === BtoB ===
    Tool(
        name="google_ads.btob.optimizations",
        description="Run B2B business optimization checks and generate improvement suggestions",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    # === Creative ===
    Tool(
        name="google_ads.landing_page.analyze",
        description=(
            "Fetch a landing page over HTTP(S) and extract structured "
            "content for ad-copy alignment. Returns title, meta_description, "
            "h1_texts, h2_texts, main_text (truncated to ~1500 chars), "
            "cta_texts, features, prices (JP yen patterns), brand_name, "
            "industry_hints, og_title, og_description, and structured_data "
            "(JSON-LD). On fetch or parse failure, returns the same shape "
            "with an ``error`` field set instead of raising. Side effect: "
            "issues one outbound HTTP GET to the URL with a 15s timeout and "
            "500KB body cap; SSRF-protected against localhost, private "
            "networks, and cloud metadata endpoints. The Google Ads "
            "customer context is unused by the analysis itself — passing "
            "customer_id only scopes credential routing. Use this for "
            "ad-copy vs. LP message-match and keyword-extraction workflows. "
            "For Google's indexing/coverage view of the same URL use "
            "search_console.url_inspection.inspect; for a batched workflow "
            "that combines LP analysis with existing ads, search terms, "
            "and keyword suggestions use google_ads.creative.research."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "Absolute landing page URL to fetch (http:// or "
                        "https:// scheme only, e.g. "
                        "'https://example.com/lp/offer'). Private-range, "
                        "loopback, and cloud-metadata hosts are rejected."
                    ),
                },
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="google_ads.creative.research",
        description="Creative research: batch collection of LP analysis, existing ads, search terms, and keyword suggestions",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "url": {"type": "string", "description": "Landing page URL"},
                "ad_group_id": {
                    "type": "string",
                    "description": "Filter by ad group ID",
                },
            },
            "required": ["campaign_id", "url"],
        },
    ),
    # === Monitoring ===
    Tool(
        name="google_ads.monitoring.delivery_goal",
        description="Evaluate Google Ads delivery goals and assess delivery status and performance",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.monitoring.cpa_goal",
        description="Evaluate current performance against Google Ads CPA goals",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "target_cpa": {"type": "number", "description": "Target CPA"},
            },
            "required": ["campaign_id", "target_cpa"],
        },
    ),
    Tool(
        name="google_ads.monitoring.cv_goal",
        description="Evaluate current performance against Google Ads daily conversion goals",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "target_cv_daily": {
                    "type": "number",
                    "description": "Daily conversion target",
                },
            },
            "required": ["campaign_id", "target_cv_daily"],
        },
    ),
    Tool(
        name="google_ads.monitoring.zero_conversions",
        description="Diagnose causes of zero conversions in Google Ads",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
            },
            "required": ["campaign_id"],
        },
    ),
    # === Capture ===
    Tool(
        name="google_ads.capture.screenshot",
        description="Capture a URL screenshot in PNG format (for message match evaluation)",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to capture"},
            },
            "required": ["url"],
        },
    ),
]
