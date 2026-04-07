"""Meta Ads tool definitions — Conversions (CAPI)"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Conversions (CAPI) ===
    Tool(
        name="meta_ads.conversions.send",
        description="Send a conversion event via Meta Ads Conversions API (generic)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "events": {
                    "type": "array",
                    "description": "List of event data",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event_name": {
                                "type": "string",
                                "description": "Event name (Purchase, Lead etc.)",
                            },
                            "event_time": {
                                "type": "integer",
                                "description": "Event timestamp (UNIX timestamp)",
                            },
                            "action_source": {
                                "type": "string",
                                "description": "Action source (website etc.)",
                            },
                            "user_data": {
                                "type": "object",
                                "description": "User data (em, ph etc. will be SHA-256 hashed)",
                            },
                            "custom_data": {
                                "type": "object",
                                "description": "Custom data (currency, value etc.)",
                            },
                            "event_source_url": {
                                "type": "string",
                                "description": "Event source URL",
                            },
                        },
                        "required": [
                            "event_name",
                            "event_time",
                            "action_source",
                            "user_data",
                        ],
                    },
                },
                "test_event_code": {
                    "type": "string",
                    "description": "Test event code (for test mode)",
                },
            },
            "required": ["pixel_id", "events"],
        },
    ),
    Tool(
        name="meta_ads.conversions.send_purchase",
        description="Send a purchase event via Meta Ads Conversions API",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "event_time": {
                    "type": "integer",
                    "description": "Event timestamp (UNIX timestamp)",
                },
                "user_data": {
                    "type": "object",
                    "description": "User data (em, ph etc. will be SHA-256 hashed)",
                },
                "currency": {
                    "type": "string",
                    "description": "Currency code (USD, JPY etc.)",
                },
                "value": {"type": "number", "description": "Purchase amount"},
                "content_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of product IDs",
                },
                "event_source_url": {
                    "type": "string",
                    "description": "Event source URL",
                },
                "test_event_code": {
                    "type": "string",
                    "description": "Test event code",
                },
            },
            "required": [
                "account_id",
                "pixel_id",
                "event_time",
                "user_data",
                "currency",
                "value",
            ],
        },
    ),
    Tool(
        name="meta_ads.conversions.send_lead",
        description="Send a lead event via Meta Ads Conversions API",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "event_time": {
                    "type": "integer",
                    "description": "Event timestamp (UNIX timestamp)",
                },
                "user_data": {
                    "type": "object",
                    "description": "User data (em, ph etc. will be SHA-256 hashed)",
                },
                "event_source_url": {
                    "type": "string",
                    "description": "Event source URL",
                },
                "test_event_code": {
                    "type": "string",
                    "description": "Test event code",
                },
            },
            "required": ["pixel_id", "event_time", "user_data"],
        },
    ),
]
