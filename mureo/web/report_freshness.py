"""Is this platform's figure still worth showing? (#535, #798)

Lifted out of :mod:`mureo.web.report_document`, which had reached the
800-line budget. Nothing moved changed in the move — same names, same
bodies, same order — and the section had already been one self-contained
question: *how old are these numbers, and is that too old for the window
they claim to describe?*

Two facts, and they are not the same fact:

  - ``fetched_at`` — when the rollup was WRITTEN. Optional and
    writer-supplied, though the state layer stamps its own write time when
    the caller leaves it out (#637), so it is usually present.
  - ``period_end`` — the last calendar date the figures COVER, as
    ``YYYY-MM-DD``. Optional, and supplied by the writer alone: the server
    cannot derive it (see
    :func:`~mureo.context.state._stamp_fetched_at`), because "yesterday"
    depends on the ad account's own timezone.

#798 is what happens when the second one is missing and the first is read as
if it were the second. daily-check's step 13 is best-effort: a run can
persist the report and the display, report that it did, and leave
``platforms[<key>].periods`` untouched — or re-write a window from figures
that cover an earlier day. ``fetched_at`` then says "14 hours ago" about a
card showing the day before yesterday, and nothing on screen contradicts it.
So where a rollup states what it covers, THAT is what the stale verdict is
taken on; ``fetched_at`` remains the fallback, and is still reported either
way.

Read-only, like everything on this side: nothing here mutates, nothing
raises, and an uninterpretable value is reported as unknown rather than
guessed at.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

# The stored shape's own bound for a calendar-date key (#690), reused rather
# than restated: a coverage date and a day-grain history key are the same
# ``YYYY-MM-DD`` shape, and two patterns would be free to drift.
from mureo.context.models import DAILY_DATE_KEY_PATTERN
from mureo.core.metrics_windows import CANONICAL_METRICS_WINDOWS

# Canonical window → the length of that window in days. The stale threshold
# is derived from this rather than written down as a per-window magic number,
# so the rationale below is the only thing to check when a window is added.
_PERIOD_LENGTH_DAYS: dict[str, int] = dict(CANONICAL_METRICS_WINDOWS)

_STALE_GRACE_DAYS = 1
"""Slack added to a window's own length before its figure is called stale.

Absorbs one missed daily sync run and the platforms' own reporting lag
(conversions backfill for a day or two is normal), so a single hiccup does
not paint a healthy account red.
"""

_STALE_AFTER_DAYS_DEFAULT = max(_PERIOD_LENGTH_DAYS.values()) + _STALE_GRACE_DAYS
"""Threshold for a window whose length mureo does not know.

The most forgiving known threshold, not the strictest: a window we cannot
reason about must not be flagged on a guess. Crying wolf on figures mureo
cannot judge would teach operators to ignore the marker, which costs more
than the occasional missed stale entry.
"""

_PERIOD_END_RE = re.compile(DAILY_DATE_KEY_PATTERN)
"""What a ``period_end`` has to look like before it is read as a date."""

JUDGED_ON_PERIOD_END = "period_end"
JUDGED_ON_FETCHED_AT = "fetched_at"
"""Which fact a ``stale`` verdict was taken on — the freshness block's
``judged_on``. Stated by the server so the screen never re-derives it: a
second copy of "was the coverage date parseable?" would drift from this one.
"""

_WESTERNMOST_UTC_OFFSET = timedelta(hours=12)
"""How far behind UTC the westernmost timezone runs (UTC-12).

