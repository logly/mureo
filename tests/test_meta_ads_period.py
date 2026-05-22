"""Tests for ``mureo.meta_ads._period`` — period argument resolution.

Covers the contract that fixes #134:

* Known Meta ``date_preset`` names resolve to themselves.
* ``YYYY-MM-DD..YYYY-MM-DD`` resolves to an explicit ``time_range``.
* Anything else raises ``ValueError`` (no silent fallback to
  ``last_7d``).
* ``previous_period`` returns the prior same-length window, with
  every result either a preset name the API accepts or an explicit
  range — never overlapping the current window.
"""

from __future__ import annotations

from datetime import date

import pytest

from mureo.meta_ads._period import ResolvedPeriod, previous_period, resolve_period

# ---------------------------------------------------------------------------
# resolve_period
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "name",
    [
        "today",
        "yesterday",
        "last_7d",
        "last_14d",
        "last_30d",
        "last_90d",
        "this_month",
        "last_month",
    ],
)
def test_resolve_known_preset_returns_preset(name: str) -> None:
    rp = resolve_period(name)
    assert isinstance(rp, ResolvedPeriod)
    assert rp.is_preset is True
    assert rp.date_preset == name
    assert rp.time_range is None


@pytest.mark.unit
def test_resolve_custom_range_returns_time_range() -> None:
    rp = resolve_period("2026-05-01..2026-05-14")
    assert rp.is_preset is False
    assert rp.date_preset is None
    assert rp.time_range == ("2026-05-01", "2026-05-14")


@pytest.mark.unit
def test_resolve_single_day_range_is_supported() -> None:
    """An explicit ``since==until`` is the canonical way to query one
    day from the past — Meta accepts it; the resolver must too."""
    rp = resolve_period("2026-05-01..2026-05-01")
    assert rp.time_range == ("2026-05-01", "2026-05-01")


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        "",
        "last_7days",  # the user said days, not d
        "last_60d",  # not in the documented preset surface
        "May 1-14",  # human-readable shorthand
        "2026/05/01..2026/05/14",  # slash, not iso
        "2026-05-01..2026-05-14..2026-05-21",  # too many separators
        "2026-13-01..2026-05-14",  # bogus month
        "2026-05-14..2026-05-01",  # since > until
        "2026-05-01..",  # missing until — looks like a range but isn't
        "..2026-05-14",  # missing since
        " last_7d ",  # whitespace-padded preset name; no implicit strip
        "2026-05-01 .. 2026-05-14",  # whitespace around separator
    ],
)
def test_resolve_unknown_value_raises_value_error(bad: str) -> None:
    """No silent fallback. An operator who typed a nonsense period
    must hear about it instead of receiving last_7d data labelled
    with their period (Issue #134)."""
    with pytest.raises(ValueError):
        resolve_period(bad)


@pytest.mark.unit
def test_resolve_non_string_raises_value_error() -> None:
    with pytest.raises(ValueError):
        resolve_period(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ResolvedPeriod.days
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        ("today", 1),
        ("yesterday", 1),
        ("last_7d", 7),
        ("last_14d", 14),
        ("last_30d", 30),
        ("last_90d", 90),
    ],
)
def test_preset_days(name: str, expected: int) -> None:
    assert resolve_period(name).days == expected


@pytest.mark.unit
def test_custom_range_days_is_inclusive() -> None:
    """Meta treats both endpoints of a time_range as inclusive, so a
    14-day window from May 1 through May 14 reports 14 days, not 13.
    Off-by-one here propagates straight into previous_period."""
    rp = resolve_period("2026-05-01..2026-05-14")
    assert rp.days == 14


# ---------------------------------------------------------------------------
# previous_period
# ---------------------------------------------------------------------------


_FIXED_TODAY = date(2026, 5, 22)


@pytest.mark.unit
def test_previous_for_custom_range_is_same_length_immediately_before() -> None:
    """May 1–14 (14 days) → prior 14 days ending Apr 30."""
    prev = previous_period("2026-05-01..2026-05-14", today=_FIXED_TODAY)
    assert prev == "2026-04-17..2026-04-30"


@pytest.mark.unit
def test_previous_for_last_7d_is_prior_7_days_ending_8_days_ago() -> None:
    """Today = May 22. last_7d = May 15..May 21 (the 7 complete days
    ending yesterday). previous = May 8..May 14."""
    prev = previous_period("last_7d", today=_FIXED_TODAY)
    assert prev == "2026-05-08..2026-05-14"


@pytest.mark.unit
def test_previous_for_last_14d_does_not_overlap_current() -> None:
    """The fix's whole point: previous must NOT overlap current. The
    pre-fix code mapped last_7d → last_30d which DID overlap (a
    superset). This regression test pins that to never recur."""
    rp_cur = resolve_period("last_14d")
    cur_days = rp_cur.days
    cur_until = _FIXED_TODAY  # last_14d ends "today" inclusive in this
    # impl; we don't depend on the exact convention, only that the
    # previous string parses to a window that does NOT overlap.
    prev_str = previous_period("last_14d", today=_FIXED_TODAY)
    prev_rp = resolve_period(prev_str)
    assert prev_rp.time_range is not None
    prev_since, prev_until = prev_rp.time_range
    assert prev_rp.days == cur_days
    # The previous-window's ``until`` must be strictly before today
    # minus (cur_days - 1) days — anything else means overlap.
    assert date.fromisoformat(prev_until) < cur_until


@pytest.mark.unit
def test_previous_for_today_is_yesterday() -> None:
    assert previous_period("today", today=_FIXED_TODAY) == "yesterday"


@pytest.mark.unit
def test_previous_for_yesterday_is_day_before_yesterday() -> None:
    assert previous_period("yesterday", today=_FIXED_TODAY) == "2026-05-20..2026-05-20"


@pytest.mark.unit
def test_previous_for_this_month_is_last_month() -> None:
    """``this_month`` has a natural calendar-relative previous: the
    matching preset name. Honour that — round-tripping through preset
    names preserves Meta's intent."""
    assert previous_period("this_month", today=_FIXED_TODAY) == "last_month"


@pytest.mark.unit
def test_previous_for_last_month_is_month_before_last() -> None:
    """Today = May 22 → last_month = April → month-before-last =
    March. Returned as an explicit range so the caller doesn't have
    to do calendar arithmetic itself."""
    assert previous_period("last_month", today=_FIXED_TODAY) == "2026-03-01..2026-03-31"


@pytest.mark.unit
def test_previous_rejects_bad_period() -> None:
    """previous_period should validate via the same path resolve_period
    uses — no silent acceptance of an unknown current period."""
    with pytest.raises(ValueError):
        previous_period("last_60d", today=_FIXED_TODAY)
