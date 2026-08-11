"""Meta Ads tool definitions — ad-set publisher exclusions (#544).

The Meta half of the delivery-surface exclusion surface: which publishers,
Audience Network app categories and content types an ad set must NOT be
delivered against. Meta stores these inside the ad set's targeting spec,
so the write tool below is deliberately narrow — it names the operation
so mureo can record and reverse it, instead of letting it disappear into
a generic ``meta_ads_ad_sets_update`` targeting blob.

Tool descriptions follow ``docs/tdqs-style-guide.md``.
"""

from __future__ import annotations

from mcp.types import Tool

_AD_SET_ID_PARAM = {
    "type": "string",
    "description": (
        "Ad set ID whose exclusions to read or write (e.g. "
        "'23851234567890123'). Exclusions live on the ad set, not on the "
        "campaign — set them per ad set."
    ),
}

_CATEGORIES_PARAM = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Complete new value for targeting.excluded_publisher_categories — "
        "Audience Network publisher/app categories to exclude. Replaces the "
        "current list rather than appending, so read the current value with "
        "meta_ads_excluded_placements_get first and send the full intended "
        "set. An empty array clears the facet."
    ),
}

_LIST_IDS_PARAM = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Complete new value for targeting.excluded_publisher_list_ids — "
        "numeric ids of Audience Network publisher block lists to apply. "
        "Replaces the current list; an empty array clears the facet."
    ),
}

_BRAND_SAFETY_PARAM = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Complete new value for "
        "targeting.excluded_brand_safety_content_types — content types to "
        "exclude. Replaces the current list; an empty array clears the "
        "facet."
    ),
}

TOOLS: list[Tool] = [
    Tool(
        name="meta_ads_excluded_placements_get",
        description=(
            "Reads one ad set's delivery-surface exclusions from its "
            "targeting spec. Returns ad_set_id plus "
            "excluded_publisher_categories, excluded_publisher_list_ids and "
            "excluded_brand_safety_content_types — always all three keys, "
            "with an unset facet reported as an empty array. Read-only. Use "
            "this before meta_ads_excluded_placements_set (which replaces "
            "rather than appends), or to check whether an exclusion change "
            "explains a delivery drop. For where an ad set actually "
            "delivered, use meta_ads_analysis_placements."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ad_set_id": _AD_SET_ID_PARAM,
                "account_id": {
                    "type": "string",
                    "description": (
                        "Ad account ID in 'act_XXXXXXXXXX' form. Optional — "
                        "falls back to META_ADS_ACCOUNT_ID from the "
                        "configured credentials."
                    ),
                },
            },
            "required": ["ad_set_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="meta_ads_excluded_placements_set",
        description=(
            "Sets one ad set's delivery-surface exclusions. Returns "
            "ad_set_id, the applied facets, and Meta's update result. "
            "Mutating and delivery-affecting — excluding too much can take "
            "an ad set to zero delivery. Each supplied facet REPLACES its "
            "current value (Meta has no append here); an omitted facet is "
            "left untouched. The rest of the targeting spec (geo, "
            "audiences, interests) is preserved by a read-modify-write "
            "merge. Recorded in STATE.json's action_log with an observation "
            "window and reversible via rollback_apply, which restores the "
            "prior lists."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ad_set_id": _AD_SET_ID_PARAM,
                "account_id": {
                    "type": "string",
                    "description": (
                        "Ad account ID in 'act_XXXXXXXXXX' form. Optional — "
                        "falls back to META_ADS_ACCOUNT_ID from the "
                        "configured credentials."
                    ),
                },
                "excluded_publisher_categories": _CATEGORIES_PARAM,
                "excluded_publisher_list_ids": _LIST_IDS_PARAM,
                "excluded_brand_safety_content_types": _BRAND_SAFETY_PARAM,
            },
            "required": ["ad_set_id"],
            "additionalProperties": False,
        },
    ),
]
