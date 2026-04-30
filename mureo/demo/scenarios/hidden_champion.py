"""The "Hidden Champion" demo scenario — PulseGrid B2B SaaS observability.

A B2B SaaS observability/monitoring vendor running ~JPY 6M / month.
Headline metrics look fine (blended cost-per-trial ~JPY 18,500 vs
target JPY 22,000). Three months of routine optimization actions in
the action_log: budget shifts, creative refreshes, negative-keyword
adds. None of them touched the search term hiding the real story.

Buried in the low-priority "Generic - Observability Discovery" ad
group, one specific long-tail term —
"kubernetes monitoring open source" — has CVR ~18%, more than 4x
the surrounding ad group's ~4% average. It has been there for 90
days but is throttled by the ad group's daily budget, so it produces
only ~5 clicks / day and ~0.9 trials / day. The volume looks small,
which is exactly why nobody escalated it.

The "wow": mureo's outlier detection isolates the term and models
the impact of promoting it to its own campaign with 5x budget —
projecting ~+104 trial signups / month at the strong existing CVR
(roughly 26 / month today, ~130 / month uncapped). The framing is
deliberately monthly because day-level volume is currently below
1 trial / day; any user-facing copy that quotes a per-day count
should phrase it as "~1 trial / day today" rather than "5 / day".

All numbers deterministic; re-running ``mureo demo init`` produces an
identical bundle.
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

_NAME = "hidden-champion"
_TITLE = "The Hidden Champion (PulseGrid / B2B SaaS observability)"
_BLURB = (
    "A long-tail Google search term has been quietly converting at 18% CVR "
    "(vs the ad group's 4% average) for 90 days, buried in a low-priority "
    "Generic ad group nobody escalated. mureo finds the outlier, models the "
    "uplift of promoting it to its own campaign with 5x budget."
)
_DAYS = 90
_END_DATE = date(2026, 4, 29)
_BRAND = "PulseGrid"


def _date_for_day(d: int) -> date:
    return _END_DATE - timedelta(days=_DAYS - 1 - d)


# ---------------------------------------------------------------------------
# Google Ads — steady state across 90 days
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GAdsCampaignSpec:
    name: str
    daily_impr: int
    ctr: float
    cpc: float
    cvr: float


_GADS_CAMPAIGNS = (
    _GAdsCampaignSpec("Brand - Exact", 800, 0.20, 350.0, 0.16),
    _GAdsCampaignSpec("Generic - APM Tools", 4500, 0.05, 1100.0, 0.040),
    _GAdsCampaignSpec("Generic - Observability Discovery", 6000, 0.045, 950.0, 0.045),
    _GAdsCampaignSpec("Retargeting - Trial Users", 1200, 0.10, 400.0, 0.18),
)


_GADS_AD_GROUPS = (
    ("Brand - Exact", "Brand - Exact - Core", 0.65),
    ("Brand - Exact", "Brand - Exact - Comparison", 0.35),
    ("Generic - APM Tools", "Application Monitoring", 0.55),
    ("Generic - APM Tools", "Performance Monitoring", 0.45),
    ("Generic - Observability Discovery", "Open Source Stack", 0.40),
    ("Generic - Observability Discovery", "Logs and Metrics", 0.60),
    ("Retargeting - Trial Users", "Trial Reactivation", 1.0),
)


# Search terms: most healthy mid-funnel, one is the HIDDEN CHAMPION
# in the low-priority "Open Source Stack" ad group.
_GADS_SEARCH_TERMS = (
    # Brand - Exact (steady, comparison + core)
    ("pulsegrid", "Brand - Exact", "Brand - Exact - Core", 38000, 7600, 2660000, 1216),
    (
        "pulsegrid pricing",
        "Brand - Exact",
        "Brand - Exact - Core",
        9200,
        1840,
        644000,
        294,
    ),
    (
        "pulsegrid login",
        "Brand - Exact",
        "Brand - Exact - Core",
        4800,
        960,
        336000,
        154,
    ),
    (
        "pulsegrid review",
        "Brand - Exact",
        "Brand - Exact - Comparison",
        7500,
        1500,
        525000,
        240,
    ),
    (
        "pulsegrid vs newrelic",
        "Brand - Exact",
        "Brand - Exact - Comparison",
        5200,
        1040,
        364000,
        166,
    ),
    # Generic - APM Tools (competitive, healthy ~4% CVR territory)
    (
        "application performance monitoring",
        "Generic - APM Tools",
        "Application Monitoring",
        88000,
        4400,
        4840000,
        176,
    ),
    (
        "best apm tools",
        "Generic - APM Tools",
        "Application Monitoring",
        56000,
        2800,
        3080000,
        112,
    ),
    (
        "node js apm",
        "Generic - APM Tools",
        "Application Monitoring",
        24000,
        1200,
        1320000,
        48,
    ),
    (
        "performance monitoring tools",
        "Generic - APM Tools",
        "Performance Monitoring",
        72000,
        3600,
        3960000,
        144,
    ),
    (
        "site reliability monitoring",
        "Generic - APM Tools",
        "Performance Monitoring",
        18000,
        900,
        990000,
        36,
    ),
    # Generic - Observability Discovery — Open Source Stack ad group
    # is where the HIDDEN CHAMPION lives.
    (
        # *** HIDDEN CHAMPION *** — CVR ~18% vs ad-group avg ~4%
        "kubernetes monitoring open source",
        "Generic - Observability Discovery",
        "Open Source Stack",
        5400,
        432,
        410400,
        78,
    ),
    (
        "self hosted observability",
        "Generic - Observability Discovery",
        "Open Source Stack",
        14000,
        630,
        598500,
        12,
    ),
    (
        "prometheus alternative",
        "Generic - Observability Discovery",
        "Open Source Stack",
        22000,
        990,
        940500,
        20,
    ),
    # Generic - Observability Discovery — Logs and Metrics ad group (healthy 4-5%)
    (
        "log management tools",
        "Generic - Observability Discovery",
        "Logs and Metrics",
        45000,
        2025,
        1923750,
        81,
    ),
    (
        "metrics dashboard saas",
        "Generic - Observability Discovery",
        "Logs and Metrics",
        38000,
        1710,
        1624500,
        77,
    ),
    (
        "centralized logging",
        "Generic - Observability Discovery",
        "Logs and Metrics",
        28000,
        1260,
        1197000,
        50,
    ),
    # Retargeting - Trial Users (healthy)
    (
        "pulsegrid free trial",
        "Retargeting - Trial Users",
        "Trial Reactivation",
        8800,
        880,
        352000,
        158,
    ),
    (
        "pulsegrid sign up",
        "Retargeting - Trial Users",
        "Trial Reactivation",
        4200,
        420,
        168000,
        76,
    ),
)


_GADS_KEYWORDS = (
    (
        "[pulsegrid]",
        "EXACT",
        10,
        "Brand - Exact",
        "Brand - Exact - Core",
        52000,
        10400,
        3640000,
        1664,
    ),
    (
        "[pulsegrid pricing]",
        "EXACT",
        10,
        "Brand - Exact",
        "Brand - Exact - Core",
        9200,
        1840,
        644000,
        294,
    ),
    (
        "application performance monitoring",
        "PHRASE",
        7,
        "Generic - APM Tools",
        "Application Monitoring",
        168000,
        8400,
        9240000,
        336,
    ),
    (
        "performance monitoring tools",
        "PHRASE",
        7,
        "Generic - APM Tools",
        "Performance Monitoring",
        90000,
        4500,
        4950000,
        180,
    ),
    (
        "kubernetes monitoring",
        "PHRASE",
        6,
        "Generic - Observability Discovery",
        "Open Source Stack",
        41400,
        2052,
        1948500,
        110,
    ),
    (
        "log management",
        "PHRASE",
        7,
        "Generic - Observability Discovery",
        "Logs and Metrics",
        73000,
        3285,
        3120750,
        131,
    ),
    (
        "metrics monitoring",
        "PHRASE",
        7,
        "Generic - Observability Discovery",
        "Logs and Metrics",
        38000,
        1710,
        1624500,
        77,
    ),
    (
        '"pulsegrid"',
        "PHRASE",
        9,
        "Retargeting - Trial Users",
        "Trial Reactivation",
        13000,
        1300,
        520000,
        234,
    ),
)


def _build_google_campaigns_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        ["day", "campaign", "impressions", "clicks", "cost", "conversions"]
    ]
    for c in _GADS_CAMPAIGNS:
        for d in range(_DAYS):
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
# Meta Ads — steady state across 90 days
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


_META_ADS: tuple[_MetaAdSpec, ...] = (
    _MetaAdSpec(
        ad="Video - Engineering Pain Points",
        campaign="Awareness - Engineer Education",
        adset="Engineers JP/EN 28-50",
        ctr=0.013,
        cpc=180,
        rpc=0.025,
        daily_spend=22000,
    ),
    _MetaAdSpec(
        ad="Image - Trial CTA Generic",
        campaign="Conversion - Free Trial",
        adset="LAL 1% Trial Users",
        ctr=0.018,
        cpc=240,
        rpc=0.060,
        daily_spend=42000,
    ),
    _MetaAdSpec(
        ad="Image - Open Source Friendly Story",
        campaign="Conversion - Free Trial",
        adset="Custom - GitHub Visitors",
        ctr=0.022,
        cpc=210,
        rpc=0.075,
        daily_spend=28000,
    ),
    _MetaAdSpec(
        ad="Carousel - Trial Drop-off Recovery",
        campaign="Retargeting - Trial Drop-off",
        adset="Started trial, no conversion",
        ctr=0.030,
        cpc=160,
        rpc=0.12,
        daily_spend=18000,
    ),
    _MetaAdSpec(
        ad="Image - Annual Plan Promo",
        campaign="Lead Form - Sales Outreach",
        adset="VP Engineering / SRE Lead",
        ctr=0.012,
        cpc=320,
        rpc=0.18,
        daily_spend=12000,
    ),
)


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
            spend = ad.daily_spend
            clicks = int(round(spend / ad.cpc))
            impressions = int(round(clicks / ad.ctr))
            results = round(clicks * ad.rpc, 1)
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
        "daily_budget": 65000,
        "campaign_goal": (
            "Capture branded demand at high efficiency "
            "(target cost-per-trial <= JPY 3,500)."
        ),
    },
    {
        "campaign_id": campaign_id("Generic - APM Tools"),
        "campaign_name": "Generic - APM Tools",
        "status": "ENABLED",
        "daily_budget": 280000,
        "campaign_goal": (
            "Compete in the APM tools category; target cost-per-trial " "<= JPY 28,000."
        ),
    },
    {
        "campaign_id": campaign_id("Generic - Observability Discovery"),
        "campaign_name": "Generic - Observability Discovery",
        "status": "ENABLED",
        "daily_budget": 95000,
        "campaign_goal": (
            "Top-of-funnel discovery for adjacent categories "
            "(open-source stacks, logs, metrics). Lower-priority spend cap."
        ),
    },
    {
        "campaign_id": campaign_id("Retargeting - Trial Users"),
        "campaign_name": "Retargeting - Trial Users",
        "status": "ENABLED",
        "daily_budget": 50000,
        "campaign_goal": (
            "Recover dropped trial signups; target cost-per-conversion " "<= JPY 2,500."
        ),
    },
)

_META_ADS_STATE_CAMPAIGNS = (
    {
        "campaign_id": campaign_id("Awareness - Engineer Education"),
        "campaign_name": "Awareness - Engineer Education",
        "status": "ENABLED",
        "daily_budget": 22000,
        "campaign_goal": "Top-of-funnel engineer education content.",
    },
    {
        "campaign_id": campaign_id("Conversion - Free Trial"),
        "campaign_name": "Conversion - Free Trial",
        "status": "ENABLED",
        "daily_budget": 70000,
        "campaign_goal": ("Drive Free Trial signups at <= JPY 4,000 cost-per-trial."),
    },
    {
        "campaign_id": campaign_id("Retargeting - Trial Drop-off"),
        "campaign_name": "Retargeting - Trial Drop-off",
        "status": "ENABLED",
        "daily_budget": 18000,
        "campaign_goal": (
            "Re-engage users who started but did not complete trial; "
            "target conversion rate >= 8%."
        ),
    },
    {
        "campaign_id": campaign_id("Lead Form - Sales Outreach"),
        "campaign_name": "Lead Form - Sales Outreach",
        "status": "ENABLED",
        "daily_budget": 12000,
        "campaign_goal": (
            "Build qualified-lead list for outbound sales (Annual Plan)."
        ),
    },
)


def _action_iso(day: int, hour: int = 10, minute: int = 0) -> str:
    d = _date_for_day(day)
    dt = datetime(
        d.year, d.month, d.day, hour, minute, tzinfo=timezone(timedelta(hours=9))
    )
    return dt.isoformat(timespec="seconds")


_ACTION_LOG = (
    {
        "timestamp": _action_iso(15, 10, 30),
        "action": "Increased Generic - APM Tools daily_budget by +20%",
        "platform": "google_ads",
        "campaign_id": campaign_id("Generic - APM Tools"),
        "summary": (
            "Strong APM-category growth signal; bumped budget to capture "
            "more trial volume. (Manual action — pre-mureo. Did not touch "
            "Generic - Observability Discovery.)"
        ),
        "metrics_at_action": {
            "google_apm_cost_per_trial": 27500,
            "google_blended_cost_per_trial": 18800,
        },
        "observation_due": _date_for_day(29).isoformat(),
    },
    {
        "timestamp": _action_iso(40, 14, 0),
        "action": "Paused 3 underperforming creative variants on Conversion - Free Trial",
        "platform": "meta_ads",
        "campaign_id": campaign_id("Conversion - Free Trial"),
        "summary": (
            "Routine creative cleanup; consolidated to LAL 1% + GitHub "
            "Custom Audience. (Manual action — pre-mureo.)"
        ),
        "metrics_at_action": {
            "meta_conversion_results_per_day": 88,
            "meta_blended_cost_per_result": 4200,
        },
        "observation_due": _date_for_day(54).isoformat(),
    },
    {
        "timestamp": _action_iso(70, 9, 15),
        "action": "Added 12 negative keywords to Generic - APM Tools",
        "platform": "google_ads",
        "campaign_id": campaign_id("Generic - APM Tools"),
        "summary": (
            "Cleaned up irrelevant queries (mostly 'apm car repair' "
            "noise). (Manual action — pre-mureo. Did not investigate "
            "search-term-level CVR distribution.)"
        ),
        "metrics_at_action": {
            "google_apm_cost_per_trial": 27500,
            "google_blended_cost_per_trial": 18500,
        },
        "observation_due": _date_for_day(84).isoformat(),
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
            "account_id": "demo-pulsegrid-google-ads",
            "campaigns": list(_GOOGLE_ADS_STATE_CAMPAIGNS),
        },
        "meta_ads": {
            "account_id": "demo-pulsegrid-meta-ads",
            "campaigns": list(_META_ADS_STATE_CAMPAIGNS),
        },
    },
    "action_log": list(_ACTION_LOG),
}


# ---------------------------------------------------------------------------
# STRATEGY.md
# ---------------------------------------------------------------------------

_STRATEGY_MD = """# STRATEGY — PulseGrid (demo: Hidden Champion)

