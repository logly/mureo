"""The "Strategy Drift" demo scenario — PulseFit fitness app subscription.

A subscription-based fitness app running ~JPY 5M / month. STRATEGY.md
explicitly forbids three things, codified after past lessons:

  1. No competitor-name bidding on either platform
  2. Conversion campaigns optimize for "Subscribed" (paid signup),
     never for "Started trial" (LTV signal is too thin on trials)
  3. Meta Lookalike stack capped at 3 active variants (audience
     overlap collapses CTR past that point)

A new growth manager joined on Day 30 and made three changes
without logging them — each one violates exactly one of the rules
above:

  Day 30 — Launched a "Competitor Names" Google campaign targeting
           rivals' brand terms (violates rule 1)
  Day 45 — Switched Meta Conversion campaigns from "Subscribed" to
           "7-day trial" optimization (violates rule 2). Apparent CV
           count surges, downstream trial-to-paid rate collapses.
  Day 60 — Added LAL 4%, 7%, 10% on top of the existing 1%, 2%, 5%
           stack (violates rule 3). Frequency rises, CTR drops.

action_log around these changes is empty. That silence is itself a
signal: STRATEGY.md says all actions must be logged.

The "wow": mureo's STRATEGY-vs-STATE compliance audit reads each
constraint, walks STATE.json campaigns, and produces a list of
violations with start dates and JPY-impact estimates. None of these
are reachable through ordinary metric dashboards because each
violation is paired with a *better-looking* surface metric (apparent
CPA improvement, trial-volume uplift, "more LAL = more reach").

Detection caveat: rule 1 (competitor-name campaign) and rule 3 (LAL
stack > 3) are detectable from the bundle data alone (campaign /
ad-set name patterns). Rule 2 (optimization-target swap) is not —
the conversion-event label is not a CSV column; only the Day-45 rpc
jump is observable, which could equally be a creative refresh. The
audit relies on STATE.json ``campaign_goal`` text to make rule 2
machine-detectable. In a real account that text would come from the
agent's own log of optimization-target changes; for the demo it is
pre-seeded.

All numbers deterministic; re-running ``mureo demo init`` produces
an identical bundle.
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

_NAME = "strategy-drift"
_TITLE = "Strategy Drift (PulseFit / Fitness app subscription)"
_BLURB = (
    "New manager since Day 30 silently violated 3 explicit STRATEGY rules "
    "(competitor bidding, optimization-target swap, LAL stack >3). "
    "action_log empty — that silence is itself the signal. mureo's "
    "compliance audit produces a violation list with start dates and JPY impact."
)
_DAYS = 90
_END_DATE = date(2026, 4, 29)
_BRAND = "PulseFit"

# Violation timeline
_VIOLATION_COMPETITOR_DAY = 30  # rule 1: competitor-name campaign launched
_VIOLATION_OPTIMIZATION_SWAP_DAY = 45  # rule 2: conversion event changed
_VIOLATION_LAL_STACK_DAY = 60  # rule 3: LAL 4%/7%/10% added


def _date_for_day(d: int) -> date:
    return _END_DATE - timedelta(days=_DAYS - 1 - d)


# ---------------------------------------------------------------------------
# Google Ads — 4 baseline campaigns + 1 violating "Competitor Names"
# (the violator is ENABLED from Day 30 onward, zero before that)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GAdsCampaignSpec:
    name: str
    daily_impr: int
    ctr: float
    cpc: float
    cvr: float
    start_day: int = 0  # 0 = active from Day 0


_GADS_CAMPAIGNS = (
    _GAdsCampaignSpec("Brand - Exact", 600, 0.22, 90.0, 0.18),
    _GAdsCampaignSpec("Generic - Fitness Apps", 4000, 0.04, 220.0, 0.06),
    _GAdsCampaignSpec("Generic - Workout Plans", 5500, 0.03, 180.0, 0.045),
    _GAdsCampaignSpec("Retargeting - App Visitors", 1000, 0.10, 150.0, 0.12),
    # *** STRATEGY VIOLATION (rule 1) — competitor-name bidding ***
    # Active only from Day 30 (the new manager's launch day).
    _GAdsCampaignSpec(
        "Competitor Names",
        2400,
        0.025,
        380.0,
        0.012,
        start_day=_VIOLATION_COMPETITOR_DAY,
    ),
)


_GADS_AD_GROUPS = (
    ("Brand - Exact", "Brand - Exact - Core", 1.0),
    ("Generic - Fitness Apps", "Fitness App General", 0.55),
    ("Generic - Fitness Apps", "Workout Tracker", 0.45),
    ("Generic - Workout Plans", "Beginner Workouts", 0.50),
    ("Generic - Workout Plans", "Home Workouts", 0.50),
    ("Retargeting - App Visitors", "Site Visitors 30d", 1.0),
    # Competitor Names ad group is only present in Days 30-89
    ("Competitor Names", "Rival Brand Terms", 1.0),
)


_GADS_SEARCH_TERMS = (
    # Brand - Exact
    ("pulsefit", "Brand - Exact", "Brand - Exact - Core", 22000, 4840, 435600, 871),
    (
        "pulsefit app",
        "Brand - Exact",
        "Brand - Exact - Core",
        6800,
        1496,
        134640,
        269,
    ),
    (
        "pulsefit subscription",
        "Brand - Exact",
        "Brand - Exact - Core",
        3200,
        704,
        63360,
        127,
    ),
    # Generic - Fitness Apps
    (
        "fitness app japan",
        "Generic - Fitness Apps",
        "Fitness App General",
        62000,
        2480,
        545600,
        149,
    ),
    (
        "best fitness app subscription",
        "Generic - Fitness Apps",
        "Fitness App General",
        38000,
        1520,
        334400,
        91,
    ),
    (
        "workout tracker app",
        "Generic - Fitness Apps",
        "Workout Tracker",
        45000,
        1800,
        396000,
        108,
    ),
    (
        "fitness tracking subscription",
        "Generic - Fitness Apps",
        "Workout Tracker",
        18000,
        720,
        158400,
        43,
    ),
    # Generic - Workout Plans
    (
        "beginner workout plan",
        "Generic - Workout Plans",
        "Beginner Workouts",
        78000,
        2340,
        421200,
        105,
    ),
    (
        "30 day fitness plan",
        "Generic - Workout Plans",
        "Beginner Workouts",
        42000,
        1260,
        226800,
        57,
    ),
    (
        "home workout no equipment",
        "Generic - Workout Plans",
        "Home Workouts",
        88000,
        2640,
        475200,
        119,
    ),
    (
        "home gym workout app",
        "Generic - Workout Plans",
        "Home Workouts",
        34000,
        1020,
        183600,
        46,
    ),
    # Retargeting (healthy)
    (
        "pulsefit free trial",
        "Retargeting - App Visitors",
        "Site Visitors 30d",
        7200,
        720,
        108000,
        86,
    ),
    (
        "pulsefit cancel",
        "Retargeting - App Visitors",
        "Site Visitors 30d",
        2800,
        280,
        42000,
        34,
    ),
    # *** Competitor Names campaign — STRATEGY violation ***
    # Aggregate values reflect 60 days of spend (Day 30-89). Tuned so
    # search-term aggregate clicks (~3840) cover ~107% of the
    # campaign-row total clicks (60 days × 60 clicks/day = 3600), so
    # /search-term-cleanup sees full coverage rather than appearing
    # to be missing query data on this campaign.
    (
        "muscle mate app",  # competitor brand term
        "Competitor Names",
        "Rival Brand Terms",
        72000,
        1800,
        684000,
        22,
    ),
    (
        "fitnow subscription",  # competitor brand term
        "Competitor Names",
        "Rival Brand Terms",
        48000,
        1200,
        456000,
        14,
    ),
    (
        "trainerly app review",  # competitor brand term
        "Competitor Names",
        "Rival Brand Terms",
        33600,
        840,
        319200,
        10,
    ),
)


_GADS_KEYWORDS = (
    (
        "[pulsefit]",
        "EXACT",
        10,
        "Brand - Exact",
        "Brand - Exact - Core",
        32000,
        7040,
        633600,
        1267,
    ),
    (
        "fitness app",
        "PHRASE",
        7,
        "Generic - Fitness Apps",
        "Fitness App General",
        100000,
        4000,
        880000,
        240,
    ),
    (
        "workout tracker",
        "PHRASE",
        7,
        "Generic - Fitness Apps",
        "Workout Tracker",
        63000,
        2520,
        554400,
        151,
    ),
    (
        "beginner workout",
        "PHRASE",
        7,
        "Generic - Workout Plans",
        "Beginner Workouts",
        120000,
        3600,
        648000,
        162,
    ),
    (
        "home workout",
        "PHRASE",
        7,
        "Generic - Workout Plans",
        "Home Workouts",
        122000,
        3660,
        658800,
        165,
    ),
    (
        '"pulsefit"',
        "PHRASE",
        9,
        "Retargeting - App Visitors",
        "Site Visitors 30d",
        10000,
        1000,
        150000,
        120,
    ),
    # *** Competitor brand keywords — VIOLATION ***
    (
        "muscle mate",
        "PHRASE",
        4,
        "Competitor Names",
        "Rival Brand Terms",
        72000,
        1800,
        684000,
        22,
    ),
    (
        "fitnow",
        "PHRASE",
        4,
        "Competitor Names",
        "Rival Brand Terms",
        48000,
        1200,
        456000,
        14,
    ),
)


def _gads_campaign_active(spec: _GAdsCampaignSpec, day: int) -> bool:
    return day >= spec.start_day


def _build_google_campaigns_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        ["day", "campaign", "impressions", "clicks", "cost", "conversions"]
    ]
    for c in _GADS_CAMPAIGNS:
        for d in range(_DAYS):
            if not _gads_campaign_active(c, d):
                continue
            day_iso = _date_for_day(d).isoformat()
            clicks = int(round(c.daily_impr * c.ctr))
            cost = round(clicks * c.cpc, 2)
            conv = round(clicks * c.cvr, 2)
            rows.append([day_iso, c.name, c.daily_impr, clicks, cost, conv])
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
    by_camp = {c.name: c for c in _GADS_CAMPAIGNS}
    for camp_name, ag_name, share in _GADS_AD_GROUPS:
        c = by_camp[camp_name]
        for d in range(_DAYS):
            if not _gads_campaign_active(c, d):
                continue
            day_iso = _date_for_day(d).isoformat()
            impr = int(round(c.daily_impr * share))
            clicks = int(round(impr * c.ctr))
            cost = round(clicks * c.cpc, 2)
            conv = round(clicks * c.cvr, 2)
            rows.append([day_iso, camp_name, ag_name, impr, clicks, cost, conv])
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
# Meta Ads — optimization-target swap on Day 45 + LAL stack expansion Day 60
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MetaAdSpec:
    ad: str
    campaign: str
    adset: str
    ctr: float
    cpc: int
    rpc: float
    daily_spend: int
    start_day: int = 0
    # Day 45+ optimization swap: ``rpc_post_swap`` overrides rpc on
    # the conversion campaign. Reflects "more shallow conversions
    # (trial starts) being counted as Results".
    rpc_post_swap: float | None = None


_META_ADS: tuple[_MetaAdSpec, ...] = (
    # Awareness — unchanged throughout
    _MetaAdSpec(
        ad="Video - Daily Workout Routines",
        campaign="Awareness - Workout Routines",
        adset="JP 25-44 Active",
        ctr=0.014,
        cpc=85,
        rpc=0.04,
        daily_spend=22000,
    ),
    # Conversion - LAL 1% (existing, allowed by rule 3)
    _MetaAdSpec(
        ad="Image - LAL 1% Subscribers",
        campaign="Conversion - Subscription",
        adset="LAL 1% Paid Subscribers",
        ctr=0.018,
        cpc=180,
        rpc=0.06,
        daily_spend=28000,
        rpc_post_swap=0.18,
    ),
    # Conversion - LAL 2% (existing, allowed)
    _MetaAdSpec(
        ad="Image - LAL 2% Subscribers",
        campaign="Conversion - Subscription",
        adset="LAL 2% Paid Subscribers",
        ctr=0.016,
        cpc=200,
        rpc=0.05,
        daily_spend=18000,
        rpc_post_swap=0.16,
    ),
    # Conversion - LAL 5% (existing, allowed — at the cap)
    _MetaAdSpec(
        ad="Image - LAL 5% Subscribers",
        campaign="Conversion - Subscription",
        adset="LAL 5% Paid Subscribers",
        ctr=0.014,
        cpc=220,
        rpc=0.04,
        daily_spend=12000,
        rpc_post_swap=0.14,
    ),
    # *** STRATEGY VIOLATION (rule 3) — LAL stack > 3 ***
    # Added Day 60. Three more LAL ads launched simultaneously.
    _MetaAdSpec(
        ad="Image - LAL 4% Subscribers",
        campaign="Conversion - Subscription",
        adset="LAL 4% Paid Subscribers",
        ctr=0.013,
        cpc=240,
        rpc=0.030,
        daily_spend=8000,
        start_day=_VIOLATION_LAL_STACK_DAY,
        rpc_post_swap=0.10,
    ),
    _MetaAdSpec(
        ad="Image - LAL 7% Subscribers",
        campaign="Conversion - Subscription",
        adset="LAL 7% Paid Subscribers",
        ctr=0.011,
        cpc=260,
        rpc=0.022,
        daily_spend=8000,
        start_day=_VIOLATION_LAL_STACK_DAY,
        rpc_post_swap=0.08,
    ),
    _MetaAdSpec(
        ad="Image - LAL 10% Subscribers",
        campaign="Conversion - Subscription",
        adset="LAL 10% Paid Subscribers",
        ctr=0.010,
        cpc=280,
        rpc=0.018,
        daily_spend=8000,
        start_day=_VIOLATION_LAL_STACK_DAY,
        rpc_post_swap=0.06,
    ),
    # Retargeting - unchanged
    _MetaAdSpec(
        ad="Carousel - Cart Abandoner Reminder",
        campaign="Retargeting - Cart Abandoners",
        adset="App-installed, no subscription",
        ctr=0.025,
        cpc=140,
        rpc=0.10,
        daily_spend=14000,
    ),
)


def _meta_active(ad: _MetaAdSpec, day: int) -> bool:
    return day >= ad.start_day


def _meta_rpc_for_day(ad: _MetaAdSpec, day: int) -> float:
    """Apply Day 45 optimization-target swap on Conversion campaigns."""
    if ad.rpc_post_swap is not None and day >= _VIOLATION_OPTIMIZATION_SWAP_DAY:
        return ad.rpc_post_swap
    return ad.rpc


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
        date_iso = _date_for_day(d).isoformat()
        for ad in _META_ADS:
            if not _meta_active(ad, d):
                continue
            spend = ad.daily_spend
            clicks = int(round(spend / ad.cpc))
            impressions = int(round(clicks / ad.ctr))
            rpc = _meta_rpc_for_day(ad, d)
            results = round(clicks * rpc, 1)
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
# STATE.json
# ---------------------------------------------------------------------------


_GOOGLE_ADS_STATE_CAMPAIGNS = (
    {
        "campaign_id": campaign_id("Brand - Exact"),
        "campaign_name": "Brand - Exact",
        "status": "ENABLED",
        "daily_budget": 12000,
        "campaign_goal": (
            "Capture branded demand at high efficiency "
            "(target cost-per-subscription <= JPY 600)."
        ),
    },
    {
        "campaign_id": campaign_id("Generic - Fitness Apps"),
        "campaign_name": "Generic - Fitness Apps",
        "status": "ENABLED",
        "daily_budget": 40000,
        "campaign_goal": (
            "Acquire net-new subscribers in fitness-app category "
            "(target cost-per-subscription <= JPY 4,500)."
        ),
    },
    {
        "campaign_id": campaign_id("Generic - Workout Plans"),
        "campaign_name": "Generic - Workout Plans",
        "status": "ENABLED",
        "daily_budget": 35000,
        "campaign_goal": (
            "Top-of-funnel workout-plan demand; target "
            "cost-per-subscription <= JPY 4,500."
        ),
    },
    {
        "campaign_id": campaign_id("Retargeting - App Visitors"),
        "campaign_name": "Retargeting - App Visitors",
        "status": "ENABLED",
        "daily_budget": 16000,
        "campaign_goal": (
            "Recover 30-day site visitors at <= JPY 1,500 " "cost-per-subscription."
        ),
    },
    # *** STRATEGY VIOLATION (rule 1) — appears in STATE because it's
    # currently ENABLED and consuming budget. mureo's compliance audit
    # cross-references against the STRATEGY constraint to flag it.
    {
        "campaign_id": campaign_id("Competitor Names"),
        "campaign_name": "Competitor Names",
        "status": "ENABLED",
        "daily_budget": 15000,
        "campaign_goal": (
            "VIOLATES STRATEGY rule 1 (no competitor-name bidding). "
            "Launched Day 30 by new manager; never reviewed."
        ),
    },
)

_META_ADS_STATE_CAMPAIGNS = (
    {
        "campaign_id": campaign_id("Awareness - Workout Routines"),
        "campaign_name": "Awareness - Workout Routines",
        "status": "ENABLED",
        "daily_budget": 22000,
        "campaign_goal": "Top-of-funnel awareness in active-lifestyle segment.",
    },
    {
        "campaign_id": campaign_id("Conversion - Subscription"),
        "campaign_name": "Conversion - Subscription",
        "status": "ENABLED",
        "daily_budget": 90000,
        "campaign_goal": (
            "Drive paid Subscriptions. Note: optimization target was "
            "switched on Day 45 to '7-day trial' (VIOLATES STRATEGY rule 2). "
            "LAL stack expanded to 6 variants on Day 60 (VIOLATES "
            "STRATEGY rule 3)."
        ),
    },
    {
        "campaign_id": campaign_id("Retargeting - Cart Abandoners"),
        "campaign_name": "Retargeting - Cart Abandoners",
        "status": "ENABLED",
        "daily_budget": 14000,
        "campaign_goal": "Re-engage app-installed users who did not subscribe.",
    },
)


def _action_iso(day: int, hour: int = 10, minute: int = 0) -> str:
    d = _date_for_day(day)
    dt = datetime(
        d.year, d.month, d.day, hour, minute, tzinfo=timezone(timedelta(hours=9))
    )
    return dt.isoformat(timespec="seconds")


# action_log: only routine entries from BEFORE the new manager joined
# Day 30. The silence after Day 30 — three concurrent strategy
# violations with zero log entries — is itself the diagnostic signal,
# because STRATEGY says all actions must be logged.
_ACTION_LOG = (
    {
        "timestamp": _action_iso(8, 9, 0),
        "action": "Increased Generic - Fitness Apps daily_budget by +15%",
        "platform": "google_ads",
        "campaign_id": campaign_id("Generic - Fitness Apps"),
        "summary": (
            "Routine seasonality bump for Q1 New Year fitness peak. "
            "(Manual action — pre-mureo, pre-new-manager.)"
        ),
        "metrics_at_action": {
            "google_blended_cost_per_subscription": 4100,
            "meta_blended_cost_per_subscription": 3800,
        },
        "observation_due": _date_for_day(22).isoformat(),
    },
    {
        "timestamp": _action_iso(20, 11, 30),
        "action": "Paused 2 underperforming creative variants on Awareness - Workout Routines",
        "platform": "meta_ads",
        "campaign_id": campaign_id("Awareness - Workout Routines"),
        "summary": (
            "Routine creative cleanup. (Manual action — pre-mureo, " "pre-new-manager.)"
        ),
        "metrics_at_action": {
            "meta_awareness_results_per_day": 36,
            "meta_blended_cost_per_subscription": 3700,
        },
        "observation_due": _date_for_day(34).isoformat(),
    },
    {
        "timestamp": _action_iso(28, 14, 0),
        "action": "Approved hire: new growth manager (start date Day 30)",
        "platform": "meta_ads",
        "campaign_id": None,
        "summary": (
            "New manager onboarded with admin access on Day 30. Briefed on "
            "STRATEGY.md including rules 1-3 (no competitor bidding, "
            "Subscribed-only optimization, LAL cap 3). Subsequent campaign "
            "changes by this user must be reflected in action_log per "
            "STRATEGY policy. (Manual action — pre-mureo. As of "
            "today, action_log shows ZERO entries since Day 30.)"
        ),
        "metrics_at_action": {
            "headcount_growth_team": 3,
        },
        "observation_due": _date_for_day(89).isoformat(),
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
            "account_id": "demo-pulsefit-google-ads",
            "campaigns": list(_GOOGLE_ADS_STATE_CAMPAIGNS),
        },
        "meta_ads": {
            "account_id": "demo-pulsefit-meta-ads",
            "campaigns": list(_META_ADS_STATE_CAMPAIGNS),
        },
    },
    "action_log": list(_ACTION_LOG),
}


# ---------------------------------------------------------------------------
# STRATEGY.md — explicit numeric goals + the three rules being violated.
# ---------------------------------------------------------------------------

_STRATEGY_MD = """# STRATEGY — PulseFit (demo: Strategy Drift)

