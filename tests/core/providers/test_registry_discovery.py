"""Entry-points-based discovery tests for ``mureo.core.providers.registry``.

RED phase tests for Issue #89 Phase 1 subtask P1-07 (discovery path).

These tests exercise the entry-points iteration loop inside
``discover_providers`` / ``Registry.discover``. They mock the registry's
imported reference to ``importlib.metadata.entry_points`` (not the
upstream stdlib symbol — the patch target is the *local name* inside
``mureo.core.providers.registry``) and feed in synthetic ``EntryPoint``
objects built from :class:`types.SimpleNamespace`.

Why ``SimpleNamespace``: the real ``importlib.metadata.EntryPoint`` is a
NamedTuple that is intentionally hard to construct directly; duck-typing
via ``SimpleNamespace`` with the same attribute shape (``name``,
``group``, ``dist``, ``load``) is the standard recommended pattern, is
simpler than installing real distributions, and is fully deterministic.

Marks: every test in this file is ``@pytest.mark.integration`` —
although the mocks keep everything in-process, the surface under test is
the cross-module entry-points integration boundary.
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import patch

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module ``mureo.core.providers.registry`` does not exist yet.
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import (  # noqa: E402
    PROVIDERS_ENTRY_POINT_GROUP,
    RegistryWarning,
    clear_registry,
    default_registry,
    discover_providers,
    get_provider,
)

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registry() -> Any:
    """Reset the global registry (and its discovery cache) per test.

    Discovery is cached for the lifetime of the process, so even an
    accidental cross-test ``discover_providers()`` call would otherwise
    leak between tests.
    """
    clear_registry()
    yield
    clear_registry()


class _FakeProvider:
    """Well-formed provider class returned by the well-formed fake EP."""

    name = "fake_provider"
    display_name = "Fake Provider"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})


class _BadProvider_NoCapabilities:  # noqa: N801 — semantic fixture name
    """Missing the ``capabilities`` class attribute — must be skipped."""

    name = "bad_no_caps"
    display_name = "Bad No Caps"


class _BadProvider_PlainSetCapabilities:  # noqa: N801 — semantic fixture name
    """``capabilities`` is a plain ``set`` (not a frozenset) — must be
    skipped because ``validate_provider`` rejects it.
    """

    name = "bad_plain_set"
    display_name = "Bad Plain Set"
    capabilities = {Capability.READ_CAMPAIGNS}  # type: ignore[assignment]


def _make_fake_entry_point(
    *,
    name: str,
    distribution: str | None,
    load_result: object | None = None,
    load_exception: BaseException | None = None,
) -> types.SimpleNamespace:
    """Build a duck-typed ``EntryPoint`` for the registry to consume.

    The registry only touches ``ep.name``, ``ep.dist.name``, and
    ``ep.load()`` so ``SimpleNamespace`` with those attributes is
    sufficient. ``dist`` may be ``None`` (rare in real installations,
    but documented behaviour) or a namespace with a ``.name``.
    """

    def _load() -> object:
        if load_exception is not None:
            raise load_exception
        return load_result

    dist: types.SimpleNamespace | None = (
        None if distribution is None else types.SimpleNamespace(name=distribution)
    )

    return types.SimpleNamespace(
        name=name,
        group=PROVIDERS_ENTRY_POINT_GROUP,
        dist=dist,
        load=_load,
    )


# ---------------------------------------------------------------------------
# Case 11 — discover_providers finds a well-formed entry-point class
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_discover_finds_well_formed_entry_point_class() -> None:
    """A well-formed entry-point class is loaded, validated, and exposed
    via ``get_provider``. ``source_distribution`` is captured from the
    EP's ``dist.name``. The second call to ``discover_providers`` does
    NOT re-call ``entry_points`` — cached idempotence (AC: idempotence).
    """
    fake_ep = _make_fake_entry_point(
        name="fake_provider",
        distribution="mureo-fake-plugin",
        load_result=_FakeProvider,
    )

    call_counter = {"n": 0}

    def _fake_entry_points(group: str) -> tuple[Any, ...]:
        assert group == PROVIDERS_ENTRY_POINT_GROUP, (
            "discover must iterate the providers group only; " f"got group={group!r}"
        )
        call_counter["n"] += 1
        return (fake_ep,)

    with patch(
        "mureo.core.providers.registry.entry_points",
        side_effect=_fake_entry_points,
    ):
        result = discover_providers()
        assert len(result) == 1
        (entry,) = result
        assert entry.name == "fake_provider"
        assert entry.provider_class is _FakeProvider
        assert entry.source_distribution == "mureo-fake-plugin"
        assert entry.capabilities == _FakeProvider.capabilities

        # Lookup via the public API resolves.
        resolved = get_provider("fake_provider")
        assert resolved.provider_class is _FakeProvider

        # Idempotence: a second call without refresh=True must NOT
        # re-iterate entry_points.
        result2 = discover_providers()
        assert result2 == result
        assert call_counter["n"] == 1, (
            "discover_providers() must be cached; "
            f"entry_points was called {call_counter['n']}x, expected 1"
        )


# ---------------------------------------------------------------------------
# Case 12 — discover_providers warns and skips on load failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_discover_warns_and_skips_on_load_failure() -> None:
    """A broken plugin (whose ``ep.load()`` raises) must not break
    discovery for the rest. The registry emits ``RegistryWarning`` and
    skips the offender. The well-formed sibling EP is still registered.

    This is the critical fault-isolation invariant.
    """
    broken_ep = _make_fake_entry_point(
        name="broken_plugin",
        distribution="mureo-broken-plugin",
        load_exception=ImportError("simulated broken plugin"),
    )
    good_ep = _make_fake_entry_point(
        name="fake_provider",
        distribution="mureo-good-plugin",
        load_result=_FakeProvider,
    )

    def _fake_entry_points(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (broken_ep, good_ep)

    with patch(
        "mureo.core.providers.registry.entry_points",
        side_effect=_fake_entry_points,
    ):
        with pytest.warns(RegistryWarning) as recorded:
            result = discover_providers()

        # The good plugin survived discovery.
        assert len(result) == 1
        (entry,) = result
        assert entry.name == "fake_provider"
        assert len(default_registry) == 1

        # The warning must mention the offending EP name and the
        # underlying exception message so the user can diagnose.
        combined = " ".join(str(w.message) for w in recorded)
        assert (
            "broken_plugin" in combined
        ), f"warning must include the EP name; got: {combined!r}"
        assert "simulated broken plugin" in combined, (
            f"warning must include the underlying exception message; "
            f"got: {combined!r}"
        )


# ---------------------------------------------------------------------------
# Case 13 — discover_providers warns and skips on validation failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("loaded_obj", "skip_reason"),
    [
        # The EP loaded a *function*, not a class. Must be rejected.
        (lambda: None, "non_class"),
        # The EP loaded a class missing ``capabilities``.
        (_BadProvider_NoCapabilities, "missing_attr"),
        # The EP loaded a class whose ``capabilities`` is a plain set.
        (_BadProvider_PlainSetCapabilities, "bad_frozenset"),
    ],
    ids=["non_class", "missing_attr", "bad_frozenset"],
)
def test_discover_warns_and_skips_on_validation_failure(
    loaded_obj: object,
    skip_reason: str,  # noqa: ARG001 — id-only param
) -> None:
    """Validation failures in entry-point discovery emit
    ``RegistryWarning`` and skip the offending entry. The registry is
    NOT poisoned: no partial-state insertion before validation passes.
    """
    fake_ep = _make_fake_entry_point(
        name="malformed",
        distribution="mureo-malformed-plugin",
        load_result=loaded_obj,
    )

    def _fake_entry_points(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (fake_ep,)

    with patch(
        "mureo.core.providers.registry.entry_points",
        side_effect=_fake_entry_points,
    ):
        with pytest.warns(RegistryWarning):
            result = discover_providers()

        assert result == (), "validation-failing EP must be skipped, not registered"
        assert len(default_registry) == 0


# ---------------------------------------------------------------------------
# Case 14 — discover_providers coerces non-str dist.name to None
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_discover_resolves_source_distribution_to_none_when_dist_name_non_str() -> None:
    """Defensive: weird ``Distribution`` shims (custom finders, build
    backends, or test stubs) may return a non-``str`` ``.name``. The
    registry must coerce that to ``None`` rather than propagating an
    untyped value into :class:`ProviderEntry.source_distribution`.

    Covers the ``isinstance(name, str)`` branch in
    :func:`_resolve_source`.
    """
    fake_ep = types.SimpleNamespace(
        name="weird_dist_provider",
        group=PROVIDERS_ENTRY_POINT_GROUP,
        dist=types.SimpleNamespace(name=123),  # non-str on purpose
        load=lambda: _FakeProvider,
    )

    def _fake_entry_points(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (fake_ep,)

    with patch(
        "mureo.core.providers.registry.entry_points",
        side_effect=_fake_entry_points,
    ):
        entries = discover_providers()
        assert len(entries) == 1
        assert entries[0].source_distribution is None
