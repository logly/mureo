"""Tests for ``mureo.core.providers.capabilities``.

RED phase tests for Issue #89 Phase 1 subtask P1-01.

These tests pin the stable ABI surface for the Capability enum that all
provider Protocols, adapters, the entry-points registry, the skill matcher,
and third-party plugins will depend on.

Marks: all tests are ``@pytest.mark.unit`` — pure logic, no I/O, no mocks
needed.
"""

from __future__ import annotations

import ast
import inspect
import re
from enum import Enum
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable

# NOTE: This import is expected to FAIL during the RED phase — the module
# does not exist yet. That is correct. The implementer (GREEN phase) will
# create ``mureo/core/providers/capabilities.py``.
from mureo.core.providers.capabilities import (  # noqa: E402
    CAPABILITY_NAMES,
    Capability,
    parse_capabilities,
    parse_capability,
)

# Names that must exist on the enum per HANDOFF Acceptance Criteria #2.
_REQUIRED_CAPABILITY_NAMES: tuple[str, ...] = (
    "READ_CAMPAIGNS",
    "READ_PERFORMANCE",
    "READ_KEYWORDS",
    "READ_SEARCH_TERMS",
    "READ_AUDIENCES",
    "READ_EXTENSIONS",
    "WRITE_BUDGET",
    "WRITE_BID",
    "WRITE_CREATIVE",
    "WRITE_KEYWORDS",
    "WRITE_AUDIENCES",
    "WRITE_EXTENSIONS",
    "WRITE_CAMPAIGN_STATUS",
)

_SNAKE_CASE_RE: re.Pattern[str] = re.compile(r"[a-z_]+")


# ---------------------------------------------------------------------------
# Case 1 — Capability is a str-mixin Enum (StrEnum on 3.11+, shim on 3.10)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_capability_is_str_enum() -> None:
    """``Capability`` is a str-mixed Enum (StrEnum semantics).

    HANDOFF Risk note: ``StrEnum`` requires Python 3.11+. The project supports
    3.10+, so the implementer may use a shim (``class StrEnum(str, Enum): ...``).
    This test verifies the *semantics* required of a StrEnum — every member
    must be both an Enum member and a ``str`` instance whose string value
    equals its ``.value`` — without binding to the concrete ``StrEnum`` type
    name.
    """
    assert issubclass(
        Capability, str
    ), "Capability must be a subclass of str (StrEnum semantics)"
    assert issubclass(Capability, Enum), "Capability must be an Enum"

    # Round-trip: enum member equals and stringifies to its .value.
    for member in Capability:
        assert isinstance(member, str)
        assert member == member.value
        # Strict StrEnum semantics: ``str(member)`` must equal ``member.value``
        # exactly (no ``ClassName.MEMBER`` repr leak). Both 3.11+ stdlib
        # ``StrEnum`` and our 3.10 shim's ``__str__`` guarantee this.
        assert str(member) == member.value


# ---------------------------------------------------------------------------
# Case 2 — values are snake_case (parametrized over enum)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "member",
    list(Capability),
    ids=lambda m: m.name,
)
def test_capability_values_are_snake_case(member: Capability) -> None:
    """Every Capability member value matches ``^[a-z_]+$`` (AC #3)."""
    assert _SNAKE_CASE_RE.fullmatch(
        member.value
    ), f"{member.name}={member.value!r} is not snake_case"


# ---------------------------------------------------------------------------
# Case 3 — required members are present (parametrized over 13 names)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("name", _REQUIRED_CAPABILITY_NAMES)
def test_required_capability_members_present(name: str) -> None:
    """All 13 required Capability members exist (AC #2)."""
    assert hasattr(Capability, name), f"Capability is missing required member: {name}"


# ---------------------------------------------------------------------------
# Case 4 — CAPABILITY_NAMES is a frozenset mirroring all enum values
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_capability_names_frozenset() -> None:
    """``CAPABILITY_NAMES`` is a frozenset of all enum values (AC #4)."""
    assert isinstance(
        CAPABILITY_NAMES, frozenset
    ), f"CAPABILITY_NAMES must be a frozenset, got {type(CAPABILITY_NAMES).__name__}"
    assert frozenset(c.value for c in Capability) == CAPABILITY_NAMES


