"""Which ``action_log`` observations are still open — decided once (#651).

An entry with an ``observation_due`` is one whose outcome someone owes a
review. Nothing marks such an entry "done": ``mureo_outcome_evaluate`` is
pure and writes nothing, so an observation only leaves the pending set when
a LATER entry records its closure — a rollback (``rollback_of=<index>``,
written by :mod:`mureo.rollback.executor`) or an evaluation record
(``evaluation_of=<index>``, appended by daily-check after it evaluates the
outcome). Without the latter a past-due entry would be re-evaluated on every
run and the pending set would grow without bound.

That rule had exactly one consumer — ``mureo_state_get(action_log="pending")``
— until the Reports triage layer needed the same answer for a client card.
It lives here rather than in either caller because the two hold the log in
different shapes and a private copy is how a dashboard ends up nagging about
a review that was done a fortnight ago: the MCP handler works over the
rendered dicts it is about to return, the report builder over the parsed
:class:`~mureo.context.models.ActionLogEntry` dataclasses. One rule, two
shapes, no second opinion.

Nothing here reads a file or a clock. ``today`` is passed in, because "is
this window closed?" is a question about a date the CALLER establishes —
the same discipline the skills follow with ``server_now``.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "CLOSURE_INDEX_FIELDS",
    "closed_observation_indices",
    "due_observation_dates",
]

CLOSURE_INDEX_FIELDS: tuple[str, ...] = ("rollback_of", "evaluation_of")
"""Fields whose value is the positional index of an entry they CLOSE.

A later rollback reverses the action; a later evaluation record reviews its
outcome. Either takes the target out of the pending set. Shared by the
pending filter, the append-time index validation and the Reports triage
count, so none of the three can disagree about what "closes" an observation.
"""


def _field(entry: Any, name: str) -> Any:
    """Read ``name`` off a rendered dict OR a dataclass entry.

    The two shapes are the two callers (see the module docstring). A shape
    that answers to neither yields ``None`` rather than raising — this runs
    on the read path of a view that must degrade, never 500.
    """
    if isinstance(entry, dict):
        return entry.get(name)
    return getattr(entry, name, None)


def closed_observation_indices(entries: Iterable[Any]) -> set[int]:
    """Positional indices closed by a later ``rollback_of`` / ``evaluation_of``.

    ``entries`` must be the FULL, append-only log, so the positional indices
    here match the ones the rollback executor and daily-check's evaluation
    records write.

    ``bool`` is rejected explicitly: it is an ``int`` subclass in Python, so
    a writer storing ``True`` would otherwise close entry 1 — an entry it
    has nothing to do with.
    """
    closed: set[int] = set()
    for entry in entries:
        for name in CLOSURE_INDEX_FIELDS:
            value = _field(entry, name)
            if isinstance(value, int) and not isinstance(value, bool):
                closed.add(value)
    return closed


def due_observation_dates(entries: Sequence[Any], today: date) -> list[date]:
    """Every OPEN observation whose window has closed, as its due date.

    "Due" is narrower than "pending" on purpose: an entry whose
    ``observation_due`` is still in the future is under observation, not
    owed. Surfacing it would ask an operator to review a change made
    yesterday, and a signal that fires on healthy state stops being read.

    An ``observation_due`` that is not an ISO date is skipped. It cannot be
    judged against ``today``, and unknown is not a verdict — the same
    position :func:`mureo.web.report_document._platform_freshness` takes on a
    ``fetched_at`` it cannot parse. It is also writer-supplied text, so
    parsing is what keeps it from reaching a caller that relays the date.

    Returned unsorted, in document order; the caller decides what to do with
    them (a count, the oldest, a list).
    """
    closed = closed_observation_indices(entries)
    due: list[date] = []
    for index, entry in enumerate(entries):
        if index in closed:
            continue
        parsed = _parse_due_date(_field(entry, "observation_due"))
        if parsed is not None and parsed <= today:
            due.append(parsed)
    return due


def _parse_due_date(value: Any) -> date | None:
    """Parse an ISO-8601 ``observation_due`` date, or ``None``.

    Accepts the date-time spelling too (``2026-04-15T00:00:00+09:00``) and
    keeps only the date: the field is documented as a date, but a writer
    that stamped a full timestamp still meant one, and refusing it would
    report a real due date as unreadable.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
