"""Built-in Google Ads analytics adapter tests."""

from __future__ import annotations

import pytest

from mureo.analysis.anomaly_detector import CampaignMetrics
from mureo.analytics.builtin.google_ads import GoogleAdsAnalyticsModule
from mureo.analytics.models import AnomalySeverity, PerformanceScope
from mureo.analytics.protocol import AnalyticsCapability


@pytest.mark.unit
def test_platform_identifier_is_stable() -> None:
    assert GoogleAdsAnalyticsModule().platform == "google_ads"


@pytest.mark.unit
def test_advertised_capabilities() -> None:
    caps = GoogleAdsAnalyticsModule().capabilities()
    assert AnalyticsCapability.DETECT_ANOMALIES in caps
    assert AnalyticsCapability.DIAGNOSE_PERFORMANCE in caps
    assert AnalyticsCapability.AUDIT_CREATIVE not in caps
    assert AnalyticsCapability.ANALYZE_BUDGET_EFFICIENCY not in caps


@pytest.mark.asyncio
async def test_detect_anomalies_returns_empty_without_fetcher() -> None:
    module = GoogleAdsAnalyticsModule()
    result = await module.detect_anomalies("acct-123")
    assert result == ()


@pytest.mark.asyncio
async def test_detect_anomalies_uses_injected_fetcher() -> None:
    # CPA spike: 200/cv current vs 100/cv baseline at 30+ conversions.
    current = CampaignMetrics(
        campaign_id="c1",
        cost=6000,
        impressions=2000,
        clicks=100,
        conversions=30,
    )
    baseline = CampaignMetrics(
        campaign_id="c1",
        cost=3000,
        impressions=2000,
        clicks=100,
        conversions=30,
    )

    def _fetcher(
        account_id: str, *, window_days: int
    ) -> tuple[CampaignMetrics, CampaignMetrics]:
        assert account_id == "acct-123"
        assert window_days == 7
        return current, baseline

    module = GoogleAdsAnalyticsModule(metrics_fetcher=_fetcher)
    anomalies = await module.detect_anomalies("acct-123")
    assert len(anomalies) == 1
    assert anomalies[0].metric == "cpa"
    assert anomalies[0].severity in {
        AnomalySeverity.CRITICAL,
        AnomalySeverity.HIGH,
    }


@pytest.mark.asyncio
async def test_diagnose_performance_returns_stub_shape() -> None:
    module = GoogleAdsAnalyticsModule()
    diag = await module.diagnose_performance("acct-1", scope=PerformanceScope.ACCOUNT)
    assert diag.platform == "google_ads"
    assert diag.account_id == "acct-1"
    assert diag.scope == PerformanceScope.ACCOUNT


@pytest.mark.asyncio
async def test_audit_creative_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="AUDIT_CREATIVE"):
        await GoogleAdsAnalyticsModule().audit_creative("acct")


@pytest.mark.asyncio
async def test_analyze_budget_efficiency_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="ANALYZE_BUDGET_EFFICIENCY"):
        await GoogleAdsAnalyticsModule().analyze_budget_efficiency("acct")
