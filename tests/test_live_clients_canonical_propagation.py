"""Regression tests: the resolved (canonical) account_id reaches the caller.

``_open_*_client`` canonicalizes / allow-list-binds the account id and returns
it alongside the client. The ``fetch_*_performance_rows`` / ``fetch_*_list``
fetchers now propagate that resolved id, and the adapters label their result
models with it — so ``PerformanceDiagnosis.account_id`` /
``CreativeAudit.account_id`` / ``BudgetEfficiency.account_id`` carry the
canonical value rather than the raw caller input (#435).

These patch ``_open_*_client`` directly so they exercise the propagation path
without depending on live credentials or the workspace allow-list.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mureo.analytics.builtin.google_ads import GoogleAdsAnalyticsModule
from mureo.analytics.builtin.meta_ads import MetaAdsAnalyticsModule
from mureo.analytics.models import PerformanceScope

_GOOGLE_ROWS = [
    {
        "campaign_id": "1",
        "metrics": {
            "cost": 100.0,
            "impressions": 1000,
            "clicks": 10,
            "conversions": 2.0,
        },
    }
]
_META_ROWS = [{"campaign_id": "1", "spend": 100.0, "impressions": 1000, "clicks": 10}]


def _google_client() -> AsyncMock:
    client = AsyncMock()
    client.get_performance_report = AsyncMock(return_value=_GOOGLE_ROWS)
    client.list_ads = AsyncMock(return_value=[])
    return client


def _meta_client() -> AsyncMock:
    client = AsyncMock()
    client.get_performance_report = AsyncMock(return_value=_META_ROWS)
    client.list_ads = AsyncMock(return_value=[])
    return client


@pytest.mark.unit
class TestCanonicalAccountIdPropagation:
    @pytest.mark.asyncio
    async def test_google_diagnose_uses_resolved_id(self) -> None:
        module = GoogleAdsAnalyticsModule()
        with patch(
            "mureo.analytics.builtin._live_clients._open_google_ads_client",
            return_value=(_google_client(), "canonical-123"),
        ):
            diag = await module.diagnose_performance(
                "raw-input", scope=PerformanceScope.ACCOUNT
            )
        assert diag.account_id == "canonical-123"

    @pytest.mark.asyncio
    async def test_google_audit_creative_uses_resolved_id(self) -> None:
        module = GoogleAdsAnalyticsModule()
        with patch(
            "mureo.analytics.builtin._live_clients._open_google_ads_client",
            return_value=(_google_client(), "canonical-123"),
        ):
            audit = await module.audit_creative("raw-input")
        assert audit.account_id == "canonical-123"

    @pytest.mark.asyncio
    async def test_google_budget_efficiency_uses_resolved_id(self) -> None:
        module = GoogleAdsAnalyticsModule()
        with patch(
            "mureo.analytics.builtin._live_clients._open_google_ads_client",
            return_value=(_google_client(), "canonical-123"),
        ):
            eff = await module.analyze_budget_efficiency("raw-input")
        assert eff.account_id == "canonical-123"

    @pytest.mark.asyncio
    async def test_meta_diagnose_uses_canonical_act_id(self) -> None:
        module = MetaAdsAnalyticsModule()
        with patch(
            "mureo.analytics.builtin._live_clients._open_meta_ads_client",
            return_value=(_meta_client(), "act_999"),
        ):
            diag = await module.diagnose_performance(
                "999", scope=PerformanceScope.ACCOUNT
            )
        assert diag.account_id == "act_999"

    @pytest.mark.asyncio
    async def test_meta_audit_creative_uses_canonical_act_id(self) -> None:
        module = MetaAdsAnalyticsModule()
        with patch(
            "mureo.analytics.builtin._live_clients._open_meta_ads_client",
            return_value=(_meta_client(), "act_999"),
        ):
            audit = await module.audit_creative("999")
        assert audit.account_id == "act_999"
