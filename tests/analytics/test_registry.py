"""Registry discovery + lookup invariants for ``mureo.analytics.registry``.

Mirrors the pattern in ``tests/core/providers/test_registry_discovery.py``:
duck-typed entry points via :class:`types.SimpleNamespace`, an autouse
fixture that clears the global registry, and explicit RED-style cases
for each fault-isolation branch.
"""

from __future__ import annotations

import types
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest

from mureo.analytics.models import (
    Anomaly,
    BudgetEfficiency,
    CreativeAudit,
    PerformanceDiagnosis,
    PerformanceScope,
)
from mureo.analytics.protocol import AnalyticsCapability, AnalyticsModule
from mureo.analytics.registry import (
    ANALYTICS_ENTRY_POINT_GROUP,
    AnalyticsModuleWarning,
    AnalyticsRegistry,
    clear_analytics_registry,
    default_analytics_registry,
    discover_analytics_modules,
    get_analytics_module,
    list_analytics_platforms,
    register_analytics_module,
)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    clear_analytics_registry()
    yield
    clear_analytics_registry()


# ---------------------------------------------------------------------------
# Fake modules
# ---------------------------------------------------------------------------


class _WellFormedModule:
    platform = "fake_platform"

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


class _SecondFakeModule(_WellFormedModule):
    platform = "second_fake_platform"


class _DuplicatePlatformModule(_WellFormedModule):
    platform = "fake_platform"  # collides with _WellFormedModule


class _NoPlatformAttr:
    def capabilities(self) -> frozenset[AnalyticsCapability]:
        return frozenset()


class _NotConstructible(_WellFormedModule):
    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated constructor failure")


def _ep(
    name: str,
    *,
    load_result: object | None = None,
    load_exception: BaseException | None = None,
    distribution: str | None = "fake-dist",
) -> types.SimpleNamespace:
    def _load() -> object:
        if load_exception is not None:
            raise load_exception
        return load_result

    dist = None if distribution is None else types.SimpleNamespace(name=distribution)
    return types.SimpleNamespace(
        name=name,
        group=ANALYTICS_ENTRY_POINT_GROUP,
        dist=dist,
        load=_load,
    )


def _loader(*eps: Any) -> Any:
    def _entry_points(*, group: str) -> tuple[Any, ...]:
        assert group == ANALYTICS_ENTRY_POINT_GROUP
        return eps

    return _entry_points


# ---------------------------------------------------------------------------
# AnalyticsRegistry (direct, no entry points)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_register_then_get_returns_instance() -> None:
    reg = AnalyticsRegistry()
    inst = _WellFormedModule()
    reg.register(inst)
    assert reg.get("fake_platform") is inst


@pytest.mark.unit
def test_register_unknown_platform_returns_none() -> None:
    reg = AnalyticsRegistry()
    assert reg.get("never_registered") is None


@pytest.mark.unit
def test_register_first_wins_on_platform_collision() -> None:
    reg = AnalyticsRegistry()
    first = _WellFormedModule()
    second = _DuplicatePlatformModule()
    reg.register(first)
    reg.register(second)
    assert reg.get("fake_platform") is first


@pytest.mark.unit
def test_register_skips_module_without_platform_attribute() -> None:
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="platform"):
        reg.register(_NoPlatformAttr())  # type: ignore[arg-type]
    assert reg.platforms() == ()


@pytest.mark.unit
def test_register_skips_object_failing_protocol_check() -> None:
    reg = AnalyticsRegistry()

    class _NotAModule:
        platform = "x"
        # Missing capabilities() and all async methods.

    with pytest.warns(AnalyticsModuleWarning, match="missing required attribute"):
        reg.register(_NotAModule())  # type: ignore[arg-type]
    assert reg.get("x") is None


@pytest.mark.unit
def test_platforms_returns_sorted_tuple() -> None:
    reg = AnalyticsRegistry()
    reg.register(_SecondFakeModule())
    reg.register(_WellFormedModule())
    assert reg.platforms() == ("fake_platform", "second_fake_platform")


# ---------------------------------------------------------------------------
# Entry-point discovery
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_discover_finds_well_formed_entry_point() -> None:
    reg = AnalyticsRegistry()
    registered = reg.discover(
        loader=_loader(_ep("fake", load_result=_WellFormedModule))
    )
    assert registered == ("fake_platform",)
    assert reg.get("fake_platform") is not None


