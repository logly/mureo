"""Which decision chains probably record the same change twice (#851).

Recording a decision with ``mureo_decision_record`` and then making the
change with only a ``reason`` leaves two chains for one change. They are
never joined (:mod:`mureo.context.ops_linkage`); this only NAMES the pair.

- **Record-only chain**: a chain (per
  :func:`~mureo.context.decision_chain.group_chains`) whose root carries no
  ``applied_params``, no record of which carries ``journal_call_id``,
  ``journal_tool`` or ``batch_id`` (so one a call adopted is never one),
  whose latest status is ``proposed`` or ``adopted``, and that owns no
  ``action_log`` entry (:func:`~mureo.context.decision_chain.change_owners`).
- **Call-opened chain**: its root has ``journal_call_id`` or
  ``journal_tool`` set and no ``batch_id``, and its latest status is
  ``adopted``.
- **Same target**: every target key both roots name (``platform``,
  ``campaign_id``, ``entity_type`` + ``entity_id`` as one key) is equal,
  and both name ``campaign_id`` or the entity pair.
- **Window**: the call-opened root was recorded 0 to
  :data:`DUPLICATE_DECISION_WINDOW` after the record-only root, naive
  timestamps read as UTC (:func:`~mureo.context.iso_time.iso_moment`).

Record-only chains are visited earliest first (write order on a tie). Each
is named against its nearest same-target call-opened chain in the window;
when an earlier record-only chain already named that one, it gets no hint
at all. It takes the whole document, not a record and a call sequence, so
the chain and ownership helpers are reused as they are. Pure: nothing
passed in is changed.
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from mureo.context.decision_chain import chain_roots, change_owners, group_chains
from mureo.context.iso_time import iso_moment

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from mureo.context.decisions import DecisionRecord
    from mureo.context.models import StateDocument

#: How long after a recorded decision a change on the same target is
#: flagged as possibly the same decision recorded twice.
DUPLICATE_DECISION_WINDOW: Final = timedelta(hours=24)

#: The statuses a record-only chain may still be acted on in.
_OPEN_STATUSES: Final[frozenset[str]] = frozenset({"proposed", "adopted"})

#: The only status a call-opened chain is matched in.
_ADOPTED: Final = "adopted"

#: The target keys that say WHAT was changed; a platform alone does not.
_NARROW_KEYS: Final[frozenset[str]] = frozenset({"campaign_id", "entity"})


def _record_only(records: tuple[DecisionRecord, ...], owned: set[str]) -> bool:
    root = records[0]
    by_call = any(
        r.journal_call_id is not None
        or r.journal_tool is not None
        or r.batch_id is not None
        for r in records
    )
    open_now = records[-1].status in _OPEN_STATUSES
    unowned = root.decision_id not in owned
    return root.applied_params is None and not by_call and open_now and unowned


def _call_opened(records: tuple[DecisionRecord, ...]) -> bool:
    root = records[0]
    by_call = root.journal_call_id is not None or root.journal_tool is not None
    return by_call and root.batch_id is None and records[-1].status == _ADOPTED


# _targets / _same_target compare two DecisionRecord roots; they do not reuse
# ops_fields.names_same_target, which matches sent params or an entry on id keys.
def _targets(record: DecisionRecord) -> dict[str, tuple[str | None, ...]]:
    """The target keys ``record`` names."""
    named = {
        "platform": (record.platform,),
        "campaign_id": (record.campaign_id,),
        "entity": (record.entity_type, record.entity_id),
    }
    return {key: value for key, value in named.items() if None not in value}


def _same_target(first: DecisionRecord, second: DecisionRecord) -> bool:
    mine, theirs = _targets(first), _targets(second)
    shared = mine.keys() & theirs.keys()
    if not shared & _NARROW_KEYS:
        return False
    return all(mine[key] == theirs[key] for key in shared)


def _dated(roots: list[DecisionRecord]) -> list[tuple[datetime, DecisionRecord]]:
    """The roots that carry a readable ``recorded_at``, earliest first."""
    dated = [(iso_moment(root.recorded_at), root) for root in roots]
    kept = [(moment, root) for moment, root in dated if moment is not None]
    return sorted(kept, key=lambda pair: pair[0])


def _nearest(
    moment: datetime,
    record: DecisionRecord,
    calls: list[tuple[datetime, DecisionRecord]],
    starts: list[datetime],
) -> DecisionRecord | None:
    """The nearest same-target call root in the window, taken or not."""
    end = moment + DUPLICATE_DECISION_WINDOW
    for when, call in calls[bisect_left(starts, moment) :]:
        if when > end:
            return None
        if _same_target(record, call):
            return call
    return None


def possible_duplicates(doc: StateDocument) -> Mapping[str, str]:
    """Map each record-only chain root id to the root id of the call-opened
    chain it probably duplicates.

    Pass the whole document, not a windowed slice: a pair is found
    whichever side of a date window each record falls on.
    """
    chains = group_chains(doc).values()
    owned = set(change_owners(doc, chain_roots(doc)).values())
    records = _dated([c[0] for c in chains if _record_only(c, owned)])
    calls = _dated([c[0] for c in chains if _call_opened(c)])
    starts = [when for when, _call in calls]
    found: dict[str, str] = {}
    taken: set[str] = set()
    for moment, record in records:
        call = _nearest(moment, record, calls, starts)
        if call is not None and call.decision_id not in taken:
            taken.add(call.decision_id)
            found[record.decision_id] = call.decision_id
    return found


__all__ = ["DUPLICATE_DECISION_WINDOW", "possible_duplicates"]
