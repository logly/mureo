"""Built-in Meta Ads analytics adapter tests."""

from __future__ import annotations

import pytest

from mureo.analysis.anomaly_detector import CampaignMetrics
from mureo.analytics.builtin.meta_ads import MetaAdsAnalyticsModule
from mureo.analytics.models import PerformanceScope
from mureo.analytics.protocol import AnalyticsCapability


@pytest.mark.unit
def test_platform_identifier_is_stable() -> None:
    assert MetaAdsAnalyticsModule().platform == "meta_ads"


@pytest.mark.unit
def test_advertised_capabilities() -> None:
    caps = MetaAdsAnalyticsModule().capabilities()
    assert caps == frozenset(
        {
            AnalyticsCapability.DETECT_ANOMALIES,
            AnalyticsCapability.DIAGNOSE_PERFORMANCE,
            AnalyticsCapability.AUDIT_CREATIVE,
            AnalyticsCapability.ANALYZE_BUDGET_EFFICIENCY,
        }
    )


@pytest.mark.asyncio
async def test_detect_anomalies_returns_empty_without_fetcher() -> None:
    assert await MetaAdsAnalyticsModule().detect_anomalies("act_123") == ()


@pytest.mark.asyncio
async def test_detect_anomalies_zero_spend_fires_critical() -> None:
    current = CampaignMetrics(
        campaign_id="c9", cost=0, impressions=0, clicks=0, conversions=0
    )
    baseline = CampaignMetrics(
        campaign_id="c9",
        cost=5000,
        impressions=10000,
        clicks=300,
        conversions=40,
    )

    def _fetcher(
        account_id: str, *, window_days: int
    ) -> tuple[CampaignMetrics, CampaignMetrics]:
        return current, baseline

    module = MetaAdsAnalyticsModule(metrics_fetcher=_fetcher)
    anomalies = await module.detect_anomalies("act_123")
    assert any(a.metric == "cost" for a in anomalies)


@pytest.mark.asyncio
async def test_diagnose_performance_carries_through_scope() -> None:
    diag = await MetaAdsAnalyticsModule().diagnose_performance(
        "act_1", scope=PerformanceScope.CAMPAIGN
    )
    assert diag.platform == "meta_ads"
    assert diag.scope == PerformanceScope.CAMPAIGN


@pytest.mark.asyncio
async def test_analyze_budget_efficiency_uses_performance_fetcher() -> None:
    async def fetcher(account_id: str, period: str) -> list[dict[str, object]]:
        return [
            {"campaign_id": "good", "spend": 100, "conversions": 10},
            {"campaign_id": "bad", "spend": 100, "conversions": 1},
        ]

    module = MetaAdsAnalyticsModule(performance_fetcher=fetcher)
    result = await module.analyze_budget_efficiency("act_1")
    scores = dict(result.per_campaign_score)
    assert scores["good"] == 1.0
    assert scores["bad"] == pytest.approx(0.1, abs=0.01)
