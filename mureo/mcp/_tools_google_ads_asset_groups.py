"""Google Ads tool definitions -- Performance Max asset-group text assets (#590)"""

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

_FIELD_TYPES = ["HEADLINE", "LONG_HEADLINE", "DESCRIPTION"]

TOOLS: list[Tool] = [
    Tool(
        name="google_ads_asset_group_assets_list",
        description=(
            "Lists the headlines, long headlines and descriptions attached "
            "to Performance Max asset groups. Read-only. This is the tool "
            "for P-MAX ad copy: google_ads_ads_list returns no rows for a "
            "Performance Max campaign because P-MAX has no ad_group_ad — "
            "its text lives on asset_group_asset. Returns one entry per "
            "link shaped {resource_name (the asset_group_asset handle), "
            "field_type ('HEADLINE' | 'LONG_HEADLINE' | 'DESCRIPTION'), "
            "status (the LINK status: 'ENABLED' | 'PAUSED' | 'REMOVED'), "
            "asset_id, text, asset_group_id, asset_group_name, campaign_id, "
            "campaign_resource_name}. Entries are returned in the order the "
            "API returned them and are not deduplicated — two links "
            "carrying identical text are two entries, because that is what "
            "the asset group has. Pass the asset_id of the entry you want "
            "to change to google_ads_asset_group_assets_replace."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "asset_group_id": {
                    "type": "string",
                    "description": (
                        "Restrict to one asset group. Omit to list every "
                        "Performance Max asset group in the account (or in "
                        "campaign_id, when that is given)."
                    ),
                },
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict to the asset groups of one Performance Max "
                        "campaign. Use this when you have a campaign id but "
                        "not an asset group id."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="google_ads_asset_group_assets_replace",
        description=(
            "Swaps one headline, long headline or description of a "
            "Performance Max asset group for new text. Mutating. A Google "
            "Ads text Asset is immutable, so this creates a new Asset, "
            "links it to the asset group under the same field_type, and "
            "removes the old link — all three in ONE atomic "
            "GoogleAdsService.mutate, so the asset group's asset count for "
            "that field type never dips below the Performance Max minimum "
            "(a removal issued on its own is refused with "
            "AssetGroupError.NOT_ENOUGH_*). The old Asset itself is not "
            "deleted; only its link to this asset group is. Returns "
            "{asset_group_id, field_type, added: {asset_id, "
            "asset_resource_name, text, asset_group_asset}, removed: "
            "{asset_id, text, asset_group_asset}, note}. Not automatically "
            "reversible — to swap back, call this tool again with the old "
            "text; record before-state with mureo_state_action_log_append "
            "if you may need to roll back. Call "
            "google_ads_asset_group_assets_list first to get old_asset_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "asset_group_id": {
                    "type": "string",
                    "description": (
                        "Asset group whose copy is being changed, as "
                        "reported by google_ads_asset_group_assets_list."
                    ),
                },
                "field_type": {
                    "type": "string",
                    "enum": _FIELD_TYPES,
                    "description": (
                        "Which slot to swap. Must match the field_type the "
                        "old asset is linked under — the same text asset can "
                        "be linked as more than one field type."
                    ),
                },
                "old_asset_id": {
                    "type": "string",
                    "description": (
                        "asset_id of the entry being replaced, from "
                        "google_ads_asset_group_assets_list. Rejected before "
                        "any write if it is not linked to this asset group "
                        "under this field_type."
                    ),
                },
                "new_text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 90,
                    "description": (
                        "Replacement copy. Display-width limits (a "
                        "full-width character counts as two): HEADLINE 30, "
                        "LONG_HEADLINE 90, DESCRIPTION 90. Text already "
                        "linked under the same field_type is rejected — "
                        "Google Ads refuses a duplicate link."
                    ),
                },
            },
            "required": [
                "asset_group_id",
                "field_type",
                "old_asset_id",
                "new_text",
            ],
            "additionalProperties": False,
        },
    ),
]
