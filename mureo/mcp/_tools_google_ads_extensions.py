"""Google Ads tool definitions — Sitelinks, callouts, conversions, targeting"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Sitelinks ===
    Tool(
        name="google_ads.sitelinks.list",
        description="List Google Ads campaign sitelinks",
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
        name="google_ads.sitelinks.create",
        description="Create a Google Ads sitelink and link it to a campaign",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "link_text": {"type": "string", "description": "Link text"},
                "final_url": {"type": "string", "description": "Final URL"},
                "description1": {"type": "string", "description": "Description line 1"},
                "description2": {"type": "string", "description": "Description line 2"},
            },
            "required": ["campaign_id", "link_text", "final_url"],
        },
    ),
    Tool(
        name="google_ads.sitelinks.remove",
        description="Remove a Google Ads sitelink",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "asset_id": {"type": "string", "description": "Asset ID"},
            },
            "required": ["campaign_id", "asset_id"],
        },
    ),
    # === Callouts ===
    Tool(
        name="google_ads.callouts.list",
        description="List Google Ads campaign callouts",
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
        name="google_ads.callouts.create",
        description="Create a Google Ads callout and link it to a campaign",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "callout_text": {
                    "type": "string",
                    "description": "Callout text",
                },
            },
            "required": ["campaign_id", "callout_text"],
        },
    ),
    Tool(
        name="google_ads.callouts.remove",
        description="Remove a Google Ads callout",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "asset_id": {"type": "string", "description": "Asset ID"},
            },
            "required": ["campaign_id", "asset_id"],
        },
    ),
    # === Conversions ===
    Tool(
        name="google_ads.conversions.list",
        description="List Google Ads conversion actions",
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
        name="google_ads.conversions.get",
        description="Get Google Ads conversion action details",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "conversion_action_id": {
                    "type": "string",
                    "description": "Conversion action ID",
                },
            },
            "required": ["conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads.conversions.performance",
        description="Get Google Ads conversion performance by conversion action",
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
    Tool(
        name="google_ads.conversions.create",
        description="Create a Google Ads conversion action",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "name": {
                    "type": "string",
                    "description": "Conversion action name",
                },
                "type": {
                    "type": "string",
                    "description": "Type (WEBPAGE/UPLOAD_CLICKS etc.)",
                },
                "category": {
                    "type": "string",
                    "description": "Category (PURCHASE/SIGNUP etc.)",
                },
                "default_value": {
                    "type": "number",
                    "description": "Default conversion value",
                },
                "always_use_default_value": {
                    "type": "boolean",
                    "description": "Whether to always use the default value",
                },
                "click_through_lookback_window_days": {
                    "type": "integer",
                    "description": "Click-through lookback window (1-90 days)",
                },
                "view_through_lookback_window_days": {
                    "type": "integer",
                    "description": "View-through lookback window (1-30 days)",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="google_ads.conversions.update",
        description="Update a Google Ads conversion action",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "conversion_action_id": {
                    "type": "string",
                    "description": "Conversion action ID",
                },
                "name": {"type": "string", "description": "New name"},
                "category": {"type": "string", "description": "Category"},
                "status": {
                    "type": "string",
                    "description": "Status (ENABLED/HIDDEN/REMOVED)",
                },
                "default_value": {
                    "type": "number",
                    "description": "Default conversion value",
                },
                "always_use_default_value": {
                    "type": "boolean",
                    "description": "Whether to always use the default value",
                },
                "click_through_lookback_window_days": {
                    "type": "integer",
                    "description": "Click-through lookback window (1-90 days)",
                },
                "view_through_lookback_window_days": {
                    "type": "integer",
                    "description": "View-through lookback window (1-30 days)",
                },
            },
            "required": ["conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads.conversions.remove",
        description="Remove a Google Ads conversion action",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "conversion_action_id": {
                    "type": "string",
                    "description": "Conversion action ID",
                },
            },
            "required": ["conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads.conversions.tag",
        description="Get Google Ads conversion action tag snippet",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "conversion_action_id": {
                    "type": "string",
                    "description": "Conversion action ID",
                },
            },
            "required": ["conversion_action_id"],
        },
    ),
    # === Recommendations ===
    Tool(
        name="google_ads.recommendations.list",
        description="List Google Ads recommendations",
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
                "recommendation_type": {
                    "type": "string",
                    "description": "Filter by recommendation type",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.recommendations.apply",
        description="Apply a Google Ads recommendation",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "resource_name": {
                    "type": "string",
                    "description": "Recommendation resource name",
                },
            },
            "required": ["resource_name"],
        },
    ),
    # === Device Targeting ===
    Tool(
        name="google_ads.device_targeting.get",
        description="Get Google Ads campaign device targeting settings",
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
        name="google_ads.device_targeting.set",
        description="Set Google Ads device targeting (serve only on specified devices)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "enabled_devices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of devices to enable (MOBILE/DESKTOP/TABLET)",
                },
            },
            "required": ["campaign_id", "enabled_devices"],
        },
    ),
    # === Bid adjustments ===
    Tool(
        name="google_ads.bid_adjustments.get",
        description="Get Google Ads campaign bid adjustments",
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
        name="google_ads.bid_adjustments.update",
        description="Update Google Ads bid adjustments",
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
                    "description": "Criterion ID",
                },
                "bid_modifier": {
                    "type": "number",
                    "description": "Bid modifier (0.1 to 10.0)",
                },
            },
            "required": ["campaign_id", "criterion_id", "bid_modifier"],
        },
    ),
    # === Geographic Targeting ===
    Tool(
        name="google_ads.location_targeting.list",
        description="List Google Ads campaign location targeting",
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
        name="google_ads.location_targeting.update",
        description="Update Google Ads location targeting (add/remove)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "add_locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Location IDs to add (geoTargetConstants/2392 format)",
                },
                "remove_criterion_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of criterion IDs to remove",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Ad schedules ===
    Tool(
        name="google_ads.schedule_targeting.list",
        description=(
            "List the ad-schedule (day-of-week + hour-of-day) targeting "
            "criteria attached to a Google Ads campaign. Returns one row per "
            "schedule criterion with criterion_id, day_of_week "
            "(MONDAY–SUNDAY), start_hour (0–23), end_hour (1–24), "
            "start_minute, end_minute, and bid_modifier. Read-only; returns "
            "an empty list when the campaign has no schedule targeting "
            "(meaning: 24/7 delivery). Use this to audit schedule coverage "
            "or collect criterion_ids before calling "
            "google_ads.schedule_targeting.update (which is what you use to "
            "add or remove entries). For device-level modifiers use "
            "google_ads.device_targeting.get; for geo targeting use "
            "google_ads.location_targeting.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": (
                        "Google Ads customer ID as a 10-digit string "
                        "without dashes (e.g. '1234567890'). Optional — "
                        "falls back to GOOGLE_ADS_CUSTOMER_ID / "
                        "GOOGLE_ADS_LOGIN_CUSTOMER_ID from the configured "
                        "credentials when omitted."
                    ),
                },
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign ID as a numeric string (e.g. "
                        "'23743184133'). Required — schedule targeting is "
                        "always scoped to a single campaign. Obtain via "
                        "google_ads.campaigns.list."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.schedule_targeting.update",
        description="Update Google Ads ad schedules (add/remove)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "campaign_id": {"type": "string", "description": "Campaign ID"},
                "add_schedules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {
                                "type": "string",
                                "description": "Day of week (MONDAY to SUNDAY)",
                            },
                            "start_hour": {
                                "type": "integer",
                                "description": "Start hour (0-23)",
                            },
                            "end_hour": {
                                "type": "integer",
                                "description": "End hour (1-24)",
                            },
                        },
                        "required": ["day"],
                    },
                    "description": "List of schedules to add",
                },
                "remove_criterion_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of criterion IDs to remove",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Change History ===
    Tool(
        name="google_ads.change_history.list",
        description="List Google Ads change history (default: last 14 days)",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)",
                },
            },
            "required": [],
        },
    ),
]
