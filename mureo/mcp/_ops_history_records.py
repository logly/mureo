"""Ops history requirements on the two RECORDING tools (#848).

``mureo_state_action_log_append`` and ``mureo_decision_record`` write a
record about a change rather than making one, so the dispatcher's call-level
``reason`` / ``expected`` never reaches them. Their records carry the same
two things in their own fields, and when the workspace switched ops history
on, the same requirement applies there:

- an ``action_log`` entry that would open a NEW decision must state its
  ``reason`` and ``expected`` (an evaluation, a rollback, an observed
  external change, or an entry joining an existing decision opens none);
- a ``proposed`` or ``adopted`` decision record must declare at least one
  ``expected`` effect. ``rejected`` / ``deferred`` need none.

Off, nothing here refuses anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from mureo.context.batch import active_batch
from mureo.context.ops_linkage import batch_decision_root
from mureo.context.settings import ops_history_enabled
from mureo.context.state import read_state_file

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.decisions import DecisionRecord
    from mureo.context.models import ActionLogEntry, StateDocument

ENTRY_REASON_REQUIRED: Final = (
    "entry.reason is required while ops history is enabled for this "
    "workspace: say why the recorded change was made."
)
ENTRY_EXPECTED_REQUIRED: Final = (
    "entry.expected is required while ops history is enabled for this "
    "workspace: declare at least one {metric, direction} the change should move."
)
DECISION_EXPECTED_REQUIRED: Final = (
    "expected is required for a proposed or adopted decision while ops "
    "history is enabled for this workspace."
)

#: Decision statuses that must declare an expected effect when enabled.
_EXPECTING_STATUSES: Final[frozenset[str]] = frozenset({"proposed", "adopted"})


def _enabled_doc(path: Path) -> StateDocument | None:
    """The document at ``path`` when ops history is on there, else ``None``."""
    if not path.is_file():
        return None
    doc = read_state_file(path, strict=False)
    return doc if ops_history_enabled(doc) else None


def _opens_a_decision(doc: StateDocument, entry: ActionLogEntry) -> bool:
    """Would appending ``entry`` create a new decision record?"""
    if entry.evaluation_of is not None or entry.rollback_of is not None:
        return False
    if entry.origin is not None or entry.decision_id is not None:
        return False
    batch_id = entry.batch_id
    if batch_id is None:
        batch = active_batch(doc)
        batch_id = batch.batch_id if batch is not None else None
    return batch_decision_root(doc, batch_id) is None


def require_entry_fields(path: Path, entry: ActionLogEntry, expected: Any) -> None:
    """Enforce ``reason`` / ``expected`` on an entry that opens a decision.

    Raises:
        ValueError: ops history is on and a required field is missing.
    """
    doc = _enabled_doc(path)
    if doc is None or not _opens_a_decision(doc, entry):
        return
    if entry.reason is None or not str(entry.reason).strip():
        raise ValueError(ENTRY_REASON_REQUIRED)
    if not expected:
        raise ValueError(ENTRY_EXPECTED_REQUIRED)


def require_decision_expected(path: Path, record: DecisionRecord) -> None:
    """Enforce ``expected`` on a proposed / adopted decision record.

    Raises:
        ValueError: ops history is on and the record declares none.
    """
    if record.status not in _EXPECTING_STATUSES or record.expected:
        return
    if _enabled_doc(path) is not None:
        raise ValueError(DECISION_EXPECTED_REQUIRED)


__all__ = [
    "DECISION_EXPECTED_REQUIRED",
    "ENTRY_EXPECTED_REQUIRED",
    "ENTRY_REASON_REQUIRED",
    "require_decision_expected",
    "require_entry_fields",
]
