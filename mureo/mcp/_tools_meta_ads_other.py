"""Meta Ads tool definitions — Split tests, automated rules, page posts, Instagram.

Tool descriptions follow ``docs/tdqs-style-guide.md``. Covers
miscellaneous Meta Ads surfaces beyond the core campaign / creative /
audience flow.
"""

from __future__ import annotations

from mcp.types import Tool

# Reusable parameter fragments.
_ACCOUNT_ID_PARAM = {
    "type": "string",
    "description": (
        "Meta Ads account ID in the format 'act_XXXXXXXXXX' (e.g. "
        "'act_1234567890'). Optional — falls back to META_ADS_ACCOUNT_ID "
        "from the configured credentials. The leading 'act_' prefix is "
        "required."
    ),
}

_LIMIT_50 = {
    "type": "integer",
    "minimum": 1,
    "maximum": 1000,
    "description": (
        "Max records returned per call. Default 50, max 1000 per Meta " "Graph API."
    ),
}

_LIMIT_25 = {
    "type": "integer",
    "minimum": 1,
    "maximum": 1000,
    "description": (
        "Max records returned per call. Default 25, max 1000 per Meta " "Graph API."
    ),
}

TOOLS: list[Tool] = [
    # === Split Test (A/B Test) ===
    Tool(
        name="meta_ads.split_tests.list",
        description=(
            "Lists Split Tests (A/B Tests, internally called Studies in "
            "Meta API) configured in the ad account. Returns id "
            "(study_id), name, status, start_time, end_time, and a "
            "summary of cells per study. Read-only. Use this to find a "
            "study_id before pulling detailed results via "
            "meta_ads.split_tests.get or ending via "
            "meta_ads.split_tests.end."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "limit": _LIMIT_50,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.split_tests.get",
        description=(
            "Fetches the full detail record for a single Split Test "
            "including per-cell results when the test has concluded. "
            "Returns id, name, status, cells (each with name, adsets, "
            "metric_value, confidence_interval), winner_cell_id (when "
            "determined), confidence_level, start_time, and end_time. "
            "Read-only. Call this after a test ends to read the winner; "
            "for the raw list use meta_ads.split_tests.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "study_id": {
                    "type": "string",
                    "description": (
                        "Study ID as returned by " "meta_ads.split_tests.list."
                    ),
                },
            },
            "required": ["study_id"],
        },
    ),
    Tool(
        name="meta_ads.split_tests.create",
        description=(
            "Creates a new Split Test. Returns the new study_id. "
            "Mutating, reversible via rollback.apply (rollback ends the "
            "test immediately without declaring a winner). Meta runs the "
            "test for the configured duration, then compares cells on "
            "the chosen objective (COST_PER_RESULT / CONVERSIONS / "
            "REACH / CPC / CPM). Cells must reference pre-existing ad "
            "sets; this tool does not create ad sets. For test analysis "
            "post-conclusion use meta_ads.split_tests.get."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": (
                        "Test name shown in Experiments. Should describe "
                        "the hypothesis being tested."
                    ),
                },
                "cells": {
                    "type": "array",
                    "minItems": 2,
                    "description": (
                        "Test cells (2 or more). Each cell has "
                        "{name, adsets: [ad_set_id, ...]}. Meta splits "
                        "traffic evenly across cells."
                    ),
                    "items": {"type": "object"},
                },
                "objectives": {
                    "type": "array",
                    "minItems": 1,
                    "description": (
                        "Metrics Meta will use to rank cells. Each entry "
                        "is {type: COST_PER_RESULT | CONVERSIONS | REACH "
                        "| CPC | CPM}. Multiple objectives produce "
                        "multi-dimensional results."
                    ),
                    "items": {"type": "object"},
                },
                "start_time": {
                    "type": "string",
                    "description": (
                        "Test start in ISO 8601 (e.g. "
                        "'2026-04-25T00:00:00+0900'). Must be in the "
                        "future when the test is created."
                    ),
                },
                "end_time": {
                    "type": "string",
                    "description": (
                        "Test end in ISO 8601. Meta requires at least "
                        "4 days between start_time and end_time for "
                        "statistical significance."
                    ),
                },
                "confidence_level": {
                    "type": "integer",
                    "minimum": 80,
                    "maximum": 99,
                    "description": (
                        "Statistical confidence threshold for declaring "
                        "a winner. Default 95 (95%). Higher values need "
                        "more spend / longer duration to conclude."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Free-text description of the hypothesis. "
                        "Internal — not shown to end users."
                    ),
                },
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
        description=(
            "Ends a running Split Test immediately, before its scheduled "
            "end_time. Returns the final study record with whatever "
            "confidence Meta has accumulated so far. Destructive — no "
            "further data accrues; if significance was not yet reached, "
            "winner_cell_id may be null. Reversible via rollback.apply "
            "only if the underlying ad sets have not been independently "
            "modified since the early termination."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "study_id": {
                    "type": "string",
                    "description": "Study ID to end.",
                },
            },
            "required": ["study_id"],
        },
    ),
    # === Automated Rules (Ad Rules) ===
    Tool(
        name="meta_ads.ad_rules.list",
        description=(
            "Lists Meta Automated Rules configured in the ad account. "
            "Returns id, name, status (ENABLED / DISABLED / DELETED), "
            "evaluation_spec summary, execution_spec summary "
            "(NOTIFICATION / PAUSE_CAMPAIGN / CHANGE_BUDGET / etc.), "
            "and schedule per rule. Read-only. Use this to audit "
            "existing automation before adding new rules or to find a "
            "rule_id before disabling / deleting an old one."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "limit": _LIMIT_50,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.get",
        description=(
            "Fetches the full detail record for a single Automated Rule "
            "including the full evaluation_spec and execution_spec. "
            "Returns id, name, status, evaluation_spec (triggers and "
            "filters), execution_spec (action + parameters), "
            "schedule_spec (when rule runs), created_by, created_time, "
            "and last_evaluated_time. Read-only. Call this before "
            "meta_ads.ad_rules.update so you can merge incremental "
            "changes rather than overwrite the whole spec."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "rule_id": {
                    "type": "string",
                    "description": (
                        "Rule ID as returned by " "meta_ads.ad_rules.list."
                    ),
                },
            },
            "required": ["rule_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.create",
        description=(
            "Creates a new Automated Rule that Meta evaluates on the "
            "configured schedule and fires actions when the trigger "
            "matches. Returns the new rule_id. Mutating, reversible via "
            "rollback.apply (rollback disables the rule; actions the "
            "rule already took stand). Common patterns: CPA-spike alert "
            "(execution NOTIFICATION), auto-pause ads with low ROAS "
            "(execution PAUSE), scale winners (execution CHANGE_BUDGET). "
            "evaluation_spec and execution_spec are Meta's JSON schemas "
            "— see Meta Ads Automated Rules API docs for the field set."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": (
                        "Rule name shown in Ads Manager. Should name "
                        "the trigger and action (e.g. 'Pause ads "
                        "CPA > target × 2')."
                    ),
                },
                "evaluation_spec": {
                    "type": "object",
                    "description": (
                        "Trigger definition. Shape: {evaluation_type: "
                        "SCHEDULE | TRIGGER, filters: [{field, operator, "
                        "value}, ...]}. Filters combine with AND; for OR "
                        "create multiple rules."
                    ),
                },
                "execution_spec": {
                    "type": "object",
                    "description": (
                        "Action definition. Shape: {execution_type: "
                        "NOTIFICATION | PAUSE_CAMPAIGNS | UNPAUSE_"
                        "CAMPAIGNS | CHANGE_BUDGET | CHANGE_BID, "
                        "execution_options: [...]}. Budget/bid changes "
                        "use delta or absolute value per execution_"
                        "options."
                    ),
                },
                "schedule_spec": {
                    "type": "object",
                    "description": (
                        "When the rule runs. Shape: {schedule_type: "
                        "SEMI_HOURLY | DAILY | CUSTOM, schedule: "
                        "[time specs]}. Default SEMI_HOURLY evaluates "
                        "every 30 minutes."
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": ["ENABLED", "DISABLED"],
                    "description": (
                        "Initial status. Default ENABLED. Create with "
                        "DISABLED and enable later to stage the rule "
                        "without side effects."
                    ),
                },
            },
            "required": ["name", "evaluation_spec", "execution_spec"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.update",
        description=(
            "Updates fields on an existing Automated Rule. Partial "
            "update — only supplied fields are changed. Returns the "
            "updated rule. Mutating, reversible via rollback.apply. "
            "Changes take effect on the next scheduled evaluation. To "
            "temporarily suspend a rule, set status=DISABLED rather than "
            "deleting it so history is preserved."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "rule_id": {
                    "type": "string",
                    "description": "Rule ID to update.",
                },
                "name": {
                    "type": "string",
                    "description": "New rule name.",
                },
                "evaluation_spec": {
                    "type": "object",
                    "description": (
                        "New trigger definition. Replaces the entire "
                        "spec — fetch current via "
                        "meta_ads.ad_rules.get first if merging."
                    ),
                },
                "execution_spec": {
                    "type": "object",
                    "description": (
                        "New action definition. Replaces the entire " "spec."
                    ),
                },
                "schedule_spec": {
                    "type": "object",
                    "description": "New schedule definition.",
                },
                "status": {
                    "type": "string",
                    "enum": ["ENABLED", "DISABLED"],
                    "description": (
                        "New status. DISABLED pauses evaluation without "
                        "deleting history."
                    ),
                },
            },
            "required": ["rule_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.delete",
        description=(
            "Deletes an Automated Rule. Returns a success flag. "
            "Destructive — the rule stops firing immediately and its "
            "evaluation history is purged. Reversible via rollback.apply "
            "(re-creates the rule), but the rule_id changes on re-create "
            "which can break downstream references. For temporary "
            "suspension prefer meta_ads.ad_rules.update with "
            "status=DISABLED."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "rule_id": {
                    "type": "string",
                    "description": "Rule ID to delete.",
                },
            },
            "required": ["rule_id"],
        },
    ),
    # === Page Posts ===
    Tool(
        name="meta_ads.page_posts.list",
        description=(
            "Lists published posts on a Facebook Page. Returns id "
            "(post_id), message, created_time, type (photo / video / "
            "link / status), permalink_url, and insights summary "
            "(reach, engagement, reactions) per post. Read-only. Use "
            "this to find organic posts to boost via "
            "meta_ads.page_posts.boost — boosting an organic high-"
            "performer is often cheaper per engagement than running a "
            "new ad."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "page_id": {
                    "type": "string",
                    "description": (
                        "Facebook Page ID whose posts to list. Must be "
                        "a page the authenticated user has admin access "
                        "to."
                    ),
                },
                "limit": _LIMIT_25,
            },
            "required": ["page_id"],
        },
    ),
    Tool(
        name="meta_ads.page_posts.boost",
        description=(
            "Boosts an existing Facebook Page post by creating a paid "
            "ad that uses the post as its creative. Returns the new "
            "ad_id. Mutating, reversible via rollback.apply (rollback "
            "pauses the boosting ad; the original post stays live). The "
            "parent ad_set_id must already exist with budget and "
            "targeting configured — this tool only attaches the post as "
            "creative. For new-creative paid ads use "
            "meta_ads.ads.create with a creative_id instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "page_id": {
                    "type": "string",
                    "description": ("Facebook Page ID that owns the post."),
                },
                "post_id": {
                    "type": "string",
                    "description": (
                        "Post ID as returned by "
                        "meta_ads.page_posts.list. Post must be public "
                        "and compatible with Ads eligibility policies."
                    ),
                },
                "ad_set_id": {
                    "type": "string",
                    "description": (
                        "Parent ad set that will carry the boosting ad. "
                        "Must already exist with budget and targeting."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Ad name shown in Ads Manager. Auto-generated "
                        "from the post if omitted."
                    ),
                },
            },
            "required": ["page_id", "post_id", "ad_set_id"],
        },
    ),
    # === Instagram ===
    Tool(
        name="meta_ads.instagram.accounts",
        description=(
            "Lists Instagram Business / Creator accounts linked to the "
            "ad account via Meta Business. Returns ig_user_id, username, "
            "name, profile_picture_url, followers_count, and media_count "
            "per account. Read-only. Use this to find an ig_user_id "
            "before calling meta_ads.instagram.media or .boost."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.instagram.media",
        description=(
            "Lists recent media (posts, reels, carousels) for a linked "
            "Instagram account. Returns id (media_id), caption, "
            "media_type (IMAGE / VIDEO / CAROUSEL_ALBUM), media_url, "
            "permalink, timestamp, like_count, and comments_count per "
            "item. Read-only. Use this to find a media_id before "
            "boosting via meta_ads.instagram.boost."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ig_user_id": {
                    "type": "string",
                    "description": (
                        "Instagram user_id as returned by "
                        "meta_ads.instagram.accounts."
                    ),
                },
                "limit": _LIMIT_25,
            },
            "required": ["ig_user_id"],
        },
    ),
    Tool(
        name="meta_ads.instagram.boost",
        description=(
            "Boosts an organic Instagram post by creating a paid ad "
            "that uses it as creative. Returns the new ad_id. Mutating, "
            "reversible via rollback.apply (rollback pauses the boosting "
            "ad; the organic post stays live). The parent ad_set_id "
            "must already exist with budget and targeting. For a "
            "freshly-composed ad (non-organic source) use "
            "meta_ads.ads.create with a creative_id instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ig_user_id": {
                    "type": "string",
                    "description": ("Instagram user_id that owns the media."),
                },
                "media_id": {
                    "type": "string",
                    "description": (
                        "Media ID as returned by " "meta_ads.instagram.media."
                    ),
                },
                "ad_set_id": {
                    "type": "string",
                    "description": ("Parent ad set that will carry the boosting ad."),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Ad name shown in Ads Manager. Auto-generated "
                        "from the media if omitted."
                    ),
                },
            },
            "required": ["ig_user_id", "media_id", "ad_set_id"],
        },
    ),
]