> Synthetic fitness-app subscription scenario shipped with `mureo demo init --scenario strategy-drift`.
> Replace with your real strategy when you switch to a live account.

## Business
- **Brand:** PulseFit
- **Vertical:** Subscription fitness app (workout plans + tracking)
- **ICP:** JP 25-44, urban, fitness-curious, willing to pay JPY 1,200/month
- **Subscription LTV:** ~JPY 14,400 (12-month median tenure)
- **Trial-to-paid rate (industry-standard 7-day trial):** ~12%
- **Total ad budget:** ~JPY 5M / month (Google + Meta)

## Quarterly goals
- **Cost-per-subscription <= JPY 4,500** blended across Google + Meta
- **Net new paid subscriptions >= 800 / month**
- **Brand-search CTR >= 18%** (brand health proxy)
- **Trial-to-paid rate >= 12%** (quality floor)

## Channel mix
- **Google Ads:** Brand - Exact, Generic - Fitness Apps, Generic - Workout Plans, Retargeting - App Visitors
- **Meta Ads:** Awareness Workout Routines, Conversion Subscription (LAL 1/2/5 + Custom), Retargeting Cart Abandoners

## Operation Mode
**MAINTAIN** — Q1 peak has passed. No major launches this quarter. Steady-state efficiency focus.

