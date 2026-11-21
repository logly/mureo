"""The ``period`` vocabulary resolved against the ad account's own day.

The frozen "now" is 2026-03-01 00:30 in Tokyo, which is still 2026-02-28 in
UTC: a resolver that used the host or UTC day would be one day off, and the
month presets would land in the wrong month.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from mureo.chatgpt_ads import _period
from mureo.chatgpt_ads._period import resolve_period, today_in, unix_bounds

pytestmark = pytest.mark.unit

TOKYO = ZoneInfo("Asia/Tokyo")
#: 2026-03-01 00:30 in Tokyo == 2026-02-28 15:30 UTC.
_NOW = datetime(2026, 2, 28, 15, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_period.clock, "server_now", lambda: _NOW)


def test_today_is_the_account_zone_day() -> None:
    assert today_in(TOKYO) == date(2026, 3, 1)
    assert today_in(timezone.utc) == date(2026, 2, 28)


@pytest.mark.parametrize(
    ("period", "since", "until"),
    [
        ("today", date(2026, 3, 1), date(2026, 3, 1)),
        ("yesterday", date(2026, 2, 28), date(2026, 2, 28)),
        ("last_7d", date(2026, 2, 22), date(2026, 2, 28)),
        ("last_14d", date(2026, 2, 15), date(2026, 2, 28)),
        ("last_30d", date(2026, 1, 30), date(2026, 2, 28)),
        ("last_90d", date(2025, 12, 1), date(2026, 2, 28)),
        ("this_month", date(2026, 3, 1), date(2026, 3, 1)),
        ("last_month", date(2026, 2, 1), date(2026, 2, 28)),
        ("2026-01-05..2026-01-09", date(2026, 1, 5), date(2026, 1, 9)),
    ],
)
def test_every_preset_and_an_explicit_range(
    period: str, since: date, until: date
) -> None:
    assert resolve_period(period, today_in(TOKYO)) == (since, until)


def test_a_365_day_window_is_accepted() -> None:
    since, until = date(2025, 1, 1), date(2025, 12, 31)
    assert resolve_period(f"{since}..{until}", date(2026, 3, 1)) == (since, until)


def test_a_window_longer_than_365_days_is_refused() -> None:
    with pytest.raises(ValueError, match="365"):
        resolve_period("2024-01-01..2025-01-01", date(2026, 3, 1))


@pytest.mark.parametrize(
    "period",
    ["", "last_week", "2026-01-09..2026-01-05", "2026-01-01", "a..b", "1..2..3"],
)
def test_unknown_or_malformed_periods_are_refused(period: str) -> None:
    with pytest.raises(ValueError):
        resolve_period(period, date(2026, 3, 1))


def test_a_non_string_period_is_refused() -> None:
    with pytest.raises(ValueError):
        resolve_period(7, date(2026, 3, 1))  # type: ignore[arg-type]


def test_unix_bounds_use_the_zone_midnights_with_an_inclusive_end() -> None:
    start, end = unix_bounds(date(2026, 3, 1), date(2026, 3, 1), TOKYO)
    midnight = datetime(2026, 3, 1, tzinfo=TOKYO)
    assert start == int(midnight.timestamp())
    assert end == int((midnight + timedelta(days=1)).timestamp()) - 1


def test_a_zone_behind_utc_is_still_on_the_previous_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 2026-03-01 03:00 UTC is 2026-02-28 19:00 in Los Angeles (UTC-8).
    now = datetime(2026, 3, 1, 3, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(_period.clock, "server_now", lambda: now)
    los_angeles = ZoneInfo("America/Los_Angeles")
    assert today_in(los_angeles) == date(2026, 2, 28)
    assert resolve_period("yesterday", today_in(los_angeles)) == (
        date(2026, 2, 27),
        date(2026, 2, 27),
    )


def test_last_month_from_january_is_the_previous_december() -> None:
    assert resolve_period("last_month", date(2026, 1, 15)) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )


def test_this_month_on_a_mid_month_day() -> None:
    assert resolve_period("this_month", date(2026, 2, 17)) == (
        date(2026, 2, 1),
        date(2026, 2, 17),
    )


@pytest.mark.parametrize(
    ("day", "zone", "start", "end"),
    [
        # 2026-03-01 00:00 in Tokyo == 2026-02-28 15:00 UTC.
        (date(2026, 3, 1), "Asia/Tokyo", 1772290800, 1772377199),
        # New York springs forward: a 23-hour day.
        (date(2026, 3, 8), "America/New_York", 1772946000, 1773028799),
        # New York falls back: a 25-hour day.
        (date(2026, 11, 1), "America/New_York", 1793505600, 1793595599),
    ],
)
def test_unix_bounds_against_literal_seconds(
    day: date, zone: str, start: int, end: int
) -> None:
    assert unix_bounds(day, day, ZoneInfo(zone)) == (start, end)


def test_dst_days_are_23_and_25_hours_long() -> None:
    new_york = ZoneInfo("America/New_York")
    spring = unix_bounds(date(2026, 3, 8), date(2026, 3, 8), new_york)
    autumn = unix_bounds(date(2026, 11, 1), date(2026, 11, 1), new_york)
    assert spring[1] - spring[0] + 1 == 23 * 3600
    assert autumn[1] - autumn[0] + 1 == 25 * 3600
