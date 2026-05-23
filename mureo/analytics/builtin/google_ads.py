"""Built-in :class:`AnalyticsModule` adapter for Google Ads.

Implements two of the four Protocol methods today:

- :meth:`detect_anomalies` — delegates to
  :func:`mureo.analysis.anomaly_detector.detect_anomalies` after
  resolving ``(current, baseline)`` metrics via an injectable fetcher.
- :meth:`diagnose_performance` — returns a thin
  :class:`PerformanceDiagnosis` summarising what the workflow skill
  already surfaces via ``google_ads_performance_report``.

Creative-audit and budget-efficiency methods raise
:class:`NotImplementedError` so :meth:`capabilities` is the single
source of truth on what this adapter actually supports — skills
SHOULD consult capabilities before calling.
"""

from __future__ import annotations

from mureo.analysis.anomaly_detector import detect_anomalies
from mureo.analytics.builtin._common import (
    MetricsFetcher,
    to_analytics_anomalies,
)
from mureo.analytics.models import (
    Anomaly,
    BudgetEfficiency,
    CreativeAudit,
    PerformanceDiagnosis,
    PerformanceScope,
)
from mureo.analytics.protocol import AnalyticsCapability, AnalyticsModule

_CAPABILITIES: frozenset[AnalyticsCapability] = frozenset(
    {
        AnalyticsCapability.DETECT_ANOMALIES,
        AnalyticsCapability.DIAGNOSE_PERFORMANCE,
    }
)


class GoogleAdsAnalyticsModule(AnalyticsModule):
    """mureo-native Google Ads analytics surface.

    Stateless: no client is constructed at instantiation time so the
    registry can build one with no arguments. Live wiring to the
    Google Ads client happens lazily inside the injected fetcher.
    """

    platform: str = "google_ads"

    def __init__(self, metrics_fetcher: MetricsFetcher | None = None) -> None:
        self._metrics_fetcher = metrics_fetcher

    def capabilities(self) -> frozenset[AnalyticsCapability]:
        return _CAPABILITIES

    async def detect_anomalies(
        self,
        account_id: str,
        *,
        window_days: int = 7,
    ) -> tuple[Anomaly, ...]:
        """Detect anomalies on ``account_id`` via the pure detector.

        Without an injected fetcher this returns an empty tuple — the
        adapter is registered eagerly at import time, before the live
        Google Ads client is configured, so the silent-empty default
        is the safe behaviour. Tests inject a deterministic fetcher.
        """
        if self._metrics_fetcher is None:
            return ()

        current, baseline = self._metrics_fetcher(account_id, window_days=window_days)
        had_prior_spend = baseline is not None and baseline.cost > 0
        detected = detect_anomalies(current, baseline, had_prior_spend=had_prior_spend)
        return to_analytics_anomalies(detected)

    async def diagnose_performance(
        self,
        account_id: str,
        *,
        scope: PerformanceScope,
    ) -> PerformanceDiagnosis:
        """Return a thin diagnosis stub for ``account_id``.

        The live diagnosis pipeline lives in
        :mod:`mureo.google_ads._analysis` and is exposed via the
        ``google_ads_performance_report`` MCP tool. This adapter returns
        the shape a skill expects; concrete delegation will be wired in
        the same follow-up that wires :meth:`detect_anomalies` to the
        live client.
        """
        return PerformanceDiagnosis(
            platform=self.platform,
            account_id=account_id,
            scope=scope,
            headline="google_ads diagnosis not yet wired to live client",
            findings=(),
        )

    async def audit_creative(self, account_id: str) -> CreativeAudit:
        raise NotImplementedError(
            "GoogleAdsAnalyticsModule does not advertise AUDIT_CREATIVE; "
            "consult capabilities() before calling"
        )

    async def analyze_budget_efficiency(self, account_id: str) -> BudgetEfficiency:
        raise NotImplementedError(
            "GoogleAdsAnalyticsModule does not advertise "
            "ANALYZE_BUDGET_EFFICIENCY; consult capabilities() before calling"
        )


__all__ = ["GoogleAdsAnalyticsModule"]
