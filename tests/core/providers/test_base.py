"""Tests for ``mureo.core.providers.base``.

RED phase tests for Issue #89 Phase 1 subtask P1-02.

These tests pin the stable structural contract for ``BaseProvider`` — the
runtime-checkable Protocol every mureo provider plugin (built-in
``google_ads``, ``meta_ads``, and third-party plugins via entry points)
must satisfy. Authentication is intentionally **not** part of this
contract (deferred to subclasses / a future ``AuthenticatedProvider``).

Marks: all tests are ``@pytest.mark.unit`` — pure logic, no I/O, no
mocks needed.
"""

from __future__ import annotations

import ast
import inspect
import re
import types
from dataclasses import dataclass
from typing import Protocol

import pytest

# NOTE: This import is expected to FAIL during the RED phase — the module
# does not exist yet. That is correct. The implementer (GREEN phase) will
# create ``mureo/core/providers/base.py``.
from mureo.core.providers.base import (  # noqa: E402
    BaseProvider,
    validate_provider,
    validate_provider_name,
)
from mureo.core.providers.capabilities import Capability

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeProvider:
    """Minimal frozen-dataclass fixture satisfying the BaseProvider shape.

    Used across cases to verify both ``isinstance`` (structural duck
    typing) and ``validate_provider`` (deeper structural validation) on
    a well-formed provider object.
    """

    name: str
    display_name: str
    capabilities: frozenset[Capability]


# ---------------------------------------------------------------------------
# Case 1 — BaseProvider is a runtime-checkable Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_base_provider_is_runtime_checkable_protocol() -> None:
    """``BaseProvider`` is a ``Protocol`` decorated with ``@runtime_checkable``.

    The ``runtime_checkable`` decorator sets the private attribute
    ``_is_runtime_protocol = True`` on the Protocol class. This test
    pins that attribute so the implementer cannot drop the decorator
    without failing the suite.
    """
    assert issubclass(
        BaseProvider, Protocol
    ), "BaseProvider must be a typing.Protocol subclass"
    assert getattr(BaseProvider, "_is_runtime_protocol", False) is True, (
        "BaseProvider must be decorated with @runtime_checkable so "
        "isinstance() can perform structural checks at runtime."
    )


# ---------------------------------------------------------------------------
# Case 2 — isinstance passes for an object with all required attributes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_isinstance_passes_for_object_with_required_attributes() -> None:
    """An object exposing ``name``, ``display_name``, and ``capabilities``
    satisfies ``isinstance(obj, BaseProvider)`` (AC #4).
    """
    fake = _FakeProvider(
        name="google_ads",
        display_name="Google Ads",
        capabilities=frozenset({Capability.READ_CAMPAIGNS}),
    )
    assert isinstance(fake, BaseProvider) is True


# ---------------------------------------------------------------------------
# Case 3 — isinstance fails when any required attribute is missing
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "missing_attr",
    ["name", "display_name", "capabilities"],
)
def test_isinstance_fails_when_attribute_missing(missing_attr: str) -> None:
    """Removing any one of the three required attributes makes
    ``isinstance(obj, BaseProvider)`` return ``False``.

    Uses ``types.SimpleNamespace`` so attribute removal is trivial.
    """
    attrs: dict[str, object] = {
        "name": "google_ads",
        "display_name": "Google Ads",
        "capabilities": frozenset({Capability.READ_CAMPAIGNS}),
    }
    del attrs[missing_attr]
    obj = types.SimpleNamespace(**attrs)
    assert (
        isinstance(obj, BaseProvider) is False
    ), f"Object missing {missing_attr!r} should not satisfy BaseProvider"


# ---------------------------------------------------------------------------
# Case 4 — validate_provider_name accepts valid snake_case identifiers
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "google_ads",
        "meta_ads",
        "tiktok_ads",
        "x",
        "x1",
        "long_provider_name_42",
    ],
)
def test_validate_provider_name_accepts_valid(value: str) -> None:
    """``validate_provider_name`` returns the input unchanged for
    snake_case identifiers matching ``^[a-z][a-z0-9_]*$`` (AC #5).
    """
    assert validate_provider_name(value) == value


# ---------------------------------------------------------------------------
# Case 5 — validate_provider_name rejects invalid names with ValueError
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "",
        "Google_Ads",
        "1google",
        "_google",
        "google-ads",
        "google ads",
        "google.ads",
        "GOOGLE_ADS",
        "google_ads ",
        " google_ads",
    ],
)
def test_validate_provider_name_rejects_invalid(value: str) -> None:
    """Invalid provider names raise ``ValueError`` whose message
    contains the offending input (AC #5).
    """
    with pytest.raises(ValueError, match=re.escape(repr(value))):
        validate_provider_name(value)


# ---------------------------------------------------------------------------
# Case 6 — validate_provider accepts a well-formed provider
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_provider_accepts_well_formed() -> None:
    """``validate_provider`` returns ``None`` and raises nothing for a
    well-formed provider whose name passes regex, display_name is
    non-empty, and capabilities is a ``frozenset[Capability]`` (AC #6).
    """
    fake = _FakeProvider(
        name="google_ads",
        display_name="Google Ads",
        capabilities=frozenset({Capability.READ_CAMPAIGNS, Capability.WRITE_BUDGET}),
    )
    assert validate_provider(fake) is None