@pytest.mark.integration
def test_discover_is_idempotent_without_refresh() -> None:
    reg = AnalyticsRegistry()
    calls = {"n": 0}

    def _counting_loader(*, group: str) -> tuple[Any, ...]:
        assert group == ANALYTICS_ENTRY_POINT_GROUP
        calls["n"] += 1
        return (_ep("fake", load_result=_WellFormedModule),)

    reg.discover(loader=_counting_loader)
    reg.discover(loader=_counting_loader)
    assert calls["n"] == 1


@pytest.mark.integration
def test_discover_refresh_true_re_iterates_entry_points() -> None:
    reg = AnalyticsRegistry()
    calls = {"n": 0}

    def _counting_loader(*, group: str) -> tuple[Any, ...]:
        calls["n"] += 1
        return ()

    reg.discover(loader=_counting_loader)
    reg.discover(loader=_counting_loader, refresh=True)
    assert calls["n"] == 2


@pytest.mark.integration
def test_discover_isolates_load_exception() -> None:
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="load failed"):
        reg.discover(loader=_loader(_ep("bad", load_exception=RuntimeError("boom"))))
    assert reg.platforms() == ()


@pytest.mark.integration
def test_discover_isolates_constructor_exception() -> None:
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="not instantiable"):
        reg.discover(loader=_loader(_ep("x", load_result=_NotConstructible)))
    assert reg.platforms() == ()


@pytest.mark.integration
def test_discover_skips_non_class_entry_point() -> None:
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="must yield a class"):
        reg.discover(loader=_loader(_ep("x", load_result=_WellFormedModule())))
    assert reg.platforms() == ()


@pytest.mark.integration
def test_discover_first_wins_on_plugin_plugin_collision() -> None:
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="duplicate dropped"):
        reg.discover(
            loader=_loader(
                _ep("a", load_result=_WellFormedModule),
                _ep("b", load_result=_DuplicatePlatformModule),
            )
        )
    assert reg.platforms() == ("fake_platform",)


@pytest.mark.integration
def test_discover_total_failure_does_not_raise() -> None:
    reg = AnalyticsRegistry()

    def _exploding_loader(*, group: str) -> tuple[Any, ...]:
        raise RuntimeError("loader exploded")

    with pytest.warns(AnalyticsModuleWarning, match="discovery failed"):
        result = reg.discover(loader=_exploding_loader)
    assert result == ()


@pytest.mark.integration
def test_discover_records_source_distribution_breadcrumb() -> None:
    from mureo.analytics.registry import plugin_source

    reg = AnalyticsRegistry()
    reg.discover(
        loader=_loader(
            _ep("a", load_result=_WellFormedModule, distribution="mureo-fake")
        )
    )
    module = reg.get("fake_platform")
    assert module is not None
    assert plugin_source(module) == "mureo-fake"


# ---------------------------------------------------------------------------
# Module-level façade
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_default_registry_auto_loads_builtins() -> None:
    reg = default_analytics_registry()
    platforms = reg.platforms()
    # Built-ins for the mureo-native platforms must be present.
    assert "google_ads" in platforms
    assert "meta_ads" in platforms


@pytest.mark.integration
def test_get_analytics_module_returns_builtin() -> None:
    module = get_analytics_module("google_ads")
    assert module is not None
    assert module.platform == "google_ads"


@pytest.mark.integration
def test_list_analytics_platforms_includes_builtins() -> None:
    platforms = list_analytics_platforms()
    assert "google_ads" in platforms
    assert "meta_ads" in platforms


@pytest.mark.integration
def test_register_analytics_module_facade_writes_to_default() -> None:
    class _Inline(_WellFormedModule):
        platform = "inline_fake"

    register_analytics_module(_Inline())
    assert get_analytics_module("inline_fake") is not None


@pytest.mark.integration
def test_discover_analytics_modules_returns_tuple() -> None:
    # Refresh path returns a tuple (possibly empty) without raising.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AnalyticsModuleWarning)
        result = discover_analytics_modules(refresh=True)
    assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# Discovery path: instance-level validation branches
# ---------------------------------------------------------------------------


class _ClassWithoutPlatformAttr:
    def capabilities(self) -> frozenset[AnalyticsCapability]:
        return frozenset()

    async def detect_anomalies(
        self, account_id: str, *, window_days: int = 7
    ) -> tuple[Anomaly, ...]:
        return ()

    async def diagnose_performance(
        self, account_id: str, *, scope: PerformanceScope
    ) -> PerformanceDiagnosis:
        return PerformanceDiagnosis(
            platform="x",
            account_id=account_id,
            scope=scope,
            headline="",
            findings=(),
        )

    async def audit_creative(self, account_id: str) -> CreativeAudit:
        return CreativeAudit(platform="x", account_id=account_id)

    async def analyze_budget_efficiency(self, account_id: str) -> BudgetEfficiency:
        return BudgetEfficiency(platform="x", account_id=account_id)


