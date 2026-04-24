"""Meta Ads tool definitions — Audiences, pixels.

Tool descriptions follow ``docs/tdqs-style-guide.md``. Custom audiences
define who ads target; pixels are the event-tracking source used to
measure conversions and populate website-based audiences.
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

_LIMIT_PARAM = {
    "type": "integer",
    "minimum": 1,
    "maximum": 1000,
    "description": (
        "Maximum records returned per call. Default 50, max 1000 per " "Meta Graph API."
    ),
}

TOOLS: list[Tool] = [
    # === Audiences ===
    Tool(
        name="meta_ads.audiences.list",
        description=(
            "Lists Custom Audiences in a Meta Ads account. Returns id, "
            "name, subtype (WEBSITE / CUSTOM / LOOKALIKE / APP / etc.), "
            "approximate_count, retention_days, and data_source per "
            "audience. Read-only. Use this to find an audience_id before "
            "targeting an ad set (meta_ads.ad_sets.create / update) or "
            "before creating a lookalike (audiences.create_lookalike). "
            "Approximate counts from Meta may lag actual size by 24–48h."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "limit": _LIMIT_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.audiences.create",
        description=(
            "Creates a Custom Audience in a Meta Ads account. Returns the "
            "new audience_id. Mutating, reversible via rollback.apply "
            "(rollback deletes the audience). Subtype controls the data "
            "source: WEBSITE audiences require a pixel_id and an event "
            "rule; CUSTOM audiences accept a manually supplied rule or a "
            "customer list upload (the upload path is handled out-of-band "
            "by Meta). For similarity-expanded reach use "
            "meta_ads.audiences.create_lookalike on top of this audience."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": (
                        "Audience name shown in Ads Manager. Must be "
                        "unique within the account."
                    ),
                },
                "subtype": {
                    "type": "string",
                    "enum": ["WEBSITE", "CUSTOM", "APP"],
                    "description": (
                        "Audience type hint. WEBSITE auto-generates a "
                        "PageView rule from the linked pixel when `rule` "
                        "is omitted; CUSTOM requires an explicit rule or "
                        "a customer-list upload; APP requires an app_id. "
                        "Default CUSTOM when omitted."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Optional free-text description stored with the "
                        "audience. Not visible to end users."
                    ),
                },
                "retention_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 180,
                    "description": (
                        "How long a matched user stays in the audience "
                        "after their last qualifying event. Default 30. "
                        "Meta caps at 180 days."
                    ),
                },
                "pixel_id": {
                    "type": "string",
                    "description": (
                        "Meta Pixel ID to source events from. Required "
                        "for subtype=WEBSITE. Find via meta_ads.pixels."
                        "list."
                    ),
                },
                "rule": {
                    "type": "object",
                    "description": (
                        "Audience rule definition (Meta rule JSON schema). "
                        "When omitted with subtype=WEBSITE, a default "
                        "PageView rule scoped to the supplied pixel is "
                        "auto-generated. See Meta Marketing API docs for "
                        "rule syntax — supports url filters, event "
                        "parameters, and compound boolean operators."
                    ),
                },
                "customer_file_source": {
                    "type": "string",
                    "enum": [
                        "USER_PROVIDED_ONLY",
                        "PARTNER_PROVIDED_ONLY",
                        "BOTH_USER_AND_PARTNER_PROVIDED",
                    ],
                    "description": (
                        "Source declaration required by Meta for "
                        "compliance. USER_PROVIDED_ONLY (default) — data "
                        "came from the advertiser's own first-party "
                        "sources; PARTNER — from a data provider; BOTH — "
                        "mixed. Meta uses this to set legal-basis "
                        "defaults."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    # === Audience get / delete / lookalike ===
    Tool(
        name="meta_ads.audiences.get",
        description=(
            "Fetches the full detail record for a single Custom Audience, "
            "including the rule definition and approximate_count. "
            "Returns id, name, subtype, description, retention_days, "
            "approximate_count, data_source, rule (for rule-based "
            "audiences), and pixel_id (for WEBSITE audiences). "
            "Read-only. Call this before meta_ads.audiences.delete or "
            "before create_lookalike to verify you have the right audience."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "audience_id": {
                    "type": "string",
                    "description": (
                        "Audience ID as returned by " "meta_ads.audiences.list."
                    ),
                },
            },
            "required": ["audience_id"],
        },
    ),
    Tool(
        name="meta_ads.audiences.delete",
        description=(
            "Deletes a Custom Audience. Returns a success flag. "
            "Destructive — any ad sets currently targeting this audience "
            "lose the targeting source and may stop delivering. Reversible "
            "via rollback.apply within Meta's standard retention window, "
            "but re-creation does not restore the original "
            "approximate_count. Call meta_ads.audiences.get first to "
            "confirm which ad sets use it (search ad_sets.list targeting "
            "specs client-side), and consider pausing those ad sets first."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "audience_id": {
                    "type": "string",
                    "description": "Audience ID to delete.",
                },
            },
            "required": ["audience_id"],
        },
    ),
    Tool(
        name="meta_ads.audiences.create_lookalike",
        description=(
            "Creates a Lookalike Audience from an existing source "
            "audience. Returns the new audience_id. Mutating, reversible "
            "via rollback.apply. Lookalikes typically populate within "
            "24–72h; the approximate_count remains 0 until Meta finishes "
            "the similarity build. ratio=0.01 gives the top 1% most "
            "similar users in the target country (smallest, highest "
            "match); ratio=0.10 gives top 10% (larger reach, looser "
            "match). For the base audience list use "
            "meta_ads.audiences.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": (
                        "Audience name shown in Ads Manager. Must be "
                        "unique within the account."
                    ),
                },
                "source_audience_id": {
                    "type": "string",
                    "description": (
                        "Source Custom Audience to build the lookalike "
                        "from. Meta recommends a source of at least "
                        "1,000–10,000 users for good match quality."
                    ),
                },
                "country": {
                    "description": (
                        "Target country ISO code(s) for the lookalike "
                        "expansion. Accepts a single code string (e.g. "
                        "'JP') or a list (e.g. ['JP', 'KR']). Lookalike "
                        "reach is always scoped to the specified "
                        "country/countries."
                    ),
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "ratio": {
                    "type": "number",
                    "minimum": 0.01,
                    "maximum": 0.20,
                    "description": (
                        "Similarity ratio — fraction of the target "
                        "country's population to include. 0.01 = top 1% "
                        "(tightest match, smallest audience); 0.20 = top "
                        "20% (loosest, largest). Meta caps at 0.20."
                    ),
                },
                "starting_ratio": {
                    "type": "number",
                    "minimum": 0.0,
                    "description": (
                        "Lower bound of the ratio range. Default 0.0. "
                        "Advanced: set > 0 to carve out a tiered lookalike "
                        "that excludes the top-similarity slice (e.g. "
                        "starting_ratio=0.01, ratio=0.05 = users ranked "
                        "1–5% in similarity, excluding the top 1%)."
                    ),
                },
            },
            "required": [
                "account_id",
                "name",
                "source_audience_id",
                "country",
                "ratio",
            ],
        },
    ),
    # === Pixels ===
    Tool(
        name="meta_ads.pixels.list",
        description=(
            "Lists Meta Pixels available in the ad account. Returns id, "
            "name, code (the base pixel snippet), last_fired_time, and "
            "is_created_by_business per pixel. Read-only. Use this to "
            "find a pixel_id before creating a WEBSITE audience "
            "(meta_ads.audiences.create) or fetching event statistics "
            "(meta_ads.pixels.stats / events)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "limit": _LIMIT_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.pixels.get",
        description=(
            "Fetches the full detail record for a single Meta Pixel. "
            "Returns id, name, code, creation_time, last_fired_time, "
            "owner_business, data_use_setting, and the linked ad_accounts. "
            "Read-only. Call this to verify pixel setup (e.g. confirm "
            "last_fired_time is recent) before diagnosing conversion "
            "tracking issues or before relying on the pixel for audience "
            "rules."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "pixel_id": {
                    "type": "string",
                    "description": ("Pixel ID as returned by meta_ads.pixels.list."),
                },
            },
            "required": ["pixel_id"],
        },
    ),
    Tool(
        name="meta_ads.pixels.stats",
        description=(
            "Returns aggregated pixel-event counts over a rolling time "
            "window. Returns an array of {date, event_name, count} rows. "
            "Read-only. Use this to spot unusual drops in PageView / "
            "Purchase / Lead volume that indicate a pixel break. For "
            "per-event metadata (parameter names, sample payloads) use "
            "meta_ads.pixels.events instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "pixel_id": {
                    "type": "string",
                    "description": "Pixel ID to query.",
                },
                "period": {
                    "type": "string",
                    "enum": ["last_7d", "last_14d", "last_30d", "last_90d"],
                    "description": (
                        "Aggregation window. Default last_30d. Longer "
                        "windows cost more Graph API quota but are "
                        "necessary to spot slow degradations."
                    ),
                },
            },
            "required": ["pixel_id"],
        },
    ),
    Tool(
        name="meta_ads.pixels.events",
        description=(
            "Lists distinct event types the pixel has received recently, "
            "with sample payloads. Returns event_name, sample_count, "
            "first_seen, last_seen, and a sample_parameters dict per "
            "event. Read-only. Use this to audit which standard events "
            "(Purchase, Lead, ViewContent, etc.) and custom events are "
            "firing, and to inspect parameter names before building "
            "conversion rules or audience definitions that reference "
            "them. For aggregate volume over time use "
            "meta_ads.pixels.stats."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "pixel_id": {
                    "type": "string",
                    "description": "Pixel ID to inspect.",
                },
            },
            "required": ["pixel_id"],
        },
    ),
]
