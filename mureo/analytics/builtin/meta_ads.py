"""Built-in :class:`AnalyticsModule` adapter for Meta Ads.

Parallel structure to
:class:`mureo.analytics.builtin.google_ads.GoogleAdsAnalyticsModule`.
See that module's docstring for the shared design notes.

Meta-specific:

- :meth:`diagnose_performance` does a lightweight ``result_indicator``
  CV-definition check on top of the account-level summary: if some
  campaigns are optimised for ``link_click`` while others report
  ``offsite_conversion.fb_pixel_lead`` as their "result", the headline
  metric blends two incompatible definitions and the workflow should
  flag the mismatch before any rescue action. The check is heuristic
  and conservative — it surfaces a finding rather than gating downstream
  steps. The full deep CV-mismatch analysis still lives in
  :mod:`mureo.meta_ads._analysis` and is reachable via
  ``meta_ads_insights_report``; this adapter only previews it.
"""

from __future__ import annotations

from mureo.analysis.anomaly_detector import detect_anomalies
from mureo.analytics.builtin._common import (
    MetricsFetcher,
    PerformanceFetcher,
    to_analytics_anomalies,
)
from mureo.analytics.builtin._live_clients import (
    NoCredentialsError,
    fetch_meta_ads_metrics,
    fetch_meta_ads_performance_rows,
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


# Heuristic: action_types we treat as "click-style" vs "conversion-style"
# results. A mix across campaigns is what triggers the CV-mismatch
# finding. Kept as module-level constants so tests can monkey-patch
# them if Meta introduces new action_type names.
_CLICK_RESULT_PREFIXES: tuple[str, ...] = ("link_click", "post_engagement")
_CONVERSION_RESULT_TOKENS: tuple[str, ...] = (
    "offsite_conversion",
    "lead",
    "purchase",
    "complete_registration",
)


class MetaAdsAnalyticsModule(AnalyticsModule):
    """mureo-native Meta Ads analytics surface."""

    platform: str = "meta_ads"

    def __init__(
        self,
        metrics_fetcher: MetricsFetcher | None = None,
        performance_fetcher: PerformanceFetcher | None = None,
    ) -> None:
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
        if self._metrics_fetcher is not None:
            current, baseline = self._metrics_fetcher(
                account_id, window_days=window_days
            )
        else:
            try:
                current, baseline = await fetch_meta_ads_metrics(
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
        """Same missing-credentials sentinel as Google Ads — see that
        adapter's docstring for the policy rationale.
        """
        period = "last_7d" if scope is PerformanceScope.ACCOUNT else "last_30d"

        if self._performance_fetcher is not None:
            rows = await self._performance_fetcher(account_id, period)
        else:
            try:
                rows = await fetch_meta_ads_performance_rows(account_id, period)
            except NoCredentialsError:
                return PerformanceDiagnosis(
                    platform=self.platform,
                    account_id=account_id,
                    scope=scope,
                    headline="meta_ads credentials not configured",
                    findings=(),
                )

        return _summarise_meta_performance(
            platform=self.platform,
            account_id=account_id,
            scope=scope,
            rows=rows,
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


def _classify_result_indicator(action_types: list[str]) -> str:
    """Return ``"click"``, ``"conversion"``, or ``"unknown"`` for ``action_types``.

    A campaign whose recorded ``actions`` are dominated by clicks is a
    click-optimised campaign; one with conversion / lead / purchase
    actions is a conversion-optimised campaign. The classifier picks
    the first matching bucket so a campaign with both signals lands
    where the workflow expects (clicks are the cheaper signal — if a
    conversion-optimised campaign reports clicks alongside leads it is
    still a conversion campaign).
    """
    for token in _CONVERSION_RESULT_TOKENS:
        if any(token in at for at in action_types):
            return "conversion"
    for prefix in _CLICK_RESULT_PREFIXES:
        if any(at.startswith(prefix) for at in action_types):
            return "click"
    return "unknown"


def _detect_cv_definition_mismatch(rows: list[dict[str, object]]) -> str | None:
    """Return a finding string if the account mixes click- and
    conversion-style result indicators across campaigns, else ``None``.
    """
    classifications: set[str] = set()
    for row in rows:
        actions = row.get("actions") or []
        if not isinstance(actions, list):
            continue
        action_types = [
            str(a.get("action_type", "")) for a in actions if isinstance(a, dict)
        ]
        bucket = _classify_result_indicator(action_types)
        if bucket in {"click", "conversion"}:
            classifications.add(bucket)

    if len(classifications) > 1:
        return (
            "CV-definition mismatch: some campaigns optimise for clicks "
            "while others report conversion-style actions; account-level "
            "metrics blend two incompatible definitions"
        )
    return None


def _summarise_meta_performance(
    *,
    platform: str,
    account_id: str,
    scope: PerformanceScope,
    rows: list[dict[str, object]],
) -> PerformanceDiagnosis:
    """Pure renderer for Meta performance rows."""
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
        cost += float(row.get("spend", 0) or 0)
        impressions += int(row.get("impressions", 0) or 0)
        clicks += int(row.get("clicks", 0) or 0)
        actions = row.get("actions") or []
        if isinstance(actions, list):
            for action in actions:
                if not isinstance(action, dict):
                    continue
                action_type = str(action.get("action_type", ""))
                if any(t in action_type for t in _CONVERSION_RESULT_TOKENS):
                    conversions += float(action.get("value", 0) or 0)

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

    mismatch = _detect_cv_definition_mismatch(rows)
    if mismatch is not None:
        findings.append(mismatch)

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


__all__ = ["MetaAdsAnalyticsModule"]