## Constraints

These three rules are non-negotiable. Each is codified after a past
incident; violations require explicit Operation Mode change + leadership
approval.

1. **No competitor-name bidding** on either platform. Past attempt cost
   JPY 600K/quarter and produced 8 subscriptions at JPY 75K CPS — 16x
   worse than baseline. Industry policy is now to compete on category
   intent, not on rivals' brand names.
2. **Conversion campaigns optimize for "Subscribed" (paid signup),
   never for "Started trial".** Trial-volume optimization trains the
   ad platforms toward shallow signups whose downstream trial-to-paid
   rate falls below the 12% quality floor. Lifetime value is too
   sensitive to allow the swap.
3. **Meta Lookalike stack capped at 3 active variants**, and the
   variants must be 1%, 2%, 5% (or smaller). Past stacking of LAL 7%
   and 10% caused audience overlap, frequency above 8x, and CTR
   collapse within 14 days.

## Action-logging policy

Every change to STATE (campaign create / pause / budget / optimization
target / audience set) must be recorded in ``action_log`` with a
``summary``, ``metrics_at_action``, and ``observation_due``. Empty
action_log around active changes is a process violation, not just a
data-quality issue.
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
    # Empty action_log around the new manager's changes IS the
    # diagnostic signal here, so this scenario opts out of the
    # contract test's ">=3 action_log entries" floor.
    requires_action_log=False,
)
