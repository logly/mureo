"""Tests for ``mureo.core.providers.registry`` (in-process path).

RED phase tests for Issue #89 Phase 1 subtask P1-07.

These tests pin the stable in-process surface for the entry-points-based
provider discovery registry — ``ProviderEntry``, the module-level
``register_provider_class`` / ``get_provider`` / ``list_providers_by_capability``
/ ``clear_registry`` wrappers, the duplicate-name first-wins policy, and
the validation contract enforced by ``register_provider_class``.

This file deliberately exercises only the in-process / ``register_provider_class``
code path. The entry-points discovery path (which requires mocking
``importlib.metadata.entry_points``) is exercised in the sibling file
``test_registry_discovery.py``.

Marks: every test in this file is ``@pytest.mark.unit`` — pure logic,
no I/O, no entry-points mocking.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module ``mureo.core.providers.registry`` does not exist yet. That is
# correct. The implementer (GREEN phase) will create it.
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import (  # noqa: E402
    ProviderEntry,
    RegistryWarning,
    clear_registry,
    default_registry,
    get_provider,
    list_providers_by_capability,
    register_provider_class,
)

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registry() -> Any:
    """Reset the global ``default_registry`` before and after each test.

    Without this, registrations leak between tests and the order of
    insertion would alter assertions about ``first-wins`` semantics and
    capability listings.
    """
    clear_registry()
    yield
    clear_registry()


class _FakeProvider:
    """Well-formed provider class with three class attributes.

    Mirrors the recommended provider-implementation style documented in
    ``mureo.core.providers.base`` — name / display_name / capabilities
    declared as class attributes so the registry can introspect without
    instantiating.
    """

    name = "fake_provider"
    display_name = "Fake Provider"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})


class _AnotherFakeProvider:
    """Second well-formed provider for capability-filter / sort tests."""

    name = "another_fake"
    display_name = "Another Fake"
    capabilities = frozenset({Capability.READ_AUDIENCES})


# ---------------------------------------------------------------------------
# Case 1 — ProviderEntry is a frozen dataclass with the pinned field set
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_provider_entry_is_frozen_dataclass() -> None:
    """``ProviderEntry`` is a ``@dataclass(frozen=True)`` whose field set
    and order are the pinned ABI (AC line 1).

    Field order is part of the ABI: third-party callers may destructure
    via positional ``ProviderEntry(*tup)`` so we pin both the set and the
    order. Frozenness is verified by attempting an assignment and
    expecting ``dataclasses.FrozenInstanceError``.
    """
    assert dataclasses.is_dataclass(ProviderEntry), "ProviderEntry must be a dataclass"

    fields = [f.name for f in dataclasses.fields(ProviderEntry)]
    assert fields == [
        "name",
        "display_name",
        "capabilities",
        "provider_class",
        "source_distribution",
    ], (
        "ProviderEntry field set/order is part of the public ABI; "
        f"expected the documented five fields in order, got {fields!r}"
    )

    entry = ProviderEntry(
        name="fake_provider",
        display_name="Fake Provider",
        capabilities=frozenset({Capability.READ_CAMPAIGNS}),
        provider_class=_FakeProvider,
        source_distribution="mureo-fake",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Case 2 — ProviderEntry.__post_init__ validates name / display_name / caps
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "display_name", "capabilities", "exc_type"),
    [
        # name not str
        (
            123,
            "Display",
            frozenset({Capability.READ_CAMPAIGNS}),
            (TypeError, ValueError),
        ),
        # name fails regex (uppercase)
        (
            "Google_Ads",
            "Display",
            frozenset({Capability.READ_CAMPAIGNS}),
            ValueError,
        ),
        # name empty
        (
            "",
            "Display",
            frozenset({Capability.READ_CAMPAIGNS}),
            ValueError,
        ),
        # display_name not str
        (
            "fake_provider",
            42,
            frozenset({Capability.READ_CAMPAIGNS}),
            (TypeError, ValueError),
        ),
        # display_name empty
        (
            "fake_provider",
            "",
            frozenset({Capability.READ_CAMPAIGNS}),
            (TypeError, ValueError),
        ),
        # capabilities is a plain set, not frozenset
        (
            "fake_provider",
            "Display",
            {Capability.READ_CAMPAIGNS},
            (TypeError, ValueError),
        ),
    ],
    ids=[
        "name_not_str",
        "name_fails_regex_uppercase",
        "name_empty",
        "display_name_not_str",
        "display_name_empty",
        "capabilities_set_not_frozenset",
    ],
)
def test_provider_entry_validates_in_post_init(
    name: object,
    display_name: object,
    capabilities: object,
    exc_type: type[Exception] | tuple[type[Exception], ...],
) -> None:
    """``ProviderEntry.__post_init__`` rejects malformed shapes.

    Asserts each malformed value triggers ``ValueError`` or ``TypeError``
    at construction time — before the entry can poison the registry.
    """
    with pytest.raises(exc_type):
        ProviderEntry(
            name=name,  # type: ignore[arg-type]
            display_name=display_name,  # type: ignore[arg-type]
            capabilities=capabilities,  # type: ignore[arg-type]
            provider_class=_FakeProvider,
            source_distribution=None,
        )


# ---------------------------------------------------------------------------
# Case 3 — register_provider_class succeeds for a compliant class
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_register_provider_class_succeeds_for_compliant_class() -> None:
    """``register_provider_class`` returns a ``ProviderEntry`` whose fields
    mirror the registered class and whose ``source_distribution`` is
    captured from the keyword argument (AC line 13).
    """
    entry = register_provider_class(_FakeProvider, source_distribution="mureo-fake")

    assert isinstance(entry, ProviderEntry)
    assert entry.name == _FakeProvider.name
    assert entry.display_name == _FakeProvider.display_name
    assert entry.capabilities == _FakeProvider.capabilities
    assert entry.provider_class is _FakeProvider
    assert entry.source_distribution == "mureo-fake"

    # The class is now retrievable from the default registry.
    assert _FakeProvider.name in default_registry


# ---------------------------------------------------------------------------
# Case 4 — register_provider_class rejects non-class arguments
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_value",
    [
        # An *instance* of a well-formed provider class, not the class
        # itself. Catches the common mistake of registering an instance.
        _FakeProvider(),
        # A function, not a class.
        (lambda: None),
        # A plain dict that happens to have the three required keys.
        {
            "name": "fake_provider",
            "display_name": "Fake",
            "capabilities": frozenset({Capability.READ_CAMPAIGNS}),
        },
    ],
    ids=["instance", "function", "dict"],
)
def test_register_provider_class_rejects_non_class(bad_value: object) -> None:
    """Passing a non-class to ``register_provider_class`` raises
    ``TypeError`` with a message mentioning "class" or "type" (AC line 13,
    case 4 in the test plan).
    """
    with pytest.raises(TypeError) as excinfo:
        register_provider_class(bad_value)  # type: ignore[arg-type]

    msg = str(excinfo.value).lower()
    assert (
        "class" in msg or "type" in msg
    ), f"TypeError message must mention 'class' or 'type'; got: {msg!r}"


# ---------------------------------------------------------------------------
# Case 5 — register_provider_class rejects classes failing validate_provider
# ---------------------------------------------------------------------------


class _BadProvider_NoDisplayName:  # noqa: N801 — semantic fixture name
    """Class missing ``display_name`` — must be rejected."""

    name = "bad_no_display"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})


class _BadProvider_BadCapabilitiesType:  # noqa: N801 — semantic fixture name
    """``capabilities`` is a plain set, not a frozenset — must be rejected."""

    name = "bad_caps_type"
    display_name = "Bad Caps Type"
    capabilities = {Capability.READ_CAMPAIGNS}  # type: ignore[assignment]


class _BadProvider_BadName:  # noqa: N801 — semantic fixture name
    """``name`` fails the snake_case regex — must be rejected."""

    name = "Bad-Name"
    display_name = "Bad Name"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_class",
    [
        _BadProvider_NoDisplayName,
        _BadProvider_BadCapabilitiesType,
        _BadProvider_BadName,
    ],
    ids=["missing_display_name", "capabilities_not_frozenset", "bad_name_regex"],
)
def test_register_provider_class_rejects_invalid_provider_shape(
    bad_class: type,
) -> None:
    """Classes failing the ``validate_provider`` contract are rejected by
    the explicit registration API (raise, not warn — only entry-point
    discovery uses warn+skip; AC: validation failure semantics).

    The error message must include the class ``__qualname__`` so the
    caller can locate the offending class.
    """
    with pytest.raises((TypeError, ValueError)) as excinfo:
        register_provider_class(bad_class)

    msg = str(excinfo.value)
    assert bad_class.__qualname__ in msg or bad_class.__name__ in msg, (
        f"error message must include the class qualname "
        f"({bad_class.__qualname__!r}); got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# Case 6 — duplicate name first-wins with RegistryWarning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_duplicate_name_first_wins_with_warning() -> None:
    """Registering two classes under the same ``name`` keeps the first
    and warns on the second (AC: duplicate-name handling).

    The warning category must be ``RegistryWarning``; the message must
    mention both source_distribution values when provided so the user can
    decide which plugin to uninstall.
    """

    class FirstProvider:
        name = "google_ads"
        display_name = "Google Ads (First)"
        capabilities = frozenset({Capability.READ_CAMPAIGNS})

    class SecondProvider:
        name = "google_ads"  # deliberate duplicate
        display_name = "Google Ads (Second)"
        capabilities = frozenset({Capability.READ_CAMPAIGNS})

    register_provider_class(FirstProvider, source_distribution="mureo-first")

    with pytest.warns(RegistryWarning, match="google_ads") as recorded:
        register_provider_class(SecondProvider, source_distribution="mureo-second")

    # First-wins: the registered entry is the FIRST one.
    resolved = get_provider("google_ads")
    assert resolved.provider_class is FirstProvider, (
        "duplicate registration must follow first-wins semantics; "
        "the second registration should have been dropped."
    )

    # Both source_distribution values should appear in the warning text
    # so the user can locate both contenders.
    combined_msg = " ".join(str(w.message) for w in recorded)
    assert (
        "mureo-first" in combined_msg
    ), f"warning must mention first plugin's distribution; got: {combined_msg!r}"
    assert (
        "mureo-second" in combined_msg
    ), f"warning must mention second plugin's distribution; got: {combined_msg!r}"


# ---------------------------------------------------------------------------
# Case 7 — get_provider raises KeyError with helpful listing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_provider_unknown_raises_key_error_with_listing() -> None:
    """``get_provider("nope")`` raises ``KeyError`` whose message includes
    the missing name and the sorted list of known names (AC: get_provider
    error semantics, mirrors ``parse_capability`` style).
    """
    # Register two providers so the listing has content.
    register_provider_class(_FakeProvider, source_distribution="mureo-fake")
    register_provider_class(_AnotherFakeProvider, source_distribution="mureo-another")

    with pytest.raises(KeyError) as excinfo:
        get_provider("nope")

    # KeyError stringifies with surrounding quotes; assert against the
    # underlying ``.args[0]`` AND ``str(excinfo.value)`` so the test does
    # not over-specify which the implementer chooses to populate.
    msg = str(excinfo.value)
    assert "nope" in msg, f"KeyError must mention the missing name; got: {msg!r}"
    # The error message references that the name is unknown.
    assert (
        "known" in msg.lower() or "available" in msg.lower()
    ), f"KeyError must hint at known/available providers; got: {msg!r}"
    # At least one registered provider name must appear in the listing.
    assert (
        _FakeProvider.name in msg or _AnotherFakeProvider.name in msg
    ), f"KeyError must list at least one known provider name; got: {msg!r}"


# ---------------------------------------------------------------------------
# Case 8 — list_by_capability filters and sorts
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_by_capability_filters_and_is_sorted() -> None:
    """``list_providers_by_capability(cap)`` returns the matching entries
    sorted by ``name`` ascending; empty tuple when no provider declares
    the requested capability (AC: list-by-capability semantics).
    """

    class GoogleAds:
        name = "google_ads"
        display_name = "Google Ads"
        capabilities = frozenset({Capability.READ_CAMPAIGNS, Capability.READ_KEYWORDS})

    class MetaAds:
        name = "meta_ads"
        display_name = "Meta Ads"
        capabilities = frozenset({Capability.READ_CAMPAIGNS, Capability.READ_AUDIENCES})

    class TikTokAds:
        name = "tiktok_ads"
        display_name = "TikTok Ads"
        capabilities = frozenset({Capability.READ_AUDIENCES})

    # Deliberately register out of alphabetical order to exercise sorting.
    register_provider_class(MetaAds, source_distribution="mureo-meta")
    register_provider_class(TikTokAds, source_distribution="mureo-tiktok")
    register_provider_class(GoogleAds, source_distribution="mureo-google")

    by_read_campaigns = list_providers_by_capability(Capability.READ_CAMPAIGNS)
    names = [e.name for e in by_read_campaigns]
    assert names == ["google_ads", "meta_ads"], (
        f"READ_CAMPAIGNS filter must return google_ads and meta_ads in "
        f"alphabetical order; got: {names!r}"
    )

    # Capability nobody declared — empty tuple, not None.
    by_write_budget = list_providers_by_capability(Capability.WRITE_BUDGET)
    assert by_write_budget == ()
    assert isinstance(by_write_budget, tuple)


# ---------------------------------------------------------------------------
# Case 9 — list_by_capability rejects non-Capability arguments
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_cap",
    ["read_campaigns", 42, None, ["read_campaigns"]],
    ids=["string", "int", "none", "list_of_strings"],
)
def test_list_by_capability_rejects_non_capability_argument(
    bad_cap: object,
) -> None:
    """``list_providers_by_capability`` is defensive against third-party
    callers passing strings or other non-Capability values; it raises
    ``TypeError`` mentioning ``Capability`` (AC: list-by-capability type
    guard).
    """
    with pytest.raises(TypeError) as excinfo:
        list_providers_by_capability(bad_cap)  # type: ignore[arg-type]

    assert "Capability" in str(
        excinfo.value
    ), f"TypeError must mention 'Capability'; got: {str(excinfo.value)!r}"


# ---------------------------------------------------------------------------
# Case 10 — clear_registry resets state including discovery cache
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clear_registry_resets_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """``clear_registry()`` empties both the registration map and the
    discovery cache so a fresh ``discover_providers()`` re-iterates
    ``entry_points`` (AC: clear semantics).
    """
    from mureo.core.providers import registry as registry_module

    register_provider_class(_FakeProvider, source_distribution="mureo-fake")
    register_provider_class(_AnotherFakeProvider, source_distribution="mureo-another")
    assert len(default_registry) == 2

    clear_registry()
    assert len(default_registry) == 0

    # After clearing, a discovery call must hit the (mocked) entry_points
    # rather than returning a stale cache.
    call_count = {"n": 0}

    def _empty_entry_points(group: str) -> tuple[object, ...]:  # noqa: ARG001
        call_count["n"] += 1
        return ()

    monkeypatch.setattr(registry_module, "entry_points", _empty_entry_points)

    result = registry_module.discover_providers()
    assert result == ()
    assert call_count["n"] == 1, (
        "clear_registry() must also invalidate the discovery cache so "
        "the next discover_providers() re-iterates entry_points."
    )
