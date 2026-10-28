"""Link a recorded change to the decision it carried out (#848).

Called by :func:`mureo.context.state.append_action_log` and
:func:`~mureo.context.state.begin_batch` INSIDE their locked write, so the
decision record and the ``action_log`` entry that names it land in the same
document write — there is no window in which one exists without the other.

Which decision an appended entry belongs to, in order:

1. An evaluation (``evaluation_of``) belongs to the decision of the entry it
   evaluates.
2. An observed external change and a rollback belong to none: mureo did not
   decide the first, and the second undoes a decision rather than making one.
3. An explicit ``decision_id`` — on the entry, or bound to the call — links
   to that earlier decision. A ``proposed`` one becomes ``adopted`` (a new
   record superseding it; nothing is edited). ``rejected`` and ``deferred``
   decisions are closed and refused.
4. A decision this call already linked an entry to (one call, one decision).
5. The decision of the batch the entry belongs to.
6. For an entry appended outside any change-making call: the decision of
   the one call that wrote no entry of its own and that the entry exactly
   describes (see :func:`unentried_call_candidate`) — same session, the
   entry's ``action`` is the call's tool, every target id the call sent
   appears with the same value in the entry, and no entry has carried
   that decision out yet.
7. A new ``adopted`` decision built from the change's reason, its declared
   ``expected`` effects and its ``metrics_at_action``.
8. Nothing, when the change carries no reason.

A ``decisions`` kept as written because it is not a list (#882) cannot be
recorded into: a reasoned change that would get a new decision (rule 7, or
a reasoned batch) is recorded without one and logged once at WARNING; an
explicit ``decision_id`` and :func:`record_call_decision` are refused.

Nothing else is joined. A change is never attached to an earlier decision
because it is "probably" the same one — a wrong link is worse than a
visible duplicate, which the operator can at least see.

Every entry is stamped with the decision chain's ROOT id, the id that stays
the same while the chain grows, and with the parameters the call sent.
An external ``approval`` the call stated (#854) is stamped the same way, and
lands on every decision record the change writes, like ``applied_params``.

A call that writes no entry at all (a budget update on a native platform)
gets its decision from :func:`record_call_decision`, by the same rules,
after it succeeded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

from mureo.context._preserve import refuse_if_kept
from mureo.context.batch import active_batch
from mureo.context.decision_chain import (
    chain_expected,
    chain_root,
    chain_roots,
    group_chains,
    latest_in_chain,
)
from mureo.context.decisions import (
    DecisionRecord,
    new_decision_id,
    parsed_decisions,
)
from mureo.context.expected import parse_expected
from mureo.context.ops_fields import (
    derive_call_title,
    derive_title,
    fit_title,
    names_same_target,
    project_metrics,
)
from mureo.context.ops_intent import current_ops_intent
from mureo.context.state_io import _locked_state_mutation
from mureo.core import actor

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from mureo.context.approval import ApprovalRef
    from mureo.context.expected import ExpectedEffect
    from mureo.context.models import ActionLogEntry, BatchRecord, StateDocument
    from mureo.context.ops_intent import CallDecisionSlot

#: Statuses a change can still carry out.
LINKABLE_STATUSES: Final[tuple[str, ...]] = ("proposed", "adopted")
ADOPTED: Final = "adopted"

#: Title of the decision a reasoned ``mureo_batch_begin`` opens.
BATCH_TITLE_PREFIX: Final = "Batch: "

#: Logged when a reasoned change is recorded without the decision it would
#: get because ``decisions`` is kept as written (#882); ``%s`` is ``entry`` /
#: ``batch``. Names the section only, never the value.
_UNLINKED_OVER_KEPT: Final = (
    "STATE.json: 'decisions' is kept as written; %s recorded without a "
    "decision link; fix the file by hand"
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkRequest:
    """What the running call contributes to the linkage.

    reason: The rationale already stamped on the entry (bounded, scrubbed).
    expected: Declared effects, from the call or the entry.
    explicit_id: A decision id bound to the CALL. Validated by the
        dispatcher before the call ran; if it has gone stale since, the
        entry is still recorded (linked by the remaining rules) rather
        than lost.
    arguments: The call's arguments, for the derived title.
    applied_params: The arguments as they may be stored (masked), or
        ``None``.
    call_id: The call's journal ``call_id``, kept on a decision it creates.
    approval: The external approval the call or the entry stated (#854),
        kept on the entry and on a decision record it writes.
    tool: The call's tool name, set only for a call that wrote no entry.
    slot: The call's shared decision slot; ``None`` outside a call.
    now: Server timestamp for any record written.
    """

    reason: str | None
    now: str
    expected: tuple[ExpectedEffect, ...] = ()
    explicit_id: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    applied_params: Mapping[str, Any] | None = None
    call_id: str | None = None
    approval: ApprovalRef | None = None
    tool: str | None = None
    slot: CallDecisionSlot | None = None


def call_request(reason: str | None, now: str, expected: Any = None) -> LinkRequest:
    """The request for an append made while a call may be running.

    ``expected`` given here (the entry's own) wins over the call's bound
    one. Parsed here, so an invalid one is refused before any file is
    opened.

    Raises:
        ValueError: ``expected`` is malformed.
    """
    intent = current_ops_intent()
    effects = parse_expected(expected) if expected is not None else ()
    if intent is None:
        return LinkRequest(reason=reason, now=now, expected=effects)
    return LinkRequest(
        reason=reason,
        now=now,
        expected=effects or intent.expected,
        explicit_id=intent.decision_id,
        arguments=intent.arguments,
        applied_params=intent.applied_params,
        call_id=intent.call_id,
        approval=intent.approval,
        slot=intent.slot,
    )


def check_linkable(doc: StateDocument, decision_id: str) -> str:
    """Return the root id of ``decision_id``'s chain, or refuse it.

    Raises:
        ValueError: The id names no recorded decision, or the decision's
            latest status is ``rejected`` / ``deferred``.
    """
    root = chain_root(doc, decision_id) if isinstance(decision_id, str) else None
    latest = latest_in_chain(doc, root) if root is not None else None
    if root is None or latest is None:
        raise ValueError(
            f"decision_id names no recorded decision: {decision_id!r}. Use the "
            "decision_id of a record written by mureo_decision_record."
        )
    if latest.status not in LINKABLE_STATUSES:
        raise ValueError(
            f"decision {decision_id!r} is {latest.status}; only a proposed or "
            "adopted decision can be carried out."
        )
    return root


def _actor() -> tuple[str | None, str | None]:
    return actor.session_id(), actor.client_info()


def _applied(request: LinkRequest) -> dict[str, Any] | None:
    return None if request.applied_params is None else dict(request.applied_params)


def _successor(
    doc: StateDocument,
    latest: DecisionRecord,
    request: LinkRequest,
    batch_id: str | None = None,
) -> DecisionRecord:
    """An ``adopted`` record superseding ``latest``, written for this call."""
    session, client = _actor()
    return replace(
        latest,
        decision_id=new_decision_id(request.now),
        recorded_at=request.now,
        status=ADOPTED,
        supersedes=latest.decision_id,
        batch_id=batch_id or latest.batch_id,
        expected=request.expected or chain_expected(doc, latest.decision_id),
        related_actions=(),
        session_id=session,
        client=client,
        applied_params=_applied(request),
        journal_call_id=request.call_id,
        journal_tool=request.tool,
        approval=request.approval,
    )


def _adoption(
    doc: StateDocument, root: str, request: LinkRequest, batch_id: str | None
) -> DecisionRecord | None:
    """The record that adopts ``root``'s decision, or ``None`` if not needed."""
    latest = latest_in_chain(doc, root)
    if latest is None:
        return None
    joins_batch = batch_id is None or latest.batch_id == batch_id
    if latest.status == ADOPTED and joins_batch:
        return None
    return _successor(doc, latest, request, batch_id)


def _join(
    doc: StateDocument,
    decision_id: str,
    request: LinkRequest,
    batch_id: str | None = None,
) -> tuple[StateDocument, str]:
    """Link to an existing decision, adopting it if it is still a proposal."""
    refuse_if_kept(doc, "decisions", "recording a decision")
    root = check_linkable(doc, decision_id)
    record = _adoption(doc, root, request, batch_id)
    if record is not None:
        doc = replace(doc, decisions=(*doc.decisions, record))
    return doc, root


def _stamp(entry: ActionLogEntry, root: str) -> ActionLogEntry:
    return replace(entry, decision_id=root)


def _is_change(entry: ActionLogEntry) -> bool:
    """A change mureo made, not an evaluation, an import or a reversal."""
    # Also skips ``origin`` (unlike decision_chain.is_change): observed, not made.
    return (
        entry.evaluation_of is None
        and entry.origin is None
        and entry.rollback_of is None
    )


def commit_slot(request: LinkRequest, entry: ActionLogEntry) -> None:
    """Share ``entry``'s decision with the call's later appends.

    Called only after the entry was WRITTEN: a slot set inside a write that
    then failed would point the call's next entry at a decision that was
    never stored.
    """
    slot = request.slot
    if slot is None or not _is_change(entry):
        return
    slot.wrote_entry = True
    if entry.decision_id is not None:
        slot.decision_id = entry.decision_id


def batch_decision_root(doc: StateDocument, batch_id: str | None) -> str | None:
    """The adopted decision a batch was opened under, if any."""
    if batch_id is None:
        return None
    roots = chain_roots(doc)
    for record in parsed_decisions(doc):
        if record.batch_id != batch_id:
            continue
        root = roots.get(record.decision_id, record.decision_id)
        latest = latest_in_chain(doc, root)
        if latest is not None and latest.status == ADOPTED:
            return root
    return None


def _carried_out_by(
    records: tuple[DecisionRecord, ...], entry: ActionLogEntry, session: str
) -> bool:
    """The chain's latest record is the call ``entry`` exactly describes."""
    latest = records[-1]
    return (
        latest.status == ADOPTED
        and latest.batch_id is None
        and latest.session_id == session
        and latest.journal_tool is not None
        and latest.journal_tool == entry.action
        and not any(r.related_actions for r in records)
        and names_same_target(latest.applied_params, entry)
    )


def unentried_call_candidate(doc: StateDocument, entry: ActionLogEntry) -> str | None:
    """The decision of the one no-entry call ``entry`` records, or ``None``.

    Only when exactly one decision fits; with two, the entry cannot be
    attributed and gets a decision of its own.
    """
    session = entry.session_id
    if session is None:
        return None
    carried = {e.decision_id for e in doc.action_log if e.decision_id is not None}
    found = [
        root
        for root, records in group_chains(doc).items()
        if root not in carried and _carried_out_by(records, entry, session)
    ]
    return found[0] if len(found) == 1 else None


def _join_call(
    doc: StateDocument, entry: ActionLogEntry, request: LinkRequest
) -> tuple[StateDocument, ActionLogEntry] | None:
    """Rule 6; ``None`` when no call's decision fits exactly."""
    root = unentried_call_candidate(doc, entry)
    if root is None:
        return None
    latest = latest_in_chain(doc, root)
    if latest is not None and request.expected and not chain_expected(doc, root):
        refuse_if_kept(doc, "decisions", "recording a decision")
        doc = replace(doc, decisions=(*doc.decisions, _successor(doc, latest, request)))
    return doc, _stamp(entry, root)


def _new_decision(entry: ActionLogEntry, request: LinkRequest) -> DecisionRecord:
    """A fresh ``adopted`` decision for a reasoned change.

    No ``batch_id``: a member's own decision must not become the decision
    every later member of the batch joins.
    """
    return DecisionRecord(
        decision_id=new_decision_id(request.now),
        recorded_at=request.now,
        status=ADOPTED,
        title=derive_title(entry, request.arguments),
        rationale=request.reason or "",
        metrics=project_metrics(entry.metrics_at_action),
        platform=entry.platform,
        campaign_id=entry.campaign_id,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        expected=request.expected,
        session_id=entry.session_id,
        client=entry.client,
        applied_params=_applied(request),
        journal_call_id=request.call_id,
        approval=request.approval,
    )


def _inherit_evaluated(doc: StateDocument, entry: ActionLogEntry) -> ActionLogEntry:
    """Stamp the evaluated entry's ``decision_id``, as the automatic closure does.

    A value the caller put on the evaluation record is replaced (#889): its
    table was scored against the evaluated entry's decision, so the record
    names that decision whatever it was handed.
    """
    index = entry.evaluation_of
    if index is None:
        return entry
    if not 0 <= index < len(doc.action_log):
        return entry
    return replace(entry, decision_id=doc.action_log[index].decision_id)


def _call_bound(
    doc: StateDocument, entry: ActionLogEntry, request: LinkRequest
) -> tuple[StateDocument, ActionLogEntry] | None:
    """Rules 3 (call-bound id) and 4; ``None`` when neither applies."""
    if request.explicit_id is not None:
        try:
            doc, root = _join(doc, request.explicit_id, request)
        except ValueError:
            # Validated before dispatch; gone stale since. Recording the
            # change by the remaining rules beats losing it.
            return None
        return doc, _stamp(entry, root)
    if request.slot is not None and request.slot.decision_id is not None:
        return doc, _stamp(entry, request.slot.decision_id)
    return None


def _with_applied(entry: ActionLogEntry, request: LinkRequest) -> ActionLogEntry:
    if entry.applied_params is not None or request.applied_params is None:
        return entry
    return replace(entry, applied_params=_applied(request))


def _with_approval(
    entry: ActionLogEntry, request: LinkRequest
) -> tuple[ActionLogEntry, LinkRequest]:
    """Stamp the call's approval on ``entry``; the entry's own one wins.

    The request then carries the entry's, so every decision record this
    change writes states the same approval as the entry.
    """
    if entry.approval is None and request.approval is not None:
        entry = replace(entry, approval=request.approval)
    return entry, replace(request, approval=entry.approval)


def _decisions_kept(doc: StateDocument, recorded: str) -> bool:
    """Whether ``decisions`` is kept as written (#882), warning once if so.

    A reasoned change over it is still recorded, without the decision it
    would get: refusing it would block every reasoned change until the file
    is fixed, and recording the decision would replace the kept value.
    """
    kept = doc.raw is not None and "decisions" in doc.raw
    if kept:
        logger.warning(_UNLINKED_OVER_KEPT, recorded)
    return kept


def link_entry(
    doc: StateDocument, entry: ActionLogEntry, request: LinkRequest
) -> tuple[StateDocument, ActionLogEntry]:
    """Return ``doc`` with any new decision record, and the stamped entry.

    Raises:
        ValueError: ``entry.decision_id`` is set and not linkable, or is set
            over a ``decisions`` kept as written (#882).
    """
    if entry.evaluation_of is not None:
        return doc, _inherit_evaluated(doc, entry)
    if entry.origin is not None or entry.rollback_of is not None:
        return doc, entry
    entry = _with_applied(entry, request)
    entry, request = _with_approval(entry, request)
    if entry.decision_id is not None:
        doc, root = _join(doc, entry.decision_id, request)
        return doc, _stamp(entry, root)
    linked = _call_bound(doc, entry, request)
    batch_root = batch_decision_root(doc, entry.batch_id)
    if linked is None and batch_root is not None:
        linked = doc, _stamp(entry, batch_root)
    if linked is None and request.slot is None:
        linked = _join_call(doc, entry, request)
    if linked is not None or request.reason is None:
        return linked or (doc, entry)
    if _decisions_kept(doc, "entry"):
        return doc, entry
    record = _new_decision(entry, request)
    doc = replace(doc, decisions=(*doc.decisions, record))
    return doc, _stamp(entry, record.decision_id)


def link_batch(
    doc: StateDocument, batch: BatchRecord, request: LinkRequest
) -> StateDocument:
    """Open the decision every member of ``batch`` will share.

    An explicit id adopts that decision for the batch; otherwise a reason
    creates one. Neither means the batch has no decision of its own.

    Raises:
        ValueError: ``request.explicit_id`` is not linkable, or is set over a
            ``decisions`` kept as written (#882).
    """
    if request.explicit_id is not None:
        doc, _ = _join(doc, request.explicit_id, request, batch_id=batch.batch_id)
        return doc
    if request.reason is None or _decisions_kept(doc, "batch"):
        return doc
    session, client = _actor()
    record = DecisionRecord(
        decision_id=new_decision_id(request.now),
        recorded_at=request.now,
        status=ADOPTED,
        title=fit_title(f"{BATCH_TITLE_PREFIX}{batch.label}"),
        rationale=request.reason,
        batch_id=batch.batch_id,
        expected=request.expected,
        session_id=session,
        client=client,
        journal_call_id=request.call_id,
        approval=request.approval,
    )
    return replace(doc, decisions=(*doc.decisions, record))


def _approval_rationale(request: LinkRequest) -> str:
    """The rationale of a decision recorded for an approval alone.

    A decision record requires one. It states only what is known — which
    approval the change carried out — and not why, which nobody said.
    """
    reference = None if request.approval is None else request.approval.reference
    return f"Carried out under external approval {reference}."


def _call_decision(
    doc: StateDocument, request: LinkRequest, tool: str, platform: str | None
) -> tuple[StateDocument, str | None]:
    """The decision a call that wrote no entry carried out, by the entry rules.

    One difference: an ``approval`` without a reason still creates the
    decision (#854), with :func:`_approval_rationale`. An entry keeps the
    call's approval itself; a call without one has only this record.
    """
    if request.explicit_id is not None:
        return _join(doc, request.explicit_id, request)
    batch = active_batch(doc)
    batch_root = batch_decision_root(doc, None if batch is None else batch.batch_id)
    if batch_root is not None or (request.reason is None and request.approval is None):
        return doc, batch_root
    refuse_if_kept(doc, "decisions", "recording a decision")
    session, client = _actor()
    campaign_id = request.arguments.get("campaign_id")
    campaign = None if campaign_id is None else str(campaign_id)
    record = DecisionRecord(
        decision_id=new_decision_id(request.now),
        recorded_at=request.now,
        status=ADOPTED,
        title=derive_call_title(tool, request.arguments),
        rationale=request.reason or _approval_rationale(request),
        platform=platform,
        campaign_id=campaign,
        expected=request.expected,
        session_id=session,
        client=client,
        applied_params=_applied(request),
        journal_call_id=request.call_id,
        journal_tool=tool,
        approval=request.approval,
    )
    return replace(doc, decisions=(*doc.decisions, record)), record.decision_id


def record_call_decision(
    path: Path, request: LinkRequest, *, tool: str, platform: str | None
) -> str | None:
    """Record the decision of a successful call that wrote no entry.

    One locked read, and a write only when a record is added. Returns the
    root id of the decision the call carried out, or ``None`` for none.

    Raises:
        ValueError: ``request.explicit_id`` is not linkable, or a decision
            would be recorded over a ``decisions`` kept as written (#882).
    """
    linked: list[str] = []
    request = replace(request, tool=tool)

    def _build(doc: StateDocument) -> StateDocument | None:
        updated, root = _call_decision(doc, request, tool, platform)
        if root is not None:
            linked.append(root)
        return None if updated is doc else updated

    _locked_state_mutation(path, _build)
    return linked[0] if linked else None


__all__ = [
    "ADOPTED",
    "BATCH_TITLE_PREFIX",
    "LINKABLE_STATUSES",
    "LinkRequest",
    "batch_decision_root",
    "call_request",
    "check_linkable",
    "commit_slot",
    "derive_title",
    "link_batch",
    "link_entry",
    "project_metrics",
    "record_call_decision",
    "unentried_call_candidate",
]
