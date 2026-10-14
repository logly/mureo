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
6. With a reason: the one ``adopted`` decision this session recorded for
   the same target that nothing has carried out yet (see
   :func:`session_candidate`), so recording a decision and then making the
   change does not leave two decisions for it.
7. A new ``adopted`` decision built from the change's reason, its declared
   ``expected`` effects and its ``metrics_at_action``.
8. Nothing, when the change carries no reason.

Every entry is stamped with the decision chain's ROOT id, the id that stays
the same while the chain grows, and with the parameters the call sent.

A call that writes no entry at all (a budget update on a native platform)
gets its decision from :func:`record_call_decision`, by the same rules,
after it succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

from mureo.context.batch import active_batch
from mureo.context.decision_chain import (
    chain_expected,
    chain_root,
    chain_roots,
    group_chains,
    latest_in_chain,
)
from mureo.context.decisions import DecisionRecord, new_decision_id
from mureo.context.expected import parse_expected
from mureo.context.ops_fields import (
    derive_call_title,
    derive_title,
    fit_title,
    project_metrics,
)
from mureo.context.ops_intent import current_ops_intent

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from mureo.context.expected import ExpectedEffect
    from mureo.context.models import ActionLogEntry, BatchRecord, StateDocument
    from mureo.context.ops_intent import CallDecisionSlot

#: Statuses a change can still carry out.
LINKABLE_STATUSES: Final[tuple[str, ...]] = ("proposed", "adopted")
ADOPTED: Final = "adopted"

#: Title of the decision a reasoned ``mureo_batch_begin`` opens.
BATCH_TITLE_PREFIX: Final = "Batch: "


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
    # Lazy, for the ``mureo.core`` import cycle ``mureo.context.state`` documents.
    from mureo.core.actor import client_info, session_id

    return session_id(), client_info()


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
    root = check_linkable(doc, decision_id)
    record = _adoption(doc, root, request, batch_id)
    if record is not None:
        doc = replace(doc, decisions=(*doc.decisions, record))
    return doc, root


def _stamp(entry: ActionLogEntry, root: str) -> ActionLogEntry:
    return replace(entry, decision_id=root)


def _is_change(entry: ActionLogEntry) -> bool:
    """A change mureo made, not an evaluation, an import or a reversal."""
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
    if slot is not None and entry.decision_id is not None and _is_change(entry):
        slot.decision_id = entry.decision_id


def batch_decision_root(doc: StateDocument, batch_id: str | None) -> str | None:
    """The adopted decision a batch was opened under, if any."""
    if batch_id is None:
        return None
    roots = chain_roots(doc)
    for record in doc.decisions:
        if record.batch_id != batch_id:
            continue
        root = roots.get(record.decision_id, record.decision_id)
        latest = latest_in_chain(doc, root)
        if latest is not None and latest.status == ADOPTED:
            return root
    return None


def _open_in_session(
    records: tuple[DecisionRecord, ...], session: str, for_entry: bool
) -> bool:
    """Adopted in ``session``, outside any batch, and not yet carried out.

    A decision a no-entry call carried out stays open to the agent's own
    ``action_log`` entry for that change (``for_entry``), never to a second
    call.
    """
    latest = records[-1]
    if latest.status != ADOPTED or latest.session_id != session:
        return False
    if latest.batch_id is not None or any(r.related_actions for r in records):
        return False
    return for_entry or not any(
        r.journal_call_id is not None or r.applied_params is not None for r in records
    )


def _same_target(
    record: DecisionRecord, platform: str | None, campaign_id: str | None
) -> bool:
    """The record names a target, and every part it names is the change's."""
    named = [
        (mine, theirs)
        for mine, theirs in (
            (record.platform, platform),
            (record.campaign_id, campaign_id),
        )
        if mine is not None
    ]
    return bool(named) and all(mine == theirs for mine, theirs in named)


def session_candidate(
    doc: StateDocument,
    *,
    session: str | None,
    platform: str | None,
    campaign_id: str | None,
    for_entry: bool,
) -> str | None:
    """The one decision a reasoned change without a ``decision_id`` joins.

    An ``adopted`` decision recorded in the same session, for the same
    platform / campaign (it must name at least one), that no entry or call
    has carried out yet. Only when exactly one fits: with two, the change
    cannot be attributed and gets a decision of its own.
    """
    if session is None:
        return None
    carried = {e.decision_id for e in doc.action_log if e.decision_id is not None}
    found = [
        root
        for root, records in group_chains(doc).items()
        if root not in carried
        and _open_in_session(records, session, for_entry)
        and _same_target(records[-1], platform, campaign_id)
    ]
    return found[0] if len(found) == 1 else None


