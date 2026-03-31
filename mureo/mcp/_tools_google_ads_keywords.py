"""Google Ads tool definitions — Keywords, negative keywords"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Keywords ===
    Tool(
        name="google_ads.keywords.list",
        description="List Google Ads keywords",
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
                "status_filter": {
                    "type": "string",
                    "description": "Status filter",
                },
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.keywords.add",
        description="Add Google Ads keywords",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "keywords": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "match_type": {
                                "type": "string",
                                "description": "BROAD/PHRASE/EXACT",
                            },
                        },
                        "required": ["text"],
                    },
                    "description": "List of keywords to add",
                },
            },
            "required": ["customer_id", "ad_group_id", "keywords"],
        },
    ),
    Tool(
        name="google_ads.keywords.remove",
        description="Remove a Google Ads keyword",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "criterion_id": {
                    "type": "string",
                    "description": "Keyword criterion ID",
                },
            },
            "required": ["customer_id", "ad_group_id", "criterion_id"],
        },
    ),
    Tool(
        name="google_ads.keywords.suggest",
        description="Google Ads keyword suggestions (Keyword Planner)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "seed_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of seed keywords",
                },
                "language_id": {
                    "type": "string",
                    "description": "Language ID (default: 1005=Japanese)",
                },
                "geo_id": {
                    "type": "string",
                    "description": "Geo target ID (default: 2392=Japan)",
                },
            },
            "required": ["customer_id", "seed_keywords"],
        },
    ),
    Tool(
        name="google_ads.keywords.diagnose",
        description="Diagnose Google Ads keyword quality scores and delivery status",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === Negative Keywords ===
    Tool(
        name="google_ads.negative_keywords.list",
        description="List Google Ads negative keywords",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    Tool(
        name="google_ads.negative_keywords.add",
        description="Add a Google Ads negative keyword",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "keywords": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "match_type": {
                                "type": "string",
                                "description": "BROAD/PHRASE/EXACT",
                            },
                        },
                        "required": ["text"],
                    },
                    "description": "List of negative keywords to add",
                },
            },
            "required": ["customer_id", "campaign_id", "keywords"],
        },
    ),
    # === Keyword pause ===
    Tool(
        name="google_ads.keywords.pause",
        description="Pause a Google Ads keyword",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "criterion_id": {
                    "type": "string",
                    "description": "Keyword criterion ID",
                },
            },
            "required": ["customer_id", "ad_group_id", "criterion_id"],
        },
    ),
    # === Negative keyword removal ===
    Tool(
        name="google_ads.negative_keywords.remove",
        description="Remove a Google Ads negative keyword",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "criterion_id": {
                    "type": "string",
                    "description": "Negative keyword criterion ID",
                },
            },
            "required": ["customer_id", "campaign_id", "criterion_id"],
        },
    ),
    # === Ad group-level negative keyword addition ===
    Tool(
        name="google_ads.negative_keywords.add_to_ad_group",
        description="Add Google Ads ad group-level negative keywords",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "ad_group_id": {"type": "string", "description": "Ad group ID"},
                "keywords": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "match_type": {
                                "type": "string",
                                "description": "BROAD/PHRASE/EXACT",
                            },
                        },
                        "required": ["text"],
                    },
                    "description": "List of negative keywords to add",
                },
            },
            "required": ["customer_id", "ad_group_id", "keywords"],
        },
    ),
    # === Automatic negative keyword suggestions ===
    Tool(
        name="google_ads.negative_keywords.suggest",
        description="Automatically suggest Google Ads negative keyword candidates",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
                "target_cpa": {"type": "number", "description": "Target CPA"},
                "ad_group_id": {
                    "type": "string",
                    "description": "Filter by ad group ID",
                },
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === Keyword Inventory ===
    Tool(
        name="google_ads.keywords.audit",
        description="Audit Google Ads keywords and suggest improvement actions",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "period": {"type": "string", "description": "Period"},
                "target_cpa": {"type": "number", "description": "Target CPA"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === Cross-ad-group keyword duplicate detection ===
    Tool(
        name="google_ads.keywords.cross_adgroup_duplicates",
        description="Detect cross-ad-group keyword duplicates and return consolidation/removal recommendations",
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
            "required": ["customer_id", "campaign_id"],
        },
    ),
]
