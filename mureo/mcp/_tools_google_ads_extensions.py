"""Google Ads tool definitions — Sitelinks, callouts, conversions, targeting"""

from __future__ import annotations

from mcp.types import Tool

_CUSTOMER_ID_PARAM = {
    "type": "string",
    "description": (
        "Google Ads customer ID as a 10-digit string without dashes "
        "(e.g. '1234567890'). Optional — falls back to "
        "GOOGLE_ADS_CUSTOMER_ID / GOOGLE_ADS_LOGIN_CUSTOMER_ID from "
        "the configured credentials when omitted."
    ),
}

_CAMPAIGN_ID_PARAM = {
    "type": "string",
    "description": (
        "Campaign ID as a numeric string without dashes "
        "(e.g. '23743184133'). Obtain via google_ads.campaigns.list."
    ),
}

_PERIOD_PARAM = {
    "type": "string",
    "enum": [
        "TODAY",
        "YESTERDAY",
        "LAST_7_DAYS",
        "LAST_14_DAYS",
        "LAST_30_DAYS",
        "LAST_90_DAYS",
        "THIS_MONTH",
        "LAST_MONTH",
    ],
    "description": (
        "Reporting window. Default 'LAST_30_DAYS'. Use LAST_7_DAYS / "
        "LAST_14_DAYS for recent diagnosis; LAST_90_DAYS for baseline."
    ),
}

_CONVERSION_ACTION_ID_PARAM = {
    "type": "string",
    "description": (
        "Conversion action ID as a numeric string (e.g. "
        "'987654321'). Obtain via google_ads.conversions.list."
    ),
}


