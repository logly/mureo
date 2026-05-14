"""Tests for ``mureo.core.providers.extension``.

RED phase tests for Issue #89 Phase 1 subtask P1-06.

Pins the structural contract for ``ExtensionProvider`` — the
runtime-checkable Protocol search-platform adapters use for sitelinks /
callouts / conversion extensions. Social / display platforms typically
do NOT implement this Protocol.

Marks: all tests are ``@pytest.mark.unit`` — pure logic, no I/O, no
mocks needed.
"""

from __future__ import annotations

import inspect
import typing
from typing import Protocol

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module does not exist yet. The implementer (GREEN phase) will create
# ``mureo/core/providers/extension.py``.
from mureo.core.providers.base import BaseProvider
from mureo.core.providers.extension import ExtensionProvider
from mureo.core.providers.models import ExtensionKind

_REQUIRED_METHODS: tuple[str, ...] = (
    "list_extensions",
    "add_extension",
    "set_extension_status",
)


# ---------------------------------------------------------------------------
# Case 1 — ExtensionProvider is a runtime-checkable Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_provider_is_runtime_checkable_protocol() -> None:
    """``ExtensionProvider`` is a ``Protocol`` decorated with
    ``@runtime_checkable``.
    """
    assert issubclass(
        ExtensionProvider, Protocol
    ), "ExtensionProvider must be a typing.Protocol subclass"
    assert (
        getattr(ExtensionProvider, "_is_runtime_protocol", False) is True
    ), "ExtensionProvider must be decorated with @runtime_checkable"


# ---------------------------------------------------------------------------
# Case 2 — ExtensionProvider extends BaseProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_provider_extends_base_provider() -> None:
    """``ExtensionProvider`` structurally extends ``BaseProvider``.
    The three BaseProvider attributes must appear in its type hints, AND
    BaseProvider must be in the MRO.
    """
    assert BaseProvider in ExtensionProvider.__mro__, (
        "ExtensionProvider must declare ``class ExtensionProvider"
        "(BaseProvider, Protocol): ...``"
    )
    hints = typing.get_type_hints(ExtensionProvider)
    for attr in ("name", "display_name", "capabilities"):
        assert attr in hints, (
            f"ExtensionProvider must inherit attribute {attr!r} from "
            f"BaseProvider; got hints keys: {sorted(hints.keys())}"
        )


# ---------------------------------------------------------------------------
# Case 3 — All required methods are declared on the Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("method_name", _REQUIRED_METHODS)
def test_required_methods_present(method_name: str) -> None:
    """``ExtensionProvider`` declares the three documented method names."""
    assert hasattr(
        ExtensionProvider, method_name
    ), f"ExtensionProvider must declare method {method_name!r}"
    attr = getattr(ExtensionProvider, method_name)
    assert inspect.isfunction(attr) or callable(attr), (
        f"ExtensionProvider.{method_name} must be a function / callable; "
        f"got {type(attr).__name__}"
    )


# ---------------------------------------------------------------------------
# Case 4 — list_extensions ``kind`` param is ExtensionKind, not str
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_kind_parameter_is_extensionkind_enum() -> None:
    """``ExtensionProvider.list_extensions`` declares its ``kind``
    parameter as ``ExtensionKind`` — never ``str``. Forces type-safe
    dispatch so adapter implementations cannot accept arbitrary strings.
    """
    hints = typing.get_type_hints(ExtensionProvider.list_extensions)

    assert "kind" in hints, (
        "ExtensionProvider.list_extensions must declare a 'kind' parameter; "
        f"got hints: {sorted(hints.keys())}"
    )
    kind_type = hints["kind"]

    assert kind_type is ExtensionKind, (
        f"ExtensionProvider.list_extensions.kind must be typed as "
        f"ExtensionKind enum (type-safe dispatch); got {kind_type!r}"
    )
    assert kind_type is not str, (
        "ExtensionProvider.list_extensions.kind must NOT be bare str "
        "(use the ExtensionKind enum so adapters cannot accept "
        "arbitrary strings)"
    )
