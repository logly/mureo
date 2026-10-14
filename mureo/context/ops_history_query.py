"""Date-bounded reads of the ops history (#848), and the date rule every
history source shares.

``since`` / ``until`` bound a record by the calendar date of its own
timestamp, read in the timestamp's own offset — ``2026-10-14T08:00+09:00``
is 2026-10-14. ``mureo_history_query`` applies :func:`in_window` and
:func:`iso_date` to every source, and the dashboard feed
(:func:`mureo.web.reports.build_ops_history`) reads the same items through
:func:`ops_history_items`, so the two surfaces cannot disagree about which
items a window holds.

Here rather than in the MCP layer so a non-MCP reader can use it without
importing the server's handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from mureo.context.ops_history_view import build_ops_history_items

if TYPE_CHECKING:
    from datetime import date

    from mureo.context.models import StateDocument


class DateBounds(Protocol):
    """The inclusive bounds :func:`in_window` reads."""

    @property
    def since(self) -> date | None: ...

    @property
    def until(self) -> date | None: ...


@dataclass(frozen=True)
class _Bounds:
    since: date | None
    until: date | None


def in_window(day: date | None, bounds: DateBounds) -> bool:
    """Whether ``day`` falls inside the inclusive bounds.

    An undatable record passes an unbounded query and fails a bounded one:
    it cannot be SHOWN to fall inside a window, and a record placed in one
    it might not belong to is worse than one left out of it.
    """
    if bounds.since is None and bounds.until is None:
        return True
    if day is None:
        return False
    return (bounds.since is None or day >= bounds.since) and (
        bounds.until is None or day <= bounds.until
    )


def iso_date(value: Any) -> date | None:
    """The date of an ISO 8601 timestamp in its own offset, or ``None``.

    ``Z`` is normalised by hand: ``fromisoformat`` only learned to read it
    in 3.11 and mureo still supports 3.10, where an unconverted ``Z``
    would drop the record out of every bounded query.
    """
    if not isinstance(value, str) or not value:
        return None
    text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def ops_history_items(
    doc: StateDocument,
    *,
    today: date,
    since: date | None = None,
    until: date | None = None,
) -> list[dict[str, Any]]:
    """The ops history items dated inside ``[since, until]``, newest first.

    The window is applied before an item is derived, by the same rule as
    every other history source (:func:`in_window` over the date of
    :func:`~mureo.context.ops_history_view.item_timestamp`), so an item
    outside it costs nothing (#849).
    """
    bounds = _Bounds(since=since, until=until)

    def keep(stamp: str | None) -> bool:
        return in_window(iso_date(stamp), bounds)

    return build_ops_history_items(doc, today=today, keep=keep)


__all__ = ["DateBounds", "in_window", "iso_date", "ops_history_items"]
