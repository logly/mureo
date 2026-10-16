"""The ops history view: decision → actions → evaluation, joined (#848).

One item per decision (its whole ``supersedes`` chain), carrying the
changes that carried it out and what their evaluation found. A change no
decision covers — anything written before ops history existed, or without a
reason — is an item of its own with ``decision`` ``None``, so the gap is
visible rather than hidden.

Nothing here is stored. Each item's ``state`` is DERIVED from the records:

- ``proposed`` / ``adopted``: the decision's latest status, no change yet;
- ``rejected`` / ``deferred``: terminal, whatever else exists;
- ``executed``: changed, and nothing to observe;
- ``observing``: an observation window is still open (or past due and not
  yet closed);
- ``evaluated``: every observed change has an evaluation; ``verdict`` is
  ``regressed`` if any regressed, else ``improved`` if any improved, else
  ``inconclusive`` (``None`` when no evaluation stated one);
- ``skipped``: the automatic evaluation refused to decide (see
  ``skipped_reason`` on the action).

``rolled_back`` is a flag, not a state: a rolled-back change still happened
and may still have been evaluated. A decision carried out by a call that
wrote no ``action_log`` entry (a budget update on a native platform) is
``executed`` with no actions; its ``applied_params`` say what was sent.

Each change appears under exactly one decision: the one its own
``decision_id`` names. A decision's ``related_actions`` claim only changes
that name no decision of their own, and never an evaluation or a reversal.

Pure: a document and a date in, JSON-safe dicts out, copied so a caller
cannot reach back into the document. ``command`` is never included (it can
carry flags and tokens). An action's ``before`` comes from
``reversible_params``, the only place a prior value is recorded, and its
``after`` from ``applied_params``, what the call sent. ``approval`` is the
external approval a change stated (#854): the entry's own on an action,
the newest on the chain on a decision; recorded and shown, never verified.

The date RULE is not here: the read surfaces bound items by the same rule
as the other history sources (:mod:`mureo.context.ops_history_query`), using
:func:`item_timestamp`. They pass it in as ``keep`` so an item outside the
window is skipped before anything about it is derived (#849) — deriving an
overdue change plans its closure, which is the expensive part.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Final

from mureo.context.approval import approval_to_dict
from mureo.context.auto_evaluation import AutoSkip, plan_closure
from mureo.context.decision_chain import chain_roots, group_chains
from mureo.context.expected import expected_to_list
from mureo.context.observations import parse_due_date
from mureo.context.ops_fields import ID_SUFFIX

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from mureo.context.approval import ApprovalRef
    from mureo.context.decisions import DecisionRecord
    from mureo.context.models import ActionLogEntry, StateDocument

STATE_EXECUTED: Final = "executed"
STATE_OBSERVING: Final = "observing"
STATE_EVALUATED: Final = "evaluated"
STATE_SKIPPED: Final = "skipped"
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"rejected", "deferred"})

#: Precedence when a decision's changes are in different states: anything
#: still open wins over a finished verdict.
_STATE_ORDER: Final[tuple[str, ...]] = (
    STATE_OBSERVING,
    STATE_EVALUATED,
    STATE_SKIPPED,
    STATE_EXECUTED,
)
_VERDICT_ORDER: Final[tuple[str, ...]] = ("regressed", "improved", "inconclusive")
_ADOPTED: Final = "adopted"

#: Sorts an undatable item last.
_UNDATED: Final = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Links:
    """Which entries close or reverse which, computed once per document."""

    evaluations: dict[int, int] = field(default_factory=dict)
    rollbacks: dict[int, int] = field(default_factory=dict)


def _links(doc: StateDocument) -> _Links:
    evaluations: dict[int, int] = {}
    rollbacks: dict[int, int] = {}
    size = len(doc.action_log)
    for index, entry in enumerate(doc.action_log):
        if entry.evaluation_of is not None and 0 <= entry.evaluation_of < size:
            evaluations[entry.evaluation_of] = index
        if entry.rollback_of is not None and 0 <= entry.rollback_of < size:
            rollbacks.setdefault(entry.rollback_of, index)
    return _Links(evaluations=evaluations, rollbacks=rollbacks)


def _is_change(entry: ActionLogEntry) -> bool:
    """A change in its own right, not a record about another one."""
    return entry.evaluation_of is None and entry.rollback_of is None


def _values(params: Any) -> dict[str, Any] | None:
    """The values a parameter map sets, without the ids naming its target."""
    if not isinstance(params, dict):
        return None
    kept = {k: v for k, v in params.items() if not str(k).endswith(ID_SUFFIX)}
    return copy.deepcopy(kept) or None


def _approval(ref: ApprovalRef | None) -> dict[str, str] | None:
    return None if ref is None else approval_to_dict(ref)


def _before_values(entry: ActionLogEntry) -> dict[str, Any] | None:
    return _values((entry.reversible_params or {}).get("params"))


def _evaluation_row(doc: StateDocument, index: int) -> dict[str, Any]:
    entry = doc.action_log[index]
    table = entry.evaluation or {}
    return {
        "index": index,
        "timestamp": entry.timestamp,
        "overall": table.get("overall"),
        "summary": entry.summary,
        "reason": entry.reason,
        "table": copy.deepcopy(entry.evaluation),
    }


def _action_state(
    doc: StateDocument, index: int, links: _Links, today: date
) -> tuple[str, str | None]:
    """The change's own state and, for a skip, the reason."""
    if index in links.evaluations:
        return STATE_EVALUATED, None
    due = parse_due_date(doc.action_log[index].observation_due)
    if due is None:
        return STATE_EXECUTED, None
    if due > today:
        return STATE_OBSERVING, None
    plan = plan_closure(doc, index, today)
    if isinstance(plan, AutoSkip):
        return STATE_SKIPPED, plan.reason
    return STATE_OBSERVING, None


