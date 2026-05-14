"""Tests for ``mureo.core.providers.keyword``.

RED phase tests for Issue #89 Phase 1 subtask P1-04.

Pins the structural contract for ``KeywordProvider`` — the
runtime-checkable Protocol search-platform adapters (Google Ads,
Bing/Microsoft Ads, Apple Search Ads) must satisfy. Social / display
platforms typically do NOT implement this Protocol.

Marks: all tests are ``@pytest.mark.unit`` — pure logic, no I/O, no
mocks needed.
"""

from __future__ import annotations

import collections.abc
import inspect
import typing
from typing import Protocol

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module does not exist yet. The implementer (GREEN phase) will create
# ``mureo/core/providers/keyword.py``.
from mureo.core.providers.base import BaseProvider
from mureo.core.providers.keyword import KeywordProvider
from mureo.core.providers.models import KeywordSpec

_REQUIRED_METHODS: tuple[str, ...] = (
    "list_keywords",
    "add_keywords",
    "set_keyword_status",
    "search_terms",
)


# ---------------------------------------------------------------------------
# Case 1 — KeywordProvider is a runtime-checkable Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_keyword_provider_is_runtime_checkable_protocol() -> None:
    """``KeywordProvider`` is a ``Protocol`` decorated with
    ``@runtime_checkable``.
    """
    assert issubclass(
        KeywordProvider, Protocol
    ), "KeywordProvider must be a typing.Protocol subclass"
    assert (
        getattr(KeywordProvider, "_is_runtime_protocol", False) is True
    ), "KeywordProvider must be decorated with @runtime_checkable"


# ---------------------------------------------------------------------------
# Case 2 — KeywordProvider extends BaseProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_keyword_provider_extends_base_provider() -> None:
    """``KeywordProvider`` structurally extends ``BaseProvider``.
    The three BaseProvider attributes must appear in its type hints, AND
    BaseProvider must be in the MRO.
    """
    assert BaseProvider in KeywordProvider.__mro__, (
        "KeywordProvider must declare ``class KeywordProvider"
        "(BaseProvider, Protocol): ...``"
    )
    hints = typing.get_type_hints(KeywordProvider)
    for attr in ("name", "display_name", "capabilities"):
        assert attr in hints, (
            f"KeywordProvider must inherit attribute {attr!r} from "
            f"BaseProvider; got hints keys: {sorted(hints.keys())}"
        )


# ---------------------------------------------------------------------------
# Case 3 — All required methods are declared on the Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("method_name", _REQUIRED_METHODS)
def test_required_methods_present(method_name: str) -> None:
    """``KeywordProvider`` declares the four documented method names."""
    assert hasattr(
        KeywordProvider, method_name
    ), f"KeywordProvider must declare method {method_name!r}"
    attr = getattr(KeywordProvider, method_name)
    assert inspect.isfunction(attr) or callable(attr), (
        f"KeywordProvider.{method_name} must be a function / callable; "
        f"got {type(attr).__name__}"
    )


# ---------------------------------------------------------------------------
# Case 4 — add_keywords accepts Sequence[KeywordSpec], not list[KeywordSpec]
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_add_keywords_accepts_sequence_not_list() -> None:
    """``KeywordProvider.add_keywords`` declares its ``keywords``
    parameter as ``Sequence[KeywordSpec]`` (covariant, read-only input
    view) — NOT ``list[KeywordSpec]``. Inputs that are collections must
    use ``Sequence`` per the immutability convention.

    The return type must also be ``tuple[Keyword, ...]`` — never
    ``list[Keyword]`` — per the same convention.
    """
    hints = typing.get_type_hints(KeywordProvider.add_keywords)

    assert "keywords" in hints, (
        "KeywordProvider.add_keywords must declare a 'keywords' parameter; "
        f"got hints: {sorted(hints.keys())}"
    )
    param_type = hints["keywords"]
    origin = typing.get_origin(param_type)

    # Origin should be collections.abc.Sequence (typing.Sequence aliases to
    # it on Python 3.9+).
    assert origin is collections.abc.Sequence, (
        f"KeywordProvider.add_keywords.keywords must be typed as "
        f"Sequence[KeywordSpec] (read-only input view), NOT list[...]; "
        f"got origin {origin!r}, type {param_type!r}"
    )

    # Defensive: explicit list rejection.
    assert origin is not list, (
        "KeywordProvider.add_keywords.keywords must NOT be list[...] "
        "(violates input-immutability rule)"
    )

    type_args = typing.get_args(param_type)
    assert KeywordSpec in type_args, (
        f"KeywordProvider.add_keywords.keywords must carry KeywordSpec "
        f"elements; got args {type_args!r}"
    )
