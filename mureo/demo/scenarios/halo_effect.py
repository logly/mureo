"""The "Halo Effect" demo scenario — SkyRoof local roofing contractor.

A small Japanese roofing contractor running ~JPY 5M / month split
roughly 35% Google Search / 65% Meta. The owner believes Google
Search "phone calls" are the workhorse — and reading any single-day
report would agree. Last-click attribution credits Google Brand
search for almost every conversion.

The truth: Meta retargeting silently warms users into branded
searches. The owner doesn't see this because the lift is delayed
(~3 days) and shows up in a different channel.

On Day 50 the owner ran a "controlled test" pausing Meta retargeting
for 5 days to "prove it was wasted spend". The Meta retargeting
spend dropped to zero Day 50-54. With a 3-day lag, Google Brand -
Exact volume dropped 40% (Day 53-57). Day 55 Meta retargeting
resumed; Day 58 onwards Brand - Exact recovered. The damage:
~35 missed calls and a misleading "test" that, read literally,
"proves" Meta retargeting is dispensable — the opposite of the truth.

The "wow": mureo's analysis identifies the Day 53-57 Brand - Exact
dip, cross-references the action_log entry on Day 50 (Meta pause),
and reports the temporal correlation. Recommendation: do NOT cut
Meta retargeting; it is upstream of the brand-search calls the owner
is mentally crediting to Google.

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

_NAME = "halo-effect"
_TITLE = "The Halo Effect (SkyRoof / Local home services)"
_BLURB = (
    "Owner believed Google Search was the workhorse — Meta retargeting was "
    "silently driving the brand-search calls. A 5-day Meta pause "
    '"controlled test" cut Brand-Exact volume 40% three days later. mureo '
    "spots the lagged dip and the action_log together to recommend keeping "
    "Meta upstream investment, not cutting it."
)
_DAYS = 90
_END_DATE = date(2026, 4, 29)
_BRAND = "SkyRoof"

# Day 50: owner pauses Meta retargeting for a "5-day test"
_META_PAUSE_START_DAY = 50
_META_PAUSE_END_DAY = 54  # inclusive — pause covers Day 50-54
# Day 53-57: Google Brand-Exact volume drops 40% (3-day lag, 5-day window)
_BRAND_DIP_START_DAY = 53
_BRAND_DIP_END_DAY = 57  # inclusive
_BRAND_DIP_FACTOR = 0.60  # 40% drop


def _date_for_day(d: int) -> date:
    return _END_DATE - timedelta(days=_DAYS - 1 - d)


# ---------------------------------------------------------------------------
# Google Ads — Brand-Exact dips Day 53-57; others stable
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GAdsCampaignSpec:
    name: str
    daily_impr: int
    ctr: float
    cpc: float
    cvr: float


_GADS_CAMPAIGNS = (
    _GAdsCampaignSpec("Brand - Exact", 200, 0.25, 80.0, 0.35),
    _GAdsCampaignSpec("Generic - Roof Repair JP", 1500, 0.06, 350.0, 0.080),
    _GAdsCampaignSpec("Generic - Local Roofer JP", 1200, 0.05, 320.0, 0.090),
    _GAdsCampaignSpec("Retargeting - Branded Search", 400, 0.12, 180.0, 0.15),
)


_GADS_AD_GROUPS = (
    ("Brand - Exact", "Brand - Exact - Core", 0.70),
    ("Brand - Exact", "Brand - Exact - Service Areas", 0.30),
    ("Generic - Roof Repair JP", "Roof Repair General", 0.55),
    ("Generic - Roof Repair JP", "Storm Damage Repair", 0.45),
    ("Generic - Local Roofer JP", "Local Roofer", 1.0),
    ("Retargeting - Branded Search", "Site Visitors - Branded Search", 1.0),
)


def _brand_dip_factor(day: int) -> float:
    """Return Brand-Exact's per-day demand multiplier."""
    if _BRAND_DIP_START_DAY <= day <= _BRAND_DIP_END_DAY:
        return _BRAND_DIP_FACTOR
    return 1.0


