"""Google Ads tool definitions — Demographic & audience criteria reads (#366)"""

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

_AD_GROUP_ID_PARAM = {
    "type": "string",
    "description": (
        "Restrict results to criteria on this ad group. Omit to read "
        "across the whole account (or scope with campaign_id)."
    ),
}

_CAMPAIGN_ID_PARAM = {
    "type": "string",
    "description": (
        "Restrict results to criteria under this campaign. Omit to read "
        "across the whole account."
    ),
}

TOOLS: list[Tool] = [
    Tool(
        name="google_ads_demographic_targeting_list",
        description=(
            "Lists explicit demographic criteria (age range, gender, "
            "parental status, household income) set on ad groups. Returns "
            "one entry per criterion shaped {criterion_id, type "
            "('AGE_RANGE'|'GENDER'|'PARENTAL_STATUS'|'INCOME_RANGE'), "
            "value (the segment enum, e.g. 'AGE_RANGE_25_34', 'FEMALE'), "
            "status, negative (true = excluded segment), campaign_id, "
            "ad_group_id, ad_group_name}. Read-only. Segments with no "
            "explicit criterion are targeted by default and do NOT appear "
            "— an empty result means 'all demographics, no exclusions', "
            "not 'nothing targeted'. Scope with ad_group_id and/or "
            "campaign_id, or omit both for the whole account (capped at "
            "1000 criteria)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": _AD_GROUP_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads_audience_targeting_list",
        description=(
            "Lists audience-type criteria attached to ad groups: user "
            "interests (affinity / in-market), remarketing & customer-match "
            "user lists, custom / combined audiences, and Audience "
            "resources. Returns one entry per criterion shaped "
            "{criterion_id, type ('USER_INTEREST'|'USER_LIST'|'AUDIENCE'|"
            "'CUSTOM_AFFINITY'|'CUSTOM_AUDIENCE'|'COMBINED_AUDIENCE'), "
            "value (the criterion's resource name, e.g. "
            "'customers/1/userLists/42'), status, negative, campaign_id, "
            "ad_group_id, ad_group_name}. Read-only. Use this to audit "
            "which audience segments an ad group targets or excludes "
            "before proposing targeting changes. Scope with ad_group_id "
            "and/or campaign_id, or omit both for the whole account "
            "(capped at 1000 criteria)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": _AD_GROUP_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": [],
        },
    ),
]
