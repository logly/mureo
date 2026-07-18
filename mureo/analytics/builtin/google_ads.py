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

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from mureo.analysis.anomaly_detector import detect_anomalies
from mureo.analytics.builtin._budget_efficiency import score_budget_efficiency
from mureo.analytics.builtin._common import (
    MetricsFetcher,
    PerCampaignMetricsFetcher,
    PerformanceFetcher,
    google_row_metrics,
    to_analytics_anomalies,
)

if TYPE_CHECKING:
    from mureo.analysis.anomaly_detector import CampaignMetrics
from mureo.analytics.builtin._creative_audit import (
    audit_google_ads_creatives,
    summarise_findings_by_campaign,
)
from mureo.analytics.builtin._live_clients import (
    NoCredentialsError,
    fetch_google_ads_list,
    fetch_google_ads_per_campaign_metrics,
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
        AnalyticsCapability.AUDIT_CREATIVE,
        AnalyticsCapability.ANALYZE_BUDGET_EFFICIENCY,
    }
)

# Injectable fetchers for ``audit_creative`` and
# ``analyze_budget_efficiency``. Production paths resolve to the live
# client; tests inject deterministic stubs. Aliased here rather than in
# ``_common.py`` because they're adapter-local — only used by one of
# the two methods on one of the two adapters each.
AdsListFetcher = Callable[[str], "Awaitable[list[dict[str, object]]]"]


