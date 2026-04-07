"""Google Ads tool definitions — Performance analysis, search terms, auctions, monitoring, capture"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Analysis ===
    Tool(
        name="google_ads.performance.report",
        description="Get Google Ads performance report",
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
                "period": {
                    "type": "string",
                    "description": "Period (LAST_7_DAYS, LAST_30_DAYS etc.)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.search_terms.report",
        description="Get Google Ads search terms report",
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
                "ad_group_id": {
                    "type": "string",
                    "description": "Filter by ad group ID",
                },
                "period": {"type": "string", "description": "Period"},
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
        description="Analyze a landing page and return structured data",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "url": {"type": "string", "description": "Landing page URL"},
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
