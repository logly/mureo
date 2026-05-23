"""Protocol-shape invariants for :class:`AnalyticsModule`."""

from __future__ import annotations

from typing import Any

import pytest

from mureo.analytics.models import (
    Anomaly,
    BudgetEfficiency,
    CreativeAudit,
    PerformanceDiagnosis,
    PerformanceScope,
)
from mureo.analytics.protocol import AnalyticsCapability, AnalyticsModule


class _WellFormedModule:
    """Minimal duck-typed implementation — all methods present."""

    platform = "fake"

    def capabilities(self) -> frozenset[AnalyticsCapability]:
        return frozenset({AnalyticsCapability.DETECT_ANOMALIES})

    async def detect_anomalies(
        self, account_id: str, *, window_days: int = 7
    ) -> tuple[Anomaly, ...]:
        return ()

    async def diagnose_performance(
        self, account_id: str, *, scope: PerformanceScope
    ) -> PerformanceDiagnosis:
        return PerformanceDiagnosis(
            platform=self.platform,
            account_id=account_id,
            scope=scope,
            headline="ok",
            findings=(),
        )

    async def audit_creative(self, account_id: str) -> CreativeAudit:
        return CreativeAudit(platform=self.platform, account_id=account_id)

    async def analyze_budget_efficiency(self, account_id: str) -> BudgetEfficiency:
        return BudgetEfficiency(platform=self.platform, account_id=account_id)


class _MissingMethod:
    platform = "fake"

    def capabilities(self) -> frozenset[AnalyticsCapability]:
        return frozenset()


@pytest.mark.unit
def test_well_formed_satisfies_runtime_protocol() -> None:
    assert isinstance(_WellFormedModule(), AnalyticsModule)


@pytest.mark.unit
def test_missing_method_does_not_satisfy_protocol() -> None:
    # runtime_checkable only verifies attribute presence, not signatures.
    # An instance missing async methods entirely must fail isinstance.
    assert not isinstance(_MissingMethod(), AnalyticsModule)


@pytest.mark.unit
def test_capability_values_are_stable_strings() -> None:
    # Capability values are part of the plugin ABI.
    assert AnalyticsCapability.DETECT_ANOMALIES == "detect_anomalies"
    assert AnalyticsCapability.DIAGNOSE_PERFORMANCE == "diagnose_performance"
    assert AnalyticsCapability.AUDIT_CREATIVE == "audit_creative"
    assert AnalyticsCapability.ANALYZE_BUDGET_EFFICIENCY == "analyze_budget_efficiency"


@pytest.mark.unit
def test_capability_enum_is_complete() -> None:
    # Four capabilities map 1:1 with the four Protocol methods.
    assert len(AnalyticsCapability) == 4


@pytest.mark.asyncio
async def test_protocol_methods_are_awaitable_on_well_formed() -> None:
    m: Any = _WellFormedModule()
    anomalies = await m.detect_anomalies("acct")
    assert anomalies == ()
    diag = await m.diagnose_performance("acct", scope=PerformanceScope.ACCOUNT)
    assert diag.headline == "ok"