def _join_session(
    doc: StateDocument, entry: ActionLogEntry, request: LinkRequest
) -> tuple[StateDocument, ActionLogEntry] | None:
    """Rule 6; ``None`` when no decision fits."""
    root = session_candidate(
        doc,
        session=entry.session_id,
        platform=entry.platform,
        campaign_id=entry.campaign_id,
        for_entry=True,
    )
    if root is None:
        return None
    latest = latest_in_chain(doc, root)
    if latest is not None and request.expected and not chain_expected(doc, root):
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
    )


def _inherit_evaluated(doc: StateDocument, entry: ActionLogEntry) -> ActionLogEntry:
    index = entry.evaluation_of
    if entry.decision_id is not None or index is None:
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


def link_entry(
    doc: StateDocument, entry: ActionLogEntry, request: LinkRequest
) -> tuple[StateDocument, ActionLogEntry]:
    """Return ``doc`` with any new decision record, and the stamped entry.

    Raises:
        ValueError: ``entry.decision_id`` is set and not linkable.
    """
    if entry.evaluation_of is not None:
        return doc, _inherit_evaluated(doc, entry)
    if entry.origin is not None or entry.rollback_of is not None:
        return doc, entry
    entry = _with_applied(entry, request)
    if entry.decision_id is not None:
        doc, root = _join(doc, entry.decision_id, request)
        return doc, _stamp(entry, root)
    linked = _call_bound(doc, entry, request)
    batch_root = batch_decision_root(doc, entry.batch_id)
    if linked is None and batch_root is not None:
        linked = doc, _stamp(entry, batch_root)
    if linked is None and request.reason is not None:
        linked = _join_session(doc, entry, request)
    if linked is not None or request.reason is None:
        return linked or (doc, entry)
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
        ValueError: ``request.explicit_id`` is not linkable.
    """
    if request.explicit_id is not None:
        doc, _ = _join(doc, request.explicit_id, request, batch_id=batch.batch_id)
        return doc
    if request.reason is None:
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
    )
    return replace(doc, decisions=(*doc.decisions, record))


def _call_decision(
    doc: StateDocument, request: LinkRequest, tool: str, platform: str | None
) -> tuple[StateDocument, str | None]:
    """The decision a call that wrote no entry carried out, by the entry rules."""
    if request.explicit_id is not None:
        return _join(doc, request.explicit_id, request)
    batch = active_batch(doc)
    batch_root = batch_decision_root(doc, None if batch is None else batch.batch_id)
    if batch_root is not None or request.reason is None:
        return doc, batch_root
    session, client = _actor()
    campaign_id = request.arguments.get("campaign_id")
    campaign = None if campaign_id is None else str(campaign_id)
    root = session_candidate(
        doc, session=session, platform=platform, campaign_id=campaign, for_entry=False
    )
    latest = None if root is None else latest_in_chain(doc, root)
    if root is not None and latest is not None:
        record = _successor(doc, latest, request)
        return replace(doc, decisions=(*doc.decisions, record)), root
    record = DecisionRecord(
        decision_id=new_decision_id(request.now),
        recorded_at=request.now,
        status=ADOPTED,
        title=derive_call_title(tool, request.arguments),
        rationale=request.reason,
        platform=platform,
        campaign_id=campaign,
        expected=request.expected,
        session_id=session,
        client=client,
        applied_params=_applied(request),
        journal_call_id=request.call_id,
    )
    return replace(doc, decisions=(*doc.decisions, record)), record.decision_id


def record_call_decision(
    path: Path, request: LinkRequest, *, tool: str, platform: str | None
) -> str | None:
    """Record the decision of a successful call that wrote no entry.

    One locked read, and a write only when a record is added. Returns the
    root id of the decision the call carried out, or ``None`` for none.

    Raises:
        ValueError: ``request.explicit_id`` is not linkable.
    """
    # Lazy, for the import cycle ``mureo.context.batch`` documents.
    from mureo.context.state import _locked_state_mutation

    linked: list[str] = []

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
    "session_candidate",
]
