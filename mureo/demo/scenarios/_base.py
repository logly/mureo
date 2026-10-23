"""Shared types and helpers for the demo scenario registry.

A :class:`Scenario` bundles everything ``mureo demo init`` needs for a
single named demo: the XLSX sheet rows, the STATE.json document, and
the STRATEGY.md text. Each registered scenario is a frozen dataclass
instance — adding a new one is "drop a module under
``mureo/demo/scenarios/`` and register it in ``__init__``".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from mureo.byod.adapters.google_ads import _synthetic_id as _byod_synthetic_id

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class Scenario:
    """A single named demo dataset.

    Attributes:
        name: CLI key (kebab-case, e.g. ``"seasonality-trap"``).
        title: Human-readable title for ``mureo demo list``.
        blurb: One-line description for ``mureo demo list``.
        days: Length of the data period in days.
        end_date: Last calendar day in the data.
        brand: Synthetic brand name used in copy and identifiers.
        sheet_rows: Mapping of XLSX sheet name -> rows (header first).
            Required keys: ``campaigns``, ``ad_groups``, ``search_terms``,
            ``keywords`` (Google Ads), ``meta_ads`` (Meta Ads export).
        state_doc: Full STATE.json document (must round-trip through
            :func:`mureo.context.state.parse_state`). Use schema v2 with
            per-platform campaigns and an ``action_log`` array.
        strategy_md: STRATEGY.md text — should include numeric goals
            and explicit constraints so workflow skills can detect
            violations.
    """

    name: str
    title: str
    blurb: str
    days: int
    end_date: date
    brand: str
    sheet_rows: Mapping[str, Sequence[Sequence[object]]]
    state_doc: Mapping[str, object]
    strategy_md: str
    # When False, the scenario's diagnostic story relies on a sparse
    # or absent action_log (e.g. strategy-drift demos undocumented
    # changes by a manager — empty action_log around active changes
    # is itself the diagnostic signal). Contract tests skip the >=3
    # entries floor only for these scenarios.
    requires_action_log: bool = True


def campaign_id(name: str) -> str:
    """Synthesize the campaign_id BYOD will assign to ``name``.

    Imports the BYOD adapter's helper directly so any change to the
    formula automatically propagates to the demo's STATE.json. Both
    Google Ads and Meta Ads adapters use the same formula today; if
    they diverge in the future we'd need per-platform branches here.
    """
    return _byod_synthetic_id("camp", name)


@dataclass(frozen=True)
class GoogleCampaignSpec:
    """Per-campaign Google Ads rates a scenario's rows derive from.

    Attributes:
        name: Campaign name as it appears in the sheets.
        daily_impr: Baseline daily impressions.
        ctr: Click-through rate.
        cpc: Cost per click.
        cvr: Conversion rate per click.
        start_day: First active day index; ``0`` = active from day 0.
    """

    name: str
    daily_impr: int
    ctr: float
    cpc: float
    cvr: float
    start_day: int = 0


def date_for_day(day: int, *, end_date: date, days: int) -> date:
    """Return the calendar date of day index ``day`` (0 = first day)."""
    return end_date - timedelta(days=days - 1 - day)


def action_iso(
    day: int, hour: int = 10, minute: int = 0, *, end_date: date, days: int
) -> str:
    """Build a ``YYYY-MM-DDTHH:MM:SS+09:00`` timestamp for ``day``."""
    d = date_for_day(day, end_date=end_date, days=days)
    dt = datetime(
        d.year, d.month, d.day, hour, minute, tzinfo=timezone(timedelta(hours=9))
    )
    return dt.isoformat(timespec="seconds")


def build_google_ad_groups_rows(
    campaigns: Sequence[GoogleCampaignSpec],
    ad_groups: Iterable[tuple[str, str, float]],
    *,
    end_date: date,
    days: int,
    impr_factor: Callable[[str, int], float] | None = None,
    is_active: Callable[[GoogleCampaignSpec, int], bool] | None = None,
) -> list[list[object]]:
    """Build the daily ``ad_groups`` sheet (header first).

    Args:
        campaigns: Campaign specs; ``ad_groups`` refers to them by name.
        ad_groups: ``(campaign_name, ad_group_name, share_of_campaign)``.
        end_date: Last calendar day in the data.
        days: Length of the data period in days.
        impr_factor: Per-``(campaign_name, day)`` impression multiplier
            for scenarios whose story moves demand (default ``1.0``).
        is_active: Per-``(campaign, day)`` filter for scenarios whose
            campaigns start mid-period; inactive days emit no row.
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
    by_camp = {c.name: c for c in campaigns}
    for camp_name, ag_name, share in ad_groups:
        c = by_camp[camp_name]
        for d in range(days):
            if is_active is not None and not is_active(c, d):
                continue
            day_iso = date_for_day(d, end_date=end_date, days=days).isoformat()
            factor = impr_factor(camp_name, d) if impr_factor is not None else 1.0
            impr = int(round(c.daily_impr * share * factor))
            clicks = int(round(impr * c.ctr))
            cost = round(clicks * c.cpc, 2)
            conv = round(clicks * c.cvr, 2)
            rows.append([day_iso, camp_name, ag_name, impr, clicks, cost, conv])
    return rows


def build_google_search_terms_rows(
    search_terms: Iterable[Sequence[object]],
) -> list[list[object]]:
    """Build the aggregated ``search_terms`` sheet (header first).

    Each entry is ``(search_term, campaign, ad_group, impressions,
    clicks, cost, conversions)``.
    """
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
    for term, camp, ag, impr, clicks, cost, conv in search_terms:
        rows.append([term, camp, ag, impr, clicks, cost, conv])
    return rows


def build_google_keywords_rows(
    keywords: Iterable[Sequence[object]],
) -> list[list[object]]:
    """Build the aggregated ``keywords`` sheet (header first).

    Each entry is ``(keyword, match_type, quality_score, campaign,
    ad_group, impressions, clicks, cost, conversions)``.
    """
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
    for kw, mt, qs, camp, ag, impr, clicks, cost, conv in keywords:
        rows.append([kw, mt, qs, camp, ag, impr, clicks, cost, conv])
    return rows
