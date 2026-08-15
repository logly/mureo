"""Google Ads tool definitions -- Performance Max asset-group assets (#590, #626)"""

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

_IMAGE_FIELD_TYPES = [
    "MARKETING_IMAGE",
    "SQUARE_MARKETING_IMAGE",
    "PORTRAIT_MARKETING_IMAGE",
    "LOGO",
    "LANDSCAPE_LOGO",
]

TOOLS: list[Tool] = [
    Tool(
        name="google_ads_asset_group_assets_list",
        description=(
            "Lists the text AND the images attached to Performance Max "
            "asset groups. Read-only. This is the tool for P-MAX creative: "
            "google_ads_ads_list returns no rows for a Performance Max "
            "campaign because P-MAX has no ad_group_ad — its headlines and "
            "its pictures alike live on asset_group_asset. It is also the "
            "only way to say WHICH asset group serves a given image; "
            "google_ads_image_assets_list is account-wide and does not. "
            "Returns one entry per link. Every entry carries {resource_name "
            "(the asset_group_asset handle), field_type, status (the LINK "
            "status: 'ENABLED' | 'PAUSED' | 'REMOVED'), asset_id, "
            "asset_group_id, asset_group_name, campaign_id, "
            "campaign_resource_name}. field_type says what the rest of the "
            "entry holds: a text link ('HEADLINE' | 'LONG_HEADLINE' | "
            "'DESCRIPTION') adds {text}; an image link ('MARKETING_IMAGE' | "
            "'SQUARE_MARKETING_IMAGE' | 'PORTRAIT_MARKETING_IMAGE' | 'LOGO' "
            "| 'LANDSCAPE_LOGO') adds {asset_name, url (the full-size "
            "serving URL — fetch it to actually look at the creative), "
            "width_pixels, height_pixels}. Entries are returned in the "
            "order the API returned them and are not deduplicated — two "
            "links carrying the same asset are two entries, because that is "
            "what the asset group has. Video, business name and other field "
            "types are not returned. Pass the asset_id of the entry you "
            "want to change to google_ads_asset_group_assets_replace (text) "
            "or google_ads_asset_group_images_replace (images)."
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
    Tool(
        name="google_ads_asset_group_images_replace",
        description=(
            "Swaps one image or logo of a Performance Max asset group for "
            "another. Mutating. Use this whichever situation you are in: "
            "pass new_asset_id when the account already holds the image "
            "(google_ads_image_assets_list finds one), or new_image_path to "
            "upload a local file first — exactly one of the two, and mureo "
            "handles the difference. The replacement is linked under the "
            "same field_type and the old link is removed in ONE atomic "
            "GoogleAdsService.mutate, so the asset group's asset count for "
            "that field type never dips below the Performance Max minimum "
            "(a removal issued on its own is refused with "
            "AssetGroupError.NOT_ENOUGH_MARKETING_IMAGE_ASSET or its square "
            "/ logo twin). Neither Asset is deleted; only the old link to "
            "this asset group is. Google enforces a shape per slot — "
            "MARKETING_IMAGE 1.91:1 (min 600x314), SQUARE_MARKETING_IMAGE "
            "1:1 (min 300x300), PORTRAIT_MARKETING_IMAGE 4:5 (min 480x600), "
            "LOGO 1:1 (min 128x128), LANDSCAPE_LOGO 4:1 (min 512x128) — and "
            "mureo checks it before uploading or linking anything, then "
            "refuses with the rule spelled out. It never crops or resizes. "
            "Returns {asset_group_id, field_type, added: {asset_id, "
            "asset_name, width_pixels, height_pixels, source "
            "('existing_asset' | 'uploaded'), asset_group_asset}, removed: "
            "{asset_id, asset_name, url, asset_group_asset}, note}. Not "
            "automatically reversible — to swap back, call this tool again "
            "with the old asset_id; record before-state with "
            "mureo_state_action_log_append if you may need to roll back. "
            "Call google_ads_asset_group_assets_list first to get "
            "old_asset_id. For headlines and descriptions use "
            "google_ads_asset_group_assets_replace instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "asset_group_id": {
                    "type": "string",
                    "description": (
                        "Asset group whose image is being changed, as "
                        "reported by google_ads_asset_group_assets_list."
                    ),
                },
                "field_type": {
                    "type": "string",
                    "enum": _IMAGE_FIELD_TYPES,
                    "description": (
                        "Which image slot to swap. Must match the field_type "
                        "the old asset is linked under — the same image can "
                        "be linked as more than one field type, and each has "
                        "its own required aspect ratio."
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
                "new_asset_id": {
                    "type": "string",
                    "description": (
                        "An image asset the account already holds, from "
                        "google_ads_image_assets_list or from another asset "
                        "group's entry. Rejected if it is not an image "
                        "asset, if its dimensions do not fit this "
                        "field_type, or if it is already linked to this "
                        "asset group under this field_type (Google Ads "
                        "refuses a duplicate link). Supply this OR "
                        "new_image_path, never both."
                    ),
                },
                "new_image_path": {
                    "type": "string",
                    "description": (
                        "Local path to an image to upload and link "
                        "(jpg/jpeg/png/gif, max 5MB). Its dimensions are "
                        "checked against this field_type BEFORE the upload, "
                        "so a wrongly proportioned file costs no API call. "
                        "Supply this OR new_asset_id, never both."
                    ),
                },
                "new_image_name": {
                    "type": "string",
                    "description": (
                        "Asset name for the uploaded image. Only used with "
                        "new_image_path; defaults to the file name."
                    ),
                },
            },
            "required": [
                "asset_group_id",
                "field_type",
                "old_asset_id",
            ],
            "additionalProperties": False,
        },
    ),
]
