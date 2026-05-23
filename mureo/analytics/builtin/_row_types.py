"""TypedDict definitions for the platform performance / list_ads rows
the built-in adapters consume.

The aggregators and scorers previously typed rows as
``list[dict[str, Any]]``. That works at runtime but loses every type
guarantee the moment a row is touched — `row.get("cost")` returns
`Any`, mypy cannot verify field presence, and an IDE cannot suggest
field names. Promoting the row shapes to TypedDicts:

- documents the field set we depend on (one source of truth shared by
  scorer / aggregator / summariser);
- gives mypy enough information to flag a misspelled key or a missing
  type cast on the integer fields;
- keeps the dataclass-frozen public ABI unchanged — these dicts are
  *what the platform client returns to us*, not what we expose to
  plugins.

Two physical shapes for each platform — live and BYOD — share a
common metric vocabulary. We model them as separate ``TypedDict(
total=False)`` classes and then ``Union`` them; ``total=False`` lets
the optional-presence reality of real API responses through without
forcing exhaustive construction at every call site.

Public re-exports live in :mod:`mureo.analytics.builtin._common`
under the same names so downstream callers (including future
plugin-side TypedDict consumers, if we ever offer them) have one
import path. The helpers ``google_row_metrics`` and
``meta_row_conversions`` already exposed from ``_common`` consume
these types directly.
"""

from __future__ import annotations

from typing import TypedDict


class GoogleMetricsDict(TypedDict, total=False):
    """Inner ``metrics`` view returned by the live Google Ads mapper.

    All values are optional because:
    - the mapper omits keys whose underlying field was ``None``;
    - day-grain or aggregated reports may strip a column entirely.

    Plus a few derived keys (``cpa``, ``ctr``, ``average_cpc``,
    ``cost_per_conversion``) that the mapper computes — included so
    mypy does not flag adapter code that reads them.
    """

    cost: float
    cost_micros: int
    impressions: int
    clicks: int
    conversions: float
    ctr: float
    average_cpc: float
    average_cpc_micros: int
    cost_per_conversion: float
    cost_per_conversion_micros: int


class GoogleLivePerformanceRow(TypedDict, total=False):
    """Shape returned by ``mureo.google_ads.mappers.map_performance_report``.

    Metrics live under the ``metrics`` sub-key. Campaign metadata is
    at the top level.
    """

    campaign_id: str
    campaign_name: str
    metrics: GoogleMetricsDict


class GoogleByodPerformanceRow(TypedDict, total=False):
    """Shape returned by
    :meth:`mureo.byod.clients.ByodGoogleAdsClient.get_performance_report`.

    Same metric vocabulary as :class:`GoogleMetricsDict` but flat at
    the top level (no ``metrics`` sub-key).
    """

    campaign_id: str
    campaign_name: str
    cost: float
    impressions: int
    clicks: int
    conversions: float
    ctr: float
    average_cpc: float
    cost_per_conversion: float


# Union accepted by all aggregators / scorers. Both shapes are valid
# factory outputs, so the helpers in ``_common`` accept either.
GooglePerformanceRow = GoogleLivePerformanceRow | GoogleByodPerformanceRow


class MetaActionEntry(TypedDict, total=False):
    """One element of the live Meta ``actions`` list.

    The Marketing API returns ``actions: [{action_type, value}, ...]``
    keyed by event name (``offsite_conversion.fb_pixel_lead``,
    ``link_click``, etc.).
    """

    action_type: str
    value: float


class MetaLivePerformanceRow(TypedDict, total=False):
    """Shape returned by :class:`MetaAdsApiClient.get_performance_report`.

    Conversions live inside ``actions``; the wrapper extracts them via
    :func:`meta_row_conversions`.
    """

    campaign_id: str
    campaign_name: str
    spend: float
    impressions: int
    clicks: int
    cpc: float
    cpm: float
    ctr: float
    reach: int
    frequency: float
    actions: list[MetaActionEntry]
    date_start: str
    date_stop: str


class MetaByodPerformanceRow(TypedDict, total=False):
    """Shape returned by
    :meth:`mureo.byod.clients.ByodMetaAdsClient.get_performance_report`.

    Conversions are pre-aggregated into a top-level field; the
    ``result_indicator`` is the BYOD-native equivalent of the live
    ``actions`` join.
    """

    campaign_id: str
    campaign_name: str
    spend: float
    impressions: int
    clicks: int
    conversions: float
    ctr: float
    cpc: float
    cpa: float
    result_indicator: str


MetaPerformanceRow = MetaLivePerformanceRow | MetaByodPerformanceRow


class GoogleAdRow(TypedDict, total=False):
    """Subset of ``list_ads`` row fields the creative audit reads.

    Covers both the live (mapper-produced) and BYOD (flat) shapes
    since both keep the audit-relevant keys at the top level.
    ``type`` is split into ``"RESPONSIVE_SEARCH_AD"`` /
    ``"RESPONSIVE_DISPLAY_AD"`` etc. — see :mod:`_creative_audit`.
    """

    id: str
    ad_id: str
    campaign_id: str
    campaign: dict[str, str]
    ad_group_id: str
    type: str
    ad_type: str
    headlines: list[object]  # list[str] | list[dict[str, str]]
    descriptions: list[object]
    long_headline: str
    marketing_images: list[object]
    square_marketing_images: list[object]
    final_url: str
    status: str


class MetaAdRow(TypedDict, total=False):
    """Subset of Meta ``list_ads`` row fields the creative audit reads.

    Live wraps creative fields under ``creative`` / ``object_story_spec``;
    BYOD may keep them flat. The audit code accepts either via
    :func:`mureo.analytics.builtin._creative_audit.audit_meta_ads_creatives`.
    """

    id: str
    ad_id: str
    name: str
    campaign_id: str
    adset_id: str
    status: str
    title: str
    body: str
    image_url: str
    thumbnail_url: str
    creative: dict[str, object]
    object_story_spec: dict[str, object]


__all__ = [
    "GoogleAdRow",
    "GoogleByodPerformanceRow",
    "GoogleLivePerformanceRow",
    "GoogleMetricsDict",
    "GooglePerformanceRow",
    "MetaActionEntry",
    "MetaAdRow",
    "MetaByodPerformanceRow",
    "MetaLivePerformanceRow",
    "MetaPerformanceRow",
]
