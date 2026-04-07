"""Meta Ads tool definitions — Insights, analysis"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Insights ===
    Tool(
        name="meta_ads.insights.report",
        description="Get Meta Ads performance report",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Filter by campaign ID",
                },
                "period": {
                    "type": "string",
                    "description": "Period (today, yesterday, last_7d, last_30d etc.)",
                },
                "level": {
                    "type": "string",
                    "description": "Aggregation level (campaign, adset, ad)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.insights.breakdown",
        description="Get Meta Ads report with breakdown",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "breakdown": {
                    "type": "string",
                    "description": "Breakdown type (age, gender etc.)",
                },
                "period": {"type": "string", "description": "Period"},
            },
            "required": ["campaign_id"],
        },
    ),
    # === Performance analysis ===
    Tool(
        name="meta_ads.analysis.performance",
        description="Comprehensively analyze Meta Ads campaign performance (with period comparison and insights)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID (omit for entire account)",
                },
                "period": {
                    "type": "string",
                    "description": "Period (today, yesterday, last_7d, last_30d etc.)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.analysis.audience",
        description="Analyze Meta Ads audience efficiency by age and gender",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {
                    "type": "string",
                    "description": "Period (last_7d, last_30d etc.)",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.placements",
        description="Analyze Meta Ads performance by placement",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {
                    "type": "string",
                    "description": "Period (last_7d, last_30d etc.)",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.cost",
        description="Investigate causes of Meta Ads cost increase or CPA degradation",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {
                    "type": "string",
                    "description": "Period (last_7d, last_30d etc.)",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.compare_ads",
        description="A/B compare ad performance within a Meta Ads ad set",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_set_id": {"type": "string", "description": "Ad set ID"},
                "period": {
                    "type": "string",
                    "description": "Period (last_7d, last_30d etc.)",
                },
            },
            "required": ["ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.suggest_creative",
        description="Generate creative improvement suggestions based on Meta Ads ad performance",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {
                    "type": "string",
                    "description": "Period (last_7d, last_30d etc.)",
                },
            },
            "required": ["campaign_id"],
        },
    ),
]