_GADS_SEARCH_TERMS = (
    # Brand - Exact (core demand)
    ("skyroof", "Brand - Exact", "Brand - Exact - Core", 8500, 2125, 170000, 744),
    (
        "skyroof 屋根工事",
        "Brand - Exact",
        "Brand - Exact - Core",
        2400,
        600,
        48000,
        210,
    ),
    (
        "skyroof 見積もり",
        "Brand - Exact",
        "Brand - Exact - Core",
        1800,
        450,
        36000,
        158,
    ),
    (
        "skyroof 評判",
        "Brand - Exact",
        "Brand - Exact - Core",
        1200,
        300,
        24000,
        105,
    ),
    (
        "skyroof 横浜",
        "Brand - Exact",
        "Brand - Exact - Service Areas",
        2200,
        550,
        44000,
        193,
    ),
    (
        "skyroof 川崎",
        "Brand - Exact",
        "Brand - Exact - Service Areas",
        1600,
        400,
        32000,
        140,
    ),
    # Generic - Roof Repair JP
    (
        "屋根 修理 業者",
        "Generic - Roof Repair JP",
        "Roof Repair General",
        38000,
        2280,
        798000,
        182,
    ),
    (
        "雨漏り 修理",
        "Generic - Roof Repair JP",
        "Roof Repair General",
        24000,
        1440,
        504000,
        115,
    ),
    (
        "屋根 修理 費用",
        "Generic - Roof Repair JP",
        "Roof Repair General",
        18000,
        1080,
        378000,
        86,
    ),
    (
        "台風 屋根 修理",
        "Generic - Roof Repair JP",
        "Storm Damage Repair",
        22000,
        1320,
        462000,
        158,
    ),
    (
        "強風 瓦 修理",
        "Generic - Roof Repair JP",
        "Storm Damage Repair",
        12000,
        720,
        252000,
        86,
    ),
    # Generic - Local Roofer JP
    (
        "屋根屋 横浜",
        "Generic - Local Roofer JP",
        "Local Roofer",
        28000,
        1400,
        448000,
        126,
    ),
    (
        "屋根 業者 川崎",
        "Generic - Local Roofer JP",
        "Local Roofer",
        18000,
        900,
        288000,
        81,
    ),
    (
        "屋根工事 神奈川",
        "Generic - Local Roofer JP",
        "Local Roofer",
        14000,
        700,
        224000,
        63,
    ),
    # Retargeting - Branded Search (high CVR — second-touch)
    (
        "skyroof 申し込み",
        "Retargeting - Branded Search",
        "Site Visitors - Branded Search",
        4800,
        576,
        103680,
        87,
    ),
    (
        "skyroof 連絡",
        "Retargeting - Branded Search",
        "Site Visitors - Branded Search",
        2200,
        264,
        47520,
        40,
    ),
)


_GADS_KEYWORDS = (
    (
        "[skyroof]",
        "EXACT",
        10,
        "Brand - Exact",
        "Brand - Exact - Core",
        14000,
        3500,
        280000,
        1225,
    ),
    (
        "[skyroof 横浜]",
        "EXACT",
        9,
        "Brand - Exact",
        "Brand - Exact - Service Areas",
        4200,
        1050,
        84000,
        368,
    ),
    (
        "屋根 修理",
        "PHRASE",
        7,
        "Generic - Roof Repair JP",
        "Roof Repair General",
        82000,
        4920,
        1722000,
        394,
    ),
    (
        "雨漏り 修理",
        "PHRASE",
        8,
        "Generic - Roof Repair JP",
        "Roof Repair General",
        24000,
        1440,
        504000,
        115,
    ),
    (
        "台風 屋根",
        "PHRASE",
        7,
        "Generic - Roof Repair JP",
        "Storm Damage Repair",
        34000,
        2040,
        714000,
        244,
    ),
    (
        "屋根屋",
        "PHRASE",
        6,
        "Generic - Local Roofer JP",
        "Local Roofer",
        46000,
        2300,
        736000,
        207,
    ),
    (
        "屋根工事",
        "PHRASE",
        7,
        "Generic - Local Roofer JP",
        "Local Roofer",
        14000,
        700,
        224000,
        63,
    ),
    (
        '"skyroof"',
        "PHRASE",
        9,
        "Retargeting - Branded Search",
        "Site Visitors - Branded Search",
        7000,
        840,
        151200,
        126,
    ),
)