# ---------------------------------------------------------------------------
# Case 5 — parse_capability round-trips every member (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "member",
    list(Capability),
    ids=lambda m: m.name,
)
def test_parse_capability_round_trip(member: Capability) -> None:
    """``parse_capability(m.value) is m`` for every member (AC #5)."""
    parsed = parse_capability(member.value)
    assert parsed is member


# ---------------------------------------------------------------------------
# Case 6 — parse_capability raises ValueError mentioning the bad token
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_capability_unknown_raises_with_token() -> None:
    """Unknown capability token raises ``ValueError`` containing the token (AC #5)."""
    with pytest.raises(ValueError, match="does_not_exist"):
        parse_capability("does_not_exist")


# ---------------------------------------------------------------------------
# Case 7 — parse_capabilities returns a frozenset, dedupes silently
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_capabilities_returns_frozenset() -> None:
    """``parse_capabilities`` dedupes input and returns a ``frozenset`` (AC #6)."""
    inputs: Iterable[str] = ["read_campaigns", "read_campaigns", "write_budget"]
    result = parse_capabilities(inputs)

    # Strict identity check (not isinstance) — a frozenset subclass return
    # value would silently broaden the public ABI return type.
    assert (
        type(result) is frozenset
    ), f"return type must be exactly frozenset, got {type(result).__name__}"
    assert result == frozenset({Capability.READ_CAMPAIGNS, Capability.WRITE_BUDGET})


# ---------------------------------------------------------------------------
# Case 8 — parse_capabilities raises ValueError on unknown token
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_capabilities_unknown_raises() -> None:
    """An unknown token in the list raises ``ValueError`` mentioning that token.

    A valid token before the bad one must not suppress the error (AC #6).
    """
    with pytest.raises(ValueError, match="bogus_capability"):
        parse_capabilities(["read_campaigns", "bogus_capability", "write_budget"])


# ---------------------------------------------------------------------------
# Case 9 — module has no internal mureo.* imports (foundation rule, AST scan)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_capabilities_module_has_no_internal_mureo_imports() -> None:
    """The capabilities module is a foundation layer — it must not import
    from any other ``mureo.*`` module (AC #7).

    Uses ``ast.parse`` on the module's source to scan every ``Import`` and
    ``ImportFrom`` node. The module's own dotted path is allowed (it has no
    legitimate reason to appear, but excluding it explicitly future-proofs
    against ``from . import X`` style edits the implementer might add).

    Note: AST scan covers static ``import`` / ``from ... import`` only.
    ``importlib.import_module(...)`` and ``__import__(...)`` bypass
    detection. ``TYPE_CHECKING``-guarded imports are intentionally treated
    identically to runtime imports for this foundation module — zero
    internal mureo deps are allowed regardless of guard.
    """
    import mureo.core.providers.capabilities as capabilities_module

    source_path = inspect.getsourcefile(capabilities_module)
    assert source_path is not None, "Could not locate capabilities.py on disk"

    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=source_path)

    own_module = capabilities_module.__name__  # "mureo.core.providers.capabilities"
    offending: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("mureo.") and alias.name != own_module:
                    offending.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports (node.level > 0) — they are still
            # internal mureo.* and must also be forbidden here.
            mod = node.module or ""
            if node.level > 0:
                offending.append(f"from {'.' * node.level}{mod} import ... (relative)")
            elif mod.startswith("mureo.") and mod != own_module:
                offending.append(f"from {mod} import ...")
            elif mod == "mureo":
                offending.append("from mureo import ...")

    assert offending == [], (
        "capabilities.py must have no internal mureo.* imports "
        f"(foundation rule). Found: {offending}"
    )


# ---------------------------------------------------------------------------
# Bonus — AC #1 re-export check: the public package re-exports the API.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_core_providers_package_reexports_public_api() -> None:
    """``mureo.core.providers`` re-exports the four public names (AC #1).

    This is the import path third-party plugins and SKILL frontmatter
    consumers are encouraged to use.
    """
    import mureo.core.providers as pkg

    assert pkg.Capability is Capability
    assert pkg.CAPABILITY_NAMES is CAPABILITY_NAMES
    assert pkg.parse_capability is parse_capability
    assert pkg.parse_capabilities is parse_capabilities
