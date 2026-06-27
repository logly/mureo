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

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from mureo.analysis.anomaly_detector import detect_anomalies
from mureo.analytics.builtin._budget_efficiency import score_budget_efficiency
from mureo.analytics.builtin._common import (
    MetricsFetcher,
    PerCampaignMetricsFetcher,
    PerformanceFetcher,
    meta_row_conversions,
    to_analytics_anomalies,
)
from mureo.context.state import load_conversion_action_types

if TYPE_CHECKING:
    from mureo.analysis.anomaly_detector import CampaignMetrics
from mureo.analytics.builtin._creative_audit import (
    audit_meta_ads_creatives,
    summarise_findings_by_campaign,
)
from mureo.analytics.builtin._live_clients import (
    NoCredentialsError,
    fetch_meta_ads_list,
    fetch_meta_ads_per_campaign_metrics,
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
        AnalyticsCapability.AUDIT_CREATIVE,
        AnalyticsCapability.ANALYZE_BUDGET_EFFICIENCY,
    }
)

AdsListFetcher = Callable[[str], "Awaitable[list[dict[str, object]]]"]


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
        per_campaign_metrics_fetcher: PerCampaignMetricsFetcher | None = None,
        ads_list_fetcher: AdsListFetcher | None = None,
    ) -> None:
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
        """Detect anomalies per campaign — parallel to the Google
        adapter's docstring (see that module for the rationale).
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
        if self._per_campaign_metrics_fetcher is not None:
            return await self._per_campaign_metrics_fetcher(
                account_id, window_days=window_days
            )
        try:
            return await fetch_meta_ads_per_campaign_metrics(
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
        """Audit Meta creative assets — see the Google adapter docstring."""
        if self._ads_list_fetcher is not None:
            ads = await self._ads_list_fetcher(account_id)
        else:
            try:
                ads = await fetch_meta_ads_list(account_id)
            except NoCredentialsError:
                return CreativeAudit(
                    platform=self.platform,
                    account_id=account_id,
                    findings=(),
                )
        findings = tuple(audit_meta_ads_creatives(ads))
        return CreativeAudit(
            platform=self.platform,
            account_id=account_id,
            findings=findings,
            per_campaign_summary=summarise_findings_by_campaign(findings),
        )

    async def analyze_budget_efficiency(self, account_id: str) -> BudgetEfficiency:
        """Score per-campaign budget efficiency on Meta — see the
        Google adapter docstring for the policy.
        """
        period = "last_30d"
        if self._performance_fetcher is not None:
            rows = await self._performance_fetcher(account_id, period)
        else:
            try:
                rows = await fetch_meta_ads_performance_rows(account_id, period)
            except NoCredentialsError:
                return BudgetEfficiency(
                    platform=self.platform,
                    account_id=account_id,
                    rebalance_suggestion="meta_ads credentials not configured",
                )
        return score_budget_efficiency(
            rows,
            platform=self.platform,
            account_id=account_id,
            spend_key="spend",
            nested_metrics=False,
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


def _detect_cv_definition_mismatch(rows: list[dict[str, Any]]) -> str | None:
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
    rows: list[dict[str, Any]],
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

    per_campaign: list[tuple[str, dict[str, float]]] = []
    cost = 0.0
    impressions = 0
    clicks = 0
    conversions = 0.0
    cv_types = load_conversion_action_types(account_id)  # #342 per-account override
    for row in rows:
        row_cost = float(row.get("spend") or 0)
        row_impressions = int(row.get("impressions") or 0)
        row_clicks = int(row.get("clicks") or 0)
        # Tolerates live (actions list) and BYOD (flat conversions);
        # both shapes are valid factory outputs.
        row_conversions = meta_row_conversions(row, conversion_action_types=cv_types)
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

    mismatch = _detect_cv_definition_mismatch(rows)
    if mismatch is not None:
        findings.append(mismatch)

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

    # DEEP scope: same per-campaign rendering policy as the Google
    # adapter. Sort by spend descending so the highest-impact campaigns
    # surface first.
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


__all__ = ["MetaAdsAnalyticsModule"]
