"""Tests for ``mureo.core.providers.audience``.

RED phase tests for Issue #89 Phase 1 subtask P1-05.

Pins the structural contract for ``AudienceProvider`` — the
runtime-checkable Protocol audience-supporting adapters must satisfy.

Per the HANDOFF Open Question resolution, the canonical delete signal
is ``set_audience_status(audience_id, AudienceStatus.REMOVED)`` rather
than a separate ``delete_audience`` method. This keeps the Capability
enum locked and matches ``CampaignProvider.set_ad_status`` /
``KeywordProvider.set_keyword_status``.

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
# ``mureo/core/providers/audience.py``.
from mureo.core.providers.audience import AudienceProvider
from mureo.core.providers.base import BaseProvider

_REQUIRED_METHODS: tuple[str, ...] = (
    "list_audiences",
    "get_audience",
    "create_audience",
    "set_audience_status",
)


# ---------------------------------------------------------------------------
# Case 1 — AudienceProvider is a runtime-checkable Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_audience_provider_is_runtime_checkable_protocol() -> None:
    """``AudienceProvider`` is a ``Protocol`` decorated with
    ``@runtime_checkable``.
    """
    assert issubclass(
        AudienceProvider, Protocol
    ), "AudienceProvider must be a typing.Protocol subclass"
    assert (
        getattr(AudienceProvider, "_is_runtime_protocol", False) is True
    ), "AudienceProvider must be decorated with @runtime_checkable"


# ---------------------------------------------------------------------------
# Case 2 — AudienceProvider extends BaseProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_audience_provider_extends_base_provider() -> None:
    """``AudienceProvider`` structurally extends ``BaseProvider``.
    The three BaseProvider attributes must appear in its type hints, AND
    BaseProvider must be in the MRO.
    """
    assert BaseProvider in AudienceProvider.__mro__, (
        "AudienceProvider must declare ``class AudienceProvider"
        "(BaseProvider, Protocol): ...``"
    )
    hints = typing.get_type_hints(AudienceProvider)
    for attr in ("name", "display_name", "capabilities"):
        assert attr in hints, (
            f"AudienceProvider must inherit attribute {attr!r} from "
            f"BaseProvider; got hints keys: {sorted(hints.keys())}"
        )


# ---------------------------------------------------------------------------
# Case 3 — All required methods are declared on the Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("method_name", _REQUIRED_METHODS)
def test_required_methods_present(method_name: str) -> None:
    """``AudienceProvider`` declares the four documented method names.

    Note: ``set_audience_status`` is preferred over ``delete_audience``
    per the HANDOFF Open Question resolution (matches the
    delete-via-status convention used elsewhere in the provider ABI).
    """
    assert hasattr(
        AudienceProvider, method_name
    ), f"AudienceProvider must declare method {method_name!r}"
    attr = getattr(AudienceProvider, method_name)
    assert inspect.isfunction(attr) or callable(attr), (
        f"AudienceProvider.{method_name} must be a function / callable; "
        f"got {type(attr).__name__}"
    )
