"""The ops history counts on each client card (#849).

"Last 30 days: N changes · a improved · b regressed · c inconclusive · d
observing" — counted here so the browser never counts. The items are the
ones :mod:`mureo.context.ops_history_view` derives, read through the same
date rule as every other history surface
(:func:`~mureo.context.ops_history_query.ops_history_items`), so the card
and the detail section's default window cannot disagree about which
changes the last 30 days hold.

What is counted:

- ``changes``: items something was CHANGED for — state ``executed``,
  ``observing``, ``evaluated`` or ``skipped``. A decision still
  ``proposed`` / ``adopted`` with no change, or ``rejected`` / ``deferred``,
  changed nothing and is not a change.
- ``improved`` / ``regressed``: evaluated items with that verdict.
- ``inconclusive``: evaluated items with any other verdict, including none.
- ``observing``: items whose observation window is still open.

Pure: items or a document in, a new dict out.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from mureo.context.ops_history_query import ops_history_items
from mureo.context.ops_history_view import (
    STATE_EVALUATED,
    STATE_EXECUTED,
    STATE_OBSERVING,
    STATE_SKIPPED,
)
from mureo.context.settings import ops_history_enabled

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from mureo.context.models import StateDocument

#: The window the client card counts over, and the detail section's default.
OPS_HISTORY_WINDOW_DAYS: Final = 30

#: The states in which something was changed.
CHANGE_STATES: Final[frozenset[str]] = frozenset(
    {STATE_EXECUTED, STATE_OBSERVING, STATE_EVALUATED, STATE_SKIPPED}
)

_IMPROVED: Final = "improved"
_REGRESSED: Final = "regressed"


def _zero() -> dict[str, int]:
    return {
        "changes": 0,
        "improved": 0,
        "regressed": 0,
        "inconclusive": 0,
        "observing": 0,
    }


def count_ops_history_items(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    """How many changes ``items`` hold, and how they turned out."""
    counts = _zero()
    for item in items:
        state = item.get("state")
        if state not in CHANGE_STATES:
            continue
        counts["changes"] += 1
        if state == STATE_OBSERVING:
            counts["observing"] += 1
        elif state == STATE_EVALUATED:
            verdict = item.get("verdict")
            key = verdict if verdict in (_IMPROVED, _REGRESSED) else "inconclusive"
            counts[key] += 1
    return counts


def ops_history_counts(
    doc: StateDocument | None,
    *,
    today: date,
    window_days: int = OPS_HISTORY_WINDOW_DAYS,
) -> dict[str, Any]:
    """The client card's aggregate for ``doc`` over the last ``window_days``.

    ``since`` is ``today - window_days`` and ``until`` is ``today``, both
    inclusive — the detail section's default window. While ops history is
    off nothing is read and every count is zero.
    """
    enabled = ops_history_enabled(doc)
    counts = _zero()
    if enabled and doc is not None:
        since = today - timedelta(days=window_days)
        items = ops_history_items(doc, today=today, since=since, until=today)
        counts = count_ops_history_items(items)
    return {"enabled": enabled, "window_days": window_days, **counts}


__all__ = [
    "CHANGE_STATES",
    "OPS_HISTORY_WINDOW_DAYS",
    "count_ops_history_items",
    "ops_history_counts",
]
