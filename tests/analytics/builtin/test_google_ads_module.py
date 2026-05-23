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
    assert AnalyticsCapability.AUDIT_CREATIVE in caps
    # ANALYZE_BUDGET_EFFICIENCY is advertised so the registry routes
    # the call; the live wiring lands in the next step of this PR.
    assert AnalyticsCapability.ANALYZE_BUDGET_EFFICIENCY in caps


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
async def test_per_campaign_fanout_surfaces_masked_anomaly() -> None:
    """Demonstrates that per-campaign fan-out catches the offsetting
    anomaly that the legacy aggregate path masked: campaign A drops to
    zero spend while B keeps running.
    """
    from mureo.analysis.anomaly_detector import CampaignMetrics

    async def per_campaign_fetcher(
        account_id: str, *, window_days: int
    ) -> dict[str, tuple[CampaignMetrics, CampaignMetrics | None]]:
        # camp_A: spend collapsed to zero.
        a_current = CampaignMetrics(
            campaign_id="camp_A", cost=0, impressions=0, clicks=0, conversions=0
        )
        a_baseline = CampaignMetrics(
            campaign_id="camp_A",
            cost=500,
            impressions=2500,
            clicks=100,
            conversions=10,
        )
        # camp_B: running normally.
        b_current = CampaignMetrics(
            campaign_id="camp_B",
            cost=1000,
            impressions=5000,
            clicks=200,
            conversions=20,
        )
        b_baseline = CampaignMetrics(
            campaign_id="camp_B",
            cost=500,
            impressions=2500,
            clicks=100,
            conversions=10,
        )
        return {
            "camp_A": (a_current, a_baseline),
            "camp_B": (b_current, b_baseline),
        }

    module = GoogleAdsAnalyticsModule(per_campaign_metrics_fetcher=per_campaign_fetcher)
    anomalies = await module.detect_anomalies("acct-1")
    # Fan-out should fire the zero-spend critical on camp_A.
    assert any(a.campaign_id == "camp_A" and a.metric == "cost" for a in anomalies)


@pytest.mark.asyncio
async def test_analyze_budget_efficiency_uses_performance_fetcher() -> None:
    async def fetcher(account_id: str, period: str) -> list[dict[str, object]]:
        return [
            {
                "campaign_id": "good",
                "metrics": {"cost": 1000.0, "conversions": 50},
            },
            {
                "campaign_id": "bad",
                "metrics": {"cost": 1000.0, "conversions": 5},
            },
        ]

    module = GoogleAdsAnalyticsModule(performance_fetcher=fetcher)
    result = await module.analyze_budget_efficiency("acct-1")
    scores = dict(result.per_campaign_score)
    assert scores["good"] == 1.0
    assert scores["bad"] == pytest.approx(0.1, abs=0.01)
    assert "reallocate" in result.rebalance_suggestion
