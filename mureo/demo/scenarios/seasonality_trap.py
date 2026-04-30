"""The "Seasonality Trap" demo scenario — FlavorBox D2C cosmetics.

A small Japanese D2C cosmetics brand spending ~JPY 8M / month across
Google Ads + Meta. On Day 22 of the period, a Shopify migration
silently broke the Meta Pixel — the conversion event still fires but
the deduplicated server-side / browser path drops ~65% of conversions.
The marketing manager interpreted the resulting CPA spike as Q1
seasonality and made three escalating bidding decisions over the next
25 days, all of which made the situation worse:

  Day 25 — Bumped Meta budget +40% to "maintain volume"
  Day 35 — Paused the Awareness Carousel ("worst CPA")
  Day 50 — Paused the Lead Form ad ("still climbing")

The "wow" the demo is designed to deliver: mureo identifies that
Meta-only CPA spiked while Google CPA stayed flat — a tracking-break
signature, not a bidding problem. It also surfaces a hidden winner
("Sample Box - Free Shipping") whose pre-Day-22 results were the
strongest in the account, and a Google Ads search term
"敏感肌 化粧水 おすすめ" with CVR ~3.5x the surrounding ad group.

All numbers are deterministic — re-running ``mureo demo init`` on the
same scenario produces an identical bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from mureo.demo.scenarios._base import Scenario, campaign_id

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_NAME = "seasonality-trap"
_TITLE = "The Seasonality Trap (FlavorBox / D2C cosmetics)"
_BLURB = (
    "Meta CPA spike misdiagnosed as seasonal demand drop — three escalating "
    "bidding actions in 25 days made it worse. Real cause: pixel break on "
    "Day 22 of a Shopify migration. mureo connects the dots and surfaces "
    "a hidden winner ad."
)
_DAYS = 90
_END_DATE = date(2026, 4, 29)
_BRAND = "FlavorBox"

# Day 22 = pixel break onset. Days are 0-indexed from the start of the
# 90-day period (Day 0 = end_date - 89 days).
_PIXEL_BREAK_DAY = 22
_PIXEL_FACTOR_PRE = 1.0
_PIXEL_FACTOR_POST = 0.20  # ~80% of conversions silently lost
# Tuned so post-break Meta blended CPA lands roughly 5x the
# (constant) Google blended CPA — that's the visual signature mureo's
# diagnosis hinges on, and a smaller drop wouldn't be dramatic enough
# to plausibly drive a manager's three escalating reactions.

# Action timeline — must match the action_log timestamps below so the
# demo data and STATE.json action history tell a single coherent story.
_ACTION_BUDGET_BUMP_DAY = 25  # +40% Meta budget
_ACTION_PAUSE_AWARENESS_DAY = 35  # Awareness Carousel paused
_ACTION_PAUSE_LEAD_FORM_DAY = 50  # Lead Form paused


def _days_iso() -> list[str]:
    return [
        (_END_DATE - timedelta(days=_DAYS - 1 - i)).isoformat() for i in range(_DAYS)
    ]


def _date_for_day(d: int) -> date:
    return _END_DATE - timedelta(days=_DAYS - 1 - d)


# ---------------------------------------------------------------------------
# Google Ads — stable throughout the period
# ---------------------------------------------------------------------------
#
# Google's conversion tracking is unaffected by the Shopify pixel
# break (Google has its own gtag/conversions infrastructure). This is
# the platform divergence mureo's diagnosis hinges on.

_GADS_CAMPAIGNS = (
    # name, daily_impr, ctr, cpc_jpy, cvr
    ("Brand - Exact", 600, 0.22, 60.0, 0.12),
    ("Generic - Sensitive Skin", 5000, 0.04, 150.0, 0.05),
    ("Generic - Discovery", 8000, 0.025, 175.0, 0.030),
    ("Retargeting - Search", 1500, 0.08, 225.0, 0.14),
)

# Each ad group: (parent_campaign, ad_group_name, share_of_campaign)
_GADS_AD_GROUPS = (
    ("Brand - Exact", "Brand - Exact", 1.0),
    ("Generic - Sensitive Skin", "Sensitive Skin Care", 0.65),
    ("Generic - Sensitive Skin", "Sensitive Skin Discovery", 0.35),
    ("Generic - Discovery", "Cosmetic Reviews", 0.55),
    ("Generic - Discovery", "First-Time Buyers", 0.45),
    ("Retargeting - Search", "Cart Abandoners", 1.0),
)

# Search terms — aggregated, no daily breakdown. Includes the HIDDEN
# WINNER ("敏感肌 化粧水 おすすめ"): CVR ~11% in an ad group whose
# average is ~5%, a 2x outlier worth promoting to its own campaign.
_GADS_SEARCH_TERMS = (
    # search_term, campaign, ad_group, impressions, clicks, cost_jpy, conversions
    ("flavorbox", "Brand - Exact", "Brand - Exact", 32000, 7040, 422400, 985),
    ("flavorbox 敏感肌", "Brand - Exact", "Brand - Exact", 8400, 2100, 126000, 273),
    ("flavorbox クーポン", "Brand - Exact", "Brand - Exact", 4200, 1050, 63000, 105),
    ("flavorbox 評判", "Brand - Exact", "Brand - Exact", 3600, 900, 54000, 81),
    # HIDDEN WINNER — high CVR vs ad-group average.
    (
        "敏感肌 化粧水 おすすめ",
        "Generic - Sensitive Skin",
        "Sensitive Skin Care",
        18000,
        720,
        108000,
        79,
    ),
    (
        "敏感肌 化粧水",
        "Generic - Sensitive Skin",
        "Sensitive Skin Care",
        85000,
        3400,
        510000,
        170,
    ),
    (
        "low irritation foundation",
        "Generic - Sensitive Skin",
        "Sensitive Skin Discovery",
        24000,
        960,
        144000,
        43,
    ),
    (
        "敏感肌 ファンデーション",
        "Generic - Sensitive Skin",
        "Sensitive Skin Discovery",
        62000,
        2480,
        372000,
        99,
    ),
    (
        "おすすめ コスメ 30代",
        "Generic - Discovery",
        "Cosmetic Reviews",
        96000,
        2400,
        420000,
        72,
    ),
    (
        "化粧品 比較",
        "Generic - Discovery",
        "Cosmetic Reviews",
        140000,
        3500,
        612500,
        88,
    ),
    (
        "コスメ 安い",
        "Generic - Discovery",
        "Cosmetic Reviews",
        180000,
        4500,
        787500,
        45,
    ),
    (
        "化粧品 初めて",
        "Generic - Discovery",
        "First-Time Buyers",
        48000,
        1200,
        210000,
        36,
    ),
    (
        "おすすめ ファンデーション",
        "Generic - Discovery",
        "First-Time Buyers",
        85000,
        2125,
        371875,
        72,
    ),
    (
        "flavorbox レビュー",
        "Retargeting - Search",
        "Cart Abandoners",
        12000,
        960,
        216000,
        134,
    ),
    (
        "flavorbox 解約",
        "Retargeting - Search",
        "Cart Abandoners",
        4500,
        360,
        81000,
        43,
    ),
)

# Keyword inventory — passthrough, also aggregated.
_GADS_KEYWORDS = (
    # keyword, match_type, quality_score, campaign, ad_group, impressions, clicks, cost_jpy, conversions
    (
        "[flavorbox]",
        "EXACT",
        10,
        "Brand - Exact",
        "Brand - Exact",
        38600,
        8492,
        509520,
        1188,
    ),
    (
        "敏感肌 化粧水",
        "PHRASE",
        8,
        "Generic - Sensitive Skin",
        "Sensitive Skin Care",
        108000,
        4320,
        648000,
        249,
    ),
    (
        "low irritation foundation",
        "PHRASE",
        7,
        "Generic - Sensitive Skin",
        "Sensitive Skin Discovery",
        86000,
        3440,
        516000,
        142,
    ),
    (
        "おすすめ コスメ",
        "PHRASE",
        6,
        "Generic - Discovery",
        "Cosmetic Reviews",
        252000,
        6300,
        1102500,
        205,
    ),
    (
        "化粧品 初めて",
        "PHRASE",
        7,
        "Generic - Discovery",
        "First-Time Buyers",
        140000,
        3500,
        612500,
        108,
    ),
    (
        '"flavorbox"',
        "PHRASE",
        9,
        "Retargeting - Search",
        "Cart Abandoners",
        16500,
        1320,
        297000,
        177,
    ),
    (
        "flavorbox レビュー",
        "PHRASE",
        9,
        "Retargeting - Search",
        "Cart Abandoners",
        13500,
        1080,
        243000,
        151,
    ),
    (
        "化粧品 比較",
        "PHRASE",
        6,
        "Generic - Discovery",
        "Cosmetic Reviews",
        140000,
        3500,
        612500,
        88,
    ),
)


def _build_google_campaigns_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        ["day", "campaign", "impressions", "clicks", "cost", "conversions"]
    ]
    days = _days_iso()
    for name, base_impr, ctr, cpc, cvr in _GADS_CAMPAIGNS:
        for d in days:
            clicks = int(round(base_impr * ctr))
            cost = round(clicks * cpc, 2)
            conv = round(clicks * cvr, 2)
            rows.append([d, name, base_impr, clicks, cost, conv])
    return rows


def _build_google_ad_groups_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        [
            "day",
            "campaign",
            "ad_group",
            "impressions",
            "clicks",
            "cost",
            "conversions",
        ]
    ]
    by_campaign = {c[0]: c for c in _GADS_CAMPAIGNS}
    days = _days_iso()
    for camp_name, ag_name, share in _GADS_AD_GROUPS:
        _, base_impr, ctr, cpc, cvr = by_campaign[camp_name]
        for d in days:
            impr = int(round(base_impr * share))
            clicks = int(round(impr * ctr))
            cost = round(clicks * cpc, 2)
            conv = round(clicks * cvr, 2)
            rows.append([d, camp_name, ag_name, impr, clicks, cost, conv])
    return rows


def _build_google_search_terms_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        [
            "search_term",
            "campaign",
            "ad_group",
            "impressions",
            "clicks",
            "cost",
            "conversions",
        ]
    ]
    for term, camp, ag, impr, clicks, cost, conv in _GADS_SEARCH_TERMS:
        rows.append([term, camp, ag, impr, clicks, cost, conv])
    return rows


def _build_google_keywords_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        [
            "keyword",
            "match_type",
            "quality_score",
            "campaign",
            "ad_group",
            "impressions",
            "clicks",
            "cost",
            "conversions",
        ]
    ]
    for kw, mt, qs, camp, ag, impr, clicks, cost, conv in _GADS_KEYWORDS:
        rows.append([kw, mt, qs, camp, ag, impr, clicks, cost, conv])
    return rows


# ---------------------------------------------------------------------------
# Meta Ads — phased: pixel break + 3 escalating actions
# ---------------------------------------------------------------------------
#
# Each Meta ad has 5 phases. ``daily_spend`` reflects the manager's
# escalating reactions; ``pixel_factor`` reflects the broken tracking.
# ``ctr`` and ``cpc`` are constant per ad — only spend redistribution
# and the results column move.


@dataclass(frozen=True)
class _MetaAdSpec:
    """Per-ad demo spec for the Meta Ads Manager export.

    ``spend`` is indexed by phase 0..4 (see :func:`_phase_for_day`).
    A 0 entry means "paused this phase — omit the row entirely".
    """

    ad: str
    campaign: str
    adset: str
    ctr: float
    cpc: int
    rpc: float
    spend: tuple[int, int, int, int, int]


_META_ADS: tuple[_MetaAdSpec, ...] = (
    # rpc values are 0.4x the per-ad raw funnel rate, scaled so that
    # pre-break blended Meta CPA lands near Google's JPY ~2,050 — the
    # demo only "lands" if Meta and Google look comparable BEFORE the
    # pixel break, then diverge sharply after.
    _MetaAdSpec(
        ad="Carousel - Skincare Lineup",
        campaign="Awareness - Carousel",
        adset="JP 25-44 Female",
        ctr=0.013,
        cpc=90,
        rpc=0.020,
        spend=(50000, 50000, 70000, 0, 0),
    ),
    _MetaAdSpec(
        ad="Image - Lookalike Skincare 1pct",
        campaign="Conversion - Lookalike Skincare",
        adset="LAL 1% Skincare Buyers",
        ctr=0.016,
        cpc=130,
        rpc=0.036,
        spend=(60000, 60000, 84000, 120000, 145000),
    ),
    _MetaAdSpec(
        ad="Video - Sample Box Free Shipping",
        campaign="Conversion - Sample Box",
        adset="Cold JP Female 25-44",
        ctr=0.024,
        cpc=95,
        rpc=0.072,
        spend=(40000, 40000, 56000, 80000, 95000),
    ),
    _MetaAdSpec(
        ad="Image - Waitlist Lead Form",
        campaign="Lead Form - Waitlist",
        adset="Engaged Followers",
        ctr=0.015,
        cpc=110,
        rpc=0.120,
        spend=(20000, 20000, 28000, 40000, 0),
    ),
)


def _meta_metrics_window(
    end_day_inclusive: int, *, window: int = 3
) -> tuple[int, float]:
    """Compute (blended_cpa, results_per_day) for Meta over a window.

    The window includes ``end_day_inclusive`` and the ``window - 1``
    days preceding it, clamped to day 0. Used so the action_log's
    ``metrics_at_action`` can be derived from the same arithmetic that
    builds the bundle rows — hand-written numbers would drift the
    moment a single ``rpc`` or ``cpc`` is tweaked.
    """
    start = max(0, end_day_inclusive - window + 1)
    total_spend = 0
    total_results = 0.0
    for d in range(start, end_day_inclusive + 1):
        phase = _phase_for_day(d)
        pf = _pixel_factor(d)
        for ad in _META_ADS:
            spend = ad.spend[phase]
            if spend == 0:
                continue
            clicks = int(round(spend / ad.cpc))
            results = round(clicks * ad.rpc * pf, 1)
            total_spend += spend
            total_results += results
    days = end_day_inclusive - start + 1
    if total_results <= 0:
        return (0, 0.0)
    return (
        int(round(total_spend / total_results)),
        round(total_results / days, 1),
    )


# Google blended CPA is constant by construction (no phases, no
# pixel-break analog), so we hardcode it from the same arithmetic the
# row builder uses. If you change ``_GADS_CAMPAIGNS`` math, recompute.
_GOOGLE_CPA_BASELINE = 2050


def _phase_for_day(d: int) -> int:
    """Return phase index 0..4 for day ``d``."""
    if d < _PIXEL_BREAK_DAY:
        return 0  # PHASE_A: pre-pixel-break, healthy
    if d < _ACTION_BUDGET_BUMP_DAY:
        return 1  # PHASE_B: pixel just broke, no action yet
    if d < _ACTION_PAUSE_AWARENESS_DAY:
        return 2  # PHASE_C: budget +40%
    if d < _ACTION_PAUSE_LEAD_FORM_DAY:
        return 3  # PHASE_D: Awareness paused, others scaled up
    return 4  # PHASE_E: Lead Form also paused


def _pixel_factor(d: int) -> float:
    return _PIXEL_FACTOR_PRE if d < _PIXEL_BREAK_DAY else _PIXEL_FACTOR_POST


def _build_meta_ads_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        [
            "Day",
            "Campaign name",
            "Ad set name",
            "Ad name",
            "Impressions",
            "Clicks (all)",
            "Amount spent (JPY)",
            "Results",
        ]
    ]
    for d in range(_DAYS):
        phase = _phase_for_day(d)
        pf = _pixel_factor(d)
        date_iso = _date_for_day(d).isoformat()
        for ad in _META_ADS:
            spend = ad.spend[phase]
            if spend == 0:
                # Paused ad: omit the row entirely so the export
                # mirrors a real Ads Manager export, which simply
                # leaves paused-day rows out rather than emitting
                # zero-spend rows.
                continue
            clicks = int(round(spend / ad.cpc))
            impressions = int(round(clicks / ad.ctr))
            results = round(clicks * ad.rpc * pf, 1)
            rows.append(
                [
                    date_iso,
                    ad.campaign,
                    ad.adset,
                    ad.ad,
                    impressions,
                    clicks,
                    spend,
                    results,
                ]
            )
    return rows


# ---------------------------------------------------------------------------
# STATE.json — current platform state + action_log
# ---------------------------------------------------------------------------


_GOOGLE_ADS_STATE_CAMPAIGNS = (
    {
        "campaign_id": campaign_id("Brand - Exact"),
        "campaign_name": "Brand - Exact",
        "status": "ENABLED",
        "daily_budget": 10000,
        "campaign_goal": (
            "Capture branded demand at high efficiency (target CPA <= JPY 800)."
        ),
    },
    {
        "campaign_id": campaign_id("Generic - Sensitive Skin"),
        "campaign_name": "Generic - Sensitive Skin",
        "status": "ENABLED",
        "daily_budget": 35000,
        "campaign_goal": ("Acquire net-new sensitive-skin buyers at <= JPY 4,500 CPA."),
    },
    {
        "campaign_id": campaign_id("Generic - Discovery"),
        "campaign_name": "Generic - Discovery",
        "status": "ENABLED",
        "daily_budget": 40000,
        "campaign_goal": "Top-of-funnel cosmetics demand; target CPA <= JPY 6,000.",
    },
    {
        "campaign_id": campaign_id("Retargeting - Search"),
        "campaign_name": "Retargeting - Search",
        "status": "ENABLED",
        "daily_budget": 30000,
        "campaign_goal": "Re-engage cart abandoners at <= JPY 2,500 CPA.",
    },
)

_META_ADS_STATE_CAMPAIGNS = (
    {
        "campaign_id": campaign_id("Awareness - Carousel"),
        "campaign_name": "Awareness - Carousel",
        "status": "PAUSED",
        "daily_budget": 50000,
        "campaign_goal": (
            "Top-of-funnel awareness; paused on Day 35 by manager (see action_log)."
        ),
    },
    {
        "campaign_id": campaign_id("Conversion - Lookalike Skincare"),
        "campaign_name": "Conversion - Lookalike Skincare",
        "status": "ENABLED",
        "daily_budget": 145000,
        "campaign_goal": (
            "Acquire skincare-LAL converters at <= JPY 4,500 cost-per-result."
        ),
    },
    {
        "campaign_id": campaign_id("Conversion - Sample Box"),
        "campaign_name": "Conversion - Sample Box",
        "status": "ENABLED",
        "daily_budget": 95000,
        "campaign_goal": ("Drive Sample Box requests at <= JPY 1,200 cost-per-result."),
    },
    {
        "campaign_id": campaign_id("Lead Form - Waitlist"),
        "campaign_name": "Lead Form - Waitlist",
        "status": "PAUSED",
        "daily_budget": 20000,
        "campaign_goal": (
            "Build waitlist; paused on Day 50 by manager (see action_log)."
        ),
    },
)


def _action_iso(day: int, hour: int = 10, minute: int = 0) -> str:
    """Build a ``YYYY-MM-DDTHH:MM:SS+09:00`` timestamp for ``day``."""
    d = _date_for_day(day)
    dt = datetime(
        d.year, d.month, d.day, hour, minute, tzinfo=timezone(timedelta(hours=9))
    )
    return dt.isoformat(timespec="seconds")


# Derive each action's metrics from the same row arithmetic the
# bundle uses. ``end_day_inclusive`` is the day BEFORE the action so
# the snapshot reflects what the manager was looking at when they
# made the call, not the post-action numbers.
_a1_meta_cpa, _a1_meta_rpd = _meta_metrics_window(_ACTION_BUDGET_BUMP_DAY - 1)
_a2_meta_cpa, _a2_meta_rpd = _meta_metrics_window(_ACTION_PAUSE_AWARENESS_DAY - 1)
_a3_meta_cpa, _a3_meta_rpd = _meta_metrics_window(_ACTION_PAUSE_LEAD_FORM_DAY - 1)


_ACTION_LOG = (
    {
        "timestamp": _action_iso(_ACTION_BUDGET_BUMP_DAY, 10, 0),
        "action": (
            "Increased Meta total budget by +40% across all Awareness "
            "and Conversion ads"
        ),
        "platform": "meta_ads",
        "campaign_id": None,
        "summary": (
            "Hypothesis: rising Meta CPA is competitive seasonality. Doubled "
            "down to maintain volume. (Manual action — pre-mureo.)"
        ),
        "metrics_at_action": {
            "meta_cpa_apparent": _a1_meta_cpa,
            "meta_results_per_day": _a1_meta_rpd,
            "google_cpa": _GOOGLE_CPA_BASELINE,
        },
        "observation_due": _date_for_day(_ACTION_BUDGET_BUMP_DAY + 9).isoformat(),
    },
    {
        "timestamp": _action_iso(_ACTION_PAUSE_AWARENESS_DAY, 14, 30),
        "action": "Paused Awareness - Carousel campaign",
        "platform": "meta_ads",
        "campaign_id": campaign_id("Awareness - Carousel"),
        "summary": (
            "Apparent worst CPA after the budget bump; cleaned out the "
            "perceived underperformer. Lookalike Skincare and Sample Box "
            "kept running. (Manual action — pre-mureo.)"
        ),
        "metrics_at_action": {
            "meta_cpa_apparent": _a2_meta_cpa,
            "meta_results_per_day": _a2_meta_rpd,
            "google_cpa": _GOOGLE_CPA_BASELINE,
        },
        "observation_due": _date_for_day(_ACTION_PAUSE_AWARENESS_DAY + 14).isoformat(),
    },
    {
        "timestamp": _action_iso(_ACTION_PAUSE_LEAD_FORM_DAY, 11, 0),
        "action": "Paused Lead Form - Waitlist campaign",
        "platform": "meta_ads",
        "campaign_id": campaign_id("Lead Form - Waitlist"),
        "summary": (
            "Despite both prior actions, Meta CPA still climbing. Cutting "
            "more ads. (Manual action — pre-mureo. Three escalating cuts "
            "in 25 days have not bent the curve.)"
        ),
        "metrics_at_action": {
            "meta_cpa_apparent": _a3_meta_cpa,
            "meta_results_per_day": _a3_meta_rpd,
            "google_cpa": _GOOGLE_CPA_BASELINE,
        },
        "observation_due": _date_for_day(_ACTION_PAUSE_LEAD_FORM_DAY + 14).isoformat(),
    },
)


_LAST_SYNCED_AT = datetime.combine(
    _END_DATE, datetime.min.time(), tzinfo=timezone.utc
).isoformat(timespec="seconds")


_STATE_DOC: Mapping[str, object] = {
    "version": "2",
    "last_synced_at": _LAST_SYNCED_AT,
    "platforms": {
        "google_ads": {
            "account_id": "demo-flavorbox-google-ads",
            "campaigns": list(_GOOGLE_ADS_STATE_CAMPAIGNS),
        },
        "meta_ads": {
            "account_id": "demo-flavorbox-meta-ads",
            "campaigns": list(_META_ADS_STATE_CAMPAIGNS),
        },
    },
    "action_log": list(_ACTION_LOG),
}


# ---------------------------------------------------------------------------
# STRATEGY.md — explicit numeric goals and constraints so workflow
# skills can detect deviations.
# ---------------------------------------------------------------------------

_STRATEGY_MD = """# STRATEGY — FlavorBox (demo: Seasonality Trap)

