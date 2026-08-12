"""Built-in adapters' ``detect_delivery_collapse`` capability (#546).

The point of routing collapse detection through the AnalyticsModule
Protocol is that the *same* core detector runs for every platform and
only the day-grain fetch is platform-specific. These tests pin that,
plus the two honest failure states — no credentials and no day-grain
data — which must never be rendered as "no collapse".
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mureo.analysis.delivery_collapse import (
    BASELINE_SOURCE,
    CollapseSeverity,
    DailyDelivery,
    DeliverySeries,
)
from mureo.analytics.builtin._live_clients import (
    DeliveryDataUnavailableError,
    NoCredentialsError,
)
from mureo.analytics.builtin.google_ads import GoogleAdsAnalyticsModule
from mureo.analytics.builtin.meta_ads import MetaAdsAnalyticsModule
from mureo.analytics.protocol import AnalyticsCapability

AS_OF = date(2026, 6, 1)
MODULES = (GoogleAdsAnalyticsModule, MetaAdsAnalyticsModule)


def _collapsed_series(platform: str) -> DeliverySeries:
    days = [
        DailyDelivery(
            date=AS_OF - timedelta(days=offset),
            impressions=350_000,
            clicks=3_500,
            cost=120_000.0,
        )
        for offset in reversed(range(2, 30))
    ]
    days.append(DailyDelivery(date=AS_OF - timedelta(days=1), impressions=0, cost=0.0))
    return DeliverySeries(
        platform=platform,
        campaign_id="c-1",
        campaign_name="Display / Prospecting",
        status="ENABLED",
        daily=tuple(days),
    )


@pytest.mark.unit
@pytest.mark.parametrize("module_cls", MODULES)
def test_capability_is_advertised(module_cls: type) -> None:
    assert AnalyticsCapability.DETECT_DELIVERY_COLLAPSE in module_cls().capabilities()


@pytest.mark.asyncio
@pytest.mark.parametrize("module_cls", MODULES)
async def test_injected_fetcher_drives_the_shared_detector(module_cls: type) -> None:
    module = module_cls()
    platform = module.platform

    async def fetcher(account_id: str, *, days: int):
        assert days >= 29
        return (_collapsed_series(platform),), account_id

    module = module_cls(delivery_fetcher=fetcher)
    report = await module.detect_delivery_collapse("acct-1", as_of=AS_OF)

    assert report.status == "ok"
    assert report.platform == platform
    assert report.evaluated_campaigns == 1
    assert report.baseline_source == BASELINE_SOURCE
    assert len(report.signals) == 1
    assert report.signals[0].severity is CollapseSeverity.CRITICAL


@pytest.mark.asyncio
@pytest.mark.parametrize("module_cls", MODULES)
async def test_missing_credentials_is_reported_not_silently_empty(
    module_cls: type,
) -> None:
    async def fetcher(account_id: str, *, days: int):
        raise NoCredentialsError("credentials not configured")

    report = await module_cls(delivery_fetcher=fetcher).detect_delivery_collapse(
        "acct-1", as_of=AS_OF
    )

    assert report.status == "no_credentials"
    assert report.signals == ()
    assert report.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("module_cls", MODULES)
async def test_missing_day_grain_data_is_reported_not_silently_empty(
    module_cls: type,
) -> None:
    """A client that cannot produce day-grain delivery (a BYOD bundle
    without a daily metrics tab) must say so. Returning "no signals"
    would be a false all-clear on a dead account."""

    async def fetcher(account_id: str, *, days: int):
        raise DeliveryDataUnavailableError("no day-grain delivery data")

    report = await module_cls(delivery_fetcher=fetcher).detect_delivery_collapse(
        "acct-1", as_of=AS_OF
    )

    assert report.status == "data_unavailable"
    assert report.signals == ()
    assert "day-grain" in report.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("module_cls", MODULES)
async def test_healthy_account_reports_ok_with_no_signals(module_cls: type) -> None:
    module = module_cls()
    platform = module.platform
    healthy = DeliverySeries(
        platform=platform,
        campaign_id="c-1",
        campaign_name="Healthy",
        status="ENABLED",
        daily=tuple(
            DailyDelivery(
                date=AS_OF - timedelta(days=offset), impressions=350_000, cost=120_000.0
            )
            for offset in reversed(range(1, 30))
        ),
    )

    async def fetcher(account_id: str, *, days: int):
        return (healthy,), account_id

    report = await module_cls(delivery_fetcher=fetcher).detect_delivery_collapse(
        "acct-1", as_of=AS_OF
    )

    assert report.status == "ok"
    assert report.signals == ()
    assert report.evaluated_campaigns == 1
