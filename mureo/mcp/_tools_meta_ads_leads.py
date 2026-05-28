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
        name="meta_ads_lead_forms_list",
        description=(
            "Lists lead forms configured for a Facebook Page. Returns id, "
            "name, status, leads_count, locale, and created_time per "
            "form. Read-only. Lead forms belong to Pages, not ad "
            "accounts — use this to find a form_id before attaching it "
            "to a Lead Ads creative or before pulling submitted lead "
            "data via meta_ads_leads_get."
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
        name="meta_ads_lead_forms_get",
        description=(
            "Fetches the full detail record for a single lead form, "
            "including its question definitions and legal pages. "
            "Returns id, name, status, locale, questions (array with "
            "type / key / label per question), privacy_policy "
            "(``{url, link_text?}``) and the legacy "
            "``privacy_policy_url`` flat field, "
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
                        "Lead form ID as returned by " "meta_ads_lead_forms_list."
                    ),
                },
            },
            "required": ["form_id"],
        },
    ),
    Tool(
        name="meta_ads_lead_forms_create",
        description=(
            "Creates a new lead form on a Facebook Page. Returns the new "
            "form_id. Mutating, reversible via rollback_apply (rollback "
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
                        "Meta's default confirmation only. Superseded by "
                        "thank_you_page when both are supplied."
                    ),
                },
                "locale": {
                    "type": "string",
                    "description": (
                        "Optional form locale (e.g. ``ja_JP``). Defaults "
                        "to the Page's primary locale."
                    ),
                },
                "context_card": {
                    "type": "object",
                    "description": (
                        "Optional intro / welcome screen shown before "
                        "the form. Lifts conversion rate measurably when "
                        "supplied. Expected keys: title, content, style "
                        "(PARAGRAPH_STYLE or LIST_STYLE), cover_photo_id."
                    ),
                },
                "thank_you_page": {
                    "type": "object",
                    "description": (
                        "Optional custom completion screen with a CTA. "
                        "Replaces follow_up_action_url's simple "
                        "redirect when supplied. Expected keys: title, "
                        "body, button_type (VIEW_WEBSITE / "
                        "CALL_BUSINESS / MESSAGE_BUSINESS / DOWNLOAD / "
                        "DOWNLOAD_APP), website_url, button_text."
                    ),
                },
                "is_higher_intent": {
                    "type": "boolean",
                    "description": (
                        "When true, Meta renders a 3-step form "
                        "(input → review → submit) which trims junk "
                        "submissions at the cost of total leads "
                        "volume. Default false (single-step)."
                    ),
                },
                "conditional_questions_choices": {
                    "type": "array",
                    "description": (
                        "Branching logic — given a prior question's "
                        "value, choose which question to ask next. "
                        "Each entry: {question: <key>, value: "
                        "<choice>, next_question_key: <key>}. Meta "
                        "validates the keys refer to real questions."
                    ),
                    "items": {"type": "object"},
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
        name="meta_ads_lead_forms_update",
        description=(
            "Changes a lead form's lifecycle status. This tool updates "
            "only the status field — other form fields (questions, "
            "privacy_policy_url, name, follow_up_action_url, locale, "
            "advanced layout) are intentionally out of scope; Meta's "
            "post-creation mutability has shifted between versions, "
            "so mureo stays conservative. Pass status=ARCHIVED to "
            "retire a form (existing leads stay queryable; the form "
            "stops accepting new submissions). Pass status=ACTIVE to "
            "undo an archive. Mutating, reversible (re-call with the "
            "opposite value)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "form_id": {
                    "type": "string",
                    "description": "Lead form ID to update.",
                },
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "ARCHIVED"],
                    "description": (
                        "Target status. ACTIVE accepts submissions; "
                        "ARCHIVED stops them. Other values (DRAFT, "
                        "DELETED, DELETION_PENDING) appear in read "
                        "paths but cannot be set by an operator."
                    ),
                },
            },
            "required": ["form_id", "status"],
        },
    ),
    Tool(
        name="meta_ads_lead_forms_duplicate",
        description=(
            "Duplicates a lead form under the same (or another) Page. "
            "Meta has no native copy endpoint, so this fetches the "
            "source form's questions, privacy_policy, optional "
            "follow_up_action_url and locale, then creates a fresh "
            "form with the supplied new_name. Returns the new form's "
            "id. Source form is untouched. Mutating, reversible via "
            "meta_ads_lead_forms_update {status: ARCHIVED} on the new "
            "form's id. **Lossy:** advanced fields on the source "
            "(legal_content_id, gdpr_required / custom_disclaimer, "
            "question_page_custom_headline, intro/thank-you screens, "
            "conditional question branches) are NOT copied; re-create "
            "them on the new form manually if needed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "form_id": {
                    "type": "string",
                    "description": ("Source lead form ID to copy from."),
                },
                "page_id": {
                    "type": "string",
                    "description": (
                        "Facebook Page that will own the new form. "
                        "Usually the same Page that owns the source "
                        "form."
                    ),
                },
                "new_name": {
                    "type": "string",
                    "description": (
                        "Name for the new form. Pick something "
                        "distinct from the source."
                    ),
                },
            },
            "required": ["form_id", "page_id", "new_name"],
        },
    ),
    Tool(
        name="meta_ads_leads_export_csv",
        description=(
            "Fetches all leads for a lead form and writes them to a "
            "local CSV file. Returns the number of rows written. "
            'Header row is ``["id", "created_time", *question_keys]``; '
            "question_keys come from the form's declared questions "
            "(in declared order) so column order stays stable across "
            "exports. Pass field_order to lock a different column "
            "order (useful for stable CRM-import schemas). PII never "
            "appears in mureo's log output — only the row count. "
            "Read-only with respect to Meta, but writes locally. "
            "Meta retains lead data for 90 days; export regularly."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "form_id": {
                    "type": "string",
                    "description": "Lead form ID whose leads to export.",
                },
                "output_path": {
                    "type": "string",
                    "description": (
                        "Absolute local path for the CSV file. Parent "
                        "directory is auto-created if missing; "
                        "existing file is overwritten. UTF-8 encoded."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": (
                        "Max leads per API call. Default 1000, "
                        "Meta's per-call ceiling."
                    ),
                },
                "field_order": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of question keys to lock the "
                        "column order. Overrides the form's declared "
                        "question order."
                    ),
                },
            },
            "required": ["form_id", "output_path"],
        },
    ),
    Tool(
        name="meta_ads_leads_get",
        description=(
            "Retrieves submitted leads for a single form. Returns per "
            "lead: id, created_time, ad_id, campaign_id, form_id, and "
            "field_data (array of {name, values} matching the form "
            "questions). Read-only. Use this for batch CRM sync or "
            "retrospective analysis. For leads attributed to a specific "
            "ad across forms use meta_ads_leads_get_by_ad. Meta retains "
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
        name="meta_ads_leads_get_by_ad",
        description=(
            "Retrieves leads attributed to a specific ad, regardless of "
            "which form they used. Returns the same lead record shape as "
            "meta_ads_leads_get. Read-only. Use this to measure lead "
            "volume of a particular creative / ad ID when ranking "
            "winners. For full form-based lead pulls (cross-ad) use "
            "meta_ads_leads_get."
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