class GoogleAdsAnalyticsModule(AnalyticsModule):
    """mureo-native Google Ads analytics surface."""

    platform: str = "google_ads"

    def __init__(
        self,
        metrics_fetcher: MetricsFetcher | None = None,
        performance_fetcher: PerformanceFetcher | None = None,
        per_campaign_metrics_fetcher: PerCampaignMetricsFetcher | None = None,
        ads_list_fetcher: AdsListFetcher | None = None,
    ) -> None:
        # ``metrics_fetcher`` is the legacy aggregate-path injection
        # (kept for back-compat with existing tests); the live default
        # is per-campaign fan-out via
        # :func:`fetch_google_ads_per_campaign_metrics`. Tests that
        # care about per-campaign behaviour inject
        # ``per_campaign_metrics_fetcher`` instead.
        self._metrics_fetcher = metrics_fetcher
        self._performance_fetcher = performance_fetcher
        self._per_campaign_metrics_fetcher = per_campaign_metrics_fetcher
        self._ads_list_fetcher = ads_list_fetcher

    def capabilities(self) -> frozenset[AnalyticsCapability]:
        return _CAPABILITIES

    async def detect_anomalies(
        self,
        account_id: str,
        *,
        window_days: int = 7,
    ) -> tuple[Anomaly, ...]:
        """Detect anomalies per campaign on ``account_id``.

        Default path: per-campaign fan-out — the live fetcher returns
        ``{campaign_id: (current, baseline)}`` and the pure detector
        runs once per campaign. This surfaces single-campaign anomalies
        that the previous account-level aggregation masked when an
        offsetting campaign moved in the opposite direction (see #120).

        Back-compat: an injected ``metrics_fetcher`` still triggers
        the legacy aggregate path; existing tests continue to work
        without modification. Missing credentials return an empty
        anomaly tuple — config error, not an anomaly.
        """
        if self._metrics_fetcher is not None:
            current, baseline = self._metrics_fetcher(
                account_id, window_days=window_days
            )
            had_prior_spend = baseline is not None and baseline.cost > 0
            detected = detect_anomalies(
                current, baseline, had_prior_spend=had_prior_spend
            )
            return to_analytics_anomalies(detected)

        per_campaign = await self._resolve_per_campaign_metrics(
            account_id, window_days=window_days
        )
        if per_campaign is None:
            return ()

        all_anomalies: list[Anomaly] = []
        for current, baseline in per_campaign.values():
            had_prior_spend = baseline is not None and baseline.cost > 0
            detected = detect_anomalies(
                current, baseline, had_prior_spend=had_prior_spend
            )
            all_anomalies.extend(to_analytics_anomalies(detected))
        return tuple(all_anomalies)

    async def _resolve_per_campaign_metrics(
        self,
        account_id: str,
        *,
        window_days: int,
    ) -> dict[str, tuple[CampaignMetrics, CampaignMetrics | None]] | None:
        """Resolve the per-campaign metrics map for ``account_id``.

        Returns ``None`` on missing credentials (the adapter renders
        that as an empty anomaly tuple); returns the dict otherwise.
        """
        if self._per_campaign_metrics_fetcher is not None:
            return await self._per_campaign_metrics_fetcher(
                account_id, window_days=window_days
            )
        try:
            return await fetch_google_ads_per_campaign_metrics(
                account_id, window_days=window_days
            )
        except NoCredentialsError:
            return None

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
                # The live fetcher returns the resolved (allow-list-bound)
                # account id so the diagnosis is labelled with the canonical
                # value, not the raw input (#435).
                rows, account_id = await fetch_google_ads_performance_rows(
                    account_id, period
                )
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
        """Audit RSA / RDA creative assets on ``account_id``.

        Pulls ads via the live (or injected) ``list_ads`` fetcher,
        passes the result through the pure
        :func:`audit_google_ads_creatives` checker, and packs the
        findings into a :class:`CreativeAudit`. Returns an empty audit
        when credentials are missing (config error, not "no findings").
        """
        if self._ads_list_fetcher is not None:
            ads = await self._ads_list_fetcher(account_id)
        else:
            try:
                # Resolved account id propagates so the audit is labelled with
                # the canonical value (#435).
                ads, account_id = await fetch_google_ads_list(account_id)
            except NoCredentialsError:
                return CreativeAudit(
                    platform=self.platform,
                    account_id=account_id,
                    findings=(),
                )
        findings = tuple(audit_google_ads_creatives(ads))
        return CreativeAudit(
            platform=self.platform,
            account_id=account_id,
            findings=findings,
            per_campaign_summary=summarise_findings_by_campaign(findings),
        )

    async def analyze_budget_efficiency(self, account_id: str) -> BudgetEfficiency:
        """Score per-campaign budget efficiency over the last 30 days.

        Re-uses the same performance fetcher as
        :meth:`diagnose_performance` (the data is the same — only the
        analysis differs). Returns an empty :class:`BudgetEfficiency`
        on missing credentials so the caller can branch uniformly with
        :meth:`detect_anomalies` and :meth:`diagnose_performance`.
        """
        period = "LAST_30_DAYS"
        if self._performance_fetcher is not None:
            rows = await self._performance_fetcher(account_id, period)
        else:
            try:
                # Resolved account id propagates so the result is labelled with
                # the canonical value (#435).
                rows, account_id = await fetch_google_ads_performance_rows(
                    account_id, period
                )
            except NoCredentialsError:
                return BudgetEfficiency(
                    platform=self.platform,
                    account_id=account_id,
                    rebalance_suggestion="google_ads credentials not configured",
                )
        return score_budget_efficiency(
            rows,
            platform=self.platform,
            account_id=account_id,
            spend_key="cost",
            nested_metrics=True,
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

    # Per-campaign extraction first: the DEEP scope re-uses these, and
    # the aggregate sums also fall out of them — single pass.
    per_campaign: list[tuple[str, dict[str, float]]] = []
    cost = 0.0
    impressions = 0
    clicks = 0
    conversions = 0.0
    for row in rows:
        metrics = google_row_metrics(row)
        row_cost = float(metrics.get("cost") or 0)
        row_impressions = int(metrics.get("impressions") or 0)
        row_clicks = int(metrics.get("clicks") or 0)
        row_conversions = float(metrics.get("conversions") or 0)
        cost += row_cost
        impressions += row_impressions
        clicks += row_clicks
        conversions += row_conversions
        campaign_id = str(row.get("campaign_id") or "").strip()
        if campaign_id:
            per_campaign.append(
                (
                    campaign_id,
                    {
                        "cost": row_cost,
                        "impressions": float(row_impressions),
                        "clicks": float(row_clicks),
                        "conversions": row_conversions,
                    },
                )
            )

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

    # DEEP scope: emit per-campaign findings + structured per-campaign
    # metrics. Sort by spend descending so the highest-impact campaigns
    # appear first regardless of the API's row order.
    per_campaign_metrics: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = ()
    if scope is PerformanceScope.DEEP:
        per_campaign.sort(key=lambda entry: entry[1]["cost"], reverse=True)
        deep_findings: list[str] = []
        deep_metrics: list[tuple[str, tuple[tuple[str, float], ...]]] = []
        for campaign_id, m in per_campaign:
            campaign_cpa = (
                (m["cost"] / m["conversions"]) if m["conversions"] > 0 else None
            )
            metrics_pairs: tuple[tuple[str, float], ...] = (
                ("cost", m["cost"]),
                ("impressions", m["impressions"]),
                ("clicks", m["clicks"]),
                ("conversions", m["conversions"]),
            )
            cpa_text = f", CPA={campaign_cpa:,.0f}" if campaign_cpa is not None else ""
            deep_findings.append(
                f"{campaign_id}: spend={m['cost']:,.0f}, "
                f"CV={m['conversions']:.1f}{cpa_text}"
            )
            if campaign_cpa is not None:
                metrics_pairs = (*metrics_pairs, ("cpa", campaign_cpa))
            deep_metrics.append((campaign_id, metrics_pairs))
        findings.extend(deep_findings)
        per_campaign_metrics = tuple(deep_metrics)

    headline = f"{platform}: {len(rows)} campaigns, spend={cost:,.0f}"
    return PerformanceDiagnosis(
        platform=platform,
        account_id=account_id,
        scope=scope,
        headline=headline,
        findings=tuple(findings),
        metrics=metrics_tuple,
        per_campaign_metrics=per_campaign_metrics,
    )


__all__ = ["GoogleAdsAnalyticsModule"]
