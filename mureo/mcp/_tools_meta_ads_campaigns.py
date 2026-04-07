"""Meta Ads tool definitions — Campaigns, ad sets, ads"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Campaigns ===
    Tool(
        name="meta_ads.campaigns.list",
        description="List Meta Ads campaigns",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "status_filter": {
                    "type": "string",
                    "description": "Status filter (ACTIVE/PAUSED etc.)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 50)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.campaigns.get",
        description="Get Meta Ads campaign details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.campaigns.create",
        description="Create a Meta Ads campaign",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "name": {"type": "string", "description": "Campaign name"},
                "objective": {
                    "type": "string",
                    "description": "Campaign objective (CONVERSIONS, LINK_CLICKS etc.)",
                },
                "status": {
                    "type": "string",
                    "description": "Initial status (default: PAUSED)",
                },
                "daily_budget": {
                    "type": "integer",
                    "description": "Daily budget (in cents)",
                },
                "lifetime_budget": {
                    "type": "integer",
                    "description": "Lifetime budget (in cents)",
                },
            },
            "required": ["name", "objective"],
        },
    ),
    Tool(
        name="meta_ads.campaigns.update",
        description="Update a Meta Ads campaign",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "name": {"type": "string", "description": "New campaign name"},
                "status": {"type": "string", "description": "Status"},
                "daily_budget": {
                    "type": "integer",
                    "description": "Daily budget (in cents)",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Campaign pause / enable ===
    Tool(
        name="meta_ads.campaigns.pause",
        description="Pause a Meta Ads campaign",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.campaigns.enable",
        description="Enable (ACTIVE) a Meta Ads campaign",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
            },
            "required": ["campaign_id"],
        },
    ),
    # === Ad sets ===
    Tool(
        name="meta_ads.ad_sets.list",
        description="List Meta Ads ad sets",
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
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 50)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.ad_sets.create",
        description="Create a Meta Ads ad set",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "campaign_id": {"type": "string", "description": "Parent campaign ID"},
                "name": {"type": "string", "description": "Ad set name"},
                "daily_budget": {
                    "type": "integer",
                    "description": "Daily budget (in cents)",
                },
                "billing_event": {
                    "type": "string",
                    "description": "Billing event (default: IMPRESSIONS)",
                },
                "optimization_goal": {
                    "type": "string",
                    "description": "Optimization goal (default: REACH)",
                },
                "targeting": {"type": "object", "description": "Targeting settings"},
                "status": {
                    "type": "string",
                    "description": "Initial status (default: PAUSED)",
                },
                "bid_amount": {
                    "type": "integer",
                    "description": "Bid amount in cents (required for some optimization goals)",
                },
            },
            "required": ["campaign_id", "name"],
        },
    ),
    Tool(
        name="meta_ads.ad_sets.update",
        description="Update a Meta Ads ad set",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_set_id": {"type": "string", "description": "Ad set ID"},
                "name": {"type": "string", "description": "New name"},
                "status": {"type": "string", "description": "Status"},
                "daily_budget": {
                    "type": "integer",
                    "description": "Daily budget (in cents)",
                },
                "targeting": {"type": "object", "description": "Targeting settings"},
            },
            "required": ["ad_set_id"],
        },
    ),
    # === Ad set get / pause / enable ===
    Tool(
        name="meta_ads.ad_sets.get",
        description="Get Meta Ads ad set details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_set_id": {"type": "string", "description": "Ad set ID"},
            },
            "required": ["ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_sets.pause",
        description="Pause a Meta Ads ad set",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_set_id": {"type": "string", "description": "Ad set ID"},
            },
            "required": ["ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_sets.enable",
        description="Enable (ACTIVE) a Meta Ads ad set",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_set_id": {"type": "string", "description": "Ad set ID"},
            },
            "required": ["ad_set_id"],
        },
    ),
    # === Ads ===
    Tool(
        name="meta_ads.ads.list",
        description="List Meta Ads ads",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_set_id": {
                    "type": "string",
                    "description": "Filter by ad set ID",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 50)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.ads.create",
        description="Create a Meta Ads ad",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_set_id": {"type": "string", "description": "Parent ad set ID"},
                "name": {"type": "string", "description": "Ad name"},
                "creative_id": {"type": "string", "description": "Creative ID"},
                "status": {
                    "type": "string",
                    "description": "Initial status (default: PAUSED)",
                },
            },
            "required": ["ad_set_id", "name", "creative_id"],
        },
    ),
    Tool(
        name="meta_ads.ads.update",
        description="Update a Meta Ads ad",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_id": {"type": "string", "description": "Ad ID"},
                "name": {"type": "string", "description": "New name"},
                "status": {"type": "string", "description": "Status"},
            },
            "required": ["ad_id"],
        },
    ),
    # === Ad get / pause / enable ===
    Tool(
        name="meta_ads.ads.get",
        description="Get Meta Ads ad details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_id": {"type": "string", "description": "Ad ID"},
            },
            "required": ["ad_id"],
        },
    ),
    Tool(
        name="meta_ads.ads.pause",
        description="Pause a Meta Ads ad",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_id": {"type": "string", "description": "Ad ID"},
            },
            "required": ["ad_id"],
        },
    ),
    Tool(
        name="meta_ads.ads.enable",
        description="Enable (ACTIVE) a Meta Ads ad",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_id": {"type": "string", "description": "Ad ID"},
            },
            "required": ["ad_id"],
        },
    ),
]
