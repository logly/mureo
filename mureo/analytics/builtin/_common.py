"""Shared helpers for built-in analytics adapters.

The two adapters (google_ads / meta_ads) translate the existing pure
detector's :class:`mureo.analysis.anomaly_detector.Anomaly` /
``Severity`` into the analytics-package's
:class:`mureo.analytics.models.Anomaly` /
:class:`mureo.analytics.models.AnomalySeverity`. The translation is
mechanical and identical for both platforms, so it lives here.

A :class:`MetricsFetcher` callable abstracts how an adapter obtains a
``(current, baseline)`` pair for a given account: the live adapter
will eventually call the platform client; tests inject a deterministic
stub. Keeping the fetcher injectable means the adapter has no hard
dependency on the platform client module, which keeps imports cheap and
avoids cycles at registration time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from typing import TYPE_CHECKING, Any, Protocol

from mureo.analysis.anomaly_detector import (
    Anomaly as _DetectorAnomaly,
)
from mureo.analysis.anomaly_detector import (
    Severity as _DetectorSeverity,
)
from mureo.analytics.builtin._row_types import (
    GoogleAdRow,
    GoogleByodPerformanceRow,
    GoogleLivePerformanceRow,
    GoogleMetricsDict,
    GooglePerformanceRow,
    MetaActionEntry,
    MetaAdRow,
    MetaByodPerformanceRow,
    MetaLivePerformanceRow,
    MetaPerformanceRow,
)
from mureo.analytics.models import Anomaly, AnomalySeverity

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mureo.analysis.anomaly_detector import CampaignMetrics


def google_row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    """Return the metrics view of a Google Ads performance row.

    Live :func:`mureo.google_ads.mappers.map_performance_report` nests
    metrics under ``row["metrics"]``; BYOD
    :class:`mureo.byod.clients.ByodGoogleAdsClient.get_performance_report`
    returns them flat at the top level. Both are valid factory outputs
    so the helper accepts either — strictly preferring the nested view
    when it is a non-empty dict (the live mapper always populates it),
    falling back to the row itself for the BYOD shape.

    The parameter is typed as ``dict[str, Any]`` rather than the
    :class:`GooglePerformanceRow` union because callers pass the raw
    factory output and TypedDicts cannot freely accept ``dict[str, Any]``
    at the call site without a `cast`. The expected runtime shape is
    documented by :class:`GoogleLivePerformanceRow` /
    :class:`GoogleByodPerformanceRow`.
    """
    nested = row.get("metrics")
    if isinstance(nested, dict) and nested:
        return nested
    return row


def meta_row_conversions(
    row: dict[str, Any],
    *,
    conversion_action_types: Collection[str] | None = None,
) -> float:
    """Return the conversion count for a Meta performance row.

    Live: conversions live inside an ``actions`` list keyed by
    ``action_type``. BYOD: pre-aggregated under a top-level
    ``conversions`` field with no ``actions`` list. Detected during
    the #120 live-wiring validation — accepting only the live shape
    silently zeroes BYOD conversions.

    ``conversion_action_types`` (#342) is the operator's per-account override
    for which action_types count as conversions; ``None`` uses the built-in
    deduped generic set. It applies only to the live ``actions`` shape (BYOD
    rows carry a pre-aggregated total).

    Expected runtime shape: :class:`MetaLivePerformanceRow` /
    :class:`MetaByodPerformanceRow`. Same caller-ergonomics rationale
    as :func:`google_row_metrics` for the looser parameter type.
    """
    actions = row.get("actions")
    if isinstance(actions, list):
        # #340 — count via the canonical exact-match counter (deduped
        # generic conversion action_types) instead of a substring scan,
        # which double-counted aggregate+component aliases (lead +
        # offsite_conversion.fb_pixel_lead) and swept in custom-conversion
        # slugs. Lazy import keeps adapter registration free of the
        # mureo.meta_ads client weight (this runs only on the live path).
        from mureo.meta_ads._conversion_count import count_conversions_from_actions

        return count_conversions_from_actions(
            actions, conversion_action_types=conversion_action_types
        )
    return float(row.get("conversions") or 0)


# Type alias used by both built-in adapters' ``diagnose_performance``.
# Tests inject a deterministic stub; production paths resolve to the
# live client inside the adapter.
PerformanceFetcher = Callable[[str, str], Awaitable[list[dict[str, object]]]]


# Per-campaign fan-out fetcher — successor to the legacy
# :class:`MetricsFetcher` aggregate path. Returns a mapping of
# ``campaign_id`` to ``(current, baseline)`` so the detector runs once
# per campaign instead of once per account. ``baseline`` is ``None``
# when the campaign has no usable prior-window data.
if TYPE_CHECKING:
    from mureo.analysis.anomaly_detector import CampaignMetrics

PerCampaignMetricsFetcher = Callable[
    ...,
    "Awaitable[dict[str, tuple[CampaignMetrics, CampaignMetrics | None]]]",
]


_SEVERITY_MAP: dict[_DetectorSeverity, AnomalySeverity] = {
    _DetectorSeverity.CRITICAL: AnomalySeverity.CRITICAL,
    _DetectorSeverity.HIGH: AnomalySeverity.HIGH,
}


def to_analytics_anomaly(source: _DetectorAnomaly) -> Anomaly:
    """Translate a detector anomaly into the analytics-package model.

    Field-for-field mapping. The severity enum is a separate type so
    the two anomaly modules can evolve independently without ABI risk
    (the analytics models are part of the plugin ABI;
    ``anomaly_detector`` is internal).
    """
    return Anomaly(
        campaign_id=source.campaign_id,
        metric=source.metric,
        severity=_SEVERITY_MAP[source.severity],
        current_value=source.current_value,
        baseline_value=source.baseline_value,
        deviation_pct=source.deviation_pct,
        sample_size=source.sample_size,
        message=source.message,
        recommended_action=source.recommended_action,
    )


def to_analytics_anomalies(
    sources: Iterable[_DetectorAnomaly],
) -> tuple[Anomaly, ...]:
    """Batch helper for :func:`to_analytics_anomaly`."""
    return tuple(to_analytics_anomaly(a) for a in sources)


class MetricsFetcher(Protocol):
    """Callable returning a ``(current, baseline)`` pair for one account.

    Adapter ↔ live-client wiring deferred via this Protocol — see the
    module docstring for why.

    Args:
        account_id: Platform-scoped account identifier.
        window_days: Trailing window the detector should use.

    Returns:
        ``(current, baseline)`` — ``baseline`` may be ``None`` when the
        account is too new to support a comparison.
    """

    def __call__(
        self,
        account_id: str,
        *,
        window_days: int,
    ) -> tuple[CampaignMetrics, CampaignMetrics | None]: ...


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
    "MetricsFetcher",
    "PerCampaignMetricsFetcher",
    "PerformanceFetcher",
    "google_row_metrics",
    "meta_row_conversions",
    "to_analytics_anomalies",
    "to_analytics_anomaly",
]
