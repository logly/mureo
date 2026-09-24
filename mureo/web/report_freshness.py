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


# ---------------------------------------------------------------------------
# Per-platform freshness (#535, #798)
# ---------------------------------------------------------------------------


def _platform_freshness(
    totals: dict[str, Any] | None, metrics_period: str | None
) -> dict[str, Any]:
    """How old THIS platform's figures are — ``{fetched_at, period_end,
    stale, stale_after_days}``.

    ``fetched_at`` is the optional, writer-stamped time the numbers were
    pulled (canonical vocabulary; see ``_mureo-strategy`` → *Performance
    Metrics*). It is read off the rollup actually being rendered, so a
    period-toggled view reports the freshness of the window on screen, and it
    is relayed **verbatim** — including a value that is not a timestamp at
    all. ``stale`` is the authoritative "could this be interpreted?" answer;
    blanking an uninterpretable string would throw away the only clue an
    operator has for finding the writer that produced it, and this module
    reports what the document says rather than silently normalising it.
    Consumers must therefore treat ``fetched_at`` as an opaque string unless
    ``stale`` is not ``None``.

    ``period_end`` is the last calendar date the figures COVER (#798),
    relayed by exactly the same rule: verbatim, including a value that is not
    a date. It is the fact staleness is really asking about — the write time
    was only ever a proxy — so when it is present AND parseable it is what
    the verdict is taken on. Both are reported either way: they answer
    different questions ("what day is this?" and "when was this last
    written?") and showing one in place of the other is the defect.

    ``stale`` is deliberately three-valued. ``None`` means **unknown** —
    neither date could be interpreted — and that is a real state, not an
    error: both fields are optional and writer-dependent, so claiming either
    "fresh" or "stale" would assert something mureo cannot back. Callers
    render it as its own thing.

    Why this exists at all: the only freshness the dashboard used to show was
    the document-level ``last_synced_at``, which the state layer re-stamps on
    ANY platform write — so refreshing one platform made every other
    platform's months-old numbers read as just-synced (#535). That timestamp
    is still correct about what it means; it just cannot answer this
    question.
    """
    stale_after = _stale_after_days(metrics_period)
    fetched_raw = totals.get("fetched_at") if totals else None
    fetched_at = fetched_raw if isinstance(fetched_raw, str) and fetched_raw else None
    covers_raw = totals.get("period_end") if totals else None
    period_end = covers_raw if isinstance(covers_raw, str) and covers_raw else None
    return {
        "fetched_at": fetched_at,
        "period_end": period_end,
        "stale": _is_stale(fetched_at, period_end, stale_after),
        "stale_after_days": stale_after,
    }


def _is_stale(
    fetched_at: str | None, period_end: str | None, stale_after: int
) -> bool | None:
    """Are figures covering ``period_end``, written at ``fetched_at``, stale?

    Coverage first, write time second, ``None`` (unknown) when neither can be
    interpreted. The precedence is the whole of #798: the question is "do
    these numbers still describe the window on screen", and only the coverage
    date answers it directly — a rollup re-written today from figures that
    cover last week is not fresh, and one written a fortnight ago from
    figures that cover yesterday is not stale.

    The threshold itself is untouched (see :func:`_stale_after_days`) and is
    applied to both the same way: strictly older than ``stale_after`` days,
    so a figure exactly on the boundary is still inside the grace.
    """
    covered = _parse_period_end(period_end)
    if covered is not None:
        return covered < datetime.now(timezone.utc).date() - timedelta(days=stale_after)
    parsed = _parse_timestamp(fetched_at)
    if parsed is None:
        return None
    return parsed < datetime.now(timezone.utc) - timedelta(days=stale_after)


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