A ``period_end`` is a calendar date in the ad ACCOUNT's timezone, which this
process does not know. Judging it against the UTC date would take up to half
a day of the one-missed-sync grace from every account west of UTC — a US
Pacific account's figures would turn stale while its own day was still in
progress. So coverage is judged against the calendar date still in progress
in the westernmost zone, ``(now - 12h).date()``. An account east of UTC gains
up to twelve hours of extra grace instead, which is the safe direction: a
late stale marker costs one day's attention, a false one teaches operators
to ignore the marker.
"""


# ---------------------------------------------------------------------------
# Per-platform freshness (#535, #798)
# ---------------------------------------------------------------------------


def _platform_freshness(
    totals: dict[str, Any] | None,
    metrics_period: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """How old THIS platform's figures are — ``{fetched_at, period_end,
    stale, judged_on, stale_after_days}``.

    ``fetched_at`` is when the numbers were WRITTEN and ``period_end`` the
    last calendar date they COVER (#798) — different facts, both optional and
    writer-supplied, both read off the rollup actually being rendered (so a
    period-toggled view reports the window on screen) and both relayed
    **verbatim**, including a value that is not a timestamp or a date at all:
    blanking it would throw away the only clue to the writer that produced
    it. Consumers treat either as an opaque string unless ``judged_on`` names
    it.

    ``stale`` is taken on the coverage date when it is present and parseable
    — it is the fact staleness is really asking about; the write time was
    only ever a proxy — and on ``fetched_at`` otherwise. ``judged_on`` says
    which (:data:`JUDGED_ON_PERIOD_END` / :data:`JUDGED_ON_FETCHED_AT`).

    ``stale`` is deliberately three-valued, and ``judged_on`` is ``None``
    exactly when it is. ``None`` means **unknown** — neither date could be
    interpreted — which is a real state, not an error; claiming "fresh" or
    "stale" would assert something mureo cannot back.

    Why this exists at all: the document-level ``last_synced_at`` is
    re-stamped on ANY platform write, so refreshing one platform made every
    other platform's months-old numbers read as just-synced (#535).

    ``now`` is injectable for tests; it defaults to the current UTC instant.
    """
    stale_after = _stale_after_days(metrics_period)
    fetched_at = _relayed_string(totals, "fetched_at")
    period_end = _relayed_string(totals, "period_end")
    stale, judged_on = _is_stale(fetched_at, period_end, stale_after, now)
    return {
        "fetched_at": fetched_at,
        "period_end": period_end,
        "stale": stale,
        "judged_on": judged_on,
        "stale_after_days": stale_after,
    }


def _relayed_string(totals: dict[str, Any] | None, key: str) -> str | None:
    """``totals[key]`` when it is a non-empty string, else ``None``."""
    raw = totals.get(key) if totals else None
    return raw if isinstance(raw, str) and raw else None


def _is_stale(
    fetched_at: str | None,
    period_end: str | None,
    stale_after: int,
    now: datetime | None = None,
) -> tuple[bool | None, str | None]:
    """Are figures covering ``period_end``, written at ``fetched_at``, stale
    — and which of the two decided? ``(stale, judged_on)``.

    Coverage first, write time second, ``(None, None)`` (unknown) when
    neither can be interpreted. The precedence is the whole of #798: the
    question is "do these numbers still describe the window on screen", and
    only the coverage date answers it directly — a rollup re-written today
    from figures that cover last week is not fresh, and one written a
    fortnight ago from figures that cover yesterday is not stale.

    The threshold itself is untouched (see :func:`_stale_after_days`) and is
    applied to both the same way: strictly older than ``stale_after`` days,
    so a figure exactly on the boundary is still inside the grace. The
    coverage date is compared with the westernmost calendar date still in
    progress (see :data:`_WESTERNMOST_UTC_OFFSET`), not with UTC's.
    """
    current = now if now is not None else datetime.now(timezone.utc)
    covered = _parse_period_end(period_end)
    if covered is not None:
        in_progress = (current - _WESTERNMOST_UTC_OFFSET).date()
        stale = covered < in_progress - timedelta(days=stale_after)
        return stale, JUDGED_ON_PERIOD_END
    parsed = _parse_timestamp(fetched_at)
    if parsed is None:
        return None, None
    return parsed < current - timedelta(days=stale_after), JUDGED_ON_FETCHED_AT


def _stale_after_days(metrics_period: str | None) -> int:
    """Age at which a figure covering ``metrics_period`` is called stale.

    **The window's own length, plus one grace day.** A figure covering a day
    further back than the window it summarises no longer overlaps that window
    at all: a ``LAST_30_DAYS`` rollup running to 31 days ago describes days
    -31 to -61, while today's ``LAST_30_DAYS`` is days 0 to -30 — not one
    shared day. So the figure is not "a bit old", it is about a different
    period than the label claims. :data:`_STALE_GRACE_DAYS` then absorbs one
    missed daily sync and platform reporting lag.

    That is why a ``YESTERDAY`` figure (stale after 2 days) and a
    ``LAST_30_DAYS`` figure (stale after 31) are judged so differently: they
    are not the same claim aging at the same rate.

    An unrecognised window falls back to :data:`_STALE_AFTER_DAYS_DEFAULT`.
    """
    if metrics_period is None:
        return _STALE_AFTER_DAYS_DEFAULT
    length = _PERIOD_LENGTH_DAYS.get(metrics_period)
    if length is None:
        return _STALE_AFTER_DAYS_DEFAULT
    return length + _STALE_GRACE_DAYS


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 ``fetched_at``, or ``None`` if it is not one.

    Tolerates a trailing ``Z`` (Python < 3.11 ``fromisoformat`` does not) and
    treats a naive timestamp as UTC — writers are inconsistent about the
    offset and refusing one would report a real timestamp as unknown.
    A value that is not a timestamp at all yields ``None`` (unknown) rather
    than a guess, and never an exception out of this read-only view.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _parse_period_end(value: str | None) -> date | None:
    """Parse a ``YYYY-MM-DD`` coverage date, or ``None`` if it is not one.

    Strict on the shape on purpose, and stricter than ``fetched_at``'s reader
    is on a timestamp. ``date.fromisoformat`` accepts ``20260922`` and week
    dates on newer Pythons, and a coverage date arrives from an agent
    composing JSON by hand; reading one of those as a date would put a
    verdict on screen that the operator cannot check against the string the
    document actually holds. The shape guard is the same
    :data:`~mureo.context.models.DAILY_DATE_KEY_PATTERN` the day-grain
    history keys are written under, and the parse behind it is what rejects a
    date that matches the shape without existing (``2026-02-30``).

    Anything else is **unknown**, exactly as an uninterpretable ``fetched_at``
    is: the value is still relayed to the consumer verbatim (it is the only
    clue to the writer that produced it), it simply decides nothing. It never
    raises — this is a read-only view.
    """
    if not value or not _PERIOD_END_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
