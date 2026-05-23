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

from typing import TYPE_CHECKING, Protocol

from mureo.analysis.anomaly_detector import (
    Anomaly as _DetectorAnomaly,
)
from mureo.analysis.anomaly_detector import (
    Severity as _DetectorSeverity,
)
from mureo.analytics.models import Anomaly, AnomalySeverity

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mureo.analysis.anomaly_detector import CampaignMetrics


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
    "MetricsFetcher",
    "to_analytics_anomalies",
    "to_analytics_anomaly",
]