TOOLS: list[Tool] = [
    # === Sitelinks ===
    Tool(
        name="google_ads_sitelinks_list",
        description=(
            "List sitelink assets attached to a Google Ads campaign, "
            "merging campaign-level and account-level entries. Returns "
            "[{id, resource_name, link_text, description1, "
            "description2, final_urls:[string], level "
            "('campaign'|'account')}]. Account-level sitelinks apply "
            "to the whole customer and are deduplicated by id. "
            "Read-only. Use this to audit extensions before calling "
            "google_ads_sitelinks_create (20 per-campaign limit) or "
            "google_ads.sitelinks.remove. For callouts use "
            "google_ads.callouts.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_sitelinks_create",
        description=(
            "Create a sitelink Asset and link it to a Google Ads "
            "campaign in a two-step mutate (AssetService then "
            "CampaignAssetService). Returns {resource_name} of the "
            "created asset on success, or {error:true, "
            "error_type:'validation_error', message} when the "
            "campaign already has 20 campaign-level sitelinks "
            "(hardcoded _MAX_SITELINKS_PER_CAMPAIGN limit). Mutating "
            "— reversible only by google_ads_sitelinks_remove using "
            "the returned asset_id. The asset is newly minted per "
            "call; identical text produces duplicate assets unless "
            "deduplicated upstream."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "link_text": {
                    "type": "string",
                    "maxLength": 25,
                    "description": (
                        "Link text shown to searchers (e.g. 'Pricing'). "
                        "Google Ads limits this to 25 characters."
                    ),
                },
                "final_url": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "Absolute landing URL (http:// or https://) "
                        "for the sitelink. Must be a crawlable page on "
                        "the advertiser's verified domain."
                    ),
                },
                "description1": {
                    "type": "string",
                    "maxLength": 35,
                    "description": (
                        "Optional first description line (max 35 "
                        "characters). Only displayed when "
                        "description2 is also provided and Google "
                        "chooses to render the expanded format."
                    ),
                },
                "description2": {
                    "type": "string",
                    "maxLength": 35,
                    "description": (
                        "Optional second description line (max 35 "
                        "characters). Requires description1."
                    ),
                },
            },
            "required": ["campaign_id", "link_text", "final_url"],
        },
    ),
    Tool(
        name="google_ads_sitelinks_remove",
        description=(
            "Detach a sitelink asset from a Google Ads campaign by "
            "removing the CampaignAsset link. Returns {resource_name} "
            "of the removed campaign-asset association. Destructive — "
            "unlinks the asset from the campaign so it stops serving, "
            "but does not delete the underlying Asset row. Re-linking "
            "requires google_ads_sitelinks_create with the same "
            "text/URL. To list current sitelinks use "
            "google_ads.sitelinks.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "asset_id": {
                    "type": "string",
                    "description": (
                        "Asset ID as a numeric string (e.g. "
                        "'123456789'). Obtain from the 'id' field of "
                        "google_ads_sitelinks_list rows where "
                        "level=='campaign'."
                    ),
                },
            },
            "required": ["campaign_id", "asset_id"],
        },
    ),
    # === Callouts ===
    Tool(
        name="google_ads_callouts_list",
        description=(
            "List callout extension assets linked to a Google Ads "
            "campaign. Returns [{id, resource_name, callout_text}]. "
            "Unlike google_ads_sitelinks_list, this only scans "
            "campaign_asset rows (no account-level merge). Read-only. "
            "Use this to audit coverage before calling "
            "google_ads_callouts_create (hardcoded limit: 20 callouts "
            "per campaign) or google_ads.callouts.remove."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_callouts_create",
        description=(
            "Create a callout Asset and link it to a Google Ads "
            "campaign in a two-step mutate (AssetService then "
            "CampaignAssetService). Returns {resource_name} of the "
            "newly created asset, or {error:true, "
            "error_type:'validation_error', message} when the "
            "campaign already has 20 callouts "
            "(_MAX_CALLOUTS_PER_CAMPAIGN limit). Mutating — "
            "reversible only by google_ads.callouts.remove. The asset "
            "is minted per call, so identical text creates duplicate "
            "asset rows. For sitelink variants use "
            "google_ads.sitelinks.create."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "callout_text": {
                    "type": "string",
                    "maxLength": 25,
                    "description": (
                        "Callout text shown below the ad (e.g. "
                        "'Free shipping', '24/7 support'). Google "
                        "Ads limit: 25 characters."
                    ),
                },
            },
            "required": ["campaign_id", "callout_text"],
        },
    ),
    Tool(
        name="google_ads_callouts_remove",
        description=(
            "Detach a callout asset from a Google Ads campaign by "
            "removing the CampaignAsset link. Returns {resource_name} "
            "of the removed campaign-asset association. Destructive — "
            "the callout stops serving on the campaign but the Asset "
            "row itself is not deleted. Re-enabling requires "
            "google_ads_callouts_create with the same text. For the "
            "sibling list operation use google_ads.callouts.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "asset_id": {
                    "type": "string",
                    "description": (
                        "Asset ID as a numeric string (e.g. "
                        "'123456789'). Obtain from the 'id' field of "
                        "google_ads.callouts.list."
                    ),
                },
            },
            "required": ["campaign_id", "asset_id"],
        },
    ),
    # === Conversions ===
    Tool(
        name="google_ads_conversions_list",
        description=(
            "List every conversion action configured on the Google "
            "Ads customer, ordered by numeric id. Returns [{id "
            "(string), name, type (ConversionActionType enum string, "
            "e.g. 'WEBPAGE'), status ('ENABLED'|'HIDDEN'|'REMOVED'|"
            "'UNSPECIFIED'|'UNKNOWN'), category (enum string, e.g. "
            "'PURCHASE', 'SIGNUP')}]. Read-only. Use this to discover "
            "conversion_action_id values before calling .get, .update, "
            ".remove, or .tag. For CV performance metrics use "
            "google_ads.conversions.performance."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads_conversions_get",
        description=(
            "Fetch one conversion action's configuration from Google "
            "Ads by numeric ID. Returns {id, name, type "
            "(ConversionActionType enum string, e.g. 'WEBPAGE'), "
            "status ('ENABLED'|'HIDDEN'|'REMOVED'|'UNSPECIFIED'|"
            "'UNKNOWN'), category (enum string, e.g. 'PURCHASE', "
            "'SIGNUP')} or null when no row matches. Read-only; does "
            "NOT return value settings or lookback-window values — use "
            "the Google Ads UI for those. For the HTML/JS tag snippet "
            "to embed on a site use google_ads_conversions_tag; for "
            "full listings use google_ads.conversions.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "conversion_action_id": _CONVERSION_ACTION_ID_PARAM,
            },
            "required": ["conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads_conversions_performance",
        description=(
            "Report Google Ads conversions broken down by "
            "conversion_action and date, with optional campaign "
            "filter. Returns {period, campaign_id, total_conversions, "
            "actions:[{campaign_id, campaign_name, "
            "conversion_action_name, conversions, conversions_value, "
            "first_date, last_date, cost_per_conversion}] (sorted by "
            "conversions desc), daily_details:[{date, campaign_id, "
            "campaign_name, conversion_action_name, conversions, "
            "conversions_value}], landing_pages:[{date, "
            "landing_page_url, campaign_id, campaign_name, "
            "conversions, conversions_value, clicks}]}. Only rows with "
            "conversions > 0 are included. cost_per_conversion is "
            "computed via a separate GAQL because GAQL cannot SELECT "
            "cost_per_conversion alongside segments.conversion_action_name. "
            "Read-only. For campaign-level metrics use "
            "google_ads.performance.report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Optional campaign ID as a numeric string to "
                        "restrict the report. Omit for account-wide "
                        "aggregation."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads_conversions_create",
        description=(
            "Create a new Google Ads conversion action. Returns "
            "{resource_name:'customers/<cid>/conversionActions/<caid>'} "
            "of the newly created row. Mutating — the conversion "
            "action is persisted with status ENABLED by default. "
            "Reversible via google_ads_conversions_update with "
            "status='REMOVED' or google_ads.conversions.remove. Name "
            "must be <= 256 characters. Category defaults to "
            "'DEFAULT'. For updating an existing action use "
            "google_ads.conversions.update."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "name": {
                    "type": "string",
                    "maxLength": 256,
                    "description": (
                        "Human-readable conversion action name shown "
                        "in the Google Ads UI (e.g. 'Purchase - "
                        "Checkout Complete'). Required. Max 256 "
                        "characters."
                    ),
                },
                "type": {
                    "type": "string",
                    "enum": [
                        "WEBPAGE",
                        "UPLOAD_CLICKS",
                        "UPLOAD_CALLS",
                        "AD_CALL",
                        "WEBSITE_CALL",
                        "STORE_SALES_DIRECT_UPLOAD",
                        "STORE_SALES",
                    ],
                    "description": (
                        "ConversionActionType enum. Default 'WEBPAGE' "
                        "(site tag fires). Use 'UPLOAD_CLICKS' for "
                        "offline-conversion uploads or 'WEBSITE_CALL' "
                        "for call conversions."
                    ),
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "DEFAULT",
                        "PAGE_VIEW",
                        "PURCHASE",
                        "SIGNUP",
                        "DOWNLOAD",
                        "ADD_TO_CART",
                        "BEGIN_CHECKOUT",
                        "SUBSCRIBE_PAID",
                        "PHONE_CALL_LEAD",
                        "IMPORTED_LEAD",
                        "SUBMIT_LEAD_FORM",
                        "BOOK_APPOINTMENT",
                        "QUALIFIED_LEAD",
                        "CONVERTED_LEAD",
                        "REQUEST_QUOTE",
                        "GET_DIRECTIONS",
                        "OUTBOUND_CLICK",
                        "CONTACT",
                        "ENGAGEMENT",
                        "STORE_VISIT",
                        "STORE_SALE",
                    ],
                    "description": (
                        "Conversion category. Default 'DEFAULT'. "
                        "Smart bidding uses this to group similar "
                        "goals."
                    ),
                },
                "default_value": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "Default monetary conversion value in account "
                        "currency (e.g. 5000 = ¥5,000). Used when the "
                        "site tag does not send a value."
                    ),
                },
                "always_use_default_value": {
                    "type": "boolean",
                    "description": (
                        "When true, always use default_value even if "
                        "the site tag sends a dynamic value."
                    ),
                },
                "click_through_lookback_window_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 90,
                    "description": (
                        "Click-through attribution window in days "
                        "(1-90). Server-side validated — invalid "
                        "values raise ValueError."
                    ),
                },
                "view_through_lookback_window_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "description": (
                        "View-through attribution window in days "
                        "(1-30). Server-side validated."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="google_ads_conversions_update",
        description=(
            "Update fields on an existing Google Ads conversion "
            "action via FieldMask mutate. Returns {resource_name} of "
            "the updated row. Mutating — partial update: only the "
            "fields you pass are modified, the rest are preserved. "
            "At least one updatable field must be supplied (name, "
            "category, status, default_value, "
            "always_use_default_value, "
            "click_through_lookback_window_days, "
            "view_through_lookback_window_days) or the call raises "
            "ValueError. To delete/archive an action use status "
            "'REMOVED' here or call google_ads.conversions.remove."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "conversion_action_id": _CONVERSION_ACTION_ID_PARAM,
                "name": {
                    "type": "string",
                    "maxLength": 256,
                    "description": (
                        "New display name (max 256 characters). Omit "
                        "to leave the name unchanged."
                    ),
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "DEFAULT",
                        "PAGE_VIEW",
                        "PURCHASE",
                        "SIGNUP",
                        "DOWNLOAD",
                        "ADD_TO_CART",
                        "BEGIN_CHECKOUT",
                        "SUBSCRIBE_PAID",
                        "PHONE_CALL_LEAD",
                        "IMPORTED_LEAD",
                        "SUBMIT_LEAD_FORM",
                        "BOOK_APPOINTMENT",
                        "QUALIFIED_LEAD",
                        "CONVERTED_LEAD",
                        "REQUEST_QUOTE",
                        "GET_DIRECTIONS",
                        "OUTBOUND_CLICK",
                        "CONTACT",
                        "ENGAGEMENT",
                        "STORE_VISIT",
                        "STORE_SALE",
                    ],
                    "description": ("New category. Must match the allowed enum."),
                },
                "status": {
                    "type": "string",
                    "enum": ["ENABLED", "HIDDEN", "REMOVED"],
                    "description": (
                        "New status. 'ENABLED' counts toward "
                        "'Conversions' column; 'HIDDEN' excludes it "
                        "from the column but keeps the action; "
                        "'REMOVED' archives it."
                    ),
                },
                "default_value": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "New default conversion value in account " "currency."
                    ),
                },
                "always_use_default_value": {
                    "type": "boolean",
                    "description": (
                        "Toggle whether default_value always overrides "
                        "tag-supplied values."
                    ),
                },
                "click_through_lookback_window_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 90,
                    "description": (
                        "New click-through attribution window in days " "(1-90)."
                    ),
                },
                "view_through_lookback_window_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "description": (
                        "New view-through attribution window in days " "(1-30)."
                    ),
                },
            },
            "required": ["conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads_conversions_remove",
        description=(
            "Archive (status=REMOVED) a Google Ads conversion action. "
            "Returns {resource_name} of the removed row. Destructive — "
            "historical data remains but the action stops counting "
            "toward 'Conversions'. Re-enabling requires "
            "google_ads_conversions_update with status='ENABLED'. For "
            "soft-hide that keeps the row visible use "
            "google_ads_conversions_update with status='HIDDEN'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "conversion_action_id": _CONVERSION_ACTION_ID_PARAM,
            },
            "required": ["conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads_conversions_tag",
        description=(
            "Fetch the HTML/JavaScript tag snippets for a Google Ads "
            "conversion action so you can install them on the "
            "advertiser's site. Returns [{type (TagSnippetType enum "
            "string, e.g. 'WEBPAGE', 'WEBPAGE_ONCLICK'), page_header "
            "(the <script> block that goes in <head>), event_snippet "
            "(the goal event snippet)}]. Empty list when no snippets "
            "are configured (e.g. UPLOAD_CLICKS actions have no web "
            "tag). Read-only. For configuration metadata use "
            "google_ads.conversions.get."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "conversion_action_id": _CONVERSION_ACTION_ID_PARAM,
            },
            "required": ["conversion_action_id"],
        },
    ),
    # === Recommendations ===
    Tool(
        name="google_ads_recommendations_list",
        description=(
            "List Google's current automated recommendations for the "
            "account. Returns [{resource_name, type "
            "(RecommendationType enum string, e.g. "
            "'KEYWORD', 'TEXT_AD', 'TARGET_CPA_OPT_IN', "
            "'MAXIMIZE_CONVERSIONS_OPT_IN'), impact:{base_metrics:{"
            "impressions, clicks, cost_micros}}, campaign_id "
            "(resource path when scoped to a campaign)}]. Read-only. "
            "Filter by campaign_id to scope to one campaign, or by "
            "recommendation_type to scope to one kind. To apply a "
            "recommendation use google_ads_recommendations_apply with "
            "resource_name from this list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Optional campaign ID as a numeric string. "
                        "Omit to list account-wide recommendations."
                    ),
                },
                "recommendation_type": {
                    "type": "string",
                    "description": (
                        "Optional RecommendationType enum string "
                        "(e.g. 'KEYWORD', 'TEXT_AD', "
                        "'TARGET_CPA_OPT_IN'). Validated against the "
                        "client's allow-list before GAQL embedding."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads_recommendations_apply",
        description=(
            "Apply one Google Ads recommendation by resource name. "
            "Returns {resource_name} of the applied recommendation. "
            "Mutating — the underlying change (new keyword, ad copy, "
            "bidding strategy switch, etc.) is committed to the "
            "campaign immediately and is NOT reversible through this "
            "tool. The resource_name format "
            "'customers/<cid>/recommendations/<rid>' is re-validated "
            "server-side to prevent injection. To list candidates "
            "use google_ads_recommendations_list; some recommendation "
            "types also change budget, device, or schedule settings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "resource_name": {
                    "type": "string",
                    "pattern": r"^customers/\d+/recommendations/\d+$",
                    "description": (
                        "Recommendation resource name exactly as "
                        "returned by google_ads_recommendations_list "
                        "(format: 'customers/<cid>/recommendations/"
                        "<rid>'). Re-validated against a strict regex "
                        "before submission."
                    ),
                },
            },
            "required": ["resource_name"],
        },
    ),
    # === Device Targeting ===
    Tool(
        name="google_ads_device_targeting_get",
        description=(
            "Get the device targeting state for a Google Ads "
            "campaign. Always returns three entries (DESKTOP, MOBILE, "
            "TABLET in that order), each shaped {criterion_id "
            "(string or null when no explicit criterion exists), "
            "device_type ('DESKTOP'|'MOBILE'|'TABLET'), bid_modifier "
            "(float or null), enabled (bool — True when no criterion "
            "exists OR bid_modifier != 0.0; False when "
            "bid_modifier==0 meaning delivery is off)}. Read-only. "
            "The 'enabled=False' semantics are mureo's convention: "
            "Google represents 'don't serve' as bid_modifier=0.0 "
            "(i.e. -100%). For modifying, use "
            "google_ads_device_targeting_set or "
            "google_ads.bid_adjustments.update."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_device_targeting_set",
        description=(
            "Toggle device delivery on a Google Ads campaign by "
            "setting bid_modifier=1.0 on enabled devices and 0.0 on "
            "disabled ones. Iterates all three devices individually "
            "so one failure does not abort the others. Returns "
            "{message, enabled_devices (sorted list), "
            "disabled_devices (sorted list), updated (list of "
            "resource_names that succeeded), errors (list of "
            "'<device>(<op>): <detail>' strings, or null)}. Mutating "
            "— existing device criteria are UPDATE-ed, missing ones "
            "are CREATE-ed. Reversible only by calling this tool "
            "again with a different enabled_devices. enabled_devices "
            "must be non-empty (passing an empty array raises "
            "ValueError). For fine-grained non-zero bid modifiers "
            "use google_ads.bid_adjustments.update."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "enabled_devices": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["MOBILE", "DESKTOP", "TABLET"],
                    },
                    "minItems": 1,
                    "maxItems": 3,
                    "uniqueItems": True,
                    "description": (
                        "Devices that should continue serving "
                        "(bid_modifier=1.0). Devices not in this "
                        "list have bid_modifier set to 0.0 (delivery "
                        "off). At least one device must be enabled."
                    ),
                },
            },
            "required": ["campaign_id", "enabled_devices"],
        },
    ),
    # === Bid adjustments ===
    Tool(
        name="google_ads_bid_adjustments_get",
        description=(
            "List every campaign_criterion row that has a non-null "
            "bid_modifier on a Google Ads campaign. Returns [{"
            "criterion_id, type (CriterionType enum string, e.g. "
            "'DEVICE', 'LOCATION', 'AD_SCHEDULE'), bid_modifier "
            "(float), device_type ('DESKTOP'|'MOBILE'|'TABLET' for "
            "DEVICE criteria; 'UNKNOWN(<n>)' for non-DEVICE rows "
            "such as LOCATION or AD_SCHEDULE, where n is the raw "
            "device-type enum ordinal — never null)}]. Read-only. "
            "For the device-summary view (all three devices, even "
            "implicit ones) use google_ads.device_targeting.get. For "
            "location-only use google_ads.location_targeting.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_bid_adjustments_update",
        description=(
            "Update the bid_modifier of a single campaign_criterion. "
            "Returns {resource_name} of the updated criterion. "
            "Mutating — FieldMask-based partial update on "
            "bid_modifier only; other criterion fields are "
            "preserved. Reversible by another call to this tool. "
            "bid_modifier must be 0.1-10.0 (0.1 = -90%, 1.0 = "
            "neutral, 10.0 = +900%); values outside this range "
            "raise ValueError. To toggle a device on/off with "
            "bid_modifier 0.0 use google_ads_device_targeting_set "
            "instead (this tool rejects 0.0)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "criterion_id": {
                    "type": "string",
                    "description": (
                        "Criterion ID as a numeric string (e.g. "
                        "'30001'). Obtain via "
                        "google_ads_bid_adjustments_get or "
                        "google_ads.device_targeting.get."
                    ),
                },
                "bid_modifier": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 10.0,
                    "description": (
                        "New bid modifier (0.1 = -90%, 1.0 = no "
                        "change, 2.0 = +100%, 10.0 = +900%). Outside "
                        "0.1-10.0 raises ValueError server-side."
                    ),
                },
            },
            "required": ["campaign_id", "criterion_id", "bid_modifier"],
        },
    ),
    # === Geographic Targeting ===
    Tool(
        name="google_ads_location_targeting_list",
        description=(
            "List every LOCATION campaign_criterion on a Google Ads "
            "campaign. Returns [{criterion_id, geo_target_constant "
            "(resource path, e.g. 'geoTargetConstants/2392' for "
            "Japan), bid_modifier (float or null)}]. Read-only. Geo "
            "target constant IDs map to countries/regions/cities — "
            "look up via Google's GeoTargetConstantService. For "
            "adding or removing locations use "
            "google_ads_location_targeting_update; for "
            "schedule-based targeting use "
            "google_ads.schedule_targeting.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_location_targeting_update",
        description=(
            "Add and/or remove location criteria on a Google Ads "
            "campaign in a single mutate. Returns [{resource_name}] "
            "— one entry per operation executed (adds first, then "
            "removes). Mutating — adds create new criteria, removes "
            "delete them by criterion_id. Reversible only by "
            "calling this tool again with the inverse operations. "
            "At least one of add_locations / remove_criterion_ids "
            "must be provided. Locations can be passed as bare "
            "numeric IDs or as full 'geoTargetConstants/<id>' paths; "
            "bare IDs are auto-prefixed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "add_locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Geo target constants to add, either as "
                        "numeric IDs (e.g. '2392' for Japan, '2840' "
                        "for US) or as full resource paths "
                        "('geoTargetConstants/2392'). Bare IDs are "
                        "auto-prefixed."
                    ),
                },
                "remove_criterion_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Existing criterion_ids to remove (numeric "
                        "strings, e.g. '30002'). Obtain via "
                        "google_ads.location_targeting.list."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Ad schedules ===
    Tool(
        name="google_ads_schedule_targeting_list",
        description=(
            "List the ad-schedule (day-of-week + hour-of-day) targeting "
            "criteria attached to a Google Ads campaign. Returns one row "
            "per schedule criterion with criterion_id (string), "
            "day_of_week (string form of the DayOfWeek enum, e.g. "
            "'MONDAY'..'SUNDAY'), start_hour (integer 0-23), end_hour "
            "(integer 0-24; 24 denotes end-of-day), start_minute and "
            "end_minute (string form of the MinuteOfHour enum: 'ZERO', "
            "'FIFTEEN', 'THIRTY', or 'FORTY_FIVE'), and bid_modifier "
            "(float, or null when unset). Read-only; returns an empty "
            "list when the campaign has no schedule targeting (meaning: "
            "24/7 delivery). Use this to audit schedule coverage or "
            "collect criterion_ids before calling "
            "google_ads_schedule_targeting_update (which is what you use "
            "to add or remove entries). For device-level modifiers use "
            "google_ads_device_targeting_get; for geo targeting use "
            "google_ads.location_targeting.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": (
                        "Google Ads customer ID as a 10-digit string "
                        "without dashes (e.g. '1234567890'). Optional — "
                        "falls back to GOOGLE_ADS_CUSTOMER_ID / "
                        "GOOGLE_ADS_LOGIN_CUSTOMER_ID from the configured "
                        "credentials when omitted."
                    ),
                },
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign ID as a numeric string (e.g. "
                        "'23743184133'). Required — schedule targeting is "
                        "always scoped to a single campaign. Obtain via "
                        "google_ads.campaigns.list."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_schedule_targeting_update",
        description=(
            "Add and/or remove ad-schedule criteria on a Google Ads "
            "campaign in a single mutate. Returns [{resource_name}] "
            "— one entry per operation (adds first, then removes). "
            "Mutating — new schedule criteria default to "
            "start_minute/end_minute=ZERO (on the hour). Reversible "
            "only by calling this tool again with inverse "
            "operations. At least one of add_schedules / "
            "remove_criterion_ids must be provided. For the "
            "read-only listing use google_ads.schedule_targeting.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "add_schedules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {
                                "type": "string",
                                "enum": [
                                    "MONDAY",
                                    "TUESDAY",
                                    "WEDNESDAY",
                                    "THURSDAY",
                                    "FRIDAY",
                                    "SATURDAY",
                                    "SUNDAY",
                                ],
                                "description": (
                                    "Day of week. Case-insensitive; "
                                    "uppercased before enum lookup."
                                ),
                            },
                            "start_hour": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 23,
                                "description": (
                                    "Hour of day when delivery starts "
                                    "(0-23). Defaults to 0 when "
                                    "omitted."
                                ),
                            },
                            "end_hour": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 24,
                                "description": (
                                    "Hour of day when delivery ends "
                                    "(1-24; 24 means end-of-day). "
                                    "Defaults to 24 when omitted."
                                ),
                            },
                        },
                        "required": ["day"],
                    },
                    "description": (
                        "List of schedules to create. Each entry "
                        "maps to one AdSchedule criterion."
                    ),
                },
                "remove_criterion_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Existing criterion_ids to remove (numeric "
                        "strings). Obtain via "
                        "google_ads.schedule_targeting.list."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Change History ===
    Tool(
        name="google_ads_change_history_list",
        description=(
            "List the most recent change_event rows on a Google Ads "
            "account, sorted newest-first and capped at 100. Returns "
            "[{change_date_time (Google-formatted timestamp string "
            "returned verbatim from the API — typically "
            "'YYYY-MM-DD HH:MM:SS.ffffff+00:00' but no format "
            "coercion is applied, so callers should parse "
            "defensively), change_resource_type (enum string e.g. "
            "'CAMPAIGN', 'CAMPAIGN_BUDGET', 'AD_GROUP', 'AD', "
            "'CAMPAIGN_BID_MODIFIER'), resource_change_operation "
            "('CREATE'|'UPDATE'|'REMOVE' as enum string), "
            "changed_fields (list of dotted field paths), "
            "user_email}]. Read-only. Defaults to the last 14 days "
            "when dates are omitted; the API rejects an open-ended "
            "range so mureo always fills one. Use this for audit-"
            "trail diagnosis. For narrower bid/budget-only filtering "
            "use google_ads.cost_increase.investigate."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "start_date": {
                    "type": "string",
                    "format": "date",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    "description": (
                        "Inclusive start date ('YYYY-MM-DD'). "
                        "Default: today - 14 days."
                    ),
                },
                "end_date": {
                    "type": "string",
                    "format": "date",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    "description": (
                        "Inclusive end date ('YYYY-MM-DD'). Default: " "today."
                    ),
                },
            },
            "required": [],
        },
    ),
]
