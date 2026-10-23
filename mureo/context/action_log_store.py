"""Append to STATE.json's ``action_log`` — the single recording choke point.

Split out of :mod:`mureo.context.state` in #917, verbatim apart from
:func:`append_action_log` being broken into its named steps (the
validation before the lock, the locked build); :mod:`mureo.context.state`
re-exports it, so existing imports keep working.

The single choke point
----------------------

:func:`append_action_log` is the single choke point every recording path
funnels through — native status toggles, ``mureo_state_action_log_append``,
and the bridged / plugin promotion — so it is also where the workspace's open
batch is stamped onto the entry (#549). Doing it here, inside the lock, is
what makes batch membership platform-agnostic: no tool schema, no
per-platform recorder and no plugin ABI has to know the batch exists.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.models import ActionLogEntry, StateDocument
    from mureo.context.ops_linkage import LinkRequest

from mureo.context._preserve import refuse_if_kept
from mureo.context.actor_stamp import stamp_actor
from mureo.context.batch import active_batch, ensure_joinable, stamp_batch
from mureo.context.ops_linkage import call_request, commit_slot, link_entry
from mureo.context.state_io import _locked_state_mutation
from mureo.core.actor import current_call_reason, normalize_reason
from mureo.core.clock import server_now_iso
from mureo.core.display_contract import validate_action_log_display


def _validated_request(entry: ActionLogEntry, expected: Any) -> LinkRequest:
    """Refuse an entry that cannot be written, and bind the call's request.

    Runs before the file is opened. It is also where WHY is resolved (#758
    phase 2): the rationale the agent gave on the call's ``reason``
    parameter. Same argument as the batch id — doing it here is what makes
    it platform-agnostic, and what joins an ``action_log`` entry to the
    ``JOURNAL.jsonl`` records of the session that wrote it.

    An **observed** entry (``origin="external"``, #545) is the exception, and
    only for the rationale: mureo did not make that change, so the reason it
    happened is not mureo's to state and the call's rationale is not inherited.

    A display field over its bound (#706) or a rationale over
    :data:`~mureo.core.actor.ACTION_REASON_MAX_CHARS` (#758) is refused,
    never truncated, and refused BEFORE the file is opened — so a rejected
    append leaves the log exactly as it was and the caller still holds the
    sentence it can shorten.
    """
    # Outside the lock: the dashboard's one-line rendering is a WRITE rule, so
    # this is the moment to refuse it. An entry already on disk is history and
    # is read back exactly as it is.
    validate_action_log_display(
        display_title=entry.display_title,
        display_summary=entry.display_summary,
    )
    # An explicit rationale on the entry wins over the one bound to the call:
    # a caller that states its own reason knows something the dispatcher's
    # blanket parameter does not. An observed change falls back to nothing
    # instead: the importing call's reason explains the IMPORT, and stamping
    # it here would file mureo's motive under somebody else's change. Bounded
    # before the file is opened, exactly like the display fields.
    inherited = None if entry.origin is not None else current_call_reason()
    reason = normalize_reason(entry.reason if entry.reason is not None else inherited)
    return call_request(reason, server_now_iso(), expected)


def _with_entry(
    doc: StateDocument,
    entry: ActionLogEntry,
    request: LinkRequest,
    *,
    join_active_batch: bool,
) -> StateDocument:
    """``doc`` with ``entry`` stamped, linked and appended — the locked step.

    An explicit ``batch_id`` on the entry is **validated, not trusted**: it must
    name a batch that exists and is still open
    (:func:`mureo.context.batch.ensure_joinable`). Checking here rather than in
    the MCP handler means no caller — handler, library user or future recorder
    — can invent a change set or grow one after it was closed and reported.

    WHO is stamped here (#758 phase 2): the writing process's journal session
    and the connected MCP client. For an observed entry they are still
    stamped — they document the process that WROTE the row, which an import
    genuinely is.

    It is also where the entry is linked to its DECISION (#848, see
    :mod:`mureo.context.ops_linkage`): a reasoned change gets an ``adopted``
    decision record written in the same locked write, an explicit
    ``decision_id`` adopts the earlier proposal it names, and the entry is
    stamped with the decision's id.
    """
    refuse_if_kept(doc, "action_log", "recording an entry")
    if entry.batch_id is not None:
        ensure_joinable(doc, entry.batch_id)
    stamped = stamp_batch(entry, active_batch(doc)) if join_active_batch else entry
    # An explicit identity is kept: an imported or replayed entry names
    # the session that made the change, not the one replaying it. Shared
    # with the automatic observation closure (#758 phase 5), which writes
    # entries of its own inside one locked document write.
    stamped = stamp_actor(stamped, request.reason)
    doc, stamped = link_entry(doc, stamped, request)
    # ``last_synced_at`` is deliberately NOT re-stamped: appending an action
    # is not a sync, and the dashboard's "Synced N ago" freshness must keep
    # reflecting the last real sync. Every other section is carried over by
    # ``replace`` — including ``batches`` (#549), which is why this no longer
    # enumerates the untouched fields by hand.
    return replace(doc, action_log=(*doc.action_log, stamped))


def append_action_log(
    path: Path,
    entry: ActionLogEntry,
    *,
    join_active_batch: bool = True,
    expected: Any = None,
) -> StateDocument:
    """Append an action log entry to STATE.json.

    Reads the current state, appends the entry, and writes back atomically —
    the single choke point every recording path funnels through (see the
    module docstring). The steps: :func:`_validated_request` before the lock
    (display bounds, WHY), :func:`_with_entry` inside it (batch, WHO, decision).

    Args:
        path: STATE.json location.
        entry: The entry to append. An explicit ``batch_id`` on it wins over the
            open batch (see :func:`mureo.context.batch.stamp_batch`) once it has
            passed :func:`~mureo.context.batch.ensure_joinable`.
        join_active_batch: Pass ``False`` for an entry that must NOT become a
            member of whatever batch is open — the rollback executor's
            ``rollback_of`` record does, because a reversal joining the batch
            it reverses would grow that batch and make the next plan offer the
            reversals as things still to reverse.
        expected: The change's declared effects (#848), for a caller that
            states them on the entry rather than on the call. ``None`` falls
            back to the ones bound to the running call.

    Returns:
        Updated StateDocument

    Raises:
        BatchError: ``entry.batch_id`` names no declared batch, or names one
            that has already been closed.
        ValueError: ``entry.display_title`` / ``entry.display_summary`` is over
            its bound (#706), or the rationale is over
            :data:`~mureo.core.actor.ACTION_REASON_MAX_CHARS` (#758), refused
            before the file is opened. Also raised for an invalid ``expected``,
            an ``entry.decision_id`` that names no decision or a rejected /
            deferred one, and a non-list ``action_log`` on disk (#882).
    """
    request = _validated_request(entry, expected)

    def _build(doc: StateDocument) -> StateDocument:
        return _with_entry(doc, entry, request, join_active_batch=join_active_batch)

    written = _locked_state_mutation(path, _build)
    # Only now, with the entry on disk, may the call's later appends join it.
    commit_slot(request, written.action_log[-1])
    return written


__all__ = ["append_action_log"]
