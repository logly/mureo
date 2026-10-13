"""#826 — a plugin platform label honours the provider's ``display_name``.

``platform_display_name`` used to derive every plugin label from the registry
name (``plugin:<dist>:<provider>`` → title-cased ``<provider>``), so a
provider could not surface its own brand casing. The provider's declared
``display_name`` is now read from the provider registry — the classes already
loaded by discovery, never a fresh entry-point scan — and used verbatim with
the ``" (plugin)"`` suffix. Anything that cannot be resolved falls back to the
old derivation.

Every test swaps in a fresh :class:`Registry` so nothing registered here
leaks into the shared ``default_registry``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from mureo.context import platform_guards
from mureo.core.providers import registry as provider_registry
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import ProviderEntry, Registry
from mureo.web.report_labels import platform_display_name

pytestmark = pytest.mark.unit

_DIST = "acme-ads"


def _provider_class(name: str, display_name: str) -> type:
    """Build a minimal class satisfying the ``BaseProvider`` contract."""
    return type(
        "FakeProvider",
        (),
        {
            "name": name,
            "display_name": display_name,
            "capabilities": frozenset({Capability.READ_CAMPAIGNS}),
        },
    )


@pytest.fixture
def fresh_registry(monkeypatch: pytest.MonkeyPatch) -> Registry:
    registry = Registry()
    monkeypatch.setattr(provider_registry, "default_registry", registry)
    return registry


def _register(
    registry: Registry,
    name: str,
    display_name: str,
    source_distribution: str | None = _DIST,
) -> None:
    registry.register_provider_class(
        _provider_class(name, display_name),
        source_distribution=source_distribution,
    )


class _StubRegistry:
    """A registry whose entries bypass ``ProviderEntry`` validation.

    Lets a test hand the resolver values ``ProviderEntry`` would refuse
    (a non-``str`` display name), which a hostile or half-built plugin
    could still produce through some other path.
    """

    def __init__(self, **entries: Any) -> None:
        self._entries = entries

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._entries

    def get(self, name: str) -> Any:
        return self._entries[name]


# ---------------------------------------------------------------------------
# Declared name is honoured
# ---------------------------------------------------------------------------


def test_declared_display_name_is_used_verbatim_with_the_suffix(
    fresh_registry: Registry,
) -> None:
    _register(fresh_registry, "acme_search_x", "ACME Search-X")

    assert (
        platform_display_name("plugin:acme-ads:acme_search_x")
        == "ACME Search-X (plugin)"
    )


def test_declared_display_name_is_stripped(fresh_registry: Registry) -> None:
    _register(fresh_registry, "acme_ads", "  ACME ads  ")

    assert platform_display_name("plugin:acme-ads:acme_ads") == "ACME ads (plugin)"


def test_bare_installed_name_agrees_with_its_canonical_key(
    monkeypatch: pytest.MonkeyPatch, fresh_registry: Registry
) -> None:
    """One platform, one label — whichever spelling the state holds (#631)."""
    monkeypatch.setattr(
        platform_guards,
        "_provider_entry_points",
        lambda: (SimpleNamespace(name="acme_ads"),),
    )
    _register(fresh_registry, "acme_ads", "ACME ads")

    assert platform_display_name("acme_ads") == "ACME ads (plugin)"
    assert platform_display_name("acme_ads") == platform_display_name(
        "plugin:acme-ads:acme_ads"
    )


# ---------------------------------------------------------------------------
# Fallback to the derived label
# ---------------------------------------------------------------------------


def test_unregistered_provider_keeps_the_derived_label(
    fresh_registry: Registry,
) -> None:
    assert platform_display_name("plugin:acme-ads:acme_ads") == "Acme Ads (plugin)"


@pytest.mark.parametrize("declared", ["   ", "\t\n"])
def test_blank_declared_name_falls_back(
    fresh_registry: Registry, declared: str
) -> None:
    _register(fresh_registry, "acme_ads", declared)

    assert platform_display_name("plugin:acme-ads:acme_ads") == "Acme Ads (plugin)"


@pytest.mark.parametrize("declared", [None, 42, b"ACME", ["ACME"]])
def test_non_string_declared_name_is_ignored(
    monkeypatch: pytest.MonkeyPatch, declared: object
) -> None:
    entry = SimpleNamespace(
        name="acme_ads", display_name=declared, source_distribution=_DIST
    )
    monkeypatch.setattr(
        provider_registry, "default_registry", _StubRegistry(acme_ads=entry)
    )

    assert platform_display_name("plugin:acme-ads:acme_ads") == "Acme Ads (plugin)"


def test_entry_without_display_name_attribute_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = SimpleNamespace(name="acme_ads", source_distribution=_DIST)
    monkeypatch.setattr(
        provider_registry, "default_registry", _StubRegistry(acme_ads=entry)
    )

    assert platform_display_name("plugin:acme-ads:acme_ads") == "Acme Ads (plugin)"


@pytest.mark.parametrize("source", ["other-dist", None])
def test_provider_from_another_distribution_is_not_borrowed(
    fresh_registry: Registry, source: str | None
) -> None:
    """The key names its distribution; a same-named provider loaded from a
    different (or unknown) one is not the platform the key denotes."""
    _register(fresh_registry, "acme_ads", "Someone Else", source_distribution=source)

    assert platform_display_name("plugin:acme-ads:acme_ads") == "Acme Ads (plugin)"


def test_legacy_short_key_keeps_its_derived_label(fresh_registry: Registry) -> None:
    """``plugin:<dist>`` names no provider, so there is no class to ask."""
    _register(fresh_registry, "acme_ads", "ACME ads")

    assert platform_display_name("plugin:acme-ads") == "Acme Ads (plugin)"


def test_uninstalled_bare_name_stays_unrecognised(
    monkeypatch: pytest.MonkeyPatch, fresh_registry: Registry
) -> None:
    """A registered class does not make an uninstalled bare key resolvable:
    ``label == key`` is the unrecognised-key signal and must not move."""
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: ())
    _register(fresh_registry, "acme_ads", "ACME ads")

    assert platform_display_name("acme_ads") == "acme_ads"