> Synthetic D2C cosmetics scenario shipped with `mureo demo init --scenario seasonality-trap`.
> Replace with your real strategy when you switch to a live account.

## Business
- **Brand:** FlavorBox
- **Vertical:** D2C cosmetics, sensitive-skin-positioned
- **ICP:** JP women 25-44, first-time premium-cosmetics buyers
- **AOV:** ~JPY 6,800 first order, ~JPY 4,200 sample box
- **Total ad budget:** ~JPY 8M / month (Google + Meta)

## Quarterly goals
- **Blended CPA <= JPY 4,500** across Google + Meta conversion campaigns
- **Sample Box requests >= 1,200 / month** (top-of-funnel growth signal)
- **Brand-search CTR >= 18%** (brand health proxy)
- **Blended ROAS >= 1.6x** at 90-day attribution window

## Channel mix
- **Google Ads:** Brand - Exact, Generic - Sensitive Skin, Generic - Discovery, Retargeting - Search
- **Meta Ads:** Awareness Carousel (top), Lookalike Skincare + Sample Box (mid), Lead Form Waitlist (bottom)

## Operation Mode
**MAINTAIN** — Q1-Q2 is steady-state. No major launches planned.

## Constraints
- **Tracking integrity is non-negotiable.** Before increasing spend on any platform, verify that
  conversion-event volume is consistent with click volume. A platform showing CPA divergence
  from its sibling channel by >= 50% in a 7-day window must be diagnosed before more budget
  is committed.
- **No competitor-name bidding** on either platform.
- **Pause-then-diagnose** before pause-then-replace: paused campaigns should be re-enabled, not
  cut from inventory, until root cause is established.
"""


# ---------------------------------------------------------------------------
# Public scenario instance
# ---------------------------------------------------------------------------


_SHEET_ROWS: Mapping[str, Sequence[Sequence[object]]] = {
    "campaigns": _build_google_campaigns_rows(),
    "ad_groups": _build_google_ad_groups_rows(),
    "search_terms": _build_google_search_terms_rows(),
    "keywords": _build_google_keywords_rows(),
    "meta_ads": _build_meta_ads_rows(),
}


SCENARIO = Scenario(
    name=_NAME,
    title=_TITLE,
    blurb=_BLURB,
    days=_DAYS,
    end_date=_END_DATE,
    brand=_BRAND,
    sheet_rows=_SHEET_ROWS,
    state_doc=_STATE_DOC,
    strategy_md=_STRATEGY_MD,
)