def _build_google_campaigns_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        ["day", "campaign", "impressions", "clicks", "cost", "conversions"]
    ]
    for c in _GADS_CAMPAIGNS:
        for d in range(_DAYS):
            day_iso = _date_for_day(d).isoformat()
            # Only Brand - Exact reflects the halo dip; Meta upstream
            # exposure is what carries demand into branded search.
            factor = _brand_dip_factor(d) if c.name == "Brand - Exact" else 1.0
            impr = int(round(c.daily_impr * factor))
            clicks = int(round(impr * c.ctr))
            cost = round(clicks * c.cpc, 2)
            conv = round(clicks * c.cvr, 2)
            rows.append([day_iso, c.name, impr, clicks, cost, conv])
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
            factor = _brand_dip_factor(d) if camp_name == "Brand - Exact" else 1.0
            impr = int(round(c.daily_impr * share * factor))
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
# Meta Ads — Retargeting paused Day 50-54
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
    pause_start: int = -1  # -1 = never paused
    pause_end: int = -1


_META_ADS: tuple[_MetaAdSpec, ...] = (
    _MetaAdSpec(
        ad="Video - Storm Damage Stories",
        campaign="Awareness - Storm Damage",
        adset="Homeowners JP 35-65",
        ctr=0.015,
        cpc=90,
        rpc=0.04,
        daily_spend=30000,
    ),
    _MetaAdSpec(
        ad="Carousel - Site Visitor Reminder",
        campaign="Retargeting - Site Visitors",
        adset="180-day site visitors",
        ctr=0.025,
        cpc=75,
        rpc=0.10,
        daily_spend=18000,
        pause_start=_META_PAUSE_START_DAY,
        pause_end=_META_PAUSE_END_DAY,
    ),
    _MetaAdSpec(
        ad="Image - Free Inspection LAL",
        campaign="Conversion - Free Inspection",
        adset="LAL 1% Past Customers",
        ctr=0.016,
        cpc=110,
        rpc=0.07,
        daily_spend=24000,
    ),
    _MetaAdSpec(
        ad="Image - Free Inspection Custom Audience",
        campaign="Conversion - Free Inspection",
        adset="Custom - Engaged 90d",
        ctr=0.014,
        cpc=130,
        rpc=0.08,
        daily_spend=18000,
    ),
)


def _meta_is_paused(ad: _MetaAdSpec, day: int) -> bool:
    if ad.pause_start < 0:
        return False
    return ad.pause_start <= day <= ad.pause_end


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
            if _meta_is_paused(ad, d):
                continue  # paused day — omit row entirely
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
        "daily_budget": 5000,
        "campaign_goal": (
            "Capture branded demand for free-inspection calls "
            "(target cost-per-call <= JPY 350)."
        ),
    },
    {
        "campaign_id": campaign_id("Generic - Roof Repair JP"),
        "campaign_name": "Generic - Roof Repair JP",
        "status": "ENABLED",
        "daily_budget": 35000,
        "campaign_goal": (
            "Acquire net-new repair-intent leads at <= JPY 5,000 cost-per-call."
        ),
    },
    {
        "campaign_id": campaign_id("Generic - Local Roofer JP"),
        "campaign_name": "Generic - Local Roofer JP",
        "status": "ENABLED",
        "daily_budget": 22000,
        "campaign_goal": (
            "Capture local-intent searches (Yokohama / Kawasaki); "
            "target cost-per-call <= JPY 4,000."
        ),
    },
    {
        "campaign_id": campaign_id("Retargeting - Branded Search"),
        "campaign_name": "Retargeting - Branded Search",
        "status": "ENABLED",
        "daily_budget": 10000,
        "campaign_goal": (
            "Recover site-visitor branded searches at <= JPY 1,500 cost-per-call."
        ),
    },
)

