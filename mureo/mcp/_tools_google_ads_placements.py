"""Google Ads tool definitions — negative placements (#544).

Delivery-surface exclusions: excluded websites, excluded mobile apps and
excluded mobile app categories, at campaign and ad group level. The
keyword exclusion surface lives in ``_tools_google_ads_keywords.py``;
these are placements, not search terms.

Tool descriptions follow ``docs/tdqs-style-guide.md``.
"""

from __future__ import annotations

from mcp.types import Tool

_CUSTOMER_ID_PARAM = {
    "type": "string",
    "description": (
        "Google Ads customer ID as a 10-digit string without dashes "
        "(e.g. '1234567890'). Optional — falls back to "
        "GOOGLE_ADS_CUSTOMER_ID / GOOGLE_ADS_LOGIN_CUSTOMER_ID from the "
        "configured credentials when omitted."
    ),
}

_CAMPAIGN_LEVEL_PARAM = {
    "type": "string",
    "description": (
        "Campaign ID for a campaign-level exclusion. Supply exactly one of "
        "campaign_id or ad_group_id — the two are separate criteria and "
        "campaign-level exclusions apply to every ad group under the "
        "campaign."
    ),
}

_AD_GROUP_LEVEL_PARAM = {
    "type": "string",
    "description": (
        "Ad group ID for an ad group-level exclusion. Supply exactly one of "
        "campaign_id or ad_group_id. Ad group-level exclusions do not "
        "cascade to sibling ad groups."
    ),
}

_PLACEMENT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["website", "mobile_application", "mobile_app_category"],
            "description": (
                "Exclusion kind. 'website' excludes a placement URL, "
                "'mobile_application' an individual app, "
                "'mobile_app_category' a whole app category."
            ),
        },
        "value": {
            "type": "string",
            "description": (
                "The thing to exclude. website: a domain or URL "
                "(e.g. 'example.com'). mobile_application: the Google Ads "
                "app id, platform-prefixed ('1-' iOS, '2-' Android — e.g. "
                "'2-com.example.app'). mobile_app_category: the category "
                "constant id (e.g. '60000') or its full "
                "'mobileAppCategoryConstants/<id>' resource name."
            ),
        },
    },
    "required": ["type", "value"],
    "additionalProperties": False,
}

TOOLS: list[Tool] = [
    Tool(
        name="google_ads_negative_placements_list",
        description=(
            "Lists delivery-surface exclusions — excluded websites, mobile "
            "apps and mobile app categories — at campaign and ad group "
            "level. Returns level ('campaign' / 'ad_group'), criterion_id, "
            "type, criterion_type, value, display_name, and the parent "
            "campaign / ad group ids per entry. Read-only, capped at 1000 "
            "rows per level. Use this to get the criterion_id needed by "
            "google_ads_negative_placements_remove, or to diagnose a "
            "delivery collapse after a bulk exclusion pass. For excluded "
            "search terms use google_ads_negative_keywords_list instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict to this campaign — its own campaign-level "
                        "exclusions plus those of its ad groups. Omit with "
                        "ad_group_id also omitted to read the whole account."
                    ),
                },
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Restrict to a single ad group. Campaign-level "
                        "exclusions are a different resource and are not "
                        "returned when this is supplied."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="google_ads_negative_placements_add",
        description=(
            "Excludes websites, mobile apps and/or mobile app categories "
            "from delivery, in one batch, at campaign or ad group level. "
            "Returns level, the scope id, count, and per entry the created "
            "criterion_id, resource_name, type and value. Mutating and "
            "delivery-affecting — a large exclusion batch can take a Display "
            "campaign to zero impressions. Recorded in STATE.json's "
            "action_log with an observation window, and reversible as one "
            "unit via rollback_apply, which removes exactly the criteria "
            "this call created. Exclude search terms with "
            "google_ads_negative_keywords_add instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_LEVEL_PARAM,
                "ad_group_id": _AD_GROUP_LEVEL_PARAM,
                "placements": {
                    "type": "array",
                    "items": _PLACEMENT_ITEM_SCHEMA,
                    "minItems": 1,
                    "description": (
                        "Exclusions to add. Types can be mixed in one call; "
                        "the whole batch becomes a single reversible "
                        "action_log entry."
                    ),
                },
            },
            "required": ["placements"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="google_ads_negative_placements_remove",
        description=(
            "Lifts delivery-surface exclusions by criterion_id, in one "
            "batch, so a bad exclusion pass can be reverted in a single "
            "call. Returns removed (criterion_id + resource_name), "
            "removed_count, and skipped entries with a reason. Mutating — "
            "lifting an exclusion lets the placement serve again from the "
            "next serving cycle. Ids are verified against the live criteria "
            "first: anything that is not a negative placement criterion at "
            "the named level is skipped, never removed. Get ids from "
            "google_ads_negative_placements_list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_LEVEL_PARAM,
                "ad_group_id": _AD_GROUP_LEVEL_PARAM,
                "criterion_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": (
                        "Criterion IDs to lift, as returned by "
                        "google_ads_negative_placements_list or by the "
                        "'created' entries of "
                        "google_ads_negative_placements_add. All must belong "
                        "to the level named above."
                    ),
                },
            },
            "required": ["criterion_ids"],
            "additionalProperties": False,
        },
    ),
]
