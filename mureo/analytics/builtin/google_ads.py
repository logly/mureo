"""Built-in :class:`AnalyticsModule` adapter for Google Ads.

Implements two of the four Protocol methods today:

- :meth:`detect_anomalies` — wraps the pure
  :func:`mureo.analysis.anomaly_detector.detect_anomalies` over
  ``(current, baseline)`` metrics resolved by an injectable fetcher
  (defaults to :func:`fetch_google_ads_metrics`, which lazily opens
  the live or BYOD client).
- :meth:`diagnose_performance` — calls
  :meth:`GoogleAdsApiClient.get_performance_report` and packs the
  result into a :class:`PerformanceDiagnosis` with deterministic
  findings strings the workflow skill can render verbatim.

Creative-audit and budget-efficiency methods raise
:class:`NotImplementedError` — :meth:`capabilities` is the single
source of truth on what this adapter actually supports, and skills
consult it before calling.

The adapter holds no state other than the optional fetcher overrides:
the live client is constructed per-call via the factory, so
credentials can be configured after the adapter has been registered
and BYOD mode is picked up automatically.
"""

from __future__ import annotations

from typing import Any

from mureo.analysis.anomaly_detector import detect_anomalies
from mureo.analytics.builtin._common import (
    MetricsFetcher,
    PerformanceFetcher,
    to_analytics_anomalies,
)
from mureo.analytics.builtin._live_clients import (
    NoCredentialsError,
    fetch_google_ads_metrics,
    fetch_google_ads_performance_rows,
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
    """mureo-native Google Ads analytics surface."""

    platform: str = "google_ads"

    def __init__(
        self,
        metrics_fetcher: MetricsFetcher | None = None,
        performance_fetcher: PerformanceFetcher | None = None,
    ) -> None:
        # Default to the live fetcher; tests inject deterministic stubs.
        # The fetcher is async but :class:`MetricsFetcher` is declared
        # as a sync callable so the existing test stubs remain valid —
        # we re-derive the async path at the call site below.
        self._metrics_fetcher = metrics_fetcher
        self._performance_fetcher = performance_fetcher

    def capabilities(self) -> frozenset[AnalyticsCapability]:
        return _CAPABILITIES

    async def detect_anomalies(
        self,
        account_id: str,
        *,
        window_days: int = 7,
    ) -> tuple[Anomaly, ...]:
        """Detect anomalies on ``account_id`` over the trailing window.

        The injected ``metrics_fetcher`` (if any) takes precedence; it
        keeps the unit-test surface synchronous so the existing tests
        in ``tests/analytics/builtin/`` keep working. When no override
        is supplied, the adapter falls back to the async live fetcher.
        Missing credentials return an empty anomaly tuple so an
        unconfigured account never shows up as "spend dropped to
        zero" — that would be a config error, not a real anomaly.
        """
        if self._metrics_fetcher is not None:
            current, baseline = self._metrics_fetcher(
                account_id, window_days=window_days
            )
        else:
            try:
                current, baseline = await fetch_google_ads_metrics(
                    account_id, window_days=window_days
                )
            except NoCredentialsError:
                return ()

        had_prior_spend = baseline is not None and baseline.cost > 0
        detected = detect_anomalies(current, baseline, had_prior_spend=had_prior_spend)
        return to_analytics_anomalies(detected)

    async def diagnose_performance(
        self,
        account_id: str,
        *,
        scope: PerformanceScope,
    ) -> PerformanceDiagnosis:
        """Summarise ``account_id`` performance for ``scope``.

        Returns the account-level metrics over the last 7/30 days plus
        a small ranked list of findings. Per-campaign drilldown
        (``scope=PerformanceScope.DEEP``) is left to follow-up; for
        now ``DEEP`` returns the same summary marked accordingly so the
        skill can still proceed and report unavailability of the
        deeper view.

        Missing-credentials handling mirrors :meth:`detect_anomalies`:
        the live fetcher raises :class:`NoCredentialsError`, which the
        adapter renders as a sentinel :class:`PerformanceDiagnosis`
        with a credentials-specific headline so the workflow can branch
        uniformly across the two methods.
        """
        period = "LAST_7_DAYS" if scope is PerformanceScope.ACCOUNT else "LAST_30_DAYS"

        if self._performance_fetcher is not None:
            rows = await self._performance_fetcher(account_id, period)
        else:
            try:
                rows = await fetch_google_ads_performance_rows(account_id, period)
            except NoCredentialsError:
                return PerformanceDiagnosis(
                    platform=self.platform,
                    account_id=account_id,
                    scope=scope,
                    headline="google_ads credentials not configured",
                    findings=(),
                )

        return _summarise_performance(
            platform=self.platform,
            account_id=account_id,
            scope=scope,
            rows=rows,
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


def _summarise_performance(
    *,
    platform: str,
    account_id: str,
    scope: PerformanceScope,
    rows: list[dict[str, Any]],
) -> PerformanceDiagnosis:
    """Build a :class:`PerformanceDiagnosis` from raw performance rows.

    Pure function so tests can exercise the rendering without
    constructing the adapter or stubbing a fetcher.
    """
    if not rows:
        return PerformanceDiagnosis(
            platform=platform,
            account_id=account_id,
            scope=scope,
            headline="no performance data available",
            findings=(),
        )

    cost = 0.0
    impressions = 0
    clicks = 0
    conversions = 0.0
    for row in rows:
        metrics = row.get("metrics") or {}
        if isinstance(metrics, dict):
            cost += float(metrics.get("cost", 0) or 0)
            impressions += int(metrics.get("impressions", 0) or 0)
            clicks += int(metrics.get("clicks", 0) or 0)
            conversions += float(metrics.get("conversions", 0) or 0)

    cpa = (cost / conversions) if conversions > 0 else None
    ctr = (clicks / impressions) if impressions > 0 else None

    findings: list[str] = [
        f"{len(rows)} campaign(s) reporting",
        f"spend={cost:,.0f}, conversions={conversions:.1f}",
    ]
    if cpa is not None:
        findings.append(f"CPA={cpa:,.0f}")
    if ctr is not None:
        findings.append(f"CTR={ctr*100:.2f}%")
    if scope is PerformanceScope.DEEP:
        findings.append("per-campaign drilldown not yet implemented for this adapter")

    metrics_tuple: tuple[tuple[str, float], ...] = (
        ("cost", cost),
        ("impressions", float(impressions)),
        ("clicks", float(clicks)),
        ("conversions", conversions),
    )
    if cpa is not None:
        metrics_tuple = (*metrics_tuple, ("cpa", cpa))
    if ctr is not None:
        metrics_tuple = (*metrics_tuple, ("ctr", ctr))

    headline = f"{platform}: {len(rows)} campaigns, spend={cost:,.0f}"
    return PerformanceDiagnosis(
        platform=platform,
        account_id=account_id,
        scope=scope,
        headline=headline,
        findings=tuple(findings),
        metrics=metrics_tuple,
    )


__all__ = ["GoogleAdsAnalyticsModule"]