def _action_row(
    doc: StateDocument, index: int, links: _Links, today: date
) -> dict[str, Any]:
    entry = doc.action_log[index]
    state, skipped_reason = _action_state(doc, index, links, today)
    evaluation_index = links.evaluations.get(index)
    reversal = entry.reversible_params or {}
    return {
        "index": index,
        "timestamp": entry.timestamp,
        "action": entry.action,
        "platform": entry.platform,
        "campaign_id": entry.campaign_id,
        "ad_id": entry.ad_id,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "batch_id": entry.batch_id,
        "origin": entry.origin,
        "summary": entry.summary,
        "display_title": entry.display_title,
        "reason": entry.reason,
        "approval": _approval(entry.approval),
        "metrics_at_action": copy.deepcopy(entry.metrics_at_action),
        "before": _before_values(entry),
        "after": _values(entry.applied_params),
        "reversal_operation": reversal.get("operation"),
        "observation_due": entry.observation_due,
        "state": state,
        "skipped_reason": skipped_reason,
        "evaluation": (
            None if evaluation_index is None else _evaluation_row(doc, evaluation_index)
        ),
        "rolled_back_by": links.rollbacks.get(index),
    }


def _newest(records: tuple[DecisionRecord, ...], name: str) -> Any:
    values = (getattr(r, name) for r in reversed(records))
    return next((v for v in values if v is not None), None)


def _carried_out_by_call(records: tuple[DecisionRecord, ...]) -> bool:
    """A call that wrote no entry carried the decision out (not a batch)."""
    return any(r.journal_call_id is not None and r.batch_id is None for r in records)


def _decision_dict(records: tuple[DecisionRecord, ...]) -> dict[str, Any]:
    root, latest = records[0], records[-1]
    expected = next((r.expected for r in reversed(records) if r.expected), ())
    return {
        "decision_id": root.decision_id,
        "status": latest.status,
        "recorded_at": root.recorded_at,
        "title": latest.title,
        "rationale": latest.rationale,
        "metrics": copy.deepcopy(latest.metrics),
        "expected": expected_to_list(expected),
        "platform": latest.platform,
        "campaign_id": latest.campaign_id,
        "entity_type": latest.entity_type,
        "entity_id": latest.entity_id,
        "batch_id": latest.batch_id,
        "applied_params": copy.deepcopy(_newest(records, "applied_params")),
        "journal_call_id": _newest(records, "journal_call_id"),
        "approval": _approval(_newest(records, "approval")),
        "history": [
            {"decision_id": r.decision_id, "status": r.status, "at": r.recorded_at}
            for r in records
        ],
    }


