"""The day-grain history write, as a DOCUMENT operation (#690, #710).

:func:`mureo.context.state.set_platform_daily` owns a path: it opens
STATE.json, takes the state lock, merges and writes back. That is the right
shape for the MCP tool and for anything whose whole job is the daily map — and
the wrong shape for a writer that must land ``daily`` **together with other
fields in one atomic document write** (the agency digest lands a rollup and
its day through a tenant-scoped store, so the file it writes is not
STATE.json and the write is not this module's to make).

Such a writer had no public way to apply the retention rule and reached into
``mureo.context.state._capped_daily`` — a private name whose rename would
break a nightly write it does not own. So the merge lives here, at the
document level and off the filesystem:

- :func:`with_platform_daily` guards, merges and trims, returning a NEW
  :class:`~mureo.context.models.StateDocument`. The path-based mutator is a
  thin wrapper around it, so both routes keep exactly one set of semantics;
- :func:`capped_platform_daily` is the retention trim on its own, for a
  writer that has already merged its own map.

The completeness rule is unchanged and non-negotiable — only complete PAST
days are stored — but WHOSE day it is became a parameter: ``as_of_date``, the
caller's own today, resolved in the ad account's timezone.

That anchor is a SELF-REPORT, and on the MCP route the caller reporting it is
an LLM. So it is not taken on trust: an ``as_of_date`` more than
:data:`_MAX_ANCHOR_DAYS_AHEAD` days ahead of the server's own date is refused,
because otherwise stating a far-future today would make every date this side
of it a "complete past day" and switch the rule off with an argument. A past
anchor is left alone — it can only make the check stricter. See
:func:`_completeness_anchor`.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from mureo.context.models import DAILY_DATE_KEY_PATTERN, StateDocument
from mureo.context.platform_guards import guard_platform_entry_write

if TYPE_CHECKING:
    from mureo.context.models import PlatformState

#: How many days of ``PlatformState.daily`` history a write keeps (#690).
#:
#: 28 + margin, not a round number: the delivery-collapse detector baselines
#: a day against the trailing
#: :data:`~mureo.analysis.delivery_collapse.DEFAULT_BASELINE_DAYS` (28) days
#: of the same weekday, so a history shorter than that would be unable to
#: answer the question it is collected for. The margin covers the operator who
#: raises ``delivery_collapse_baseline_days`` a little in STRATEGY.md, and the
#: days a collector missed — a gap is not backfilled, so 28 stored keys are
#: not necessarily 28 calendar days.
#:
#: Applied at WRITE time rather than on read: an account collected every day
#: for a year would otherwise grow STATE.json without bound, and the whole
#: document is read and re-rendered on every mutation.
DAILY_RETENTION_DAYS = 35

_DAILY_DATE_KEY_RE = re.compile(DAILY_DATE_KEY_PATTERN)

#: How far AHEAD of the server's own date an ``as_of_date`` may sit.
#:
#: The anchor is the caller's self-report, and on the MCP route the caller is
#: an LLM that inferred the date — a slip or a prompt injection must not be
#: able to declare 2099 "today" and turn days nobody has lived through into
#: complete history. So it is bounded against the one clock mureo does trust.
#:
#: Two days, because that is the largest gap real timezones can open. Civil
#: offsets run from UTC-12 to UTC+14, a 26-hour spread, so an instant that is
#: date D somewhere on Earth can be D+2 somewhere else: at 22:00–24:00 on D in
#: UTC-12 it is already 00:00–02:00 on D+2 in UTC+14. The server sits
#: somewhere in that range, so does the account, and +2 is the widest honest
#: disagreement between them. The JST-account / UTC-host case this parameter
#: was added for only ever needs +1; the bound is stated for every timezone
#: rather than for the one in front of us.
_MAX_ANCHOR_DAYS_AHEAD = 2


def _completeness_anchor(as_of_date: date | None) -> tuple[date, str]:
    """The day "is this day over?" is judged against, and what to call it.

    Without an anchor it is the HOST's local day
    (:func:`mureo.core.clock.server_now`), the same clock the skills date
    their rows by — that was the whole rule until #710.

    It is the wrong clock for one caller and it is the caller that matters
    most: an ad account closes its day in the ACCOUNT's timezone. A nightly
    digest running on a UTC host at 02:00 Asia/Tokyo is asking about
    yesterday-in-Tokyo, which is still today in UTC — so a genuinely complete
    day was refused, every night, for the whole 00:00–09:00 JST window the
    cron runs in. ``as_of_date`` lets the caller state whose day it is: it
    resolves "today" in the account's timezone and hands the result in. The
    rule itself does not move — a day at or after the anchor is still refused
    — only the question of which today it is measured against.

    **The anchor is self-reported, so it is bounded.** An anchor more than
    :data:`_MAX_ANCHOR_DAYS_AHEAD` days ahead of the server's date is refused:
    without that bound, ``as_of_date="2099-01-01"`` makes every date this side
    of the century a "complete past day", which is the exact rule this module
    exists to enforce, switched off by an argument.

    **There is no bound in the other direction.** A past anchor only makes the
    check STRICTER — it can refuse a day, never admit one — so it is
    self-limiting, and a caller whose clock is behind is told so by an
    explicit refusal naming both dates rather than having its figures dropped.

    A :class:`~datetime.datetime` is accepted and narrowed, because resolving
    "now" in a timezone is what produces one; anything else is refused here
    rather than blowing up in a comparison two frames down.
    """
    # Imported lazily: ``mureo.core.__init__`` pulls in ``runtime_context``
    # -> ``state_store`` -> ``mureo.context.state`` -> this module, so a
    # module-level import would be a cycle.
    from mureo.core import clock

    server_today = clock.server_now().date()
    if as_of_date is None:
        return server_today, "server today"
    if isinstance(as_of_date, datetime):
        anchor = as_of_date.date()
    elif isinstance(as_of_date, date):
        anchor = as_of_date
    else:
        raise ValueError(
            "as_of_date must be a datetime.date (the account's today, resolved "
            f"in the account's timezone), not {type(as_of_date).__name__}"
        )
    if anchor > server_today + timedelta(days=_MAX_ANCHOR_DAYS_AHEAD):
        raise ValueError(
            f"as_of_date {anchor.isoformat()} is more than "
            f"{_MAX_ANCHOR_DAYS_AHEAD} days ahead of the server's date "
            f"({server_today.isoformat()}): no timezone is that far ahead, so "
            "this anchor would file days nobody has lived through as complete "
            "history"
        )
    return anchor, "as_of_date"


def _reject_unusable_daily_keys(
    days: dict[str, Any], *, as_of_date: date | None = None
) -> None:
    """Refuse a ``daily`` key that is not one COMPLETE PAST day (#690).

    Two checks, both about shape rather than vocabulary — unlike a metrics
    window, the set of valid dates cannot be enumerated:

    - the key is ``YYYY-MM-DD`` (:data:`~mureo.context.models.
      DAILY_DATE_KEY_PATTERN`) **and parses as a real date**. The pattern
      alone is not validation: ``2026-02-30`` matches it perfectly, and a key
      no reader can place on a timeline is a bucket nothing will ever show.
    - the day is over. Today is still being spent into, so a rollup for it is
      a partial day — the same reason
      :mod:`mureo.analysis.delivery_collapse` drops everything at or after
      ``as_of`` before comparing anything. Stored, it would be a false low
      forever, because nothing revisits a day already in the map. A future
      date is refused with it: it is not a day anyone collected.

    Which "today" the second check uses is the caller's to state — see
    :func:`_completeness_anchor`.

    Raises on the FIRST bad key, so a refused call leaves the document exactly
    as it was — ``last_synced_at`` included — and the caller still holds every
    figure and can re-file it. A half-written call is what makes that
    impossible. The path-based mutator runs this before it opens the file and
    before it takes the lock, for the same reason.
    """
    today, anchor = _completeness_anchor(as_of_date)
    for key in days:
        if not isinstance(key, str) or not _DAILY_DATE_KEY_RE.match(key):
            raise ValueError(
                f"daily key {key!r} is not a date: use YYYY-MM-DD, one key per "
                "calendar day"
            )
        try:
            day = date.fromisoformat(key)
        except ValueError:
            raise ValueError(
                f"daily key {key!r} is not a date that exists (YYYY-MM-DD)"
            ) from None
        if day >= today:
            raise ValueError(
                f"daily key {key!r} is not a complete day yet ({anchor} is "
                f"{today.isoformat()}): write a day only once it is over, so a "
                "part-spent day is never stored as the whole of it"
            )


def capped_platform_daily(
    daily: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """``daily`` trimmed to the most recent :data:`DAILY_RETENTION_DAYS` days.

    Order is preserved (the merge appends, exactly as ``periods`` does); only
    the oldest date keys beyond the cap are dropped.

    A key this module could not have written — anything that is not
    ``YYYY-MM-DD`` — is **kept, and does not count towards the cap**. The write
    guard refuses such a key today, but one already on disk is still figures
    somebody collected, filed under a name mureo cannot date; a retention
    sweep has no way to tell whether it is the oldest entry or the newest, and
    deleting data to tidy a vocabulary is the asymmetry the read side already
    refuses to make (see :func:`~mureo.web.report_document._available_periods`).

    Public since #710: a writer that merges ``daily`` inside its own atomic
    document write still has to apply the retention rule, and importing a
    private name to do it made a downstream nightly write hostage to a rename.
    """
    dated = [key for key in daily if _DAILY_DATE_KEY_RE.match(key)]
    if len(dated) <= DAILY_RETENTION_DAYS:
        return daily
    dropped = set(sorted(dated)[:-DAILY_RETENTION_DAYS])
    return {key: value for key, value in daily.items() if key not in dropped}


def with_platform_daily(
    doc: StateDocument,
    platform: str,
    account_id: str,
    days: dict[str, dict[str, Any]],
    *,
    as_of_date: date | None = None,
) -> StateDocument:
    """``doc`` with ``days`` merged into a platform's ``daily`` history (#690).

    The whole of the daily write except the file: the same guards, the same
    per-date-key merge, the same ``fetched_at`` stamping and the same
    retention trim as
    :func:`~mureo.context.state.set_platform_daily` — which is now a wrapper
    that adds the lock and the atomic write around this call, so neither route
    can drift from the other.

    Merge semantics:

    - a date this call supplies REPLACES that day's bucket wholesale, so
      re-writing a day is idempotent rather than additive;
    - every OTHER date already stored is preserved — that is the whole point;
    - the platform's campaigns, rollups, conversion override and
      ``not_collected`` note, and every other platform, are untouched.

    **A day nobody collected is not written.** Nothing here fills a gap with
    zeros: "not collected" and "collected, and the answer was zero" are
    different facts (the distinction ``not_collected`` exists for), and a
    zero-filled day is indistinguishable from an account that stopped
    spending — while also poisoning the median the collapse detector baselines
    against. Supply only the days you actually pulled; readers render a gap as
    a gap.

    Args:
        doc: The document to build on. It is not mutated.
        platform: Platform key (``"google_ads"`` / ``"meta_ads"`` /
            ``"plugin:<dist>:<provider>"`` / …) — the ``platforms`` dict key.
        account_id: The platform account id, always written onto the entry.
        days: Day-grain rollups keyed ``YYYY-MM-DD``. An empty map writes no
            day and leaves the stored history alone.
        as_of_date: The account's own today, for the completeness check. Omit
            to judge against the host's clock. More than
            :data:`_MAX_ANCHOR_DAYS_AHEAD` days ahead of the server's date is
            refused (see :func:`_completeness_anchor`).

    Returns:
        A new :class:`~mureo.context.models.StateDocument`, ``last_synced_at``
        re-stamped.

    Raises:
        ValueError: the anchor is too far ahead of the server's date, a key is
            not a complete past calendar day, or the write
            would create a SECOND key for an account another key already holds
            (see :func:`~mureo.context.platform_guards.
            guard_platform_entry_write`).
    """
    # Imported lazily: ``state`` imports THIS module to re-export it, so a
    # module-level import back would be a cycle. These three helpers stay
    # there because every other targeted mutator uses them too.
    from mureo.context.state import _now_iso, _platform_base, _stamp_fetched_at

    _reject_unusable_daily_keys(days, as_of_date=as_of_date)

    platforms: dict[str, PlatformState] = dict(doc.platforms) if doc.platforms else {}
    guard_platform_entry_write(platforms, platform, account_id)

    base = _platform_base(platforms, platform, account_id)
    # One clock read for the whole write, so a bucket's age and the document's
    # cannot disagree by a hair and read as two events.
    written_at = _now_iso()

    merged = dict(base.daily) if base.daily else {}
    # Only the days THIS write supplies are stamped; the ones it merely
    # preserves keep the age they were collected at.
    merged.update(
        {day: _stamp_fetched_at(bucket, written_at) for day, bucket in days.items()}
    )

    # Every other field has no input on a daily write and is carried over by
    # ``replace``.
    platforms[platform] = replace(
        base, account_id=account_id, daily=capped_platform_daily(merged)
    )

    return replace(doc, last_synced_at=written_at, platforms=platforms)
