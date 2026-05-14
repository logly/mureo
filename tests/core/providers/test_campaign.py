"""Tests for ``mureo.core.providers.campaign``.

RED phase tests for Issue #89 Phase 1 subtask P1-03.

Pins the structural contract for ``CampaignProvider`` — the
runtime-checkable Protocol every adapter that supports campaign /
ad / daily-report operations must satisfy.

Marks: all tests are ``@pytest.mark.unit`` — pure logic, no I/O, no
mocks needed.
"""

# ruff: noqa: TC003
# ``date`` and ``Callable`` must stay at module top-level so
# ``typing.get_type_hints()`` and dataclass-time annotation resolution
# work for the runtime assertions and the ``_FakeCampaignProvider`` fixture.
from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module does not exist yet. The implementer (GREEN phase) will create
# ``mureo/core/providers/campaign.py``.
from mureo.core.providers.base import BaseProvider
from mureo.core.providers.campaign import CampaignProvider
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Campaign,
    CampaignFilters,
    CreateAdRequest,
    CreateCampaignRequest,
    DailyReportRow,
    UpdateAdRequest,
    UpdateCampaignRequest,
)

# Names every CampaignProvider must declare (per HANDOFF AC P1-03).
_REQUIRED_METHODS: tuple[str, ...] = (
    "list_campaigns",
    "get_campaign",
    "create_campaign",
    "update_campaign",
    "list_ads",
    "get_ad",
    "create_ad",
    "update_ad",
    "set_ad_status",
    "daily_report",
)


# ---------------------------------------------------------------------------
# Local _FakeCampaignProvider fixture — frozen dataclass that satisfies the
# Protocol attribute-wise (3 BaseProvider attrs + 10 method stubs).
# ---------------------------------------------------------------------------


def _noop(*args: object, **kwargs: object) -> object:  # pragma: no cover
    """Generic stub returning ``None``; satisfies callable-attribute checks."""
    return None


@dataclass(frozen=True)
class _FakeCampaignProvider:
    """Minimal frozen-dataclass fixture satisfying the CampaignProvider
    structural shape — three BaseProvider attributes plus the ten
    Protocol methods as instance-attribute callables.
    """

    name: str = "fake_ads"
    display_name: str = "Fake Ads"
    capabilities: frozenset[Capability] = field(
        default_factory=lambda: frozenset({Capability.READ_CAMPAIGNS})
    )
    list_campaigns: Callable[..., object] = field(default_factory=lambda: _noop)
    get_campaign: Callable[..., object] = field(default_factory=lambda: _noop)
    create_campaign: Callable[..., object] = field(default_factory=lambda: _noop)
    update_campaign: Callable[..., object] = field(default_factory=lambda: _noop)
    list_ads: Callable[..., object] = field(default_factory=lambda: _noop)
    get_ad: Callable[..., object] = field(default_factory=lambda: _noop)
    create_ad: Callable[..., object] = field(default_factory=lambda: _noop)
    update_ad: Callable[..., object] = field(default_factory=lambda: _noop)
    set_ad_status: Callable[..., object] = field(default_factory=lambda: _noop)
    daily_report: Callable[..., object] = field(default_factory=lambda: _noop)


# ---------------------------------------------------------------------------
# Case 1 — CampaignProvider is a runtime-checkable Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_campaign_provider_is_runtime_checkable_protocol() -> None:
    """``CampaignProvider`` is a ``Protocol`` decorated with
    ``@runtime_checkable``.
    """
    assert issubclass(
        CampaignProvider, Protocol
    ), "CampaignProvider must be a typing.Protocol subclass"
    assert getattr(CampaignProvider, "_is_runtime_protocol", False) is True, (
        "CampaignProvider must be decorated with @runtime_checkable so "
        "isinstance() can perform structural checks at runtime."
    )