def _first(order: tuple[str, ...], values: list[str | None]) -> str | None:
    return next((v for v in order if v in values), None)


def _derive(
    status: str | None, actions: list[dict[str, Any]], by_call: bool = False
) -> dict[str, Any]:
    """``state`` / ``verdict`` / ``rolled_back`` for one item."""
    rolled_back = any(a["rolled_back_by"] is not None for a in actions)
    if not actions and by_call and status == _ADOPTED:
        return {"state": STATE_EXECUTED, "verdict": None, "rolled_back": False}
    if status in TERMINAL_STATUSES or not actions:
        return {"state": status, "verdict": None, "rolled_back": rolled_back}
    state = _first(_STATE_ORDER, [a["state"] for a in actions])
    verdict = None
    if state == STATE_EVALUATED:
        overalls = [(a["evaluation"] or {}).get("overall") for a in actions]
        verdict = _first(_VERDICT_ORDER, overalls)
    return {"state": state, "verdict": verdict, "rolled_back": rolled_back}


def item_timestamp(item: dict[str, Any]) -> str | None:
    """What an item is dated by: its decision's first record, or the change."""
    decision = item["decision"]
    stamp = decision["recorded_at"] if decision else item["actions"][0]["timestamp"]
    return stamp if isinstance(stamp, str) else None


def _stamp(value: Any) -> str | None:
    """A record's timestamp as :func:`item_timestamp` would report it."""
    return value if isinstance(value, str) else None


def _keep_all(_stamp_value: str | None) -> bool:
    return True


def _sort_key(item: dict[str, Any]) -> datetime:
    """The item's full timestamp, comparable across offsets."""
    stamp = item_timestamp(item) or ""
    text = f"{stamp[:-1]}+00:00" if stamp.endswith("Z") else stamp
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return _UNDATED
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _owners(doc: StateDocument, roots: dict[str, str]) -> dict[int, str]:
    """The one decision each change belongs to.

    Its own ``decision_id`` first; a decision's ``related_actions`` then
    claim only the changes still unowned.
    """
    owner: dict[int, str] = {}
    for index, entry in enumerate(doc.action_log):
        root = roots.get(entry.decision_id or "")
        if root is not None and _is_change(entry):
            owner[index] = root
    size = len(doc.action_log)
    for record in doc.decisions:
        root = roots.get(record.decision_id, record.decision_id)
        for index in record.related_actions:
            if 0 <= index < size and _is_change(doc.action_log[index]):
                owner.setdefault(index, root)
    return owner


def build_ops_history_items(
    doc: StateDocument,
    *,
    today: date,
    keep: Callable[[str | None], bool] | None = None,
) -> list[dict[str, Any]]:
    """Every item, newest first by :func:`item_timestamp`.

    ``keep``, when given, is asked with the timestamp :func:`item_timestamp`
    would return for an item (its decision's first record, or the change's
    own) BEFORE the item is derived; an item it refuses is never built.
    """
    wanted = keep if keep is not None else _keep_all
    links = _links(doc)
    owner = _owners(doc, chain_roots(doc))
    by_root: dict[str, list[int]] = {}
    for index in sorted(owner):
        by_root.setdefault(owner[index], []).append(index)
    items: list[dict[str, Any]] = []
    for root, records in group_chains(doc).items():
        if not wanted(_stamp(records[0].recorded_at)):
            continue
        actions = [_action_row(doc, i, links, today) for i in by_root.get(root, [])]
        decision = _decision_dict(records)
        derived = _derive(decision["status"], actions, _carried_out_by_call(records))
        items.append({"decision": decision, "actions": actions, **derived})
    for index, entry in enumerate(doc.action_log):
        if _is_change(entry) and index not in owner:
            if not wanted(_stamp(entry.timestamp)):
                continue
            actions = [_action_row(doc, index, links, today)]
            items.append(
                {"decision": None, "actions": actions, **_derive(None, actions)}
            )
    return sorted(items, key=_sort_key, reverse=True)


__all__ = [
    "STATE_EVALUATED",
    "STATE_EXECUTED",
    "STATE_OBSERVING",
    "STATE_SKIPPED",
    "TERMINAL_STATUSES",
    "build_ops_history_items",
    "item_timestamp",
]