class _NotProtocolCompliant:
    """Has a platform attribute but is missing Protocol methods."""

    platform = "broken_plugin"


class _SubclassMissingMethods(AnalyticsModule):  # type: ignore[misc]
    """Inherits the Protocol nominally but omits required methods.

    This is the CRITICAL case the explicit attribute validator must
    catch — ``isinstance(_, AnalyticsModule)`` would otherwise return
    ``True`` for any nominal subclass, regardless of method presence.
    """

    platform = "subclass_missing"


@pytest.mark.integration
def test_discover_skips_instance_without_platform_attr() -> None:
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="no `platform`"):
        reg.discover(loader=_loader(_ep("x", load_result=_ClassWithoutPlatformAttr)))
    assert reg.platforms() == ()


@pytest.mark.integration
def test_discover_skips_instance_failing_protocol_check() -> None:
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="missing required attribute"):
        reg.discover(loader=_loader(_ep("x", load_result=_NotProtocolCompliant)))
    assert reg.platforms() == ()


@pytest.mark.integration
def test_discover_rejects_subclass_with_missing_methods() -> None:
    """A class that inherits AnalyticsModule but omits required methods
    must be rejected. runtime_checkable Protocols short-circuit on
    nominal subclasses (isinstance returns True regardless of method
    presence) AND the Protocol's ``async def ...: ...`` stubs inherit
    as no-op coroutines that pass ``iscoroutinefunction``. Detecting
    the un-overridden stub by qualified name closes the gap.
    """
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="un-overridden"):
        reg.discover(loader=_loader(_ep("x", load_result=_SubclassMissingMethods)))
    assert reg.platforms() == ()


@pytest.mark.unit
def test_register_rejects_subclass_with_missing_methods() -> None:
    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="un-overridden"):
        reg.register(_SubclassMissingMethods())  # type: ignore[arg-type]
    assert reg.platforms() == ()


@pytest.mark.unit
def test_register_rejects_sync_method_override() -> None:
    """A subclass that turns an async method into a sync one must be
    rejected — the dispatch path always awaits, so a sync override
    would raise ``TypeError`` outside the fault-isolation boundary.
    """

    class _SyncMethod(_WellFormedModule):
        platform = "sync_method_platform"

        def detect_anomalies(  # type: ignore[override]
            self, account_id: str, *, window_days: int = 7
        ) -> tuple[Anomaly, ...]:
            return ()

    reg = AnalyticsRegistry()
    with pytest.warns(AnalyticsModuleWarning, match="async coroutine"):
        reg.register(_SyncMethod())
    assert reg.platforms() == ()


@pytest.mark.unit
def test_plugin_source_returns_breadcrumb_for_frozen_instance() -> None:
    """Frozen dataclass-style instances cannot accept arbitrary
    attribute mutation; the registry must record the source
    distribution in the side-table so attribution still works.
    """
    from dataclasses import dataclass

    from mureo.analytics.registry import plugin_source

    @dataclass(frozen=True)
    class _FrozenModule:
        platform: str = "frozen_platform"

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

    reg = AnalyticsRegistry()
    reg.discover(
        loader=_loader(
            _ep("frozen", load_result=_FrozenModule, distribution="mureo-frozen-plugin")
        )
    )
    module = reg.get("frozen_platform")
    assert module is not None
    assert plugin_source(module) == "mureo-frozen-plugin"


@pytest.mark.integration
def test_default_registry_warns_when_builtins_fail_to_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the deferred built-in import to raise; the registry must warn
    # and keep functioning rather than crashing the process.
    import mureo.analytics.registry as registry_mod

    def _exploding_loader() -> None:
        raise RuntimeError("simulated builtin failure")

    # Patch the symbol the registry will import via its deferred path.
    import mureo.analytics.builtin as builtin_mod

    monkeypatch.setattr(
        builtin_mod,
        "register_builtin_analytics_modules",
        _exploding_loader,
    )

    # Reset both global flags so the deferred path actually runs again.
    monkeypatch.setattr(registry_mod, "_DEFAULT_REGISTRY", None)
    monkeypatch.setattr(registry_mod, "_BUILTIN_LOADED", False)

    with pytest.warns(AnalyticsModuleWarning, match="built-in"):
        reg = registry_mod.default_analytics_registry()

    # Registry exists and is usable even when built-ins fail.
    assert reg.platforms() == ()
