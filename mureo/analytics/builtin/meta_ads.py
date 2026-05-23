"""Built-in :class:`AnalyticsModule` adapter for Meta Ads.

Parallel structure to
:class:`mureo.analytics.builtin.google_ads.GoogleAdsAnalyticsModule`.
See that module's docstring for the design notes that apply to both.

The Meta-specific difference today is conceptual rather than
implementation: ``diagnose_performance`` is the natural home for the
``result_indicator`` CV-definition mismatch check (clicks vs
``offsite_conversion.fb_pixel_lead``) that the
``meta_ads_insights_report`` MCP tool surfaces. The mismatch
detector lives in :mod:`mureo.meta_ads._analysis`; this adapter will
delegate to it once the live wiring lands.
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


class MetaAdsAnalyticsModule(AnalyticsModule):
    """mureo-native Meta Ads analytics surface."""

    platform: str = "meta_ads"

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
        return PerformanceDiagnosis(
            platform=self.platform,
            account_id=account_id,
            scope=scope,
            headline="meta_ads diagnosis not yet wired to live client",
            findings=(),
        )

    async def audit_creative(self, account_id: str) -> CreativeAudit:
        raise NotImplementedError(
            "MetaAdsAnalyticsModule does not advertise AUDIT_CREATIVE; "
            "consult capabilities() before calling"
        )

    async def analyze_budget_efficiency(self, account_id: str) -> BudgetEfficiency:
        raise NotImplementedError(
            "MetaAdsAnalyticsModule does not advertise "
            "ANALYZE_BUDGET_EFFICIENCY; consult capabilities() before calling"
        )


__all__ = ["MetaAdsAnalyticsModule"]
