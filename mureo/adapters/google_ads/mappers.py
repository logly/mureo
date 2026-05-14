"""Pure ``dict`` → frozen-dataclass converters for the Google Ads adapter.

Every function in this module is side-effect-free: it consumes the
legacy ``dict`` shape produced by ``mureo.google_ads.mappers`` and
returns a frozen dataclass from :mod:`mureo.core.providers.models`.

Module foundation rule
----------------------
Imports are restricted to stdlib plus
:mod:`mureo.core.providers.models` /
:mod:`mureo.core.providers.capabilities` /
:mod:`mureo.adapters.google_ads.errors`. The AST scan in
``tests/adapters/google_ads/test_imports.py`` enforces this allowlist.

Status string convention
------------------------
Adapter-internal enum maps use the **upper-case** wire string the Google
Ads platform emits (e.g. ``"ENABLED"``). The mapper raises
:class:`ValueError` on unknown strings — no silent fallback to a default
member.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Campaign,
    CampaignStatus,
    DailyReportRow,
    Extension,
    ExtensionKind,
    ExtensionStatus,
    Keyword,
    KeywordMatchType,
    KeywordStatus,
    SearchTerm,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


# ---------------------------------------------------------------------------
# Status / enum coercion maps (wire-string → enum)
# ---------------------------------------------------------------------------


_CAMPAIGN_STATUS_MAP: dict[str, CampaignStatus] = {
    "ENABLED": CampaignStatus.ENABLED,
    "PAUSED": CampaignStatus.PAUSED,
    "REMOVED": CampaignStatus.REMOVED,
}


_AD_STATUS_MAP: dict[str, AdStatus] = {
    "ENABLED": AdStatus.ENABLED,
    "PAUSED": AdStatus.PAUSED,
    "REMOVED": AdStatus.REMOVED,
}


_KEYWORD_STATUS_MAP: dict[str, KeywordStatus] = {
    "ENABLED": KeywordStatus.ENABLED,
    "PAUSED": KeywordStatus.PAUSED,
    "REMOVED": KeywordStatus.REMOVED,
}


_EXTENSION_STATUS_MAP: dict[str, ExtensionStatus] = {
    "ENABLED": ExtensionStatus.ENABLED,
    "PAUSED": ExtensionStatus.PAUSED,
    "REMOVED": ExtensionStatus.REMOVED,
}


_MATCH_TYPE_MAP: dict[str, KeywordMatchType] = {
    "EXACT": KeywordMatchType.EXACT,
    "PHRASE": KeywordMatchType.PHRASE,
    "BROAD": KeywordMatchType.BROAD,
}


def _coerce(raw: Any, mapping: dict[str, Any], *, field: str) -> Any:
    """Return ``mapping[str(raw).upper()]`` or raise ``ValueError``.

    The error message includes both the offending value and the field
    name so callers can locate the failure point.
    """
    if raw is None:
        raise ValueError(f"missing {field} (got None)")
    key = str(raw).upper()
    try:
        return mapping[key]
    except KeyError as exc:
        raise ValueError(
            f"unknown {field}: {raw!r} (expected one of {sorted(mapping)})"
        ) from exc


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


def to_campaign(raw: dict[str, Any], *, account_id: str) -> Campaign:
    """Build a :class:`Campaign` from the legacy mapper dict."""
    return Campaign(
        id=str(raw["id"]),
        account_id=account_id,
        name=str(raw["name"]),
        status=_coerce(
            raw.get("status"), _CAMPAIGN_STATUS_MAP, field="campaign status"
        ),
        daily_budget_micros=int(raw.get("budget_amount_micros") or 0),
    )


def to_campaigns(
    rows: Iterable[dict[str, Any]], *, account_id: str
) -> tuple[Campaign, ...]:
    """Build a tuple of :class:`Campaign` from any iterable of legacy rows."""
    return tuple(to_campaign(row, account_id=account_id) for row in rows)


# ---------------------------------------------------------------------------
# Ad
# ---------------------------------------------------------------------------


def to_ad(raw: dict[str, Any], *, account_id: str, campaign_id: str) -> Ad:
    """Build an :class:`Ad` from the legacy mapper dict.

    The ``final_url`` field is derived from the first element of
    ``final_urls`` (empty string when absent) to match the
    Protocol-boundary single-URL contract.
    """
    final_urls = raw.get("final_urls") or []
    first_url = str(final_urls[0]) if final_urls else ""
    return Ad(
        id=str(raw["id"]),
        account_id=account_id,
        campaign_id=campaign_id,
        status=_coerce(raw.get("status"), _AD_STATUS_MAP, field="ad status"),
        headlines=tuple(str(h) for h in raw.get("headlines") or ()),
        descriptions=tuple(str(d) for d in raw.get("descriptions") or ()),
        final_url=first_url,
    )


# ---------------------------------------------------------------------------
# Keyword
# ---------------------------------------------------------------------------


def to_keyword(raw: dict[str, Any], *, account_id: str, campaign_id: str) -> Keyword:
    """Build a :class:`Keyword` from the legacy mapper dict."""
    return Keyword(
        id=str(raw["id"]),
        account_id=account_id,
        campaign_id=campaign_id,
        text=str(raw["text"]),
        match_type=_coerce(
            raw.get("match_type"), _MATCH_TYPE_MAP, field="keyword match_type"
        ),
        status=_coerce(raw.get("status"), _KEYWORD_STATUS_MAP, field="keyword status"),
    )


# ---------------------------------------------------------------------------
# Extension
# ---------------------------------------------------------------------------


def to_extension(
    raw: dict[str, Any], *, account_id: str, kind: ExtensionKind
) -> Extension:
    """Build an :class:`Extension` from a kind-specific legacy dict.

    Conversion-action rows use the ``name`` key for the human-readable
    label; sitelink / callout rows use ``text``. ``text`` takes priority
    when both are present.
    """
    label_raw = raw.get("text") or raw.get("name") or ""
    return Extension(
        id=str(raw["id"]),
        account_id=account_id,
        kind=kind,
        status=_coerce(
            raw.get("status"), _EXTENSION_STATUS_MAP, field="extension status"
        ),
        text=str(label_raw),
    )


# ---------------------------------------------------------------------------
# DailyReportRow
# ---------------------------------------------------------------------------


def to_daily_report_row(raw: dict[str, Any]) -> DailyReportRow:
    """Build a :class:`DailyReportRow` from a GAQL ``segments.date`` row.

    ``date`` accepts either a ``datetime.date`` (already parsed) or an
    ISO-8601 ``YYYY-MM-DD`` string. Any other shape raises
    :class:`ValueError`.
    """
    raw_date = raw.get("date")
    parsed_date = _parse_date(raw_date)
    return DailyReportRow(
        date=parsed_date,
        impressions=int(raw.get("impressions") or 0),
        clicks=int(raw.get("clicks") or 0),
        cost_micros=int(raw.get("cost_micros") or 0),
        conversions=float(raw.get("conversions") or 0.0),
    )


def _parse_date(value: Any) -> date:
    """Return ``value`` coerced to ``datetime.date``."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        # ``datetime.strptime`` rejects ``"not-a-date"`` cleanly with
        # ``ValueError`` — exactly the contract the mapper tests rely on.
        return datetime.strptime(value, "%Y-%m-%d").date()  # noqa: DTZ007
    raise ValueError(f"unparseable date value: {value!r}")


# ---------------------------------------------------------------------------
# SearchTerm
# ---------------------------------------------------------------------------


def to_search_term(raw: dict[str, Any], *, campaign_id: str) -> SearchTerm:
    """Build a :class:`SearchTerm` from a legacy search-term row.

    Accepts both the nested ``metrics`` dict (produced by
    ``mureo.google_ads.mappers.map_search_term``) and a flat dict (used
    by adapter unit tests).
    """
    nested = raw.get("metrics")
    metrics: dict[str, Any] = nested if isinstance(nested, dict) else raw
    return SearchTerm(
        text=str(raw.get("search_term") or ""),
        campaign_id=campaign_id,
        impressions=int(metrics.get("impressions") or 0),
        clicks=int(metrics.get("clicks") or 0),
    )


__all__ = [
    "to_ad",
    "to_campaign",
    "to_campaigns",
    "to_daily_report_row",
    "to_extension",
    "to_keyword",
    "to_search_term",
]
