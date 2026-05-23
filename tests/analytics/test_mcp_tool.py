"""``mureo_analytics_modules_list`` MCP tool tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from mureo.analytics.protocol import AnalyticsCapability
from mureo.analytics.registry import (
    clear_analytics_registry,
    register_analytics_module,
)
from mureo.mcp.tools_analytics_registry import TOOLS, handle_tool


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    clear_analytics_registry()
    yield
    clear_analytics_registry()


@pytest.mark.unit
def test_tool_definition_is_zero_arg() -> None:
    [tool] = TOOLS
    assert tool.name == "mureo_analytics_modules_list"
    assert tool.inputSchema == {"type": "object", "properties": {}}


@pytest.mark.asyncio
async def test_handle_lists_builtin_modules() -> None:
    [content] = await handle_tool("mureo_analytics_modules_list", {})
    payload = json.loads(content.text)
    platforms = [m["platform"] for m in payload["modules"]]
    assert "google_ads" in platforms
    assert "meta_ads" in platforms


@pytest.mark.asyncio
async def test_handle_includes_capability_strings() -> None:
    [content] = await handle_tool("mureo_analytics_modules_list", {})
    payload = json.loads(content.text)
    google = next(m for m in payload["modules"] if m["platform"] == "google_ads")
    assert AnalyticsCapability.DETECT_ANOMALIES.value in google["capabilities"]
    assert AnalyticsCapability.DIAGNOSE_PERFORMANCE.value in google["capabilities"]
    # all_capabilities is the full enum so a skill can compute gaps.
    assert AnalyticsCapability.AUDIT_CREATIVE.value in google["all_capabilities"]


@pytest.mark.asyncio
async def test_handle_includes_plugin_module_source_distribution() -> None:
    from mureo.analytics.models import (
        Anomaly,
        BudgetEfficiency,
        CreativeAudit,
        PerformanceDiagnosis,
        PerformanceScope,
    )

    class _PluginModule:
        platform = "fake_plugin_platform"

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
                headline="",
                findings=(),
            )

        async def audit_creative(self, account_id: str) -> CreativeAudit:
            return CreativeAudit(platform=self.platform, account_id=account_id)

        async def analyze_budget_efficiency(self, account_id: str) -> BudgetEfficiency:
            return BudgetEfficiency(platform=self.platform, account_id=account_id)

    instance = _PluginModule()
    register_analytics_module(instance)
    # Inject the breadcrumb directly into the side-table so we exercise
    # the MCP tool's translation path without setting up a fake
    # entry-point distribution.
    from mureo.analytics.registry import _SOURCE_DISTRIBUTIONS

    _SOURCE_DISTRIBUTIONS[id(instance)] = "mureo-fake-plugin-dist"

    [content] = await handle_tool("mureo_analytics_modules_list", {})
    payload = json.loads(content.text)
    entry = next(
        m for m in payload["modules"] if m["platform"] == "fake_plugin_platform"
    )
    assert entry["source_distribution"] == "mureo-fake-plugin-dist"


@pytest.mark.asyncio
async def test_handle_rejects_unknown_tool() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await handle_tool("nope", {})
