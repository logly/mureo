"""Google Ads tool definitions — Keywords, negative keywords.

Tool descriptions follow ``docs/tdqs-style-guide.md``.
"""

from __future__ import annotations

from mcp.types import Tool

# Reusable parameter fragments.
_CUSTOMER_ID_PARAM = {
    "type": "string",
    "description": (
        "Google Ads customer ID as a 10-digit string without dashes "
        "(e.g. '1234567890'). Optional — falls back to "
        "GOOGLE_ADS_CUSTOMER_ID / GOOGLE_ADS_LOGIN_CUSTOMER_ID from the "
        "configured credentials when omitted."
    ),
}

_KEYWORD_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": (
                "Keyword text. Max 80 characters / 10 words. Exact match "
                "and phrase match can additionally use bracketed/quoted "
                "forms, but mureo passes match type via the match_type "
                "field — supply plain text here."
            ),
        },
        "match_type": {
            "type": "string",
            "enum": ["BROAD", "PHRASE", "EXACT"],
            "description": (
                "Match type for this keyword. BROAD (default) is widest "
                "reach; PHRASE requires the query to contain the keyword "
                "phrase; EXACT matches close variants only."
            ),
        },
    },
    "required": ["text"],
}

TOOLS: list[Tool] = [
    # === Keywords ===
    Tool(
        name="google_ads.keywords.list",
        description=(
            "Lists keyword criteria in a Google Ads account, optionally "
            "scoped to a campaign and/or ad group and filtered by status. "
            "Returns criterion_id, ad_group_id, text, match_type, status, "
            "cpc_bid_micros (if overridden), quality_score, and "
            "approval_status per keyword. Read-only. Use this to locate "
            "a criterion_id before calling keywords.pause / remove, or to "
            "audit keyword coverage. For quality-score diagnostics use "
            "google_ads.keywords.diagnose."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict to keywords under this campaign. Omit "
                        "with ad_group_id also omitted to list across the "
                        "account."
                    ),
                },
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Restrict to a single ad group. If both "
                        "campaign_id and ad_group_id are supplied they "
                        "must agree."
                    ),
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["ENABLED", "PAUSED", "REMOVED"],
                    "description": (
                        "Restrict by status. Omit for all statuses."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.keywords.add",
        description=(
            "Adds one or more keyword criteria to a single ad group. "
            "Returns the created criterion_ids keyed by their input "
            "position. Mutating, reversible via rollback.apply (rollback "
            "pauses the keywords rather than removing them). Duplicate "
            "text+match_type pairs inside the same ad group are rejected "
            "by Google Ads — call google_ads.keywords.cross_adgroup_duplicates "
            "first if you are adding at scale."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Target ad group ID. All keywords in this call are "
                        "added to this single ad group."
                    ),
                },
                "keywords": {
                    "type": "array",
                    "items": _KEYWORD_ITEM_SCHEMA,
                    "minItems": 1,
                    "description": (
                        "Keywords to add. Each item has `text` (required) "
                        "and optional `match_type` (BROAD / PHRASE / "
                        "EXACT, default BROAD)."
                    ),
                },
            },
            "required": ["ad_group_id", "keywords"],
        },
    ),
    Tool(
        name="google_ads.keywords.remove",
        description=(
            "Removes (soft-deletes) a single keyword criterion from an ad "
            "group. Returns the removed criterion_id. Destructive and "
            "reversible via rollback.apply, but rollback re-adds the "
            "keyword as a fresh criterion — the original quality score and "
            "learning are lost. For temporary suspension prefer "
            "google_ads.keywords.pause, which preserves all signals."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": "Parent ad group ID.",
                },
                "criterion_id": {
                    "type": "string",
                    "description": (
                        "Keyword criterion ID as returned by "
                        "google_ads.keywords.list."
                    ),
                },
            },
            "required": ["ad_group_id", "criterion_id"],
        },
    ),
    Tool(
        name="google_ads.keywords.suggest",
        description=(
            "Generates new keyword ideas from seed terms using the Google "
            "Ads Keyword Planner API. Returns suggested keyword text, "
            "avg_monthly_searches, competition (LOW / MEDIUM / HIGH), "
            "top_of_page_bid_low_micros, and top_of_page_bid_high_micros. "
            "Read-only — produces ideas but does not add anything to the "
            "account. Use google_ads.keywords.add to materialize the ones "
            "you want."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "seed_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 20,
                    "description": (
                        "Seed terms used to generate ideas. 1 to 20 terms; "
                        "Google Ads treats them as topic anchors, not exact "
                        "match."
                    ),
                },
                "language_id": {
                    "type": "string",
                    "description": (
                        "Google Ads language constant ID. Defaults to "
                        "'1005' (Japanese). Common values: '1000' English, "
                        "'1002' Spanish, '1003' Korean, '1017' Chinese "
                        "(Simplified)."
                    ),
                },
                "geo_id": {
                    "type": "string",
                    "description": (
                        "Google Ads geo target constant ID. Defaults to "
                        "'2392' (Japan). Common values: '2840' United "
                        "States, '2826' United Kingdom, '2276' Germany."
                    ),
                },
            },
            "required": ["seed_keywords"],
        },
    ),
    Tool(
        name="google_ads.keywords.diagnose",
        description=(
            "Reports quality-score and delivery-status issues across every "
            "keyword in a campaign. Returns keywords grouped by severity — "
            "LOW_QUALITY_SCORE (< 5/10), BELOW_FIRST_PAGE_BID, RARELY_SHOWN, "
            "DISAPPROVED — each with criterion_id, text, ad_group_id, and "
            "a remediation hint (raise bid, tighten match type, etc.). "
            "Read-only. Use this before pulling raw search-terms reports; "
            "it triages where attention should go."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign whose keywords to diagnose. Diagnosis "
                        "runs across all ad groups under this campaign."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Negative Keywords ===
    Tool(
        name="google_ads.negative_keywords.list",
        description=(
            "Lists campaign-level negative keyword criteria for a single "
            "campaign. Returns criterion_id, text, and match_type per "
            "entry. Read-only. Ad group-level negatives are not included "
            "here — they live on the ad group and are managed through "
            "google_ads.negative_keywords.add_to_ad_group."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID whose negatives to list.",
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.negative_keywords.add",
        description=(
            "Adds one or more campaign-level negative keywords. These "
            "apply to every ad group in the campaign. Returns created "
            "criterion_ids. Mutating, reversible via rollback.apply. For "
            "negatives scoped to a single ad group use "
            "google_ads.negative_keywords.add_to_ad_group instead — "
            "campaign-level negatives can over-block if applied too broadly."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign that will receive the negatives. The "
                        "negatives apply to all ad groups under this "
                        "campaign."
                    ),
                },
                "keywords": {
                    "type": "array",
                    "items": _KEYWORD_ITEM_SCHEMA,
                    "minItems": 1,
                    "description": (
                        "Negative keywords to add. Each item has `text` "
                        "and optional `match_type` (BROAD / PHRASE / "
                        "EXACT; EXACT is the safest for narrow exclusions)."
                    ),
                },
            },
            "required": ["campaign_id", "keywords"],
        },
    ),
    # === Keyword pause ===
    Tool(
        name="google_ads.keywords.pause",
        description=(
            "Sets the status of a single keyword criterion to PAUSED. "
            "Lightweight and non-destructive — quality score and historical "
            "stats are preserved, and the keyword can be resumed by "
            "calling google_ads.keywords.add with the same text+match_type "
            "(or re-enabled via the Google Ads UI). Returns the criterion "
            "ID and new status. Reversible via rollback.apply. Use this "
            "instead of google_ads.keywords.remove whenever the suspension "
            "might be temporary."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": "Parent ad group ID.",
                },
                "criterion_id": {
                    "type": "string",
                    "description": (
                        "Keyword criterion ID as returned by "
                        "google_ads.keywords.list."
                    ),
                },
            },
            "required": ["ad_group_id", "criterion_id"],
        },
    ),
    # === Negative keyword removal ===
    Tool(
        name="google_ads.negative_keywords.remove",
        description=(
            "Removes a single campaign-level negative keyword. Returns the "
            "removed criterion_id. Destructive — the exclusion is lifted "
            "immediately on the next serving cycle, which can increase "
            "unwanted traffic. Reversible via rollback.apply (re-adds the "
            "negative). For ad group-level negatives there is currently no "
            "explicit remove tool — use the Google Ads UI or raise an "
            "issue if needed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign ID the negative belongs to."
                    ),
                },
                "criterion_id": {
                    "type": "string",
                    "description": (
                        "Negative-keyword criterion ID as returned by "
                        "google_ads.negative_keywords.list."
                    ),
                },
            },
            "required": ["campaign_id", "criterion_id"],
        },
    ),
    # === Ad group-level negative keyword addition ===
    Tool(
        name="google_ads.negative_keywords.add_to_ad_group",
        description=(
            "Adds one or more ad group-level negative keywords. Scope is "
            "narrower than campaign-level negatives — exclusions apply only "
            "to the specified ad group. Returns created criterion_ids. "
            "Mutating, reversible via rollback.apply. Prefer this over "
            "google_ads.negative_keywords.add when the exclusion is only "
            "wrong in one ad group's context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Ad group that will receive the negatives. "
                        "Exclusions do not cascade to sibling ad groups."
                    ),
                },
                "keywords": {
                    "type": "array",
                    "items": _KEYWORD_ITEM_SCHEMA,
                    "minItems": 1,
                    "description": (
                        "Negative keywords to add. Each item has `text` "
                        "and optional `match_type` (BROAD / PHRASE / "
                        "EXACT)."
                    ),
                },
            },
            "required": ["ad_group_id", "keywords"],
        },
    ),
    # === Automatic negative keyword suggestions ===
    Tool(
        name="google_ads.negative_keywords.suggest",
        description=(
            "Analyses recent search-term performance and returns suggested "
            "negative keywords that waste spend relative to a target CPA. "
            "Returns candidates with text, suggested match_type, spend, "
            "conversions, and rationale (e.g. 'spend > 3x target CPA, 0 "
            "conversions'). Read-only — suggestions are not applied. Use "
            "google_ads.negative_keywords.add / add_to_ad_group to "
            "materialize the ones you want after operator review."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign whose search terms are analysed."
                    ),
                },
                "period": {
                    "type": "string",
                    "description": (
                        "Analysis window. Accepts Google Ads predefined "
                        "ranges ('LAST_7_DAYS', 'LAST_14_DAYS', "
                        "'LAST_30_DAYS' — default 'LAST_30_DAYS') or "
                        "explicit 'YYYY-MM-DD..YYYY-MM-DD'."
                    ),
                },
                "target_cpa": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "Target CPA in the account's currency. Search "
                        "terms whose effective CPA exceeds this are "
                        "flagged. If omitted, the campaign's configured "
                        "target_cpa is used when available."
                    ),
                },
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Restrict analysis to a single ad group. Omit to "
                        "analyse the whole campaign."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Keyword Inventory ===
    Tool(
        name="google_ads.keywords.audit",
        description=(
            "Runs a holistic keyword-portfolio audit for a campaign and "
            "returns grouped recommendations: pause candidates (zero-spend "
            "or zero-conversion), bid-raise candidates (below first-page "
            "bid), match-type-tighten candidates (broad stealing spend), "
            "and unused keyword-planner ideas. Each item includes "
            "criterion_id, text, spend, conversions, and a reason string. "
            "Read-only — recommendations are not applied. Materialize "
            "accepted ones via google_ads.keywords.pause / add / "
            "negative_keywords.add."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign to audit.",
                },
                "period": {
                    "type": "string",
                    "description": (
                        "Analysis window. Accepts 'LAST_7_DAYS', "
                        "'LAST_14_DAYS', 'LAST_30_DAYS' (default), or "
                        "'YYYY-MM-DD..YYYY-MM-DD'."
                    ),
                },
                "target_cpa": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "Target CPA in the account's currency used to "
                        "score efficiency. Falls back to the campaign's "
                        "configured target_cpa when omitted."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    # === Cross-ad-group keyword duplicate detection ===
    Tool(
        name="google_ads.keywords.cross_adgroup_duplicates",
        description=(
            "Finds the same text+match_type keyword appearing across "
            "multiple ad groups in a campaign. Returns groups of duplicate "
            "criteria with per-ad-group spend, conversions, and quality "
            "score, plus a consolidation recommendation (which copy to "
            "keep, which to pause/remove). Read-only. Duplicates compete "
            "in the auction and hurt aggregate quality score — run this "
            "before a keyword restructuring sprint."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign to scan for duplicates.",
                },
                "period": {
                    "type": "string",
                    "description": (
                        "Analysis window used to compute per-copy spend "
                        "and conversions. Accepts 'LAST_7_DAYS', "
                        "'LAST_14_DAYS', 'LAST_30_DAYS' (default), or "
                        "'YYYY-MM-DD..YYYY-MM-DD'."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
]
