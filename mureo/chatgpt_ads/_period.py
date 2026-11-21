"""The ``period`` vocabulary resolved against the ad account's own day.

The vocabulary is the Meta tools' (:mod:`mureo.meta_ads._period`): ``today``,
``yesterday``, ``last_Nd`` (N complete days ending yesterday), ``this_month``,
``last_month`` or an inclusive ``YYYY-MM-DD..YYYY-MM-DD``. The Advertiser API
reads a ``date_range`` in the ad account's time zone, so "today" here is the
account's today, not the host's or UTC's: near midnight the two differ by a
day, and the month presets by a month.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo

from mureo.chatgpt_ads._api import MAX_WINDOW_DAYS
from mureo.core import clock

#: ``last_Nd`` presets and their day counts.
_LAST_N_DAYS = {"last_7d": 7, "last_14d": 14, "last_30d": 30, "last_90d": 90}

#: Every accepted preset, quoted in the error for an unknown value.
_PRESETS = (
    "today",
    "yesterday",
    *_LAST_N_DAYS,
    "this_month",
    "last_month",
)


def today_in(zone: tzinfo) -> date:
    """The calendar day it is now in ``zone``."""
    return clock.server_now().astimezone(zone).date()


def _preset(period: str, today: date) -> tuple[date, date] | None:
    yesterday = today - timedelta(days=1)
    if period == "today":
        return today, today
    if period == "yesterday":
        return yesterday, yesterday
    if period in _LAST_N_DAYS:
        return yesterday - timedelta(days=_LAST_N_DAYS[period] - 1), yesterday
    if period == "this_month":
        return today.replace(day=1), today
    if period == "last_month":
        last_day = today.replace(day=1) - timedelta(days=1)
        return last_day.replace(day=1), last_day
    return None


def _explicit(period: str) -> tuple[date, date]:
    parts = period.split("..")
    if len(parts) != 2:
        raise ValueError(
            f"period must be one of {', '.join(_PRESETS)} or "
            f"YYYY-MM-DD..YYYY-MM-DD, got {period!r}"
        )
    try:
        since, until = date.fromisoformat(parts[0]), date.fromisoformat(parts[1])
    except ValueError:
        raise ValueError(f"period dates must be YYYY-MM-DD, got {period!r}") from None
    if until < since:
        raise ValueError(f"period ends before it starts: {period!r}")
    return since, until


def resolve_period(period: str, today: date) -> tuple[date, date]:
    """``period`` as an inclusive ``(since, until)`` pair.

    ``today`` is the ad account's today (:func:`today_in`). Raises
    ``ValueError`` for an unknown preset, a malformed range, or a window
    longer than :data:`~mureo.chatgpt_ads._api.MAX_WINDOW_DAYS` days.
    """
    if not isinstance(period, str):
        raise ValueError(f"period must be a string, got {type(period).__name__}")
    window = _preset(period, today) or _explicit(period)
    days = (window[1] - window[0]).days + 1
    if days > MAX_WINDOW_DAYS:
        raise ValueError(
            f"period spans {days} days; the API reports at most "
            f"{MAX_WINDOW_DAYS} days per request"
        )
    return window


def unix_bounds(since: date, until: date, zone: tzinfo) -> tuple[int, int]:
    """Unix seconds of ``since``'s midnight and the last second of ``until``.

    The audit-log filter takes inclusive ``start_time`` / ``end_time``, so the
    end is one second before the following midnight in ``zone``.
    """
    start = datetime.combine(since, time.min, tzinfo=zone)
    following = datetime.combine(until + timedelta(days=1), time.min, tzinfo=zone)
    return int(start.timestamp()), int(following.timestamp()) - 1


__all__ = ["resolve_period", "today_in", "unix_bounds"]
