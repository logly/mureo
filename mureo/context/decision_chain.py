"""Follow a decision's ``supersedes`` chain (#848).

``decisions`` is append-only, so one decision is a CHAIN of records: the
proposal, then the adoption that supersedes it, then perhaps a later
rejection. The first record's ``decision_id`` — the chain's root — is the
decision's stable identity, and it is the id an ``action_log`` entry
carries in ``decision_id``. These helpers answer the questions every reader
of the chain asks: where does it start, what is its latest status, and
what did it expect.

Pure: documents in, values out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.context.decisions import DecisionRecord
    from mureo.context.expected import ExpectedEffect
    from mureo.context.models import StateDocument


def chain_roots(doc: StateDocument) -> dict[str, str]:
    """Map every recorded ``decision_id`` to its chain's root id.

    A ``supersedes`` that names nothing on record, or a cycle in a
    hand-edited file, ends the walk at the last record reached rather than
    looping or raising: a reader must always get an answer.
    """
    parents = {r.decision_id: r.supersedes for r in doc.decisions}
    roots: dict[str, str] = {}
    for decision_id in parents:
        current = decision_id
        seen = {current}
        parent = parents.get(current)
        while parent is not None and parent in parents and parent not in seen:
            current = parent
            seen.add(current)
            parent = parents.get(current)
        roots[decision_id] = current
    return roots


def chain_root(doc: StateDocument, decision_id: str) -> str | None:
    """The root of the chain ``decision_id`` belongs to, or ``None``."""
    return chain_roots(doc).get(decision_id.strip())


def chain_records(doc: StateDocument, root_id: str) -> tuple[DecisionRecord, ...]:
    """Every record in the chain rooted at ``root_id``, in write order."""
    roots = chain_roots(doc)
    return tuple(r for r in doc.decisions if roots.get(r.decision_id) == root_id)


def latest_in_chain(doc: StateDocument, decision_id: str) -> DecisionRecord | None:
    """The most recently written record of ``decision_id``'s chain."""
    root = chain_root(doc, decision_id)
    if root is None:
        return None
    records = chain_records(doc, root)
    return records[-1] if records else None


def chain_expected(doc: StateDocument, decision_id: str) -> tuple[ExpectedEffect, ...]:
    """The expected effects of ``decision_id``'s decision.

    Taken from the NEWEST record in the chain that declares any: an adoption
    that restates the expectation replaces what the proposal said, and one
    that is silent about it keeps it.
    """
    root = chain_root(doc, decision_id)
    if root is None:
        return ()
    for record in reversed(chain_records(doc, root)):
        if record.expected:
            return record.expected
    return ()


__all__ = [
    "chain_expected",
    "chain_records",
    "chain_root",
    "chain_roots",
    "latest_in_chain",
]