# ---------------------------------------------------------------------------
# Case 7 — validate_provider rejects each ill-formed shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "display_name", "capabilities", "exc_type", "field_token"),
    [
        # name not str
        (
            123,
            "Display",
            frozenset({Capability.READ_CAMPAIGNS}),
            TypeError,
            "name",
        ),
        # name fails regex (uppercase)
        (
            "Google_Ads",
            "Display",
            frozenset({Capability.READ_CAMPAIGNS}),
            ValueError,
            "name",
        ),
        # name empty (also fails regex)
        (
            "",
            "Display",
            frozenset({Capability.READ_CAMPAIGNS}),
            ValueError,
            "name",
        ),
        # display_name not str
        (
            "google_ads",
            42,
            frozenset({Capability.READ_CAMPAIGNS}),
            TypeError,
            "display_name",
        ),
        # display_name empty string
        (
            "google_ads",
            "",
            frozenset({Capability.READ_CAMPAIGNS}),
            ValueError,
            "display_name",
        ),
        # capabilities is a regular set, not frozenset
        (
            "google_ads",
            "Display",
            {Capability.READ_CAMPAIGNS},
            TypeError,
            "capabilities",
        ),
        # capabilities frozenset contains a non-Capability member
        (
            "google_ads",
            "Display",
            frozenset({"read_campaigns"}),
            TypeError,
            "capabilities",
        ),
    ],
    ids=[
        "name_not_str",
        "name_fails_regex_uppercase",
        "name_empty",
        "display_name_not_str",
        "display_name_empty",
        "capabilities_set_not_frozenset",
        "capabilities_contains_non_capability",
    ],
)
def test_validate_provider_rejects_bad_shape(
    name: object,
    display_name: object,
    capabilities: object,
    exc_type: type[Exception],
    field_token: str,
) -> None:
    """Each malformed provider raises the documented exception type and
    the message mentions both the provider's identifying ``name`` (or
    ``repr``) and the offending field (AC #6).

    Additional pin: when ``capabilities`` is a plain ``set``, the
    message must mention ``frozenset``; when it contains a non-Capability
    element, the message must mention ``Capability``.
    """
    obj = types.SimpleNamespace(
        name=name,
        display_name=display_name,
        capabilities=capabilities,
    )

    with pytest.raises(exc_type) as excinfo:
        validate_provider(obj)

    msg = str(excinfo.value)
    assert field_token in msg, (
        f"exception message must mention the offending field "
        f"{field_token!r}; got: {msg!r}"
    )

    # Identity hint: either the provider's name (when str) or its repr
    # must appear in the message so the user can locate the bad provider.
    name_hint = name if isinstance(name, str) and name else repr(obj)
    if isinstance(name_hint, str) and name_hint:
        # Allow either the bare name or its repr in the message.
        assert name_hint in msg or repr(name_hint) in msg or repr(obj) in msg, (
            f"exception message must include provider identity "
            f"({name_hint!r} or repr); got: {msg!r}"
        )

    # Field-specific hints required by the HANDOFF.
    if (
        field_token == "capabilities"
        and isinstance(capabilities, set)
        and not isinstance(capabilities, frozenset)
    ):
        assert "frozenset" in msg, (
            "when capabilities is a plain set, message must mention "
            f"'frozenset'; got: {msg!r}"
        )
    if (
        field_token == "capabilities"
        and isinstance(capabilities, frozenset)
        and any(not isinstance(c, Capability) for c in capabilities)
    ):
        assert "Capability" in msg, (
            "when capabilities frozenset has a non-Capability member, "
            f"message must mention 'Capability'; got: {msg!r}"
        )


# ---------------------------------------------------------------------------
# Case 8 — base.py has no internal mureo.* imports other than capabilities
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_base_module_has_no_internal_mureo_imports_other_than_capabilities() -> None:
    """``base.py`` is a foundation-layer module — its only allowed
    internal import is ``mureo.core.providers.capabilities`` (AC #7).

    Uses ``ast.parse`` on the module's source to scan every ``Import``
    and ``ImportFrom`` node. ``TYPE_CHECKING``-guarded imports are
    intentionally treated identically to runtime imports for this
    foundation module — only ``capabilities`` may be referenced.

    Note: AST scan covers static ``import`` / ``from ... import`` only.
    ``importlib.import_module(...)`` and ``__import__(...)`` bypass
    detection (out of scope for this test).
    """
    import mureo.core.providers.base as base_module

    source_path = inspect.getsourcefile(base_module)
    assert source_path is not None, "Could not locate base.py on disk"

    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=source_path)

    own_module = base_module.__name__  # "mureo.core.providers.base"
    allowed = {"mureo.core.providers.capabilities"}
    offending: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (
                    alias.name.startswith("mureo.")
                    and alias.name != own_module
                    and alias.name not in allowed
                ):
                    offending.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level > 0:
                # Relative imports are still internal mureo.* — forbidden
                # unless they resolve to ``capabilities``. Even then, the
                # implementer should prefer the absolute form for clarity.
                offending.append(f"from {'.' * node.level}{mod} import ... (relative)")
            elif mod.startswith("mureo.") and mod != own_module and mod not in allowed:
                offending.append(f"from {mod} import ...")
            elif mod == "mureo":
                offending.append("from mureo import ...")

    assert offending == [], (
        "base.py may only import from mureo.core.providers.capabilities "
        f"among internal mureo.* modules. Found: {offending}"
    )


# ---------------------------------------------------------------------------
# Bonus — re-export check: the public package exposes the new API
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_re_export_from_package() -> None:
    """``mureo.core.providers`` re-exports ``BaseProvider``,
    ``validate_provider``, and ``validate_provider_name`` (AC #1).

    The re-exported objects must be the same identities as those defined
    in ``base.py`` (no wrapping / aliasing).
    """
    import mureo.core.providers as pkg

    assert pkg.BaseProvider is BaseProvider
    assert pkg.validate_provider is validate_provider
    assert pkg.validate_provider_name is validate_provider_name
