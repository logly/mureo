"""The ``campaign`` argument of ``mureo_state_upsert_campaign``.

A CampaignSnapshot plus its platform context, with the nested ``ads``
array. Kept apart from :mod:`mureo.mcp.tools_mureo_context` so that module,
which declares every context tool, stays within its line budget as the
snapshot gains fields.
"""

from __future__ import annotations

_ADS_PROPERTY = {
    "type": "array",
    "description": (
        "Ad-level (creative-level) delivery state for this campaign. Send it "
        "so a change made OUTSIDE mureo — an ad paused by hand in the "
        "platform UI, stopped by its ad set/campaign, or rejected by policy "
        "— is recorded as fact and can be diffed on the next run. "
        "``status`` is what the ad is configured as; ``effective_status`` is "
        "whether it is actually delivering, and the two disagreeing is the "
        "signal. Omit the whole field when you did not fetch ad-level status "
        "(that is different from sending an empty list, which means "
        "'fetched, this campaign has no ads')."
    ),
    "items": {
        "type": "object",
        "properties": {
            "ad_id": {"type": "string", "description": "Platform ad id."},
            "name": {"type": "string", "description": "Ad name."},
            "status": {
                "type": "string",
                "description": "Configured status (e.g. ACTIVE / PAUSED).",
            },
            "effective_status": {
                "type": "string",
                "description": (
                    "Actual delivery status where the platform exposes one "
                    "(Meta: ACTIVE / ADSET_PAUSED / CAMPAIGN_PAUSED / "
                    "DISAPPROVED / …). Omit when the platform does not "
                    "report it rather than copying ``status`` into it."
                ),
            },
            "as_of": {
                "type": "string",
                "description": (
                    "IGNORED — the server stamps each ad with its own clock "
                    "(ISO 8601 with UTC offset), so a drifted client date "
                    "can never be persisted and later read back as when the "
                    "status was observed."
                ),
            },
        },
        "required": ["ad_id"],
    },
}


CAMPAIGN_PROPERTY = {
    "type": "object",
    "description": (
        "A CampaignSnapshot for STATE.json plus its platform context. "
        "Required: campaign_id, campaign_name, status, platform, "
        "account_id. The platform + account_id populate the per-platform "
        "``platforms`` section the dashboard reads (omit them and the "
        "client renders as inactive). Optional fields mirror the snapshot "
        "schema in docs/strategy-context.md, including ``metrics`` "
        "(spend / impressions / clicks / conversions / cpa / ctr / "
        "result_indicator / period / fetched_at) for dashboard KPIs."
    ),
    "properties": {
        "campaign_id": {"type": "string"},
        "campaign_name": {"type": "string"},
        "status": {"type": "string"},
        "platform": {
            "type": "string",
            # No enum: a valid key includes ``plugin:<dist>`` for any installed
            # bridge, which no fixed list can enumerate. minLength is the
            # constraint that IS always true.
            "minLength": 1,
            "description": (
                "Platform key this campaign belongs to, e.g. "
                "``google_ads`` / ``meta_ads`` / ``tiktok_ads``, a platform "
                "an installed plugin registered (its provider name), or a "
                "plugin bridge ``plugin:<dist>:<provider>``. Use the SAME key "
                "the account is already stored under — one ad account has "
                "exactly one platform key, and a second key for an account "
                "another key already holds is REJECTED (the reporting view "
                "sums the entries, so it would double-count). A NEW key that "
                "is none of the three is REJECTED too: do not invent or "
                "abbreviate a platform name."
            ),
        },
        "account_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Platform account id (Google ``customer_id`` / Meta "
                "``act_*``) written onto the platform entry, and used to "
                "detect a second entry for the same account. A placeholder "
                "(``unknown``, ``n/a``, …) is refused: if the collection "
                "could not resolve an id, use "
                "mureo_state_platform_not_collected_set."
            ),
        },
        "bidding_strategy_type": {
            "type": "string",
            "description": (
                "Bid strategy as the platform itself names it, verbatim. "
                "Omit it for a platform that does not select delivery by a "
                "bid — never borrow another platform's strategy name."
            ),
        },
        "bidding_details": {
            "type": "object",
            "description": (
                "Free-form bidding detail in the platform's own vocabulary "
                "(e.g. {'target_cpa': 5000}); omit it alongside "
                "bidding_strategy_type where the platform has neither. One "
                "key is read by mureo: for Google Ads, "
                "'bidding_strategy_system_status' — the value "
                "google_ads_campaigns_get / google_ads_campaigns_diagnose "
                "returns — is what the learning-period pre-flight "
                "(mureo_learning_reset_preflight, and the "
                "block_learning_resets* guardrails) uses to tell whether the "
                "campaign is already re-learning. Without it that state is "
                "reported 'unknown', never 'steady'."
            ),
        },
        "campaign_type": {
            "type": "string",
            "description": (
                "The platform's OWN name for the campaign type, verbatim "
                "(Google Ads advertising_channel_type, e.g. 'SEARCH', "
                "'PERFORMANCE_MAX'; Meta objective, e.g. 'OUTCOME_LEADS'). "
                "Omit it for a platform without the concept. An upsert that "
                "omits it keeps the value already stored for the campaign."
            ),
        },
        "daily_budget": {"type": "number"},
        "monthly_budget": {
            "type": "number",
            "description": (
                "The campaign's own MONTHLY budget, on a platform that has "
                "that concept alongside the daily one. Omit it entirely for "
                "a platform configured per day (Google Ads, Meta) — do not "
                "send a daily budget multiplied out, which is an implied cap "
                "and not what the campaign is set to spend. mureo never "
                "stores a total over these: it sums them on read, and only "
                "where every campaign of a declaring platform carries one."
            ),
        },
        "device_targeting": {"type": "array"},
        "campaign_goal": {"type": "string"},
        "notes": {"type": "string"},
        "metrics": {
            "type": "object",
            "description": (
                "Optional performance metrics for the reporting dashboard: "
                "spend, impressions, clicks, conversions, cpa, ctr, "
                "result_indicator (Meta: clicks vs leads), period (e.g. "
                "``LAST_30_DAYS``), fetched_at (ISO 8601)."
            ),
        },
        "ads": _ADS_PROPERTY,
    },
    "required": [
        "campaign_id",
        "campaign_name",
        "status",
        "platform",
        "account_id",
    ],
}
