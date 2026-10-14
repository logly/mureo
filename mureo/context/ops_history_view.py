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
and may still have been evaluated.

Pure: a document and a date in, JSON-safe dicts out. ``command`` is never
included (it can carry flags and tokens); the before-values come from
``reversible_params``, the only place a prior value is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from mureo.context.auto_evaluation import AutoSkip, plan_closure
from mureo.context.decision_chain import chain_records, chain_roots
from mureo.context.expected import expected_to_list
from mureo.context.observations import parse_due_date

if TYPE_CHECKING:
    from datetime import date

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
_ID_SUFFIX: Final = "_id"


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


def _before_values(entry: ActionLogEntry) -> dict[str, Any] | None:
    params = (entry.reversible_params or {}).get("params")
    if not isinstance(params, dict):
        return None
    kept = {k: v for k, v in params.items() if not str(k).endswith(_ID_SUFFIX)}
    return kept or None


def _evaluation_row(doc: StateDocument, index: int) -> dict[str, Any]:
    entry = doc.action_log[index]
    table = entry.evaluation or {}
    return {
        "index": index,
        "timestamp": entry.timestamp,
        "overall": table.get("overall"),
        "summary": entry.summary,
        "reason": entry.reason,
        "table": entry.evaluation,
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
        "metrics_at_action": entry.metrics_at_action,
        "before": _before_values(entry),
        "reversal_operation": reversal.get("operation"),
        "observation_due": entry.observation_due,
        "state": state,
        "skipped_reason": skipped_reason,
        "evaluation": (
            None if evaluation_index is None else _evaluation_row(doc, evaluation_index)
        ),
        "rolled_back_by": links.rollbacks.get(index),
    }


def _decision_dict(records: tuple[DecisionRecord, ...]) -> dict[str, Any]:
    root, latest = records[0], records[-1]
    expected = next((r.expected for r in reversed(records) if r.expected), ())
    return {
        "decision_id": root.decision_id,
        "status": latest.status,
        "recorded_at": root.recorded_at,
        "title": latest.title,
        "rationale": latest.rationale,
        "metrics": latest.metrics,
        "expected": expected_to_list(expected),
        "platform": latest.platform,
        "campaign_id": latest.campaign_id,
        "entity_type": latest.entity_type,
        "entity_id": latest.entity_id,
        "batch_id": latest.batch_id,
        "history": [
            {"decision_id": r.decision_id, "status": r.status, "at": r.recorded_at}
            for r in records
        ],
    }


def _first(order: tuple[str, ...], values: list[str | None]) -> str | None:
    return next((v for v in order if v in values), None)


def _derive(status: str | None, actions: list[dict[str, Any]]) -> dict[str, Any]:
    """``state`` / ``verdict`` / ``rolled_back`` for one item."""
    rolled_back = any(a["rolled_back_by"] is not None for a in actions)
    if status in TERMINAL_STATUSES or not actions:
        return {"state": status, "verdict": None, "rolled_back": rolled_back}
    state = _first(_STATE_ORDER, [a["state"] for a in actions])
    verdict = None
    if state == STATE_EVALUATED:
        overalls = [(a["evaluation"] or {}).get("overall") for a in actions]
        verdict = _first(_VERDICT_ORDER, overalls)
    return {"state": state, "verdict": verdict, "rolled_back": rolled_back}


def _item_day(item: dict[str, Any]) -> date | None:
    decision = item["decision"]
    stamp = decision["recorded_at"] if decision else item["actions"][0]["timestamp"]
    return parse_due_date(stamp)


def _in_window(day: date | None, since: date | None, until: date | None) -> bool:
    if since is None and until is None:
        return True
    if day is None:
        return False
    return (since is None or day >= since) and (until is None or day <= until)


def _decision_actions(
    doc: StateDocument, roots: dict[str, str]
) -> tuple[dict[str, list[int]], list[int]]:
    """Change indices per decision root, and the ones no decision covers."""
    size = len(doc.action_log)
    by_root: dict[str, set[int]] = {}
    for record in doc.decisions:
        root = roots.get(record.decision_id, record.decision_id)
        bucket = by_root.setdefault(root, set())
        bucket.update(i for i in record.related_actions if 0 <= i < size)
    for index, entry in enumerate(doc.action_log):
        linked = roots.get(entry.decision_id or "")
        if linked is not None and _is_change(entry):
            by_root[linked].add(index)
    covered = set().union(*by_root.values()) if by_root else set()
    orphans = [
        index
        for index, entry in enumerate(doc.action_log)
        if _is_change(entry) and index not in covered
    ]
    return {root: sorted(indices) for root, indices in by_root.items()}, orphans


def build_ops_history_items(
    doc: StateDocument,
    *,
    today: date,
    since: date | None = None,
    until: date | None = None,
) -> list[dict[str, Any]]:
    """Every item whose date falls in ``[since, until]``, newest first.

    A decision is dated by its first record, a change no decision covers
    by its own timestamp.
    """
    links = _links(doc)
    roots = chain_roots(doc)
    by_root, orphans = _decision_actions(doc, roots)
    items: list[dict[str, Any]] = []
    for root, indices in by_root.items():
        actions = [_action_row(doc, i, links, today) for i in indices]
        decision = _decision_dict(chain_records(doc, root))
        derived = _derive(decision["status"], actions)
        items.append({"decision": decision, "actions": actions, **derived})
    for index in orphans:
        actions = [_action_row(doc, index, links, today)]
        items.append({"decision": None, "actions": actions, **_derive(None, actions)})
    kept = [i for i in items if _in_window(_item_day(i), since, until)]
    return sorted(kept, key=lambda i: str(_item_day(i) or ""), reverse=True)


__all__ = [
    "STATE_EVALUATED",
    "STATE_EXECUTED",
    "STATE_OBSERVING",
    "STATE_SKIPPED",
    "TERMINAL_STATUSES",
    "build_ops_history_items",
]