_META_ADS_STATE_CAMPAIGNS = (
    {
        "campaign_id": campaign_id("Awareness - Storm Damage"),
        "campaign_name": "Awareness - Storm Damage",
        "status": "ENABLED",
        "daily_budget": 30000,
        "campaign_goal": (
            "Top-of-funnel awareness in JP homeowner segment; "
            "stories about real storm-damage repairs."
        ),
    },
    {
        "campaign_id": campaign_id("Retargeting - Site Visitors"),
        "campaign_name": "Retargeting - Site Visitors",
        "status": "ENABLED",
        "daily_budget": 18000,
        "campaign_goal": (
            "Re-engage 180-day site visitors. Note: paused Day 50-54 "
            "for a 'controlled test' (see action_log)."
        ),
    },
    {
        "campaign_id": campaign_id("Conversion - Free Inspection"),
        "campaign_name": "Conversion - Free Inspection",
        "status": "ENABLED",
        "daily_budget": 42000,
        "campaign_goal": (
            "Drive Free Inspection bookings at <= JPY 1,500 cost-per-result."
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
        "timestamp": _action_iso(10, 9, 0),
        "action": "Increased Awareness - Storm Damage budget by +25%",
        "platform": "meta_ads",
        "campaign_id": campaign_id("Awareness - Storm Damage"),
        "summary": (
            "Routine seasonality bump for storm-season volume. (Manual "
            "action — pre-mureo.)"
        ),
        "metrics_at_action": {
            "meta_awareness_results_per_day": 22,
            "google_brand_calls_per_day": 17.5,
        },
        "observation_due": _date_for_day(24).isoformat(),
    },
    {
        "timestamp": _action_iso(35, 14, 0),
        "action": "Paused 2 underperforming creative variants on Conversion - Free Inspection",
        "platform": "meta_ads",
        "campaign_id": campaign_id("Conversion - Free Inspection"),
        "summary": (
            "Routine creative cleanup; consolidated to LAL 1% + Custom "
            "Audience 90d. No expected halo impact. (Manual action — pre-mureo.)"
        ),
        "metrics_at_action": {
            "meta_conversion_results_per_day": 43,
            "google_brand_calls_per_day": 17.5,
        },
        "observation_due": _date_for_day(49).isoformat(),
    },
    {
        "timestamp": _action_iso(_META_PAUSE_START_DAY, 11, 0),
        "action": "Paused Retargeting - Site Visitors for 5-day controlled test",
        "platform": "meta_ads",
        "campaign_id": campaign_id("Retargeting - Site Visitors"),
        "summary": (
            "Hypothesis: retargeting spend is largely cannibalized by "
            "direct/brand-search; if we pause it for 5 days and brand-search "
            "volume holds, we can cut the JPY 540K/month retargeting line. "
            "(Manual action — pre-mureo. The pause produced a 40% Brand - "
            "Exact dip 3 days later, the OPPOSITE of the hypothesis.)"
        ),
        "metrics_at_action": {
            "meta_retargeting_results_per_day": 40,
            "google_brand_calls_per_day": 17.5,
        },
        "observation_due": _date_for_day(_META_PAUSE_END_DAY + 9).isoformat(),
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
            "account_id": "demo-skyroof-google-ads",
            "campaigns": list(_GOOGLE_ADS_STATE_CAMPAIGNS),
        },
        "meta_ads": {
            "account_id": "demo-skyroof-meta-ads",
            "campaigns": list(_META_ADS_STATE_CAMPAIGNS),
        },
    },
    "action_log": list(_ACTION_LOG),
}


# ---------------------------------------------------------------------------
# STRATEGY.md
# ---------------------------------------------------------------------------

_STRATEGY_MD = """# STRATEGY — SkyRoof (demo: Halo Effect)

> Synthetic local-roofing scenario shipped with `mureo demo init --scenario halo-effect`.
> Replace with your real strategy when you switch to a live account.

## Business
- **Brand:** SkyRoof
- **Vertical:** Local roofing contractor, JP (primary service area: Kanagawa)
- **ICP:** Homeowners 35-65, owned home with roof age >= 10 years
- **Average job value:** JPY 320,000 first-touch
- **Total ad budget:** ~JPY 5M / month (Google + Meta)

## Quarterly goals
- **Cost-per-call <= JPY 4,500** blended across Google + Meta
- **Brand-search volume >= 30 calls / day** (brand health + Meta-halo proxy)
- **Free Inspection bookings >= 600 / month** (top-of-funnel pipeline)
- **Blended ROAS >= 5.0x** (high AOV, long sales cycle)

## Channel mix
- **Google Ads:** Brand - Exact (high-intent calls), Generic - Roof Repair JP, Generic - Local Roofer JP, Retargeting - Branded Search
- **Meta Ads:** Awareness - Storm Damage (top-of-funnel), Retargeting - Site Visitors (mid-funnel — drives branded search), Conversion - Free Inspection (LAL + Custom Audience)

## Operation Mode
**MAINTAIN** — Q2 is steady-state. No new service area expansion planned.

## Constraints
- **Cross-channel attribution awareness.** Last-click reports under-credit Meta retargeting because most users who see retargeting later complete via branded search on Google. Before cutting any Meta line, check whether brand-search volume changes in the same window with a 1-7 day lag.
- **No competitor-name bidding** on either platform.
- **Pause-then-diagnose** before pause-then-replace: paused campaigns should be re-enabled, not cut from inventory, until root cause is established. Specifically, "controlled test" pauses must verify halo channels (brand search, direct) before concluding incremental contribution.
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
