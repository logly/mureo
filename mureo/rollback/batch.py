"""Plan the reversal of a whole batch, gaps included (#549).

:func:`plan_rollback` answers "can this one entry be undone?". This module
answers the question an operator actually has after a bulk pass: "how much of
what I did on Monday can be undone, and what exactly cannot?"

The second half is the point. A revert that reports success while restoring
60 of 80 members is worse than useless — it leaves the operator unable to
eliminate their own fix as a variable, which is how an incident turns into a
rebuild. So this module classifies **every** member and reports the gaps
before anything is applied.

**Reversibility is decided by the existing planner, not re-invented here.**
Each member goes through :func:`mureo.rollback.planner.plan_rollback`, so the
allow-list, the destructive-verb refusal, the param-key bounding and the
plugin escape hatch all apply exactly as they do for a single entry. That also
means the per-platform differences fall out honestly: a native status toggle
with an allow-listed inverse plans as reversible, while a bridged tool's
reversal hint naming an operation mureo cannot dispatch plans as
``not_supported`` and is reported as a gap rather than quietly counted as
covered.

Pure and read-only: it takes a parsed :class:`StateDocument` and returns data.
Nothing here dispatches, and nothing here writes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.context.batch import batch_members, find_batch
from mureo.rollback.models import (
    BatchCoverage,
    BatchMemberPlan,
    BatchMemberStatus,
    BatchRollbackPlan,
    RollbackStatus,
)
from mureo.rollback.planner import plan_rollback

if TYPE_CHECKING:
    from mureo.context.models import ActionLogEntry, StateDocument


def _reversed_indices(doc: StateDocument) -> frozenset[int]:
    """Indices already closed by a later ``rollback_of`` marker.

    Same rule the executor enforces before dispatching, read here so the plan
    does not offer a member whose apply would be refused.
    """
    return frozenset(
        entry.rollback_of for entry in doc.action_log if entry.rollback_of is not None
    )


def _classify(
    index: int, entry: ActionLogEntry, *, already_reversed: bool
) -> BatchMemberPlan:
    """Verdict for one member, with the reason when it is a gap."""
    plan = plan_rollback(entry)
    if already_reversed:
        status = BatchMemberStatus.ALREADY_REVERSED
        reason = f"Entry #{index} was already rolled back by a later log entry."
    elif plan is None:
        status = BatchMemberStatus.NOTHING_TO_REVERSE
        reason = f"{entry.action} is a read-only action; it changed no state."
    elif plan.status is RollbackStatus.NOT_SUPPORTED:
        status = BatchMemberStatus.IRREVERSIBLE
        reason = plan.notes or (
            f"mureo cannot reverse {entry.action} on {entry.platform}."
        )
    elif plan.status is RollbackStatus.PARTIAL:
        status = BatchMemberStatus.REVERSIBLE_WITH_CAVEATS
        reason = "; ".join(plan.caveats)
    else:
        status = BatchMemberStatus.REVERSIBLE
        reason = ""
    return BatchMemberPlan(
        index=index,
        timestamp=entry.timestamp,
        action=entry.action,
        platform=entry.platform,
        status=status,
        plan=plan,
        reason=reason,
    )


def _coverage(members: tuple[BatchMemberPlan, ...]) -> BatchCoverage:
    """Aggregate coverage over the members that still need reversing.

    Members with nothing to reverse (reads) and members already reversed are
    excluded from the verdict: neither is an outstanding gap, and counting
    them would make a fully-reverted batch report ``partial`` forever.
    Everything else is either reversible or a gap, and a batch with both is
    ``PARTIAL`` — never rounded up to ``FULL``.
    """
    if not members:
        return BatchCoverage.EMPTY
    outstanding = [
        m
        for m in members
        if m.status
        not in (
            BatchMemberStatus.NOTHING_TO_REVERSE,
            BatchMemberStatus.ALREADY_REVERSED,
        )
    ]
    if not outstanding:
        return BatchCoverage.FULL
    reversible = sum(1 for m in outstanding if m.is_reversible)
    if reversible == len(outstanding):
        return BatchCoverage.FULL
    if reversible == 0:
        return BatchCoverage.NONE
    return BatchCoverage.PARTIAL


def _platform_coverage(
    members: tuple[BatchMemberPlan, ...],
) -> tuple[tuple[str, BatchCoverage], ...]:
    """Coverage per platform key, sorted by key.

    A batch that spans a native and a bridged platform usually has different
    answers for each, and the operator's next step depends on which platform
    they have to finish by hand.
    """
    by_platform: dict[str, list[BatchMemberPlan]] = {}
    for member in members:
        by_platform.setdefault(member.platform, []).append(member)
    return tuple(
        (platform, _coverage(tuple(group)))
        for platform, group in sorted(by_platform.items())
    )


def plan_batch_rollback(doc: StateDocument, batch_id: str) -> BatchRollbackPlan:
    """Build the reversal plan for every member of ``batch_id``.

    An unknown or empty batch returns a plan with
    :data:`~mureo.rollback.models.BatchCoverage.EMPTY` and no members, rather
    than raising — "this id collected nothing" is a truthful answer the
    operator needs, and it is distinguishable from "nothing can be reversed".

    Args:
        doc: The parsed STATE.json to read. Not mutated.
        batch_id: The batch id recorded on the member entries.

    Returns:
        A :class:`~mureo.rollback.models.BatchRollbackPlan` covering every
        member, each with its own verdict and — for the gaps — the reason.
    """
    already = _reversed_indices(doc)
    members = tuple(
        _classify(index, entry, already_reversed=index in already)
        for index, entry in batch_members(doc, batch_id)
    )
    # The record outlives the batch (BatchRecord.ended_at), so a closed batch
    # still reports the operator's own words for what it was.
    record = find_batch(doc, batch_id)
    return BatchRollbackPlan(
        batch_id=batch_id.strip(),
        label=record.label if record is not None else None,
        coverage=_coverage(members),
        members=members,
        platform_coverage=_platform_coverage(members),
        # Newest first — see BatchRollbackPlan.apply_order.
        apply_order=tuple(
            m.index for m in sorted(members, key=lambda m: -m.index) if m.is_reversible
        ),
    )


__all__ = ["plan_batch_rollback"]