# ---------------------------------------------------------------------------
# Case 2 — CampaignProvider extends BaseProvider attribute-wise
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_campaign_provider_extends_base_provider() -> None:
    """``CampaignProvider`` structurally extends ``BaseProvider`` — the
    three BaseProvider attributes (``name``, ``display_name``,
    ``capabilities``) must appear as annotated attributes on the
    Protocol, AND ``BaseProvider`` must be in the MRO.
    """
    assert BaseProvider in CampaignProvider.__mro__, (
        "CampaignProvider must declare ``class CampaignProvider"
        "(BaseProvider, Protocol): ...`` so BaseProvider is in its MRO."
    )

    hints = typing.get_type_hints(CampaignProvider)
    for attr in ("name", "display_name", "capabilities"):
        assert attr in hints, (
            f"CampaignProvider must inherit attribute {attr!r} from "
            f"BaseProvider; got hints keys: {sorted(hints.keys())}"
        )


# ---------------------------------------------------------------------------
# Case 3 — isinstance passes for a compliant fake (structural duck typing)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_isinstance_passes_for_compliant_fake() -> None:
    """A frozen-dataclass fixture exposing all BaseProvider attributes
    plus all CampaignProvider method attributes satisfies both
    ``isinstance(obj, CampaignProvider)`` and
    ``isinstance(obj, BaseProvider)``.
    """
    fake = _FakeCampaignProvider()
    assert isinstance(fake, BaseProvider) is True
    assert isinstance(fake, CampaignProvider) is True


# ---------------------------------------------------------------------------
# Case 4 — All required methods are declared on the Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("method_name", _REQUIRED_METHODS)
def test_required_methods_present(method_name: str) -> None:
    """``CampaignProvider`` declares every method named in the HANDOFF
    AC for P1-03. The attribute must be present and callable
    (Protocol methods are stored as function objects).
    """
    assert hasattr(
        CampaignProvider, method_name
    ), f"CampaignProvider must declare method {method_name!r}"
    attr = getattr(CampaignProvider, method_name)
    assert inspect.isfunction(attr) or callable(attr), (
        f"CampaignProvider.{method_name} must be a function / callable; "
        f"got {type(attr).__name__}"
    )


# ---------------------------------------------------------------------------
# Case 5 — daily_report uses datetime.date for start_date / end_date params
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_method_signatures_use_date_not_int() -> None:
    """``CampaignProvider.daily_report`` takes ``start_date`` and
    ``end_date`` typed as ``datetime.date`` — never ``int`` (no epoch
    seconds at the Protocol boundary).
    """
    hints = typing.get_type_hints(CampaignProvider.daily_report)

    for param in ("start_date", "end_date"):
        assert param in hints, (
            f"CampaignProvider.daily_report must declare parameter "
            f"{param!r}; got hints: {sorted(hints.keys())}"
        )
        param_type = hints[param]
        # Resolve Optional[date] / date | None to its non-None member.
        args = typing.get_args(param_type)
        if type(None) in args:
            non_none = [a for a in args if a is not type(None)]
            assert len(non_none) == 1
            inner = non_none[0]
        else:
            inner = param_type

        assert inner is date, (
            f"CampaignProvider.daily_report.{param} must be typed as "
            f"datetime.date; got {inner!r}"
        )
        assert inner is not int, (
            f"CampaignProvider.daily_report.{param} must NOT be int "
            f"(no epoch seconds at the Protocol boundary)"
        )

    # Return type must be tuple[DailyReportRow, ...] for immutability.
    return_type = hints.get("return")
    assert (
        return_type is not None
    ), "CampaignProvider.daily_report must declare a return annotation"
    origin = typing.get_origin(return_type)
    assert origin is tuple, (
        f"CampaignProvider.daily_report must return tuple[DailyReportRow, "
        f"...] (immutable); got origin {origin!r}, type {return_type!r}"
    )
    type_args = typing.get_args(return_type)
    assert DailyReportRow in type_args, (
        f"CampaignProvider.daily_report return tuple must carry "
        f"DailyReportRow elements; got args {type_args!r}"
    )


# ---------------------------------------------------------------------------
# Silence linter for imports used only for type resolution by ``get_type_hints``
# ---------------------------------------------------------------------------
_ = (
    Ad,
    AdStatus,
    Campaign,
    CampaignFilters,
    CreateAdRequest,
    CreateCampaignRequest,
    UpdateAdRequest,
    UpdateCampaignRequest,
)
