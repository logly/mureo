"""Meta Ads tool definitions — Split tests, automated rules, page posts, Instagram"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Split Test (A/B Test) ===
    Tool(
        name="meta_ads.split_tests.list",
        description="List Meta Ads split tests (A/B tests)",
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
        name="meta_ads.split_tests.get",
        description="Get Meta Ads split test details and results",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "study_id": {"type": "string", "description": "Study ID"},
            },
            "required": ["study_id"],
        },
    ),
    Tool(
        name="meta_ads.split_tests.create",
        description="Create a Meta Ads split test (A/B test)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "name": {"type": "string", "description": "Test name"},
                "cells": {
                    "type": "array",
                    "description": "Cell definitions (each cell contains name, adsets)",
                    "items": {"type": "object"},
                },
                "objectives": {
                    "type": "array",
                    "description": 'Objectives (e.g. [{"type": "COST_PER_RESULT"}])',
                    "items": {"type": "object"},
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time (ISO 8601 format)",
                },
                "end_time": {
                    "type": "string",
                    "description": "End time (ISO 8601 format)",
                },
                "confidence_level": {
                    "type": "integer",
                    "description": "Confidence level (default: 95)",
                },
                "description": {"type": "string", "description": "Test description"},
            },
            "required": [
                "account_id",
                "name",
                "cells",
                "objectives",
                "start_time",
                "end_time",
            ],
        },
    ),
    Tool(
        name="meta_ads.split_tests.end",
        description="End a Meta Ads split test",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "study_id": {"type": "string", "description": "Study ID"},
            },
            "required": ["study_id"],
        },
    ),
    # === Automated Rules (Ad Rules) ===
    Tool(
        name="meta_ads.ad_rules.list",
        description="List Meta Ads automated rules",
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
        name="meta_ads.ad_rules.get",
        description="Get Meta Ads automated rule details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "rule_id": {"type": "string", "description": "Rule ID"},
            },
            "required": ["rule_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.create",
        description="Create a Meta Ads automated rule (CPA spike alert, auto-pause etc.)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "name": {"type": "string", "description": "Rule name"},
                "evaluation_spec": {
                    "type": "object",
                    "description": "Evaluation spec (evaluation_type, trigger, filters)",
                },
                "execution_spec": {
                    "type": "object",
                    "description": "Execution spec (execution_type: NOTIFICATION, PAUSE_CAMPAIGN etc.)",
                },
                "schedule_spec": {"type": "object", "description": "Schedule settings"},
                "status": {"type": "string", "description": "Initial status"},
            },
            "required": ["name", "evaluation_spec", "execution_spec"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.update",
        description="Update a Meta Ads automated rule",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "rule_id": {"type": "string", "description": "Rule ID"},
                "name": {"type": "string", "description": "Rule name"},
                "evaluation_spec": {"type": "object", "description": "Evaluation spec"},
                "execution_spec": {"type": "object", "description": "Execution spec"},
                "schedule_spec": {"type": "object", "description": "Schedule settings"},
                "status": {"type": "string", "description": "Status"},
            },
            "required": ["rule_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.delete",
        description="Delete a Meta Ads automated rule",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "rule_id": {"type": "string", "description": "Rule ID"},
            },
            "required": ["rule_id"],
        },
    ),
    # === Page Posts ===
    Tool(
        name="meta_ads.page_posts.list",
        description="List Facebook page posts",
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
                    "description": "Max results (default: 25)",
                },
            },
            "required": ["page_id"],
        },
    ),
    Tool(
        name="meta_ads.page_posts.boost",
        description="Boost a Facebook page post (Boost Post)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "page_id": {"type": "string", "description": "Facebook page ID"},
                "post_id": {"type": "string", "description": "Post ID"},
                "ad_set_id": {"type": "string", "description": "Parent ad set ID"},
                "name": {
                    "type": "string",
                    "description": "Ad name (auto-generated if omitted)",
                },
            },
            "required": ["page_id", "post_id", "ad_set_id"],
        },
    ),
    # === Instagram ===
    Tool(
        name="meta_ads.instagram.accounts",
        description="List linked Instagram accounts",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.instagram.media",
        description="List Instagram posts",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ig_user_id": {"type": "string", "description": "Instagram user ID"},
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 25)",
                },
            },
            "required": ["ig_user_id"],
        },
    ),
    Tool(
        name="meta_ads.instagram.boost",
        description="Boost an Instagram post",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "ig_user_id": {"type": "string", "description": "Instagram user ID"},
                "media_id": {"type": "string", "description": "Media ID"},
                "ad_set_id": {"type": "string", "description": "Parent ad set ID"},
                "name": {
                    "type": "string",
                    "description": "Ad name (auto-generated if omitted)",
                },
            },
            "required": ["ig_user_id", "media_id", "ad_set_id"],
        },
    ),
]
