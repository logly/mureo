"""ISO 8601 timestamps as history reads them: the moment, and its date.

A leaf module: it imports nothing from :mod:`mureo.context`, so both the
models (by way of :mod:`mureo.context.approval`) and the history readers
(:mod:`mureo.context.ops_history_query`) can import it at the top without
a cycle.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def iso_moment(value: Any) -> datetime | None:
    """The moment an ISO 8601 timestamp names, or ``None``.

    ``Z`` is normalised by hand: ``fromisoformat`` only learned to read it
    in 3.11 and mureo still supports 3.10, where an unconverted ``Z``
    would drop the record out of every bounded query. A naive timestamp
    (hand-written, or from before offsets were stamped) is read as UTC, so
    every moment compares with every other.
    """
    if not isinstance(value, str) or not value:
        return None
    text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso_date(value: Any) -> date | None:
    """The date of an ISO 8601 timestamp in its own offset, or ``None``."""
    moment = iso_moment(value)
    return None if moment is None else moment.date()


__all__ = ["iso_date", "iso_moment"]