def test_unusable_plugin_keys_still_return_the_raw_key(
    fresh_registry: Registry,
) -> None:
    _register(fresh_registry, "acme_ads", "ACME ads")

    for key in ("plugin:", "plugin:acme-ads:"):
        assert platform_display_name(key) == key


# ---------------------------------------------------------------------------
# Built-in and official labels are unaffected
# ---------------------------------------------------------------------------


def test_builtin_keys_ignore_a_same_named_registered_provider(
    fresh_registry: Registry,
) -> None:
    _register(fresh_registry, "google_ads", "Hijacked", source_distribution=None)

    assert platform_display_name("google_ads") == "Google Ads"


def test_official_bridge_label_wins_over_a_declared_name(
    fresh_registry: Registry,
) -> None:
    _register(
        fresh_registry,
        "amazon_ads",
        "Something Else",
        source_distribution="mureo-amazon-ads-bridge",
    )

    assert (
        platform_display_name("plugin:mureo-amazon-ads-bridge:amazon_ads")
        == "Amazon Ads"
    )


def test_lookup_never_triggers_discovery(
    monkeypatch: pytest.MonkeyPatch, fresh_registry: Registry
) -> None:
    """Labelling reads what discovery already loaded; it never imports
    third-party code itself."""

    def _boom(*_args: Any, **_kwargs: Any) -> tuple[ProviderEntry, ...]:
        raise AssertionError("platform_display_name must not run discovery")

    monkeypatch.setattr(fresh_registry, "discover", _boom)
    monkeypatch.setattr(provider_registry, "entry_points", _boom)

    assert platform_display_name("plugin:acme-ads:acme_ads") == "Acme Ads (plugin)"
