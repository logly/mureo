"""Meta Ads tool definitions — Campaigns, ad sets, ads.

Tool descriptions follow ``docs/tdqs-style-guide.md``. Meta hierarchy:
Campaign → Ad Set → Ad. Budgets and targeting live on Ad Sets; creative
assets live on Ads. All budgets are passed in minor currency units
(cents for USD, 円 for JPY since JPY has no minor unit — Meta treats 1
yen as 1 unit).
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

_LIMIT_PARAM = {
    "type": "integer",
    "minimum": 1,
    "maximum": 1000,
    "description": (
        "Maximum records to return in a single call. Default 50. "
        "Meta Graph API caps at 1000 per page; for larger result sets "
        "reduce limit and filter client-side on the returned fields."
    ),
}

TOOLS: list[Tool] = [
    # === Campaigns ===
    Tool(
        name="meta_ads_campaigns_list",
        description=(
            "Lists campaigns in a Meta Ads account with optional status "
            "filtering. Returns id, name, status (ACTIVE / PAUSED / "
            "DELETED / ARCHIVED), effective_status, objective "
            "(OUTCOME_SALES / OUTCOME_LEADS / etc.), buying_type, "
            "daily_budget, and lifetime_budget per campaign. Read-only. "
            "Use this to find a campaign_id before calling campaigns.get "
            "or the pause/enable helpers. For a single campaign's full "
            "detail record use meta_ads.campaigns.get."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "status_filter": {
                    "type": "string",
                    "enum": [
                        "ACTIVE",
                        "PAUSED",
                        "DELETED",
                        "ARCHIVED",
                        "IN_PROCESS",
                        "WITH_ISSUES",
                    ],
                    "description": (
                        "Restrict results to campaigns with this status. "
                        "Omit to return all non-DELETED statuses."
                    ),
                },
                "limit": _LIMIT_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads_campaigns_get",
        description=(
            "Fetches the full detail record for a single campaign by ID. "
            "Returns the same fields as campaigns.list plus "
            "special_ad_categories, spend_cap, start_time, stop_time, and "
            "issues_info (non-empty when status is WITH_ISSUES). "
            "Read-only. Use this when a campaign_id is already known; for "
            "discovery use meta_ads.campaigns.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign ID (numeric string) as returned by "
                        "meta_ads.campaigns.list."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads_campaigns_create",
        description=(
            "Creates a new campaign in the specified Meta Ads account. "
            "Returns the new campaign id. Mutating, reversible via "
            "rollback_apply (rollback sets status to PAUSED rather than "
            "deleting). Default initial status is PAUSED — explicitly "
            "pass status='ACTIVE' only if the operator has confirmed "
            "immediate spend. A campaign acts as a container; ad sets "
            "(where budgets and targeting live) and ads must be created "
            "separately via meta_ads_ad_sets_create and meta_ads.ads.create."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": (
                        "Campaign name. Visible in Ads Manager; Meta "
                        "allows up to 400 characters."
                    ),
                },
                "objective": {
                    "type": "string",
                    "enum": [
                        "OUTCOME_AWARENESS",
                        "OUTCOME_TRAFFIC",
                        "OUTCOME_ENGAGEMENT",
                        "OUTCOME_LEADS",
                        "OUTCOME_APP_PROMOTION",
                        "OUTCOME_SALES",
                    ],
                    "description": (
                        "Campaign objective using Meta's ODAX taxonomy. "
                        "Older names (CONVERSIONS, LINK_CLICKS) are "
                        "rejected by current API versions — use the "
                        "OUTCOME_* forms."
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "PAUSED"],
                    "description": (
                        "Initial status. Default PAUSED. Only set ACTIVE "
                        "when the operator has signed off on spend."
                    ),
                },
                "daily_budget": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Daily budget in account currency minor units "
                        "(cents for USD, yen for JPY). Mutually exclusive "
                        "with lifetime_budget. Budgets can live on the "
                        "campaign (CBO) or the ad set — not both."
                    ),
                },
                "lifetime_budget": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Lifetime budget in account currency minor units. "
                        "Requires a stop_time on at least one ad set. "
                        "Mutually exclusive with daily_budget."
                    ),
                },
            },
            "required": ["name", "objective"],
        },
    ),
    Tool(
        name="meta_ads_campaigns_update",
        description=(
            "Updates fields on an existing campaign. Partial update — only "
            "the supplied fields are changed. Returns the updated campaign. "
            "Mutating, reversible via rollback.apply. For status-only "
            "transitions prefer meta_ads_campaigns_pause / "
            "meta_ads_campaigns_enable, which are safer and map to a "
            "single explicit operator intent."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID to update.",
                },
                "name": {
                    "type": "string",
                    "description": "New campaign name.",
                },
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED"],
                    "description": (
                        "New campaign status. Prefer the dedicated "
                        "meta_ads_campaigns_pause / enable tools for "
                        "ACTIVE ↔ PAUSED transitions."
                    ),
                },
                "daily_budget": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "New daily budget in account currency minor units "
                        "(cents for USD, yen for JPY). Only settable when "
                        "the campaign is configured for CBO; ad-set-level "
                        "budgets must be edited via meta_ads.ad_sets.update."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Campaign pause / enable ===
    Tool(
        name="meta_ads_campaigns_pause",
        description=(
            "Pauses a single campaign by setting its status to PAUSED. "
            "Cascades to active ad sets and ads — nothing underneath the "
            "campaign will serve while it is PAUSED. Lightweight and "
            "reversible via rollback_apply or meta_ads.campaigns.enable. "
            "Returns the campaign id and new status. Use for immediate "
            "stop-spend situations; use meta_ads_campaigns_update with "
            "status='DELETED' to soft-delete instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID to pause.",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="meta_ads_campaigns_enable",
        description=(
            "Resumes a paused campaign by setting its status to ACTIVE. "
            "Ad sets and ads underneath retain their own status — if they "
            "are still PAUSED they do NOT auto-resume; call "
            "meta_ads_ad_sets_enable / meta_ads_ads_enable for those too. "
            "Returns the campaign id and new status. Reversible via "
            "rollback_apply or meta_ads.campaigns.pause."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID to activate.",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Ad sets ===
    Tool(
        name="meta_ads_ad_sets_list",
        description=(
            "Lists ad sets in a Meta Ads account, optionally scoped to a "
            "single parent campaign. Returns id, name, campaign_id, status, "
            "effective_status, daily_budget, lifetime_budget, "
            "optimization_goal, billing_event, and targeting_summary per "
            "ad set. Read-only. Ad sets are where budgets and targeting "
            "live — use this to audit delivery settings or to find an "
            "ad_set_id before creating ads."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict results to ad sets under this campaign. "
                        "Omit to list across the whole account."
                    ),
                },
                "limit": _LIMIT_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads_ad_sets_create",
        description=(
            "Creates a new ad set inside an existing campaign. Returns the "
            "new ad_set id. Mutating, reversible via rollback_apply "
            "(rollback sets status to PAUSED). Targeting is passed as a "
            "Meta targeting spec object; at minimum supply "
            "geo_locations and age bounds. Default initial status is "
            "PAUSED — only ACTIVE when the operator has confirmed spend. "
            "After creation, attach ads with meta_ads.ads.create."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Parent campaign ID. Must exist and not be " "DELETED."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Ad set name, up to 400 characters.",
                },
                "daily_budget": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Daily budget in account currency minor units "
                        "(cents for USD, yen for JPY). Required unless "
                        "the parent campaign uses CBO; mutually exclusive "
                        "with lifetime-budget settings on the same ad set."
                    ),
                },
                "billing_event": {
                    "type": "string",
                    "enum": [
                        "IMPRESSIONS",
                        "LINK_CLICKS",
                        "PAGE_LIKES",
                        "POST_ENGAGEMENT",
                        "VIDEO_VIEWS",
                        "THRUPLAY",
                    ],
                    "description": (
                        "What Meta charges for. Default IMPRESSIONS. The "
                        "valid options depend on the optimization_goal — "
                        "incompatible pairings are rejected by Meta."
                    ),
                },
                "optimization_goal": {
                    "type": "string",
                    "description": (
                        "What Meta optimises delivery for (e.g. REACH, "
                        "LINK_CLICKS, OFFSITE_CONVERSIONS, LANDING_PAGE_VIEWS, "
                        "THRUPLAY). Default REACH. Must be compatible with "
                        "the parent campaign's objective."
                    ),
                },
                "targeting": {
                    "type": "object",
                    "description": (
                        "Meta targeting spec. Typical keys: "
                        "geo_locations (e.g. {'countries': ['JP']}), "
                        "age_min, age_max, genders, interests, custom_audiences. "
                        "See Meta Marketing API targeting docs for the "
                        "full schema."
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "PAUSED"],
                    "description": (
                        "Initial status. Default PAUSED. Only ACTIVE "
                        "after operator sign-off."
                    ),
                },
                "bid_amount": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Bid cap in account currency minor units. Required "
                        "for bid-strategy optimization goals such as "
                        "LINK_CLICKS with TARGET_COST. Omit for automatic "
                        "bidding."
                    ),
                },
            },
            "required": ["campaign_id", "name"],
        },
    ),
    Tool(
        name="meta_ads_ad_sets_update",
        description=(
            "Updates one or more settings on an existing ad set. Partial "
            "update — only provided fields are changed. Returns the updated "
            "ad set. Mutating, reversible via rollback.apply. For "
            "status-only transitions prefer meta_ads_ad_sets_pause / "
            "meta_ads.ad_sets.enable. Changing `targeting` replaces the "
            "entire targeting spec — fetch the current spec via "
            "meta_ads_ad_sets_get and merge client-side to avoid data loss."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_set_id": {
                    "type": "string",
                    "description": "Ad set ID to update.",
                },
                "name": {
                    "type": "string",
                    "description": "New ad set name.",
                },
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED"],
                    "description": (
                        "New ad set status. Prefer the dedicated "
                        "pause/enable tools for simple ACTIVE ↔ PAUSED."
                    ),
                },
                "daily_budget": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "New daily budget in account currency minor units. "
                        "Only valid when the campaign is not using CBO."
                    ),
                },
                "targeting": {
                    "type": "object",
                    "description": (
                        "Full targeting spec replacement. Any keys not "
                        "supplied here are cleared — fetch current spec "
                        "via meta_ads_ad_sets_get and merge before "
                        "writing back."
                    ),
                },
            },
            "required": ["ad_set_id"],
        },
    ),
    # === Ad set get / pause / enable ===
    Tool(
        name="meta_ads_ad_sets_get",
        description=(
            "Fetches the full detail record for a single ad set, including "
            "the complete targeting spec and budget/bidding configuration. "
            "Returns id, name, campaign_id, status, effective_status, "
            "daily_budget, lifetime_budget, optimization_goal, billing_event, "
            "targeting (full spec), start_time, end_time, and "
            "delivery_estimate (if available). Read-only. Call this before "
            "meta_ads_ad_sets_update when you plan to modify targeting, so "
            "you can merge instead of overwrite."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_set_id": {
                    "type": "string",
                    "description": "Ad set ID to inspect.",
                },
            },
            "required": ["ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads_ad_sets_pause",
        description=(
            "Pauses a single ad set by setting its status to PAUSED. "
            "Ads under this ad set stop serving while it is PAUSED, even "
            "if their own status is ACTIVE. Lightweight, reversible via "
            "rollback_apply or meta_ads.ad_sets.enable. Returns the "
            "ad_set_id and new status. Does not affect sibling ad sets."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_set_id": {
                    "type": "string",
                    "description": "Ad set ID to pause.",
                },
            },
            "required": ["ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads_ad_sets_enable",
        description=(
            "Resumes a paused ad set by setting its status to ACTIVE. The "
            "parent campaign must also be ACTIVE for the ad set to "
            "actually serve. Ads underneath retain their own status — "
            "PAUSED ads do not auto-resume. Returns the ad_set_id and "
            "new status. Reversible via rollback_apply or "
            "meta_ads.ad_sets.pause."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_set_id": {
                    "type": "string",
                    "description": "Ad set ID to activate.",
                },
            },
            "required": ["ad_set_id"],
        },
    ),
    # === Ads ===
    Tool(
        name="meta_ads_ads_list",
        description=(
            "Lists ads in a Meta Ads account, optionally scoped to one ad "
            "set. Returns id, name, ad_set_id, campaign_id, status, "
            "effective_status, creative_id, and ad_review_feedback per ad. "
            "Read-only. Use this to find an ad_id before calling "
            "ads.update / pause / enable, or to audit which creatives are "
            "in flight. For the creative itself (image URL, copy), follow "
            "up with meta_ads.creatives.get."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_set_id": {
                    "type": "string",
                    "description": (
                        "Restrict to ads under this ad set. Omit to list "
                        "across the whole account."
                    ),
                },
                "limit": _LIMIT_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads_ads_create",
        description=(
            "Creates a new ad inside an existing ad set, binding it to a "
            "pre-existing creative. Returns the new ad id. Mutating, "
            "reversible via rollback.apply. Default initial status is "
            "PAUSED. The creative must already exist — use "
            "meta_ads_creatives_create (or sibling constructors like "
            "meta_ads_creatives_create_carousel) to produce a creative_id "
            "before calling this tool."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_set_id": {
                    "type": "string",
                    "description": ("Parent ad set ID. Must exist and not be DELETED."),
                },
                "name": {
                    "type": "string",
                    "description": "Ad name visible in Ads Manager.",
                },
                "creative_id": {
                    "type": "string",
                    "description": (
                        "Existing AdCreative ID to bind to this ad. "
                        "Obtain from meta_ads_creatives_list / create."
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "PAUSED"],
                    "description": (
                        "Initial status. Default PAUSED; only ACTIVE "
                        "after operator sign-off."
                    ),
                },
            },
            "required": ["ad_set_id", "name", "creative_id"],
        },
    ),
    Tool(
        name="meta_ads_ads_update",
        description=(
            "Updates fields on an existing ad. Partial update. Returns the "
            "updated ad. Mutating, reversible via rollback.apply. The ad's "
            "creative cannot be swapped via this call — creative changes "
            "require creating a replacement ad with a new creative_id and "
            "pausing the old one. For status-only transitions use "
            "meta_ads_ads_pause / meta_ads.ads.enable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_id": {
                    "type": "string",
                    "description": "Ad ID to update.",
                },
                "name": {
                    "type": "string",
                    "description": "New ad name.",
                },
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED"],
                    "description": (
                        "New ad status. Prefer meta_ads_ads_pause / "
                        "meta_ads_ads_enable for ACTIVE ↔ PAUSED."
                    ),
                },
            },
            "required": ["ad_id"],
        },
    ),
    # === Ad get / pause / enable ===
    Tool(
        name="meta_ads_ads_get",
        description=(
            "Fetches the full detail record for a single ad, including "
            "creative_id and ad_review_feedback (populated when the ad is "
            "in WITH_ISSUES). Returns id, name, ad_set_id, campaign_id, "
            "status, effective_status, creative_id, configured_status, "
            "issues_info, and ad_review_feedback. Read-only. Call this "
            "when an ad shows up as WITH_ISSUES in ads.list — "
            "ad_review_feedback explains the policy rejection."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_id": {
                    "type": "string",
                    "description": "Ad ID to inspect.",
                },
            },
            "required": ["ad_id"],
        },
    ),
    Tool(
        name="meta_ads_ads_pause",
        description=(
            "Pauses a single ad by setting its status to PAUSED. "
            "Lightweight; the ad stops serving immediately. Reversible "
            "via rollback_apply or meta_ads.ads.enable. Returns the ad_id "
            "and new status. Does not affect the parent ad set or sibling "
            "ads. Use for creative-level pause; use "
            "meta_ads_ad_sets_pause to stop a whole ad set."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_id": {
                    "type": "string",
                    "description": "Ad ID to pause.",
                },
            },
            "required": ["ad_id"],
        },
    ),
    Tool(
        name="meta_ads_ads_enable",
        description=(
            "Resumes a paused ad by setting its status to ACTIVE. The "
            "parent ad set and campaign must also be ACTIVE for the ad "
            "to actually serve. Returns the ad_id and new status. "
            "Reversible via rollback_apply or meta_ads.ads.pause."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_id": {
                    "type": "string",
                    "description": "Ad ID to activate.",
                },
            },
            "required": ["ad_id"],
        },
    ),
]
