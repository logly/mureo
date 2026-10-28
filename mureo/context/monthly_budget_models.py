"""The monthly-budget answer type and its source vocabulary (#652, #656).

Split out of :mod:`mureo.context.monthly_budget` (#879): the reader there
falls back to :mod:`mureo.context.platform_monthly_budget`, which builds this
same :class:`MonthlyBudget`, so the type has to sit below both of them for
either to import the other at top level. :mod:`mureo.context.monthly_budget`
re-exports every name here, so ``from mureo.context.monthly_budget import
MonthlyBudget`` keeps working.

Dependency-free like :mod:`mureo.context.display_models`: nothing from
:mod:`mureo` is imported at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.platform_monthly_budget import IncompletePlatform

#: No target anywhere. ``total`` is ``None`` — the caller must not render a
#: figure, a percentage, or a pacing verdict from this.
SOURCE_NOT_SET: Final = "not_set"
#: The operator's own figure, read from the STRATEGY.md section. The only
#: source that is an AGREEMENT; the other three are configuration, a ceiling,
#: or nothing.
SOURCE_STRATEGY_SECTION: Final = "strategy_section"
#: Summed per-campaign monthly budgets, on platforms that declared they have
#: that concept (#656). What the platforms are *configured* to spend — a real
#: figure, neither derived from a ceiling nor agreed with a client. Label it
#: as configured wherever it is shown.
SOURCE_PLATFORM_CONFIGURED_SUM: Final = "platform_configured_sum"
#: Derived: ``## Guardrails`` → ``max_total_daily_budget`` × days in month. A
#: ceiling stretched over a month, not a plan. Label it as such wherever it
#: is shown.
SOURCE_IMPLIED_DAILY_CEILING: Final = "implied_daily_ceiling"

#: Shared read-only default so no instance allocates (or leaks) a mutable one.
_EMPTY_PER_PLATFORM: Final[Mapping[str, float]] = MappingProxyType({})


@dataclass(frozen=True)
class MonthlyBudget:
    """The operator's intended monthly spend, or the absence of one.

    Attributes:
        total: Whole-month figure, or ``None`` when no target is set.
            ``None`` and ``0.0`` are different answers: ``0.0`` is an
            operator who said "spend nothing", ``None`` is an operator who
            said nothing.
        per_platform: Read-only per-platform sub-targets **the operator
            wrote**, keyed by platform key (``google_ads``, ``meta_ads``, a
            plugin's own key). Empty when the section names none, and empty
            for every other source — a ceiling says nothing about the split,
            and a platform's own configuration is not a sub-target. The
            invariant is enforced, not merely documented: see
            :meth:`__post_init__`.
        configured_per_platform: Read-only per-platform subtotals **the
            platforms are configured with** (#656). Only ever populated for
            :data:`SOURCE_PLATFORM_CONFIGURED_SUM`. It is a separate field
            rather than a second meaning for ``per_platform`` because the
            two answer different questions, and a renderer built for the
            operator's split, pointed at a configured one, would otherwise
            label configuration as agreement. Reading the wrong field yields
            an empty mapping — nothing, never the other rung's figures.
        source: Which of the four answers this is — one of
            :data:`SOURCE_NOT_SET`, :data:`SOURCE_STRATEGY_SECTION`,
            :data:`SOURCE_PLATFORM_CONFIGURED_SUM`,
            :data:`SOURCE_IMPLIED_DAILY_CEILING`.
        incomplete_platforms: The platforms that have a monthly-budget
            concept but whose campaign set mureo cannot vouch for (#656), as
            :class:`~mureo.context.platform_monthly_budget.
            IncompletePlatform` records naming the platform AND why. Non-empty
            means a platform sum was possible in principle and was
            deliberately NOT taken: three of a client's five campaigns is a
            smaller number, not a smaller budget. The records ride along
            whatever answer was used instead, so every surface can say why
            the sum is missing — and which fix it needs — rather than showing
            a confident figure computed from part of the account.
    """

    total: float | None = None
    per_platform: Mapping[str, float] = field(
        default_factory=lambda: _EMPTY_PER_PLATFORM
    )
    source: str = SOURCE_NOT_SET
    incomplete_platforms: tuple[IncompletePlatform, ...] = ()
    configured_per_platform: Mapping[str, float] = field(
        default_factory=lambda: _EMPTY_PER_PLATFORM
    )

    def __post_init__(self) -> None:
        """Refuse a split that does not belong to this ``source``.

        The two mappings mean different things, and the failure this guards
        is a caller reusing the operator-split renderer on a configured sum
        — which states what a client is *charged* as what a client *agreed*.
        A docstring cannot stop that; an unconstructable object can. Raised
        at construction, not at read time, so a wrong pairing surfaces where
        it is made rather than on a screen.
        """
        if self.per_platform and self.source != SOURCE_STRATEGY_SECTION:
            raise ValueError(
                f"per_platform carries the sub-targets an operator wrote, so "
                f"it must be empty for source {self.source!r}; a platform's "
                f"own subtotals belong in configured_per_platform"
            )
        if (
            self.configured_per_platform
            and self.source != SOURCE_PLATFORM_CONFIGURED_SUM
        ):
            raise ValueError(
                f"configured_per_platform carries what the platforms are set "
                f"to spend, so it must be empty for source {self.source!r}"
            )

    @property
    def is_set(self) -> bool:
        """False when there is no target — the caller's cue to ask, not guess."""
        return self.source != SOURCE_NOT_SET

    @property
    def is_derived(self) -> bool:
        """True when ``total`` came from a ceiling, not from an operator."""
        return self.source == SOURCE_IMPLIED_DAILY_CEILING

    @property
    def is_platform_configured(self) -> bool:
        """True when ``total`` is what the PLATFORMS are set to spend.

        Never an agreement: a ¥300,000 configured ceiling routinely sits
        above a ¥200,000 agreement, and the two are worth showing side by
        side rather than collapsing. Only ``source ==``
        :data:`SOURCE_STRATEGY_SECTION` is a figure someone promised.
        """
        return self.source == SOURCE_PLATFORM_CONFIGURED_SUM


__all__ = [
    "SOURCE_IMPLIED_DAILY_CEILING",
    "SOURCE_NOT_SET",
    "SOURCE_PLATFORM_CONFIGURED_SUM",
    "SOURCE_STRATEGY_SECTION",
    "MonthlyBudget",
]
