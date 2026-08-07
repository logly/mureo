"""Immutable data models for the rollback planner."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RollbackStatus(str, Enum):
    """Outcome of a rollback planning attempt.

    ``str`` mixin keeps JSON serialization trivial.
    """

    SUPPORTED = "supported"
    """Rollback is clean: replaying ``operation(**params)`` restores the
    prior state."""

    PARTIAL = "partial"
    """Rollback reverses the configuration change but side effects (spend
    that was already incurred, impressions served, etc.) cannot be
    undone. ``caveats`` explains what remains irreversible."""

    NOT_SUPPORTED = "not_supported"
    """Rollback cannot be attempted — the source action was destructive
    (delete), carries no reversible hint, or the hint was malformed.
    ``operation`` and ``params`` are ``None`` in this case."""


@dataclass(frozen=True)
class RollbackPlan:
    """Concrete plan describing how to reverse one ``ActionLogEntry``.

    The plan is data, not execution. Executing it means invoking the
    MCP tool named in ``operation`` with ``params`` as kwargs — that
    responsibility sits with the caller.

    ``frozen=True`` blocks attribute reassignment but does not freeze
    dict contents, so ``__post_init__`` takes a defensive deep-copy of
    ``params`` to ensure a caller mutating the dict afterwards cannot
    corrupt the stored plan.
    """

    source_timestamp: str
    source_action: str
    platform: str
    status: RollbackStatus
    operation: str | None
    params: dict[str, Any] | None
    description: str
    caveats: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if self.params is not None:
            object.__setattr__(self, "params", copy.deepcopy(self.params))


class BatchMemberStatus(str, Enum):
    """What a single member of a batch can expect from a rollback (#549).

    Deliberately finer-grained than :class:`RollbackStatus`: a batch plan has
    to distinguish "there is nothing here to undo" from "there is something
    and mureo cannot undo it", because only the second is a gap in the revert
    the operator must close by hand.
    """

    REVERSIBLE = "reversible"
    """A plan exists and replaying it restores the prior state."""

    REVERSIBLE_WITH_CAVEATS = "reversible_with_caveats"
    """A plan exists, but side effects (spend incurred, impressions served)
    remain. The member's plan carries the caveats."""

    IRREVERSIBLE = "irreversible"
    """mureo cannot reverse this member — no hint, a hint outside the
    allow-list, or an operation on a platform mureo cannot dispatch to. The
    member's ``reason`` says which."""

    NOTHING_TO_REVERSE = "nothing_to_reverse"
    """A read-only action. Not a gap: there is no state change to undo."""

    ALREADY_REVERSED = "already_reversed"
    """A later ``action_log`` entry already carries ``rollback_of`` for this
    index, so applying again would be refused."""


class BatchCoverage(str, Enum):
    """How much of a batch a rollback would actually restore.

    This is the answer the motivating incident never got. An unverifiable
    revert leaves the operator unable to eliminate their own fix as a
    variable, so the honest values matter more than the optimistic one:
    ``PARTIAL`` and ``NONE`` must be reachable and must be reported BEFORE
    anything is applied.
    """

    FULL = "full"
    """Every member that changed state can be reversed."""

    PARTIAL = "partial"
    """Some members can be reversed and some cannot."""

    NONE = "none"
    """Nothing that changed state can be reversed."""

    EMPTY = "empty"
    """The batch has no members — an unknown id, or one that collected
    nothing."""


@dataclass(frozen=True)
class BatchMemberPlan:
    """One member of a batch, with its verdict.

    ``plan`` is the underlying :class:`RollbackPlan` when the planner produced
    one (including a ``not_supported`` plan, which carries the planner's
    reasoning), and ``None`` for a read-only member.
    """

    index: int
    timestamp: str
    action: str
    platform: str
    status: BatchMemberStatus
    plan: RollbackPlan | None
    reason: str = ""

    @property
    def is_reversible(self) -> bool:
        """Would applying this member's plan restore state now?

        ``ALREADY_REVERSED`` is False: it needs no action and a second apply
        is refused. ``NOTHING_TO_REVERSE`` is False for the same reason — and
        neither is counted as a gap.
        """
        return self.status in (
            BatchMemberStatus.REVERSIBLE,
            BatchMemberStatus.REVERSIBLE_WITH_CAVEATS,
        )


@dataclass(frozen=True)
class BatchRollbackPlan:
    """The reversal plan for a whole batch — every member, reversible or not.

    ``platform_coverage`` exists because reversibility is not uniform across
    platforms: an operation with a clean inverse on a native platform may have
    none on a bridged one whose tool set mureo does not own. Reporting one
    aggregate number would let a core abstraction paper over exactly that, so
    the per-platform breakdown is part of the plan, not a derived nicety.

    ``apply_order`` is reverse-chronological (newest member first), the order a
    caller should feed the indices to ``rollback_apply``: later members may
    depend on earlier ones, so undoing forwards can re-apply an effect the
    previous step just removed.
    """

    batch_id: str
    label: str | None
    coverage: BatchCoverage
    members: tuple[BatchMemberPlan, ...]
    platform_coverage: tuple[tuple[str, BatchCoverage], ...] = ()
    apply_order: tuple[int, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        """Member counts per :class:`BatchMemberStatus`, plus ``total``."""
        result = {status.value: 0 for status in BatchMemberStatus}
        for member in self.members:
            result[member.status.value] += 1
        result["total"] = len(self.members)
        return result
