"""Meta Ads tool definitions — Audiences, pixels"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Audiences ===
    Tool(
        name="meta_ads.audiences.list",
        description="List Meta Ads custom audiences",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
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
        name="meta_ads.audiences.create",
        description="Create a Meta Ads custom audience",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "name": {"type": "string", "description": "Audience name"},
                "subtype": {
                    "type": "string",
                    "description": "Subtype (WEBSITE, CUSTOM, APP etc.)",
                },
                "description": {"type": "string", "description": "Description"},
                "retention_days": {
                    "type": "integer",
                    "description": "Retention period (in days)",
                },
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
            },
            "required": ["name", "subtype"],
        },
    ),
    # === Audience get / delete / lookalike ===
    Tool(
        name="meta_ads.audiences.get",
        description="Get Meta Ads custom audience details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "audience_id": {"type": "string", "description": "Audience ID"},
            },
            "required": ["audience_id"],
        },
    ),
    Tool(
        name="meta_ads.audiences.delete",
        description="Delete a Meta Ads custom audience",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "audience_id": {"type": "string", "description": "Audience ID"},
            },
            "required": ["audience_id"],
        },
    ),
    Tool(
        name="meta_ads.audiences.create_lookalike",
        description="Create a Meta Ads lookalike audience",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "name": {"type": "string", "description": "Audience name"},
                "source_audience_id": {
                    "type": "string",
                    "description": "Source custom audience ID",
                },
                "country": {
                    "description": "Target country code (string or array)",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "ratio": {
                    "type": "number",
                    "description": "Similarity ratio (0.01=top 1%, max 0.20)",
                },
                "starting_ratio": {
                    "type": "number",
                    "description": "Starting ratio (default: 0.0)",
                },
            },
            "required": [
                "account_id",
                "name",
                "source_audience_id",
                "country",
                "ratio",
            ],
        },
    ),
    # === Pixels ===
    Tool(
        name="meta_ads.pixels.list",
        description="List Meta Ads pixels",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
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
        name="meta_ads.pixels.get",
        description="Get Meta Ads pixel details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "pixel_id": {"type": "string", "description": "Pixel ID"},
            },
            "required": ["pixel_id"],
        },
    ),
    Tool(
        name="meta_ads.pixels.stats",
        description="Get Meta Ads pixel event statistics",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "pixel_id": {"type": "string", "description": "Pixel ID"},
                "period": {
                    "type": "string",
                    "description": "Aggregation period (last_7d, last_14d, last_30d, last_90d)",
                },
            },
            "required": ["pixel_id"],
        },
    ),
    Tool(
        name="meta_ads.pixels.events",
        description="List event types received by a Meta Ads pixel",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "pixel_id": {"type": "string", "description": "Pixel ID"},
            },
            "required": ["pixel_id"],
        },
    ),
]
