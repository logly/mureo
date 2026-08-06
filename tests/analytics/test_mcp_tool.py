"""``mureo_analytics_modules_list`` MCP tool tests."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from mureo.analytics.protocol import AnalyticsCapability
from mureo.analytics.registry import (
    clear_analytics_registry,
    default_analytics_registry,
    register_analytics_module,
)
from mureo.mcp.tools_analytics_registry import TOOLS, _resolve_module, handle_tool


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    clear_analytics_registry()
    yield
    clear_analytics_registry()


@pytest.mark.unit
def test_tool_definition_is_zero_arg() -> None:
    tool = next(t for t in TOOLS if t.name == "mureo_analytics_modules_list")
    assert tool.inputSchema == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


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


def _make_plugin_module(registry_name: str) -> object:
    """A minimal valid ``AnalyticsModule`` registering under ``registry_name``."""
    from mureo.analytics.models import (
        Anomaly,
        BudgetEfficiency,
        CreativeAudit,
        PerformanceDiagnosis,
        PerformanceScope,
    )

    class _PluginModule:
        platform = registry_name

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

    return _PluginModule()


def _register_plugin(registry_name: str, distribution: str) -> object:
    """Register a fake plugin module and stamp its distribution breadcrumb.

    The breadcrumb goes straight into the side-table so the MCP tool's
    translation path is exercised without standing up a fake entry-point
    distribution.
    """
    from mureo.analytics.registry import _SOURCE_DISTRIBUTIONS

    instance = _make_plugin_module(registry_name)
    register_analytics_module(instance)
    _SOURCE_DISTRIBUTIONS[id(instance)] = distribution
    return instance


def _force_register(registry_name: str, distribution: str) -> object:
    """Insert a module under ``registry_name`` **bypassing validation**.

    Registration now refuses a ``plugin:``-shaped registry name (the
    reserved canonical-key namespace, see ``tests/analytics/test_registry``),
    so the only way to stage that hostile shape — and prove the resolver
    is safe on its own rather than only because the guard exists — is to
    write it straight into the registry. Defence in depth: the two layers
    are tested independently.
    """
    from mureo.analytics.registry import _SOURCE_DISTRIBUTIONS

    instance = _make_plugin_module(registry_name)
    default_analytics_registry()._modules.setdefault(registry_name, instance)  # type: ignore[arg-type]
    _SOURCE_DISTRIBUTIONS[id(instance)] = distribution
    return instance


@pytest.mark.asyncio
async def test_handle_includes_plugin_module_source_distribution() -> None:
    _register_plugin("fake_plugin_platform", "mureo-fake-plugin-dist")

    [content] = await handle_tool("mureo_analytics_modules_list", {})
    payload = json.loads(content.text)
    entry = next(
        m
        for m in payload["modules"]
        if m["source_distribution"] == "mureo-fake-plugin-dist"
    )
    assert entry["source_distribution"] == "mureo-fake-plugin-dist"


@pytest.mark.asyncio
async def test_plugin_module_platform_is_the_canonical_key() -> None:
    """Issues #481 / #537 — ``platform`` is the STATE.json / action_log key.

    The key carries the distribution AND the registry name, so a
    distribution shipping several platforms names each of them. The
    registry name is still reported separately as ``registry_name``; on
    its own it is not a key.
    """
    _register_plugin("fake_plugin_platform", "mureo-fake-plugin-dist")

    [content] = await handle_tool("mureo_analytics_modules_list", {})
    payload = json.loads(content.text)
    platforms = [m["platform"] for m in payload["modules"]]
    assert "plugin:mureo-fake-plugin-dist:fake_plugin_platform" in platforms
    # The registry name must NOT be reported as a platform key.
    assert "fake_plugin_platform" not in platforms
    # Nor the distribution-only form — that is what #537 replaced.
    assert "plugin:mureo-fake-plugin-dist" not in platforms

    entry = next(
        m
        for m in payload["modules"]
        if m["platform"] == "plugin:mureo-fake-plugin-dist:fake_plugin_platform"
    )
    assert entry["registry_name"] == "fake_plugin_platform"
    assert entry["source_distribution"] == "mureo-fake-plugin-dist"


@pytest.mark.asyncio
async def test_single_module_distribution_still_reports_the_provider() -> None:
    """The key shape must NOT depend on how many modules a distribution ships.

    #537: deriving the shape from that count would silently change the
    first platform's key the day a second one is added, breaking joins for
    data already written under it. A distribution with exactly one module
    therefore gets the same two-part key as one with three.
    """
    _register_plugin("solo_ads", "solo-dist")

    [content] = await handle_tool("mureo_analytics_modules_list", {})
    payload = json.loads(content.text)
    entry = next(
        m for m in payload["modules"] if m["source_distribution"] == "solo-dist"
    )
    assert entry["platform"] == "plugin:solo-dist:solo_ads"


@pytest.mark.asyncio
async def test_builtin_module_keeps_registry_name_as_platform() -> None:
    """A built-in has no plugin source, so both fields are the registry name."""
    [content] = await handle_tool("mureo_analytics_modules_list", {})
    payload = json.loads(content.text)
    google = next(m for m in payload["modules"] if m["platform"] == "google_ads")
    assert google["registry_name"] == "google_ads"
    assert google["source_distribution"] == ""


@pytest.mark.asyncio
async def test_every_entry_has_the_same_shape() -> None:
    """Built-in and plugin entries stay shape-compatible (#481)."""
    _register_plugin("fake_plugin_platform", "mureo-fake-plugin-dist")

    [content] = await handle_tool("mureo_analytics_modules_list", {})
    payload = json.loads(content.text)
    expected_keys = {
        "platform",
        "registry_name",
        "capabilities",
        "source_distribution",
        "all_capabilities",
    }
    assert payload["modules"], "expected at least the built-in modules"
    for entry in payload["modules"]:
        assert set(entry) == expected_keys


@pytest.mark.asyncio
async def test_analytics_run_accepts_the_canonical_plugin_key() -> None:
    """The two tools chain: what ``modules_list`` reports must run (#481)."""
    _register_plugin("fake_plugin_platform", "mureo-fake-plugin-dist")

    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "plugin:mureo-fake-plugin-dist",
            "capability": AnalyticsCapability.DETECT_ANOMALIES.value,
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "ok"
    assert payload["platform"] == "plugin:mureo-fake-plugin-dist"
    assert payload["source_distribution"] == "mureo-fake-plugin-dist"


@pytest.mark.asyncio
async def test_analytics_run_still_accepts_the_registry_name() -> None:
    """Back-compat: a caller holding the registry name keeps working."""
    _register_plugin("fake_plugin_platform", "mureo-fake-plugin-dist")

    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "fake_plugin_platform",
            "capability": AnalyticsCapability.DETECT_ANOMALIES.value,
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_analytics_run_unknown_plugin_key_is_a_structured_status() -> None:
    """An unmatched ``plugin:<dist>`` key degrades, it does not raise."""
    [content] = await handle_tool(
        "mureo_analytics_run",
        {
            "platform": "plugin:not-installed",
            "capability": AnalyticsCapability.DETECT_ANOMALIES.value,
            "account_id": "acct-1",
        },
    )
    payload = json.loads(content.text)
    assert payload["status"] == "no_analytics_module"
    assert payload["platform"] == "plugin:not-installed"


@pytest.mark.asyncio
async def test_canonical_key_never_resolves_via_a_lookalike_registry_name() -> None:
    """A registry name shaped like a canonical key must not hijack it (#481).

    ModA is shipped by ``foo-dist`` but registered under the *literal*
    name ``plugin:bar-dist``; ModB is the genuine ``bar-dist`` module.
    Resolving ``plugin:bar-dist`` must reach ModB — the distribution is
    authoritative, and a name that merely *looks* like a key is not one.
    """
    impostor = _force_register("plugin:bar-dist", "foo-dist")
    genuine = _register_plugin("bar_ads", "bar-dist")

    resolved = _resolve_module("plugin:bar-dist")
    assert resolved is genuine
    assert resolved is not impostor


@pytest.mark.asyncio
async def test_unmatched_canonical_key_does_not_fall_back_to_a_name_match() -> None:
    """With no module for the distribution, the canonical key resolves to None."""
    _force_register("plugin:bar-dist", "foo-dist")

    assert _resolve_module("plugin:bar-dist") is None


@pytest.mark.asyncio
async def test_duplicate_distribution_gets_one_key_each(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two registry names sharing one distribution get DISTINCT keys (#537).

    The collapse #481 produced — both modules under
    ``plugin:shared-dist`` — is exactly the bug #537 fixes. The legacy
    short form is still resolvable (deterministic sorted-first registry
    name, unchanged), and the warning now points at the unambiguous keys
    rather than calling the packaging a mistake.
    """
    _register_plugin("zzz_ads", "shared-dist")
    first = _register_plugin("aaa_ads", "shared-dist")

    with caplog.at_level(logging.WARNING, logger="mureo.mcp.tools_analytics_registry"):
        [content] = await handle_tool("mureo_analytics_modules_list", {})
        legacy = _resolve_module("plugin:shared-dist")

    payload = json.loads(content.text)
    entries = [
        m for m in payload["modules"] if m["source_distribution"] == "shared-dist"
    ]
    assert len(entries) == 2
    assert {e["platform"] for e in entries} == {
        "plugin:shared-dist:aaa_ads",
        "plugin:shared-dist:zzz_ads",
    }
    assert {e["registry_name"] for e in entries} == {"aaa_ads", "zzz_ads"}

    # Back-compat: the legacy distribution-only key still resolves, first
    # wins on the sorted registry name.
    assert legacy is first

    assert any(
        "shared-dist" in record.message and "aaa_ads" in record.message
        for record in caplog.records
        if record.levelno == logging.WARNING
    ), "expected a warning naming the duplicated distribution"


@pytest.mark.asyncio
async def test_multi_module_distribution_resolves_the_right_module() -> None:
    """Each canonical key reaches ITS module, never the sibling's (#537).

    The write-side inverse of #533's double count: filing one platform's
    figures under another's name.
    """
    line = _register_plugin("fake_line_ads", "mureo-fake-multi-bridge")
    yahoo = _register_plugin("fake_yahoo_ads", "mureo-fake-multi-bridge")
    display = _register_plugin("fake_yahoo_ads_display", "mureo-fake-multi-bridge")

    assert _resolve_module("plugin:mureo-fake-multi-bridge:fake_line_ads") is line
    assert _resolve_module("plugin:mureo-fake-multi-bridge:fake_yahoo_ads") is yahoo
    assert (
        _resolve_module("plugin:mureo-fake-multi-bridge:fake_yahoo_ads_display")
        is display
    )


@pytest.mark.asyncio
async def test_legacy_key_still_joins_for_a_single_provider_distribution() -> None:
    """The #481 key keeps resolving where it was never ambiguous (#537).

    That is what makes the vast majority of already-written state correct
    with no rewrite.
    """
    module = _register_plugin("fake_solo_ads", "mureo-fake-solo-bridge")

    assert _resolve_module("plugin:mureo-fake-solo-bridge") is module
    assert _resolve_module("plugin:mureo-fake-solo-bridge:fake_solo_ads") is module


@pytest.mark.asyncio
async def test_canonical_key_does_not_resolve_a_sibling_provider() -> None:
    """A key naming a provider the distribution does not ship is not guessed.

    Falling back to "the distribution ships only one module, so it must be
    that one" is precisely the guessing #481 and #537 both refuse.
    """
    _register_plugin("fake_solo_ads", "mureo-fake-solo-bridge")

    assert _resolve_module("plugin:mureo-fake-solo-bridge:not_a_provider") is None


@pytest.mark.asyncio
async def test_handle_rejects_unknown_tool() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await handle_tool("nope", {})
