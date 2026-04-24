"""Meta Ads tool definitions — Lead forms, leads.

Tool descriptions follow ``docs/tdqs-style-guide.md``. Lead Ads
collect prospect contact info directly inside Meta (no landing page).
Forms belong to a Facebook Page; submitted leads are retrievable via
the Page or attributed to the originating ad.
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

TOOLS: list[Tool] = [
    # === Lead Ads ===
    Tool(
        name="meta_ads.lead_forms.list",
        description=(
            "Lists lead forms configured for a Facebook Page. Returns id, "
            "name, status, leads_count, locale, and created_time per "
            "form. Read-only. Lead forms belong to Pages, not ad "
            "accounts — use this to find a form_id before attaching it "
            "to a Lead Ads creative or before pulling submitted lead "
            "data via meta_ads.leads.get."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "page_id": {
                    "type": "string",
                    "description": (
                        "Facebook Page ID whose forms to list. Must be a "
                        "page the authenticated user has admin access to."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": ("Max forms per call. Default 50, max 1000."),
                },
            },
            "required": ["page_id"],
        },
    ),
    Tool(
        name="meta_ads.lead_forms.get",
        description=(
            "Fetches the full detail record for a single lead form, "
            "including its question definitions and legal pages. "
            "Returns id, name, status, locale, questions (array with "
            "type / key / label per question), privacy_policy_url, "
            "follow_up_action_url, leads_count, and created_time. "
            "Read-only. Call this before designing downstream CRM sync "
            "so you know the exact field keys to map."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "form_id": {
                    "type": "string",
                    "description": (
                        "Lead form ID as returned by " "meta_ads.lead_forms.list."
                    ),
                },
            },
            "required": ["form_id"],
        },
    ),
    Tool(
        name="meta_ads.lead_forms.create",
        description=(
            "Creates a new lead form on a Facebook Page. Returns the new "
            "form_id. Mutating, reversible via rollback.apply (rollback "
            "archives the form rather than deleting submitted leads). "
            "Questions is an ordered list of standard Meta types "
            "(FULL_NAME, EMAIL, PHONE_NUMBER, COMPANY_NAME, JOB_TITLE, "
            "CITY, STATE, ZIP_CODE, COUNTRY, DATE_OF_BIRTH) or CUSTOM "
            "(requires key, label, and options for dropdowns). Meta "
            "requires a privacy_policy_url by policy."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "page_id": {
                    "type": "string",
                    "description": ("Facebook Page ID that will own the form."),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Form name shown in Ads Manager and Page Lead " "Center."
                    ),
                },
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "description": (
                        "Ordered question list. Standard-type questions "
                        "only need `type`; CUSTOM questions require "
                        "`key`, `label`, and (for dropdowns) `options`."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": (
                                    "Standard type (FULL_NAME, EMAIL, "
                                    "PHONE_NUMBER, COMPANY_NAME, "
                                    "JOB_TITLE, CITY, STATE, ZIP_CODE, "
                                    "COUNTRY, DATE_OF_BIRTH) or CUSTOM "
                                    "for an advertiser-defined question."
                                ),
                            },
                            "key": {
                                "type": "string",
                                "description": (
                                    "Stable field key for CUSTOM "
                                    "questions. Used as the lead-data "
                                    "field name — map this to CRM "
                                    "fields. Required when type=CUSTOM."
                                ),
                            },
                            "label": {
                                "type": "string",
                                "description": (
                                    "Question label shown to the user. "
                                    "Required when type=CUSTOM."
                                ),
                            },
                            "options": {
                                "type": "array",
                                "description": (
                                    "Dropdown options for CUSTOM "
                                    "questions. Omit for free-text."
                                ),
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
                    "description": (
                        "HTTPS URL of the advertiser's privacy policy. "
                        "Required by Meta policy — forms without one are "
                        "rejected."
                    ),
                },
                "follow_up_action_url": {
                    "type": "string",
                    "description": (
                        "Optional URL the user is redirected to after "
                        "submission (e.g. thank-you page). Omit to show "
                        "Meta's default confirmation only."
                    ),
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
        description=(
            "Retrieves submitted leads for a single form. Returns per "
            "lead: id, created_time, ad_id, campaign_id, form_id, and "
            "field_data (array of {name, values} matching the form "
            "questions). Read-only. Use this for batch CRM sync or "
            "retrospective analysis. For leads attributed to a specific "
            "ad across forms use meta_ads.leads.get_by_ad. Meta retains "
            "lead data for 90 days — pull regularly to avoid loss."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "form_id": {
                    "type": "string",
                    "description": "Form ID whose leads to fetch.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": (
                        "Max leads per call. Default 100, max 1000 per "
                        "Meta Graph API."
                    ),
                },
            },
            "required": ["form_id"],
        },
    ),
    Tool(
        name="meta_ads.leads.get_by_ad",
        description=(
            "Retrieves leads attributed to a specific ad, regardless of "
            "which form they used. Returns the same lead record shape as "
            "meta_ads.leads.get. Read-only. Use this to measure lead "
            "volume of a particular creative / ad ID when ranking "
            "winners. For full form-based lead pulls (cross-ad) use "
            "meta_ads.leads.get."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "ad_id": {
                    "type": "string",
                    "description": (
                        "Ad ID whose leads to fetch. The ad must be a "
                        "Lead Ads ad (creative linked to a lead form)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": (
                        "Max leads per call. Default 100, max 1000 per "
                        "Meta Graph API."
                    ),
                },
            },
            "required": ["ad_id"],
        },
    ),
]