> Synthetic B2B SaaS observability scenario shipped with `mureo demo init --scenario hidden-champion`.
> Replace with your real strategy when you switch to a live account.

## Business
- **Brand:** PulseGrid
- **Vertical:** B2B SaaS observability / monitoring (APM + logs + metrics)
- **ICP:** Engineering teams (10-200 engineers) at Series B+ companies, primary buyer = SRE Lead / VP Engineering
- **ARR per customer:** ~JPY 1.4M ACV, 18-month median tenure
- **Trial-to-paid rate:** ~22%
- **Total ad budget:** ~JPY 6M / month (Google + Meta)

## Quarterly goals
- **Cost-per-trial <= JPY 22,000** blended across Google + Meta
- **Free Trial signups >= 600 / month** (top-of-funnel pipeline)
- **Brand-search CTR >= 18%** (brand health)
- **Blended ROAS >= 1.5x** at 12-month attribution window (long sales cycle)

## Channel mix
- **Google Ads:** Brand - Exact, Generic - APM Tools (primary spend), Generic - Observability Discovery (lower-priority discovery), Retargeting - Trial Users
- **Meta Ads:** Awareness Engineer Education, Conversion Free Trial (LAL + GitHub Custom Audience), Retargeting Trial Drop-off, Lead Form Sales Outreach

## Operation Mode
**GROWTH** — prioritize trial-volume growth over cost efficiency. We want top-of-funnel scale to feed the sales motion.

## Constraints
- **Outlier search terms must be promoted.** When a search term inside a generic ad group converts at 3x+ the ad-group average, escalate it to its own ad group or campaign with budget protection — do not leave high-intent queries capped by a generic ad group's budget.
- **No competitor-name bidding** on either platform.
- **Pause-then-diagnose** before pause-then-replace: paused campaigns should be re-enabled, not cut from inventory, until root cause is established.
- **Trial-quality matters.** Optimize for "started trial" only when downstream trial-to-paid rate stays above 18%; if a high-volume source drops below that, demote it.
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
