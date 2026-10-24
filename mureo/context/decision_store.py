"""Append a decision to STATE.json — the path half of :mod:`mureo.context.decisions`.

Split out of :mod:`mureo.context.decisions` in #879, verbatim. That module
holds the model, its bounds, the cross-reference checks and the pure
queries; this one holds the single locked write that appends a record.
The split is what lets the writer take STATE.json's lock at top level:
:mod:`mureo.context.state_codec` reads :class:`DecisionRecord`, so
:mod:`mureo.context.decisions` sits BELOW :mod:`mureo.context.state_io` and
cannot import it, while this module sits above both.

:mod:`mureo.context.state` does not re-export :func:`append_decision`;
import it from here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.models import StateDocument

from mureo.context._preserve import refuse_if_kept
from mureo.context.actor_stamp import stamp_identity
from mureo.context.decisions import (
    DecisionRecord,
    _check_batch,
    _check_related_actions,
    _check_supersedes,
    _check_unique_id,
)
from mureo.context.state_io import _locked_state_mutation


def append_decision(path: Path, record: DecisionRecord) -> tuple[StateDocument, int]:
    """Append ``record`` to STATE.json's ``decisions``.

    Every cross-reference is validated INSIDE the lock, against the document
    as it is about to be written: an index, a ``supersedes`` or a
    ``batch_id`` checked outside it could be made stale by a concurrent
    append between the check and the write.

    ``session_id`` and ``client`` are stamped here when unset, from
    :mod:`mureo.core.actor` — the same choke-point rule
    :func:`mureo.context.state.append_action_log` follows, so a decision and
    the actions it produced carry the same session id. An explicit value is
    kept: a replayed or imported record names the session that made the
    decision, not the one writing it down.

    Returns:
        The written document and the record's index in ``decisions``.

    Raises:
        ValueError: ``decisions`` is not a list (#882), the id is on record,
            an index is out of range, or ``supersedes`` names no decision.
        BatchError: ``batch_id`` names no declared batch.
    """
    position = -1

    def _build(doc: StateDocument) -> StateDocument:
        nonlocal position
        refuse_if_kept(doc, "decisions", "recording a decision")
        _check_unique_id(doc, record)
        _check_related_actions(doc, record)
        _check_supersedes(doc, record)
        _check_batch(doc, record)
        stamped = stamp_identity(record)
        position = len(doc.decisions)
        # ``replace`` carries every other section across by construction —
        # the reason ``append_action_log`` stopped enumerating them.
        return replace(doc, decisions=(*doc.decisions, stamped))

    return _locked_state_mutation(path, _build), position


__all__ = ["append_decision"]
