"""``mureo_analytics_run`` MCP dispatcher tests (Issue #440)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mureo.analytics.models import (
    Anomaly,
    AnomalySeverity,
    BudgetEfficiency,
    CreativeAudit,
    CreativeFinding,
    PerformanceDiagnosis,
    PerformanceScope,
)
from mureo.analytics.protocol import AnalyticsCapability
from mureo.analytics.registry import (
    clear_analytics_registry,
    register_analytics_module,
)
from mureo.mcp.tools_analytics_registry import TOOLS, handle_tool

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    clear_analytics_registry()
    yield
    clear_analytics_registry()


class _RecordingModule:
    """A plugin-style module that records calls and returns canned models."""

    platform = "fake_platform"

    def __init__(self, *, caps: frozenset[AnalyticsCapability] | None = None) -> None:
        self._caps = (
            caps
            if caps is not None
            else frozenset(
                {
                    AnalyticsCapability.DETECT_ANOMALIES,
                    AnalyticsCapability.DIAGNOSE_PERFORMANCE,
                    AnalyticsCapability.AUDIT_CREATIVE,
                    AnalyticsCapability.ANALYZE_BUDGET_EFFICIENCY,
                }
            )
        )
        self.calls: list[tuple[str, tuple, dict]] = []

    def capabilities(self) -> frozenset[AnalyticsCapability]:
        return self._caps

    async def detect_anomalies(
        self, account_id: str, *, window_days: int = 7
    ) -> tuple[Anomaly, ...]:
        self.calls.append(
            ("detect_anomalies", (account_id,), {"window_days": window_days})
        )
        return (
            Anomaly(
                campaign_id="c1",
                metric="cpa",
                severity=AnomalySeverity.HIGH,
                current_value=1000.0,
                baseline_value=500.0,
                deviation_pct=100.0,
                sample_size=42,
                message="CPA doubled",
                recommended_action="investigate",
            ),
        )

    async def diagnose_performance(
        self, account_id: str, *, scope: PerformanceScope
    ) -> PerformanceDiagnosis:
        self.calls.append(("diagnose_performance", (account_id,), {"scope": scope}))
        return PerformanceDiagnosis(
            platform=self.platform,
            account_id=account_id,
            scope=scope,
            headline="ok",
            findings=("f1",),
            metrics=(("cpa", 500.0),),
        )

    async def audit_creative(self, account_id: str) -> CreativeAudit:
        self.calls.append(("audit_creative", (account_id,), {}))
        return CreativeAudit(
            platform=self.platform,
            account_id=account_id,
            findings=(
                CreativeFinding(
                    asset_id="a1",
                    asset_type="rsa",
                    severity=AnomalySeverity.CRITICAL,
                    message="missing headlines",
                    recommended_action="add",
                ),
            ),
        )

    async def analyze_budget_efficiency(self, account_id: str) -> BudgetEfficiency:
        self.calls.append(("analyze_budget_efficiency", (account_id,), {}))
        return BudgetEfficiency(
            platform=self.platform,
            account_id=account_id,
            per_campaign_score=(("c1", 0.9),),
            rebalance_suggestion="shift to c1",
        )


def _run_tool_schema() -> dict:
    tool = next(t for t in TOOLS if t.name == "mureo_analytics_run")
    return tool.inputSchema


@pytest.mark.unit
def test_run_tool_is_registered_with_required_fields() -> None:
    schema = _run_tool_schema()
    assert schema["required"] == ["platform", "capability", "account_id"]
    assert set(schema["properties"]["capability"]["enum"]) == {
        c.value for c in AnalyticsCapability
    }
    assert set(schema["properties"]["scope"]["enum"]) == {
        s.value for s in PerformanceScope
    }


@pytest.mark.asyncio
async def test_detect_anomalies_serializes_result_and_forwards_window() -> None:
    module = _RecordingModule()
    register_analytics_module(module)

    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "detect_anomalies",
            "account_id": "acct-1",
            "window_days": 14,
        },
    )
    payload = json.loads(content.text)

    assert payload["status"] == "ok"
    assert payload["capability"] == "detect_anomalies"
    # window_days forwarded to the module.
    assert module.calls[0] == ("detect_anomalies", ("acct-1",), {"window_days": 14})
    # tuple[Anomaly, ...] -> list of dicts; enum -> value.
    assert payload["result"][0]["severity"] == "high"
    assert payload["result"][0]["metric"] == "cpa"


@pytest.mark.asyncio
async def test_detect_anomalies_defaults_window_to_seven() -> None:
    module = _RecordingModule()
    register_analytics_module(module)
    await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "detect_anomalies",
            "account_id": "acct-1",
        },
    )
    assert module.calls[0][2] == {"window_days": 7}


@pytest.mark.asyncio
async def test_diagnose_performance_forwards_scope_enum() -> None:
    module = _RecordingModule()
    register_analytics_module(module)
    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "diagnose_performance",
            "account_id": "acct-1",
            "scope": "deep",
        },
    )
    payload = json.loads(content.text)
    assert module.calls[0][2]["scope"] is PerformanceScope.DEEP
    assert payload["result"]["scope"] == "deep"
    assert payload["result"]["metrics"] == [["cpa", 500.0]]


@pytest.mark.asyncio
async def test_diagnose_performance_defaults_scope_to_account() -> None:
    module = _RecordingModule()
    register_analytics_module(module)
    await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "diagnose_performance",
            "account_id": "acct-1",
        },
    )
    assert module.calls[0][2]["scope"] is PerformanceScope.ACCOUNT


@pytest.mark.asyncio
async def test_audit_creative_serializes_nested_findings() -> None:
    module = _RecordingModule()
    register_analytics_module(module)
    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "audit_creative",
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "ok"
    assert payload["result"]["findings"][0]["severity"] == "critical"
    assert payload["result"]["findings"][0]["asset_id"] == "a1"


@pytest.mark.asyncio
async def test_analyze_budget_efficiency_ok() -> None:
    module = _RecordingModule()
    register_analytics_module(module)
    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "analyze_budget_efficiency",
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "ok"
    assert payload["result"]["per_campaign_score"] == [["c1", 0.9]]


@pytest.mark.asyncio
async def test_unknown_platform_returns_no_module_status() -> None:
    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "nonexistent",
            "capability": "detect_anomalies",
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "no_analytics_module"
    assert payload["platform"] == "nonexistent"


@pytest.mark.asyncio
async def test_capability_not_advertised_returns_structured_status() -> None:
    module = _RecordingModule(caps=frozenset({AnalyticsCapability.DETECT_ANOMALIES}))
    register_analytics_module(module)
    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "audit_creative",
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "capability_not_available"
    assert payload["available_capabilities"] == ["detect_anomalies"]
    # The unsupported method must not have been called.
    assert module.calls == []


@pytest.mark.asyncio
async def test_module_failure_is_isolated_into_error_status() -> None:
    class _BrokenModule(_RecordingModule):
        async def detect_anomalies(
            self, account_id: str, *, window_days: int = 7
        ) -> tuple[Anomaly, ...]:
            raise RuntimeError("no credentials configured")

    register_analytics_module(_BrokenModule())
    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "detect_anomalies",
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "error"
    assert payload["error_type"] == "RuntimeError"
    assert "credentials" in payload["detail"]


@pytest.mark.asyncio
async def test_non_serializable_result_becomes_error_not_raw_exception() -> None:
    """A module returning a JSON-unfriendly object must not crash the handler
    (serialization is inside the fault boundary)."""

    class _WeirdReturn(_RecordingModule):
        async def detect_anomalies(
            self, account_id: str, *, window_days: int = 7
        ) -> tuple[Anomaly, ...]:
            # Not the documented tuple[Anomaly, ...]; a set is not JSON-native
            # and _jsonable leaves it as-is, so json.dumps would raise.
            return {object()}  # type: ignore[return-value]

    register_analytics_module(_WeirdReturn())
    # Must not raise — returns a structured error instead.
    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_platform",
            "capability": "detect_anomalies",
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "error"
    assert payload["error_type"] == "TypeError"


@pytest.mark.asyncio
async def test_cancelled_error_propagates() -> None:
    """CancelledError is a BaseException and must NOT be swallowed into an
    error status, or structured-concurrency cleanup would not run."""
    import asyncio

    class _Cancelling(_RecordingModule):
        async def detect_anomalies(
            self, account_id: str, *, window_days: int = 7
        ) -> tuple[Anomaly, ...]:
            raise asyncio.CancelledError

    register_analytics_module(_Cancelling())
    with pytest.raises(asyncio.CancelledError):
        await handle_tool(
            "mureo_analytics_run",
            {
                "platform": "fake_platform",
                "capability": "detect_anomalies",
                "account_id": "acct-1",
            },
        )
