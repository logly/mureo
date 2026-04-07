"""Meta Ads tool definitions — Lead forms, leads"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Lead Ads ===
    Tool(
        name="meta_ads.lead_forms.list",
        description="List Meta Ads lead forms (per page)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "page_id": {"type": "string", "description": "Facebook page ID"},
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 50)",
                },
            },
            "required": ["page_id"],
        },
    ),
    Tool(
        name="meta_ads.lead_forms.get",
        description="Get Meta Ads lead form details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "form_id": {"type": "string", "description": "Lead form ID"},
            },
            "required": ["form_id"],
        },
    ),
    Tool(
        name="meta_ads.lead_forms.create",
        description="Create a Meta Ads lead form (per page)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "page_id": {"type": "string", "description": "Facebook page ID"},
                "name": {"type": "string", "description": "Form name"},
                "questions": {
                    "type": "array",
                    "description": "List of questions (FULL_NAME, EMAIL, PHONE_NUMBER, COMPANY_NAME, CUSTOM etc.)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "description": "Question type"},
                            "key": {
                                "type": "string",
                                "description": "Custom question key (CUSTOM type only)",
                            },
                            "label": {
                                "type": "string",
                                "description": "Custom question label (CUSTOM type only)",
                            },
                            "options": {
                                "type": "array",
                                "description": "Options (CUSTOM type only)",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "value": {"type": "string"},
                                    },
                                },
                            },
                        },
                        "required": ["type"],
                    },
                },
                "privacy_policy_url": {
                    "type": "string",
                    "description": "Privacy policy URL",
                },
                "follow_up_action_url": {
                    "type": "string",
                    "description": "Redirect URL after form submission",
                },
            },
            "required": [
                "page_id",
                "name",
                "questions",
                "privacy_policy_url",
            ],
        },
    ),
    Tool(
        name="meta_ads.leads.get",
        description="Get Meta Ads lead data (per form)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "form_id": {"type": "string", "description": "Lead form ID"},
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 100)",
                },
            },
            "required": ["form_id"],
        },
    ),
    Tool(
        name="meta_ads.leads.get_by_ad",
        description="Get Meta Ads lead data by ad",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ad_id": {"type": "string", "description": "Ad ID"},
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 100)",
                },
            },
            "required": ["ad_id"],
        },
    ),
]
