"""Which tool calls are exclusion surfaces, and where their numbers come from.

A registry, in the shape the budget/bid declarations already use
(:mod:`mureo.policy.declarations`): mureo registers the surfaces it owns
the schema for, and a plugin or bridge registers its own through the same
public function. A tool with no registration is not an exclusion surface as
far as mureo is concerned, so the pre-flight skips it entirely and does no
I/O — which is what keeps the check off the other ~200 tools.

A surface is two callables:

``targets``
    Pure. Reads the tool's own arguments and returns the entities the call
    is about to exclude.
``delivery``
    Awaited. Returns the account's own recent delivery for the scope those
    entities live in — or :class:`DeliverySample` with ``records=None`` and
    a ``reason``, which is how a platform says "I cannot attribute past
    delivery to this kind of entity". Returning ``None`` records is a
    supported, honest answer; returning empty records to mean the same
    thing would print "0% impact" and read as approval.

The provider ABI hook the issue asks for is exactly this: a bridge with a
supply-side view registers a ``delivery`` that carries it, and the same
preview then gates that platform's blocks too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping

    from mureo.analysis.exclusion_impact.models import DeliveryRecord, ExclusionTarget


@dataclass(frozen=True)
class DeliverySample:
    """The account's own delivery for one exclusion scope.

    ``records=None`` means "not attributable", with ``reason`` saying why.
    ``standing=None`` means the standing exclusion set could not be listed,
    with ``standing_reason`` saying why; the cumulative figure is then
    withheld rather than understated.
    """

    records: tuple[DeliveryRecord, ...] | None
    basis: str
    attributable_types: frozenset[str] = frozenset()
    reason: str = ""
    standing: tuple[ExclusionTarget, ...] | None = None
    standing_reason: str = ""


@dataclass(frozen=True)
class ExclusionSurface:
    """One tool whose call removes inventory from delivery."""

    tool: str
    platform: str
    targets: Callable[[Mapping[str, Any]], Iterable[ExclusionTarget]]
    delivery: Callable[[Mapping[str, Any], int], Awaitable[DeliverySample]]
    #: Human-readable note carried into the preview output, e.g. a known
    #: limit of the platform's report.
    note: str = field(default="")


_SURFACES: dict[str, ExclusionSurface] = {}


def register_exclusion_surface(surface: ExclusionSurface) -> None:
    """Register (or replace) the exclusion surface for ``surface.tool``."""
    _SURFACES[surface.tool] = surface


def exclusion_surface_for(tool: str) -> ExclusionSurface | None:
    """The registered surface for ``tool``, or ``None`` if it is not one."""
    return _SURFACES.get(tool)


def registered_exclusion_tools() -> frozenset[str]:
    """Every tool name currently registered as an exclusion surface."""
    return frozenset(_SURFACES)


def reset_exclusion_surfaces() -> None:
    """Drop every registration. Test-support; not part of the plugin ABI."""
    _SURFACES.clear()


__all__ = [
    "DeliverySample",
    "ExclusionSurface",
    "exclusion_surface_for",
    "register_exclusion_surface",
    "registered_exclusion_tools",
    "reset_exclusion_surfaces",
]
