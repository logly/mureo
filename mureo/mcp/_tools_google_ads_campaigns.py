"""Google Ads tool definitions — Campaigns, ad groups, ads, budgets, account"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Campaigns ===
    Tool(
        name="google_ads.campaigns.list",
        description="List Google Ads campaigns",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "status_filter": {
                    "type": "string",
                    "description": "Status filter (ENABLED/PAUSED)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.campaigns.get",
        description="Get Google Ads campaign details",
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
        name="google_ads.campaigns.create",
        description="Create a Google Ads campaign",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "name": {"type": "string", "description": "Campaign name"},
                "bidding_strategy": {
                    "type": "string",
                    "description": "Bidding strategy (MAXIMIZE_CLICKS etc.)",
                },
                "budget_id": {"type": "string", "description": "Budget ID"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="google_ads.campaigns.update",
        description="Update Google Ads campaign settings",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "name": {"type": "string", "description": "New campaign name"},
                "bidding_strategy": {
                    "type": "string",
                    "description": "Bidding strategy",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.campaigns.update_status",
        description="Change Google Ads campaign status (ENABLED/PAUSED/REMOVED)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "status": {
                    "type": "string",
                    "description": "New status (ENABLED/PAUSED/REMOVED)",
                },
            },
            "required": ["campaign_id", "status"],
        },
    ),
    Tool(
        name="google_ads.campaigns.diagnose",
        description="Diagnose Google Ads campaign delivery status",
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
    # === Ad Groups ===
    Tool(
        name="google_ads.ad_groups.list",
        description="List Google Ads ad groups",
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
                "status_filter": {
                    "type": "string",
                    "description": "Status filter",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.ad_groups.create",
        description="Create a Google Ads ad group",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Parent campaign ID"},
                "name": {"type": "string", "description": "Ad group name"},
                "cpc_bid_micros": {
                    "type": "integer",
                    "description": "CPC bid amount (in micros)",
                },
            },
            "required": ["campaign_id", "name"],
        },
    ),
    Tool(
        name="google_ads.ad_groups.update",
        description="Update a Google Ads ad group",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "name": {"type": "string", "description": "New name"},
                "status": {
                    "type": "string",
                    "description": "Status (ENABLED/PAUSED)",
                },
                "cpc_bid_micros": {
                    "type": "integer",
                    "description": "CPC bid amount (in micros)",
                },
            },
            "required": ["ad_group_id"],
        },
    ),
    # === Ads ===
    Tool(
        name="google_ads.ads.list",
        description="List Google Ads ads",
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
                "status_filter": {
                    "type": "string",
                    "description": "Status filter",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.ads.create",
        description="Create a Google Ads responsive search ad (RSA)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "headlines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of headlines (3 to 15)",
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of descriptions (2 to 4)",
                },
                "final_url": {"type": "string", "description": "Final URL"},
                "path1": {"type": "string", "description": "Display path 1"},
                "path2": {"type": "string", "description": "Display path 2"},
            },
            "required": ["ad_group_id", "headlines", "descriptions"],
        },
    ),
    Tool(
        name="google_ads.ads.update",
        description="Update a Google Ads ad",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "ad_id": {"type": "string", "description": "Ad ID"},
                "headlines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of headlines",
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of descriptions",
                },
            },
            "required": ["ad_group_id", "ad_id"],
        },
    ),
    Tool(
        name="google_ads.ads.update_status",
        description="Change Google Ads ad status",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "ad_id": {"type": "string", "description": "Ad ID"},
                "status": {
                    "type": "string",
                    "description": "New status (ENABLED/PAUSED)",
                },
            },
            "required": ["ad_group_id", "ad_id", "status"],
        },
    ),
    # === Ad policy details ===
    Tool(
        name="google_ads.ads.policy_details",
        description="Get Google Ads ad policy details (disapproval reasons etc.)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "ad_id": {"type": "string", "description": "Ad ID"},
            },
            "required": ["ad_group_id", "ad_id"],
        },
    ),
    # === Budgets ===
    Tool(
        name="google_ads.budget.get",
        description="Get Google Ads campaign budget",
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
        name="google_ads.budget.update",
        description="Update a Google Ads budget",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "budget_id": {"type": "string", "description": "Budget ID"},
                "amount": {"type": "number", "description": "New daily budget amount"},
            },
            "required": ["budget_id", "amount"],
        },
    ),
    # === Budget creation ===
    Tool(
        name="google_ads.budget.create",
        description="Create a new Google Ads campaign budget",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "name": {"type": "string", "description": "Budget name"},
                "amount": {"type": "number", "description": "Daily budget amount"},
            },
            "required": ["name", "amount"],
        },
    ),
    # === Account ===
    Tool(
        name="google_ads.accounts.list",
        description="List Google Ads managed accounts",
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
]
