"""The one table of providers shipped inside mureo (#992).

``mureo.bundled_providers`` registers every bundled provider that is not
switched off, and ``discover_with_bundled`` puts them beside the entry-point
providers for the MCP server. These tests pin the table walk, the disable
gate, the duplicate guard and the order (bundled first, then discovery) on a
fake table, and the real table's Amazon row end to end.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import pytest

from mureo import bundled_providers
from mureo.amazon_ads.bridge import AmazonAdsBridge
from mureo.amazon_ads.provider import AMAZON_PROVIDER_NAME
from mureo.bundled_providers import discover_with_bundled, register_bundled_providers
from mureo.chatgpt_ads.provider import CHATGPT_ADS_PROVIDER_NAME, ChatGPTAdsProvider
from mureo.core.providers import default_registry
from mureo.core.providers.registry import ProviderEntry, RegistryWarning
from tests.test_amazon_provider_registration import _isolated_registry  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("_isolated_registry")]


class _Provider:
    capabilities = frozenset()


def _entry(name: str, distribution: str = "bundled-test") -> ProviderEntry:
    return ProviderEntry(
        name=name,
        display_name=name,
        capabilities=frozenset(),
        provider_class=_Provider,
        source_distribution=distribution,
    )


def _register(name: str) -> Callable[[], ProviderEntry]:
    """A row's register function: idempotent and first-wins, like the real one."""

    def _do() -> ProviderEntry:
        if name in default_registry:
            return default_registry.get(name)
        entry = _entry(name)
        default_registry.register(entry)
        return entry

    return _do


def _use_table(monkeypatch: pytest.MonkeyPatch, rows: dict[str, bool]) -> None:
    """Install a fake table: ``{name: disabled}``, in insertion order."""
    table = tuple(
        ((lambda off=off: off), _register(name)) for name, off in rows.items()
    )
    monkeypatch.setattr(bundled_providers, "_BUNDLED_PROVIDERS", table)


class TestRegisterBundledProviders:
    def test_every_enabled_row_is_registered_in_table_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_table(monkeypatch, {"first_ads": False, "second_ads": False})

        entries = register_bundled_providers()

        assert [e.name for e in entries] == ["first_ads", "second_ads"]
        assert all(default_registry.get(e.name) is e for e in entries)

    def test_a_disabled_row_is_not_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_table(monkeypatch, {"on_ads": False, "off_ads": True})

        entries = register_bundled_providers()

        assert [e.name for e in entries] == ["on_ads"]
        assert "off_ads" not in default_registry

    def test_the_real_table_registers_amazon_then_chatgpt_ads(self) -> None:
        entries = register_bundled_providers()

        assert [e.name for e in entries] == [
            AMAZON_PROVIDER_NAME,
            CHATGPT_ADS_PROVIDER_NAME,
        ]
        assert default_registry.get(AMAZON_PROVIDER_NAME).provider_class is (
            AmazonAdsBridge
        )
        assert default_registry.get(CHATGPT_ADS_PROVIDER_NAME).provider_class is (
            ChatGPTAdsProvider
        )

    def test_the_real_amazon_row_honours_its_disable_switch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MUREO_DISABLE_AMAZON_ADS", "1")

        assert [e.name for e in register_bundled_providers()] == [
            CHATGPT_ADS_PROVIDER_NAME
        ]
        assert AMAZON_PROVIDER_NAME not in default_registry

    def test_the_real_chatgpt_ads_row_honours_its_disable_switch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MUREO_DISABLE_CHATGPT_ADS", "1")

        assert [e.name for e in register_bundled_providers()] == [AMAZON_PROVIDER_NAME]
        assert CHATGPT_ADS_PROVIDER_NAME not in default_registry

    def test_repeat_calls_are_silent(self) -> None:
        first = register_bundled_providers()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            second = register_bundled_providers()
            discover_with_bundled(tuple)

        assert second == first
        assert not [w for w in captured if issubclass(w.category, RegistryWarning)]


class TestDiscoverWithBundled:
    def test_bundled_entries_follow_the_discovered_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_table(monkeypatch, {"first_ads": False, "second_ads": False})
        plugin = _entry("plugin_ads", "third-party")

        entries = discover_with_bundled(lambda: (plugin,))

        assert [e.name for e in entries] == ["plugin_ads", "first_ads", "second_ads"]

    def test_bundled_registration_runs_before_discovery(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_table(monkeypatch, {"first_ads": False, "second_ads": False})
        seen: list[set[str]] = []

        def _discover() -> tuple[ProviderEntry, ...]:
            seen.append(
                {
                    name
                    for name in ("first_ads", "second_ads")
                    if name in default_registry
                }
            )
            return ()

        discover_with_bundled(_discover)

        assert seen == [{"first_ads", "second_ads"}]

    def test_a_same_named_discovered_entry_is_not_duplicated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_table(monkeypatch, {"first_ads": False})
        discovered = _entry("first_ads", "third-party")

        entries = discover_with_bundled(lambda: [discovered])

        assert entries == (discovered,)

    def test_a_disabled_row_is_neither_registered_nor_appended(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_table(monkeypatch, {"off_ads": True})
        plugin = _entry("plugin_ads", "third-party")

        entries = discover_with_bundled(lambda: iter([plugin]))

        assert entries == (plugin,)
        assert "off_ads" not in default_registry

    def test_returns_a_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_table(monkeypatch, {"first_ads": False})

        assert isinstance(discover_with_bundled(list), tuple)
