"""The calendar date of an ISO 8601 timestamp, the rule history reads share.

A leaf module: it imports nothing from :mod:`mureo.context`, so both the
models (by way of :mod:`mureo.context.approval`) and the history readers
(:mod:`mureo.context.ops_history_query`) can import it at the top without
a cycle.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


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


__all__ = ["iso_date"]
