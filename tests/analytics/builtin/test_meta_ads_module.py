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
async def test_audit_creative_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await MetaAdsAnalyticsModule().audit_creative("act_1")


@pytest.mark.asyncio
async def test_analyze_budget_efficiency_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await MetaAdsAnalyticsModule().analyze_budget_efficiency("act_1")
