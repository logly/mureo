"""Open and close a batch in STATE.json — the path half of :mod:`mureo.context.batch`.

Split out of :mod:`mureo.context.state` in #917, verbatim;
:mod:`mureo.context.state` re-exports both functions, so existing imports keep
working. :mod:`mureo.context.batch` holds the pure rules (what "open" is, how
an entry joins); this module holds the two locked writes that open and close
the record. Every member joins through
:func:`mureo.context.action_log_store.append_action_log`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.models import StateDocument

from mureo.context.batch import BatchError, active_batch, batch_members, new_batch_id
from mureo.context.models import BatchRecord
from mureo.context.ops_linkage import call_request, link_batch
from mureo.context.state_io import _locked_state_mutation, _now_iso
from mureo.core.actor import current_call_reason, normalize_reason
from mureo.core.clock import server_now_iso


def begin_batch(path: Path, *, label: str) -> BatchRecord:
    """Open a batch: every later ``action_log`` entry joins it until it is ended.

    Args:
        path: STATE.json location.
        label: What this change set is, in the operator's words. Required and
            non-blank — an unlabelled batch id is a string the operator has to
            decode later, which is the reconstruction work #549 removes.

    Returns:
        The opened :class:`~mureo.context.models.BatchRecord`.

    A reason bound to the call opens the decision every member will share,
    and a bound ``decision_id`` adopts that decision for the batch (#848,
    :func:`mureo.context.ops_linkage.link_batch`).

    Raises:
        BatchError: A batch is already open. Refused rather than nested: two
            change sets merged into one cannot be told apart afterwards.
        ValueError: ``label`` is blank, or a bound ``decision_id`` is not
            linkable.
    """
    cleaned = label.strip() if isinstance(label, str) else ""
    if not cleaned:
        raise ValueError("label must be a non-empty string")
    request = call_request(normalize_reason(current_call_reason()), server_now_iso())

    opened: list[BatchRecord] = []

    def _build(doc: StateDocument) -> StateDocument:
        open_batch = active_batch(doc)
        if open_batch is not None:
            raise BatchError(
                f"Batch {open_batch.batch_id!r} ({open_batch.label!r}) is already "
                "open; end it before beginning another."
            )
        started_at = _now_iso()
        batch = BatchRecord(
            batch_id=new_batch_id(started_at),
            label=cleaned,
            started_at=started_at,
        )
        opened.append(batch)
        return link_batch(replace(doc, batches=(*doc.batches, batch)), batch, request)

    _locked_state_mutation(path, _build)
    return opened[0]


def end_batch(path: Path) -> tuple[BatchRecord, tuple[int, ...]]:
    """Close the open batch and report exactly what it collected.

    The record is kept (with ``ended_at`` set) rather than deleted, so the
    batch's label still answers "what was batch-2026… ?" long after the pass.

    Returns:
        The closed :class:`~mureo.context.models.BatchRecord` and the
        ``action_log`` indices of its members — the checklist that replaces
        reconstructing the change set by hand.

    Raises:
        BatchError: No batch is open.
    """
    closed: list[tuple[BatchRecord, tuple[int, ...]]] = []

    def _build(doc: StateDocument) -> StateDocument:
        open_batch = active_batch(doc)
        if open_batch is None:
            raise BatchError("No batch is open.")
        ended = replace(open_batch, ended_at=_now_iso())
        closed.append(
            (ended, tuple(index for index, _ in batch_members(doc, ended.batch_id)))
        )
        return replace(
            doc,
            batches=tuple(
                ended if b.batch_id == ended.batch_id else b for b in doc.batches
            ),
        )

    _locked_state_mutation(path, _build)
    return closed[0]


__all__ = ["begin_batch", "end_batch"]
