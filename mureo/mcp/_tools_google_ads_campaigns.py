"""Google Ads tool definitions — Campaigns, ad groups, ads, budgets, account.

Tool descriptions follow ``docs/tdqs-style-guide.md``: specific verb, returned
fields, side effects, and differentiation from sibling tools. See the guide
before adding a new tool or rewriting an existing one.
"""

from __future__ import annotations

from mcp.types import Tool

# Reusable parameter fragments — keep descriptions consistent across tools.
_CUSTOMER_ID_PARAM = {
    "type": "string",
    "description": (
        "Google Ads customer ID as a 10-digit string without dashes "
        "(e.g. '1234567890'). Optional — falls back to "
        "GOOGLE_ADS_CUSTOMER_ID / GOOGLE_ADS_LOGIN_CUSTOMER_ID from the "
        "configured credentials when omitted."
    ),
}

TOOLS: list[Tool] = [
    # === Campaigns ===
    Tool(
        name="google_ads_campaigns_list",
        description=(
            "Lists campaigns in a Google Ads account with optional status "
            "filtering. Returns one row per campaign with id, name, status, "
            "channel_type (SEARCH / DISPLAY / VIDEO / etc.), "
            "bidding_strategy_type, serving_status, primary_status, and "
            "daily_budget. Read-only. Use this to audit account structure or "
            "find a campaign_id before calling campaigns.get / update / "
            "update_status. For a single campaign's full details use "
            "google_ads_campaigns_get instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "status_filter": {
                    "type": "string",
                    "enum": ["ENABLED", "PAUSED", "REMOVED"],
                    "description": (
                        "Restrict results to campaigns with this status. "
                        "Omit to return all statuses including REMOVED."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads_campaigns_get",
        description=(
            "Fetches the full detail record for a single campaign by ID. "
            "Returns the same fields as campaigns.list plus start_date, "
            "end_date, network_settings, geo_target_type, and "
            "bidding_strategy_system_status. Read-only. Use this when you "
            "already have a campaign_id; for discovery use "
            "google_ads.campaigns.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign ID as returned by campaigns.list "
                        "(numeric string, e.g. '23743184133')."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_campaigns_create",
        description=(
            "Creates a new Search or Display campaign in the specified "
            "Google Ads account. Returns the new campaign's resource_name "
            "and id. Mutating — counts against daily write quota. "
            "Reversible via rollback_apply (reversal pauses the campaign "
            "rather than deleting it). Requires a pre-existing budget_id; "
            "to create a budget first, call google_ads.budget.create. For "
            "later edits use google_ads_campaigns_update or "
            "google_ads.campaigns.update_status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": (
                        "Campaign name (max 255 chars). Must be unique "
                        "within the account."
                    ),
                },
                "bidding_strategy": {
                    "type": "string",
                    "enum": [
                        "MAXIMIZE_CLICKS",
                        "MAXIMIZE_CONVERSIONS",
                        "MAXIMIZE_CONVERSION_VALUE",
                        "TARGET_CPA",
                        "TARGET_ROAS",
                        "MANUAL_CPC",
                    ],
                    "description": (
                        "Google Ads bidding strategy. Defaults to "
                        "MAXIMIZE_CLICKS when omitted. TARGET_CPA / "
                        "TARGET_ROAS require additional target fields that "
                        "this tool does not expose — use the Google Ads "
                        "UI or a follow-up campaigns.update for those."
                    ),
                },
                "budget_id": {
                    "type": "string",
                    "description": (
                        "Existing campaign-budget ID to attach. Create one "
                        "first with google_ads_budget_create if you do not "
                        "have one."
                    ),
                },
                "channel_type": {
                    "type": "string",
                    "enum": ["SEARCH", "DISPLAY"],
                    "description": (
                        "Advertising channel. SEARCH (default) for text "
                        "ads on Google Search; DISPLAY for image/banner "
                        "ads on the GDN."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="google_ads_campaigns_update",
        description=(
            "Updates one or more settings on an existing campaign. Partial "
            "update — only fields provided are changed; omitted fields are "
            "preserved. Returns the updated campaign record. Mutating and "
            "reversible via rollback_apply (rollback restores the previous "
            "field values). For status-only changes (ENABLED / PAUSED / "
            "REMOVED) prefer google_ads_campaigns_update_status, which is "
            "a lighter-weight call and maps cleanly to pause/resume "
            "workflows."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID to update.",
                },
                "name": {
                    "type": "string",
                    "description": "New campaign name (max 255 chars).",
                },
                "bidding_strategy": {
                    "type": "string",
                    "enum": [
                        "MAXIMIZE_CLICKS",
                        "MAXIMIZE_CONVERSIONS",
                        "MAXIMIZE_CONVERSION_VALUE",
                        "TARGET_CPA",
                        "TARGET_ROAS",
                        "MANUAL_CPC",
                    ],
                    "description": (
                        "New bidding strategy. Switching strategies can "
                        "reset learning periods — confirm with the operator "
                        "before changing on an ENABLED campaign."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_campaigns_update_status",
        description=(
            "Sets the delivery status of a single campaign to ENABLED, "
            "PAUSED, or REMOVED. Lightweight — writes only the status "
            "field. Returns the campaign ID and new status. Reversible "
            "via rollback_apply for ENABLED ↔ PAUSED; REMOVED is a soft "
            "delete that can be reversed by setting status back to "
            "PAUSED within 30 days. Use this for pause/resume; use "
            "google_ads_campaigns_update to change name, bidding, or other "
            "settings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID.",
                },
                "status": {
                    "type": "string",
                    "enum": ["ENABLED", "PAUSED", "REMOVED"],
                    "description": (
                        "Target status. REMOVED is a soft delete — the "
                        "campaign stops serving and is excluded from most "
                        "default listings but remains queryable by ID."
                    ),
                },
            },
            "required": ["campaign_id", "status"],
        },
    ),
    Tool(
        name="google_ads_campaigns_diagnose",
        description=(
            "Explains why a campaign is not serving or is under-delivering. "
            "Returns an ordered list of issues drawn from serving_status, "
            "primary_status, and primary_status_reasons (e.g. "
            "LIMITED_BY_BUDGET, AD_GROUPS_PAUSED, KEYWORDS_DISAPPROVED, "
            "NO_ELIGIBLE_ADS), each annotated with a plain-language "
            "description and a remediation hint. Read-only — does not "
            "change anything. Use this before pulling raw performance "
            "reports; it narrows the problem space."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID to diagnose.",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Ad Groups ===
    Tool(
        name="google_ads_ad_groups_list",
        description=(
            "Lists ad groups in a Google Ads account, optionally scoped to "
            "a single parent campaign and/or filtered by status. Returns id, "
            "name, campaign_id, status, type (SEARCH_STANDARD / DISPLAY_STANDARD / "
            "etc.), cpc_bid_micros, and ad_rotation_mode per ad group. "
            "Read-only. Use this to locate an ad_group_id before calling "
            "ad_groups.create / update or ads.create; if you already have "
            "the id, fetch it directly via ads.list filtered by ad_group_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict results to ad groups under this campaign. "
                        "Omit to list across the whole account."
                    ),
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["ENABLED", "PAUSED", "REMOVED"],
                    "description": (
                        "Restrict to ad groups with this status. Omit for "
                        "all statuses."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads_ad_groups_create",
        description=(
            "Creates a new ad group inside an existing campaign. Returns "
            "the new ad_group's resource_name and id. Mutating — reversible "
            "via rollback_apply (rollback pauses the ad group rather than "
            "deleting it). The parent campaign must be ENABLED or PAUSED; "
            "creating under a REMOVED campaign fails. After creation, add "
            "ads with google_ads_ads_create and keywords with "
            "google_ads.keywords.add."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Parent campaign ID. Must exist and not be REMOVED."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Ad group name (max 255 chars). Must be unique "
                        "within the parent campaign."
                    ),
                },
                "cpc_bid_micros": {
                    "type": "integer",
                    "minimum": 10000,
                    "description": (
                        "Default CPC bid in micros (1 JPY = 1_000_000 "
                        "micros; 1 USD = 1_000_000 micros). Minimum 10_000 "
                        "(= ¥0.01 / $0.01). Omit to inherit the campaign's "
                        "default."
                    ),
                },
            },
            "required": ["campaign_id", "name"],
        },
    ),
    Tool(
        name="google_ads_ad_groups_update",
        description=(
            "Updates one or more settings on an existing ad group. Partial "
            "update — only provided fields are changed. Returns the updated "
            "ad group. Mutating, reversible via rollback.apply. Does not "
            "cascade to ads or keywords under this ad group; use "
            "google_ads_ads_update / update_status and "
            "google_ads.keywords.* for those."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": "Ad group ID to update.",
                },
                "name": {
                    "type": "string",
                    "description": "New ad group name (max 255 chars).",
                },
                "status": {
                    "type": "string",
                    "enum": ["ENABLED", "PAUSED", "REMOVED"],
                    "description": (
                        "New status. For status-only changes this tool is "
                        "equivalent to setting the status field alone — "
                        "there is no separate ad_groups.update_status call."
                    ),
                },
                "cpc_bid_micros": {
                    "type": "integer",
                    "minimum": 10000,
                    "description": (
                        "New default CPC bid in micros (1_000_000 micros = "
                        "1 unit of account currency)."
                    ),
                },
            },
            "required": ["ad_group_id"],
        },
    ),
    # === Ads ===
    Tool(
        name="google_ads_ads_list",
        description=(
            "Lists ads in a Google Ads account, optionally scoped to one "
            "ad group and/or filtered by status. Returns id, ad_group_id, "
            "status, type (RESPONSIVE_SEARCH_AD / RESPONSIVE_DISPLAY_AD / "
            "etc.), final_urls, approval_status, and a creative summary "
            "(headlines / descriptions for RSAs). Read-only. Use this to "
            "find an ad_id before calling ads.update / update_status or to "
            "audit creative inventory. For disapproval details, follow up "
            "with google_ads.ads.policy_details."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Restrict to ads under this ad group. Omit to list "
                        "across the whole account."
                    ),
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["ENABLED", "PAUSED", "REMOVED"],
                    "description": ("Restrict by status. Omit for all statuses."),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads_ads_create",
        description=(
            "Creates a Responsive Search Ad (RSA) in the specified ad "
            "group. Returns the new ad's resource_name, id, and initial "
            "approval_status (usually UNDER_REVIEW for ~1 business day). "
            "Mutating, reversible via rollback_apply (rollback pauses the "
            "ad). Google Ads requires 3–15 headlines and 2–4 descriptions. "
            "For display/banner ads use google_ads_ads_create_display "
            "instead; the two creative formats are not interchangeable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Parent ad group ID. Must belong to a SEARCH "
                        "campaign; DISPLAY ad groups reject RSAs."
                    ),
                },
                "headlines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 15,
                    "description": (
                        "Headlines for the RSA. Google Ads accepts 3 to "
                        "15; each headline is max 30 characters display "
                        "width. Supply at least 5 for good learning."
                    ),
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 4,
                    "description": (
                        "Descriptions for the RSA. 2 to 4 accepted; each "
                        "description is max 90 characters display width."
                    ),
                },
                "final_url": {
                    "type": "string",
                    "description": (
                        "Landing page URL the ad links to. Must match the "
                        "campaign's allowed domains and be HTTPS."
                    ),
                },
                "path1": {
                    "type": "string",
                    "description": (
                        "First URL display path (shown after the domain). "
                        "Max 15 characters display width. Optional."
                    ),
                },
                "path2": {
                    "type": "string",
                    "description": (
                        "Second URL display path. Max 15 characters "
                        "display width. Requires path1 if set. Optional."
                    ),
                },
            },
            "required": ["ad_group_id", "headlines", "descriptions"],
        },
    ),
    Tool(
        name="google_ads_ads_create_display",
        description=(
            "Creates a Responsive Display Ad (RDA) in a DISPLAY campaign's "
            "ad group. Marketing/square/logo image paths point to local "
            "files; mureo uploads each file to Google Ads as an ImageAsset "
            "before composing the ad. Returns the new ad's resource_name, "
            "id, and the generated asset IDs. Mutating, reversible via "
            "rollback.apply. For Search campaigns use "
            "google_ads_ads_create; the ad_group must belong to a DISPLAY "
            "campaign or this call fails with a channel-mismatch error."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": ("Ad group ID. Must belong to a DISPLAY campaign."),
                },
                "headlines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "Short headlines (1 to 5). Each max 30 characters "
                        "display width."
                    ),
                },
                "long_headline": {
                    "type": "string",
                    "description": (
                        "Long headline (max 90 characters display width). "
                        "Required by Google Ads even when headlines are "
                        "supplied."
                    ),
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "Descriptions (1 to 5). Each max 90 characters "
                        "display width."
                    ),
                },
                "business_name": {
                    "type": "string",
                    "description": (
                        "Advertiser / business name shown in the ad (max "
                        "25 characters display width). Required."
                    ),
                },
                "marketing_image_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 15,
                    "description": (
                        "Local file paths for landscape marketing images "
                        "(1.91:1 ratio). 1 to 15 accepted; 3+ strongly "
                        "recommended for delivery quality. mureo uploads "
                        "the files automatically before creating the ad."
                    ),
                },
                "square_marketing_image_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 15,
                    "description": (
                        "Local file paths for square marketing images "
                        "(1:1 ratio). 1 to 15 accepted; 3+ recommended. "
                        "Uploaded automatically."
                    ),
                },
                "logo_image_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                    "description": (
                        "Optional local file paths for logo images (up to "
                        "5). Uploaded automatically. Helps ad quality but "
                        "not required."
                    ),
                },
                "final_url": {
                    "type": "string",
                    "description": (
                        "Landing page URL. Must be HTTPS and match the "
                        "campaign's allowed domains."
                    ),
                },
            },
            "required": [
                "ad_group_id",
                "headlines",
                "long_headline",
                "descriptions",
                "business_name",
                "marketing_image_paths",
                "square_marketing_image_paths",
                "final_url",
            ],
        },
    ),
    Tool(
        name="google_ads_ads_update",
        description=(
            "Updates the creative copy of an existing Responsive Search Ad "
            "by replacing headlines and/or descriptions. Returns the "
            "updated ad. Google Ads does not support in-place edit of RSA "
            "creative assets — this call typically replaces the ad with a "
            "new one under the same ID, which resets learning and triggers "
            "re-review. Mutating, reversible via rollback.apply. For "
            "status-only changes (pause/resume) use "
            "google_ads_ads_update_status, which is lighter-weight and "
            "does not reset learning."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": "Parent ad group ID.",
                },
                "ad_id": {
                    "type": "string",
                    "description": "Ad ID to update.",
                },
                "headlines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 15,
                    "description": (
                        "Replacement headlines (3 to 15). Each max 30 "
                        "characters display width."
                    ),
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 4,
                    "description": (
                        "Replacement descriptions (2 to 4). Each max 90 "
                        "characters display width."
                    ),
                },
            },
            "required": ["ad_group_id", "ad_id"],
        },
    ),
    Tool(
        name="google_ads_ads_update_status",
        description=(
            "Sets the delivery status of a single ad to ENABLED, PAUSED, "
            "or REMOVED. Lightweight — writes only the status field and "
            "does not reset learning signals. Returns the ad ID and new "
            "status. Reversible via rollback.apply. Use this for "
            "pause/resume; use google_ads_ads_update to change the "
            "creative copy itself."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": "Parent ad group ID.",
                },
                "ad_id": {
                    "type": "string",
                    "description": "Ad ID.",
                },
                "status": {
                    "type": "string",
                    "enum": ["ENABLED", "PAUSED", "REMOVED"],
                    "description": (
                        "Target status. REMOVED is a soft delete — the ad "
                        "stops serving but remains queryable by ID."
                    ),
                },
            },
            "required": ["ad_group_id", "ad_id", "status"],
        },
    ),
    # === Ad policy details ===
    Tool(
        name="google_ads_ads_policy_details",
        description=(
            "Fetches the Google Ads policy review result for a single ad, "
            "including approval_status (APPROVED / APPROVED_LIMITED / "
            "DISAPPROVED / UNDER_REVIEW), a list of policy_topic_entries "
            "with topic (e.g. DESTINATION_NOT_WORKING, RESTRICTED_CONTENT), "
            "evidence, and an appeal eligibility flag. Read-only. Call "
            "this after google_ads_ads_list surfaces a non-APPROVED ad to "
            "understand the specific disapproval reasons."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": "Parent ad group ID.",
                },
                "ad_id": {
                    "type": "string",
                    "description": "Ad ID to inspect.",
                },
            },
            "required": ["ad_group_id", "ad_id"],
        },
    ),
    # === Budgets ===
    Tool(
        name="google_ads_budget_get",
        description=(
            "Fetches the campaign-budget record attached to a campaign. "
            "Returns budget_id, name, amount_micros, delivery_method "
            "(STANDARD / ACCELERATED), period (DAILY), and "
            "reference_count (how many campaigns share this budget). "
            "Read-only. Shared budgets are common — confirm "
            "reference_count before calling google_ads_budget_update, "
            "since changes affect all linked campaigns."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign ID whose budget to fetch. mureo resolves "
                        "the attached budget_id internally."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads_budget_update",
        description=(
            "Sets the daily amount on an existing campaign budget. Mutating "
            "and reversible via rollback_apply (rollback restores the prior "
            "amount). Returns the updated budget. If the budget is shared "
            "across multiple campaigns, the change affects all of them — "
            "call google_ads_budget_get first to check reference_count. "
            "The `amount` parameter is in the account's currency unit "
            "(JPY / USD / etc.), not micros."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "budget_id": {
                    "type": "string",
                    "description": ("Budget ID as returned by google_ads.budget.get."),
                },
                "amount": {
                    "type": "number",
                    "minimum": 1,
                    "description": (
                        "New daily budget in the account's currency "
                        "(JPY / USD / etc.). Not micros — e.g. pass 5000 "
                        "for ¥5,000 / day."
                    ),
                },
            },
            "required": ["budget_id", "amount"],
        },
    ),
    # === Budget creation ===
    Tool(
        name="google_ads_budget_create",
        description=(
            "Creates a new campaign budget that can be attached to one or "
            "more campaigns. Returns the new budget's id and resource_name. "
            "Mutating, reversible via rollback.apply. Typical flow: "
            "budget.create → campaigns.create with the returned budget_id. "
            "To edit an existing budget's amount use "
            "google_ads_budget_update instead of creating a second budget."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": (
                        "Budget name (max 255 chars). Must be unique "
                        "within the account."
                    ),
                },
                "amount": {
                    "type": "number",
                    "minimum": 1,
                    "description": (
                        "Daily budget in the account's currency "
                        "(JPY / USD / etc.). Not micros — e.g. pass 5000 "
                        "for ¥5,000 / day."
                    ),
                },
            },
            "required": ["name", "amount"],
        },
    ),
    # === Account ===
    Tool(
        name="google_ads_accounts_list",
        description=(
            "Lists all Google Ads accounts accessible under the configured "
            "manager (MCC) account or directly under the authenticated "
            "user. Returns one row per accessible customer with id "
            "(10-digit), descriptive_name, currency_code, time_zone, and "
            "manager flag. Read-only. Use this at the start of a session "
            "to choose which customer_id to pass into subsequent calls; "
            "most other tools fall back to GOOGLE_ADS_CUSTOMER_ID if "
            "customer_id is omitted."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
            },
            "required": [],
        },
    ),
]
