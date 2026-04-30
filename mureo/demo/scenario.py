"""Synthetic data scenario for the ``mureo demo init`` bundle.

The scenario portrays a fictional mid-market B2B SaaS account
(brand: ``FlowDesk``) running Google Ads + Meta Ads over the 30 days
ending :data:`DEMO_END_DATE`. Numbers are picked so that the standard
mureo skills (``/daily-check``, ``/search-term-cleanup``,
``/budget-rebalance``, ``/creative-refresh``, ``/weekly-report``) each
surface at least one actionable finding when run against the demo
bundle:

  - ``Brand - Phrase`` matches on pure-brand search terms that should
    be moved into the Exact match campaign (cannibalization).
  - ``Generic - Low Intent`` consumes a disproportionate share of
    spend with poor CVR (budget skew).
  - Meta ``Awareness - Video A`` shows a CTR slope that drops late in
    the period (creative fatigue).

All values are deterministic — no randomness — so re-running
``mureo demo init`` produces an identical bundle byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Imported for ID parity with what ``mureo byod import`` will write to
# ``~/.mureo/byod/<platform>/campaigns.csv``. Reaching into the
# adapter's underscore-prefixed helper is a deliberate coupling — if
# the formula ever changes the demo's STATE.json must move in lockstep
# (otherwise STATE.json campaign_ids and BYOD CSV campaign_ids diverge
# and skills can't join them). Importing rather than duplicating means
# any rename surfaces as an ImportError instead of silent ID drift.
from mureo.byod.adapters.google_ads import _synthetic_id as _byod_synthetic_id

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

DEMO_END_DATE: date = date(2026, 4, 29)
DEMO_DAYS: int = 30
DEMO_BRAND: str = "FlowDesk"


def _days() -> list[date]:
    return [DEMO_END_DATE - timedelta(days=DEMO_DAYS - 1 - i) for i in range(DEMO_DAYS)]


# ---------------------------------------------------------------------------
# Google Ads scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GAdsCampaign:
    name: str
    base_impr: int
    ctr: float
    cpc_jpy: float
    cvr: float
    impr_slope: float
    ctr_slope: float


_GADS_CAMPAIGNS: tuple[_GAdsCampaign, ...] = (
    _GAdsCampaign("Brand - Exact", 1200, 0.18, 80.0, 0.12, 0.002, 0.0),
    _GAdsCampaign("Brand - Phrase", 800, 0.10, 110.0, 0.06, -0.003, -0.001),
    _GAdsCampaign("Generic - High Intent", 3500, 0.06, 220.0, 0.05, 0.001, 0.0),
    _GAdsCampaign("Generic - Low Intent", 6000, 0.02, 350.0, 0.008, 0.0, 0.0),
)


@dataclass(frozen=True)
class _GAdsAdGroup:
    campaign: str
    name: str
    share: float


_GADS_AD_GROUPS: tuple[_GAdsAdGroup, ...] = (
    _GAdsAdGroup("Brand - Exact", "Exact - Core", 1.0),
    _GAdsAdGroup("Brand - Phrase", "Phrase - Variants", 1.0),
    _GAdsAdGroup("Generic - High Intent", "Project Management Software", 0.55),
    _GAdsAdGroup("Generic - High Intent", "Team Collaboration Tool", 0.45),
    _GAdsAdGroup("Generic - Low Intent", "Productivity Tips", 0.60),
    _GAdsAdGroup("Generic - Low Intent", "Remote Work", 0.40),
)


@dataclass(frozen=True)
class _GAdsSearchTerm:
    term: str
    campaign: str
    ad_group: str
    impressions: int
    clicks: int
    cost_jpy: float
    conversions: float


_GADS_SEARCH_TERMS: tuple[_GAdsSearchTerm, ...] = (
    _GAdsSearchTerm(
        "flowdesk", "Brand - Exact", "Exact - Core", 8200, 1480, 118400, 178
    ),
    _GAdsSearchTerm(
        "flowdesk login", "Brand - Exact", "Exact - Core", 1100, 198, 15840, 22
    ),
    _GAdsSearchTerm(
        "flowdesk app", "Brand - Phrase", "Phrase - Variants", 950, 95, 10450, 5
    ),
    _GAdsSearchTerm(
        "flowdesk pricing", "Brand - Phrase", "Phrase - Variants", 720, 72, 7920, 4
    ),
    _GAdsSearchTerm(
        "flowdesk vs notion", "Brand - Phrase", "Phrase - Variants", 540, 38, 4180, 2
    ),
    _GAdsSearchTerm(
        "project management software",
        "Generic - High Intent",
        "Project Management Software",
        15400,
        924,
        203280,
        46,
    ),
    _GAdsSearchTerm(
        "best project management tool",
        "Generic - High Intent",
        "Project Management Software",
        8800,
        528,
        116160,
        26,
    ),
    _GAdsSearchTerm(
        "team collaboration software",
        "Generic - High Intent",
        "Team Collaboration Tool",
        6300,
        315,
        69300,
        15,
    ),
    _GAdsSearchTerm(
        "productivity tips",
        "Generic - Low Intent",
        "Productivity Tips",
        42000,
        840,
        294000,
        7,
    ),
    _GAdsSearchTerm(
        "how to be productive",
        "Generic - Low Intent",
        "Productivity Tips",
        18000,
        360,
        126000,
        2,
    ),
    _GAdsSearchTerm(
        "work from home tips",
        "Generic - Low Intent",
        "Remote Work",
        24000,
        480,
        168000,
        3,
    ),
    _GAdsSearchTerm(
        "remote work guide",
        "Generic - Low Intent",
        "Remote Work",
        12000,
        240,
        84000,
        2,
    ),
)


@dataclass(frozen=True)
class _GAdsKeyword:
    keyword: str
    match_type: str
    quality_score: int
    campaign: str
    ad_group: str
    impressions: int
    clicks: int
    cost_jpy: float
    conversions: float


_GADS_KEYWORDS: tuple[_GAdsKeyword, ...] = (
    _GAdsKeyword(
        "flowdesk",
        "EXACT",
        10,
        "Brand - Exact",
        "Exact - Core",
        9300,
        1678,
        134240,
        200,
    ),
    _GAdsKeyword(
        '"flowdesk"',
        "PHRASE",
        6,
        "Brand - Phrase",
        "Phrase - Variants",
        2210,
        205,
        22550,
        11,
    ),
    _GAdsKeyword(
        "project management software",
        "PHRASE",
        8,
        "Generic - High Intent",
        "Project Management Software",
        15400,
        924,
        203280,
        46,
    ),
    _GAdsKeyword(
        "team collaboration software",
        "PHRASE",
        7,
        "Generic - High Intent",
        "Team Collaboration Tool",
        6300,
        315,
        69300,
        15,
    ),
    _GAdsKeyword(
        "productivity tips",
        "PHRASE",
        4,
        "Generic - Low Intent",
        "Productivity Tips",
        42000,
        840,
        294000,
        7,
    ),
    _GAdsKeyword(
        "remote work",
        "PHRASE",
        4,
        "Generic - Low Intent",
        "Remote Work",
        36000,
        720,
        252000,
        5,
    ),
)


# ---------------------------------------------------------------------------
# Meta Ads scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MetaAd:
    campaign: str
    ad_set: str
    ad: str
    base_impr: int
    base_ctr: float
    cpc_jpy: float
    base_results: float
    ctr_slope: float


_META_ADS: tuple[_MetaAd, ...] = (
    _MetaAd(
        "Awareness - Video", "Tokyo 25-34", "Video A", 4800, 0.014, 95.0, 0.05, -0.0004
    ),
    _MetaAd(
        "Conversion - Lead Form",
        "Decision-makers JP",
        "Lead Form B",
        1700,
        0.022,
        240.0,
        0.18,
        0.0,
    ),
)


# ---------------------------------------------------------------------------
# Row builders — flat sequences that the workbook builder writes verbatim
# ---------------------------------------------------------------------------


def google_campaigns_rows() -> list[list[object]]:
    """``campaigns`` tab rows including header.

    Schema: day, campaign, impressions, clicks, cost, conversions
    """
    rows: list[list[object]] = [
        ["day", "campaign", "impressions", "clicks", "cost", "conversions"]
    ]
    days = _days()
    for c in _GADS_CAMPAIGNS:
        for i, d in enumerate(days):
            impr = max(0, int(round(c.base_impr * (1.0 + c.impr_slope * i))))
            ctr = max(0.0001, c.ctr + c.ctr_slope * i)
            clicks = int(round(impr * ctr))
            cost = round(clicks * c.cpc_jpy, 2)
            conversions = round(clicks * c.cvr, 2)
            rows.append([d.isoformat(), c.name, impr, clicks, cost, conversions])
    return rows


def google_ad_groups_rows() -> list[list[object]]:
    """``ad_groups`` tab rows including header.

    Schema: day, campaign, ad_group, impressions, clicks, cost, conversions
    """
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
    days = _days()
    by_campaign = {c.name: c for c in _GADS_CAMPAIGNS}
    for ag in _GADS_AD_GROUPS:
        c = by_campaign[ag.campaign]
        for i, d in enumerate(days):
            impr = max(0, int(round(c.base_impr * ag.share * (1.0 + c.impr_slope * i))))
            ctr = max(0.0001, c.ctr + c.ctr_slope * i)
            clicks = int(round(impr * ctr))
            cost = round(clicks * c.cpc_jpy, 2)
            conversions = round(clicks * c.cvr, 2)
            rows.append(
                [d.isoformat(), ag.campaign, ag.name, impr, clicks, cost, conversions]
            )
    return rows


def google_search_terms_rows() -> list[list[object]]:
    """``search_terms`` tab rows including header (aggregated, no day column)."""
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
    for st in _GADS_SEARCH_TERMS:
        rows.append(
            [
                st.term,
                st.campaign,
                st.ad_group,
                st.impressions,
                st.clicks,
                st.cost_jpy,
                st.conversions,
            ]
        )
    return rows


def google_keywords_rows() -> list[list[object]]:
    """``keywords`` tab rows including header."""
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
    for kw in _GADS_KEYWORDS:
        rows.append(
            [
                kw.keyword,
                kw.match_type,
                kw.quality_score,
                kw.campaign,
                kw.ad_group,
                kw.impressions,
                kw.clicks,
                kw.cost_jpy,
                kw.conversions,
            ]
        )
    return rows


# ---------------------------------------------------------------------------
# STATE.json campaign snapshots
# ---------------------------------------------------------------------------
#
# These are consumed by ``mureo.demo.installer`` to produce a v2
# STATE.json so that ``/daily-check`` and friends can resolve campaign
# metadata (budget, goal, status) from STATE while joining BYOD
# performance data on ``campaign_id``.


def _campaign_id(name: str) -> str:
    """Synthesize the campaign_id the BYOD pipeline will assign to ``name``.

    Delegates to ``mureo.byod.adapters.google_ads._synthetic_id`` so the
    demo's STATE.json IDs always match the BYOD-imported CSV IDs. Both
    Google and Meta adapters use the same formula today; if they ever
    diverge we'd need per-platform branches here.
    """
    return _byod_synthetic_id("camp", name)


_GADS_DAILY_BUDGETS_JPY: dict[str, int] = {
    "Brand - Exact": 30000,
    "Brand - Phrase": 15000,
    "Generic - High Intent": 80000,
    "Generic - Low Intent": 60000,
}

_GADS_GOALS: dict[str, str] = {
    "Brand - Exact": "Capture branded demand at high efficiency (target CPA <= JPY 1,500).",
    "Brand - Phrase": "Catch brand long-tail; tighten match types if cannibalization detected.",
    "Generic - High Intent": "Acquire net-new trial signups at <= JPY 12,000 CPA.",
    "Generic - Low Intent": "Top-of-funnel awareness; demote if CVR stays below 0.5%.",
}

_META_DAILY_BUDGETS_JPY: dict[str, int] = {
    "Awareness - Video": 15000,
    "Conversion - Lead Form": 50000,
}

_META_GOALS: dict[str, str] = {
    "Awareness - Video": "Build top-of-funnel awareness in JP-25-44 ICP segment.",
    "Conversion - Lead Form": "Generate sales-qualified leads at <= JPY 8,000 cost-per-lead.",
}


def google_ads_state_campaigns() -> list[dict[str, object]]:
    """Campaign records for STATE.json ``platforms.google_ads.campaigns``.

    The synthesized ``campaign_id`` matches what
    :mod:`mureo.byod.adapters.google_ads` writes to ``campaigns.csv``,
    so STATE.json and BYOD data join cleanly on the same key.
    """
    return [
        {
            "campaign_id": _campaign_id(c.name),
            "campaign_name": c.name,
            "status": "ENABLED",
            "daily_budget": _GADS_DAILY_BUDGETS_JPY[c.name],
            "campaign_goal": _GADS_GOALS[c.name],
        }
        for c in _GADS_CAMPAIGNS
    ]


def meta_ads_state_campaigns() -> list[dict[str, object]]:
    """Campaign records for STATE.json ``platforms.meta_ads.campaigns``."""
    seen: set[str] = set()
    out: list[dict[str, object]] = []
    for ad in _META_ADS:
        if ad.campaign in seen:
            continue
        seen.add(ad.campaign)
        out.append(
            {
                "campaign_id": _campaign_id(ad.campaign),
                "campaign_name": ad.campaign,
                "status": "ENABLED",
                "daily_budget": _META_DAILY_BUDGETS_JPY[ad.campaign],
                "campaign_goal": _META_GOALS[ad.campaign],
            }
        )
    return out


def meta_ads_rows() -> list[list[object]]:
    """Meta Ads Manager export — single sheet with daily breakdown.

    Header matches the verified English locale of the actual Ads
    Manager export: Day / Campaign name / Ad set name / Ad name /
    Impressions / Clicks (all) / Amount spent (JPY) / Results.
    """
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
    days = _days()
    for ad in _META_ADS:
        for i, d in enumerate(days):
            impr = ad.base_impr
            ctr = max(0.0001, ad.base_ctr + ad.ctr_slope * i)
            clicks = int(round(impr * ctr))
            spent = round(clicks * ad.cpc_jpy, 0)
            results = round(clicks * ad.base_results, 1)
            rows.append(
                [
                    d.isoformat(),
                    ad.campaign,
                    ad.ad_set,
                    ad.ad,
                    impr,
                    clicks,
                    spent,
                    results,
                ]
            )
    return rows
