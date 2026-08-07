"""Reporting lag must never read as a collapse (#546).

The gap-fill that closed the sparse-rows hole opened its mirror: if a
platform has not yet reported the most recent day, filling that day with
a zero turns normal reporting lag into a CRITICAL outage on a perfectly
healthy campaign. A detector that cries wolf gets muted, and then the
collapse it exists for goes unseen anyway — the two failures end in the
same place.

The rule these tests pin: **a missing day is only zero delivery when the
report proves the platform covered that day.** Any campaign in the
account carrying a row for date D is that proof. Beyond the last date
the platform reported anything, days are *not yet known* and are left
out of the evaluation rather than asserted to be zero.

Every case here runs at 09:00, not just after midnight — the exposure is
set by reporting lag against ``consecutive_days``, never by clock time.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.analysis.delivery_collapse import (
    CollapseThresholds,
    delivery_series_from_rows,
    detect_delivery_collapses,
    last_reported_day,
)
from mureo.google_ads._analysis_performance import _PerformanceAnalysisMixin

# 09:00, deliberately: the false positive is not a midnight edge case.
FROZEN_NOW = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
TODAY = FROZEN_NOW.date()
HEALTHY_IMPRESSIONS = 350_000
HISTORY_DAYS = 45

LAGS = [0, 1, 2, 3]
CONSECUTIVE = [1, 2, 3]


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.core.clock.server_now", lambda: FROZEN_NOW)


class _GoogleClient(_PerformanceAnalysisMixin):
    def __init__(self, rows: list[Any]) -> None:
        self._search = AsyncMock(return_value=rows)  # type: ignore[method-assign]


def _row(day: date, impressions: int, campaign_id: int = 123) -> Any:
    return SimpleNamespace(
        campaign=SimpleNamespace(
            id=campaign_id,
            name=f"Campaign {campaign_id}",
            status="ENABLED",
            end_date="",
        ),
        segments=SimpleNamespace(date=day.isoformat()),
        metrics=SimpleNamespace(
            impressions=impressions,
            clicks=impressions // 100,
            cost_micros=1_500_000,
        ),
    )


def _healthy_rows(
    *, lag_days: int, campaign_id: int = 123, dead_for: int = 0
) -> list[Any]:
    """``HISTORY_DAYS`` of delivery ending ``lag_days`` behind yesterday.

    ``dead_for`` drops the campaign's last N days from the report — what
    a platform that omits zero-delivery rows returns for a campaign that
    stopped serving.
    """
    last_reported = TODAY - timedelta(days=1 + lag_days)
    rows = [
        _row(last_reported - timedelta(days=offset), HEALTHY_IMPRESSIONS, campaign_id)
        for offset in reversed(range(HISTORY_DAYS))
    ]
    if dead_for:
        died_on = TODAY - timedelta(days=dead_for)
        rows = [r for r in rows if date.fromisoformat(r.segments.date) < died_on]
    return rows


async def _signals(rows: list[Any], *, consecutive_days: int = 1) -> dict[str, Any]:
    client = _GoogleClient(rows)
    report = await client.get_daily_delivery_report(days=60)
    series = delivery_series_from_rows(report, platform="google_ads")
    signals = detect_delivery_collapses(
        series,
        thresholds=CollapseThresholds(consecutive_days=consecutive_days),
        as_of=TODAY,
    )
    return {s.campaign_id: s for s in signals}


# ---------------------------------------------------------------------------
# The false positive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthy_campaign_whose_latest_day_is_not_yet_reported() -> None:
    """One unreported day must not read as a 100% drop."""
    assert await _signals(_healthy_rows(lag_days=1)) == {}


@pytest.mark.asyncio
async def test_healthy_campaign_with_a_two_day_reporting_lag() -> None:
    """A batch delay, a weekend or a holiday boundary is two days.

    Raising ``consecutive_days`` to 2 does not close this — the second
    unreported day simply produces ``days_at_collapse=2``.
    """
    assert await _signals(_healthy_rows(lag_days=2)) == {}
    assert await _signals(_healthy_rows(lag_days=2), consecutive_days=2) == {}


@pytest.mark.parametrize("lag_days", LAGS)
@pytest.mark.parametrize("consecutive_days", CONSECUTIVE)
@pytest.mark.asyncio
async def test_lag_matrix_is_silent_on_a_healthy_account(
    lag_days: int, consecutive_days: int
) -> None:
    """Safe at DEFAULT settings, across the whole lag x threshold matrix.

    A guardrail that needs an undocumented opt-in to avoid false alarms
    is not shipped, it is armed.
    """
    found = await _signals(
        _healthy_rows(lag_days=lag_days), consecutive_days=consecutive_days
    )

    assert found == {}, (
        f"reporting lag of {lag_days} day(s) fired at "
        f"consecutive_days={consecutive_days}"
    )


# ---------------------------------------------------------------------------
# ...without giving back the hole it was closing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lag_days", LAGS)
@pytest.mark.asyncio
async def test_a_dead_campaign_is_still_caught_while_the_account_reports(
    lag_days: int,
) -> None:
    """The sparse-rows fix must survive the lag fix.

    A second campaign still reporting is the proof that the platform
    covered those dates, so the silent campaign's missing days are
    genuinely zero and not merely unreported.
    """
    rows = [
        *_healthy_rows(lag_days=lag_days, campaign_id=123, dead_for=10 + lag_days),
        *_healthy_rows(lag_days=lag_days, campaign_id=456),
    ]

    found = await _signals(rows)

    assert "123" in found, f"dead campaign missed at lag={lag_days}"
    assert found["123"].days_at_collapse == 10
    assert "456" not in found


@pytest.mark.asyncio
async def test_interior_gaps_are_zero_even_without_another_campaign() -> None:
    """A gap bracketed by the campaign's own later rows is certain.

    Nothing has to be assumed about the platform: it reported a row after
    the gap, so it covered the gap.
    """
    rows = [
        *[
            _row(TODAY - timedelta(days=offset), HEALTHY_IMPRESSIONS)
            for offset in reversed(range(21, 51))
        ],
        _row(TODAY - timedelta(days=2), HEALTHY_IMPRESSIONS // 100),
    ]

    found = await _signals(rows)

    assert "123" in found
    assert found["123"].collapse_start_date == (TODAY - timedelta(days=20)).isoformat()


# ---------------------------------------------------------------------------
# The residual case, reported rather than hidden
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_silent_account_is_reported_as_unreported_not_as_healthy() -> None:
    """When EVERY campaign stops, nothing proves the platform covered
    those days — a total outage and a reporting failure look identical
    from here, and mureo does not get to guess which.

    So it is surfaced as a fact (``reported_through``) rather than
    swallowed: an account that has reported nothing for days is a finding
    even though it is not a per-campaign collapse signal.
    """
    rows = _healthy_rows(lag_days=6)
    client = _GoogleClient(rows)
    report = await client.get_daily_delivery_report(days=60)
    series = delivery_series_from_rows(report, platform="google_ads")

    assert detect_delivery_collapses(series, as_of=TODAY) == ()
    assert last_reported_day(series) == TODAY - timedelta(days=7)


# ---------------------------------------------------------------------------
# The precondition the report-wide bracket rests on
# ---------------------------------------------------------------------------


def _mixed_frontier_rows() -> list[dict[str, Any]]:
    """Two healthy campaigns whose reports finalise at different times."""
    rows: list[dict[str, Any]] = []
    for campaign_id, lag in (("a_lag0", 0), ("b_lag2", 2)):
        last_reported = TODAY - timedelta(days=1 + lag)
        rows += [
            {
                "campaign_id": campaign_id,
                "campaign_name": campaign_id,
                "status": "ENABLED",
                "date": (last_reported - timedelta(days=offset)).isoformat(),
                "impressions": HEALTHY_IMPRESSIONS,
                "clicks": 3_500,
                "cost": 120_000.0,
            }
            for offset in reversed(range(HISTORY_DAYS))
        ]
    return rows


def test_mixed_reporting_frontiers_break_the_single_fetch_precondition() -> None:
    """Documented hazard, pinned so it cannot surprise anyone quietly.

    The report-wide bracket assumes every campaign in one call was
    fetched together and finalises together. mureo's own Google and Meta
    clients issue a single account-wide query so they satisfy it, but
    ``analysis_delivery_collapse_check`` takes rows an agent assembled.
    Mix two frontiers and the faster campaign's latest date becomes the
    evidence for the slower one, which is then zero-filled and flagged
    while perfectly healthy.

    This asserts the behaviour to keep it *known*, not because it is
    desirable — the remedy is the next test, and the precondition is
    stated in the tool description, the docstring, docs/mcp-server.md and
    /daily-check.
    """
    series = delivery_series_from_rows(_mixed_frontier_rows(), platform="tiktok_ads")
    signals = {s.campaign_id: s for s in detect_delivery_collapses(series, as_of=TODAY)}

    assert "b_lag2" in signals
    assert signals["b_lag2"].days_at_collapse == 2
    assert "a_lag0" not in signals


def test_reported_through_makes_a_mixed_fetch_safe() -> None:
    """The escape hatch: declare the frontier you actually trust.

    The oldest per-campaign last date is the only one every campaign in
    the batch demonstrably reached.
    """
    series = delivery_series_from_rows(
        _mixed_frontier_rows(),
        platform="tiktok_ads",
        reported_through=TODAY - timedelta(days=3),
    )

    assert detect_delivery_collapses(series, as_of=TODAY) == ()


def test_reported_through_does_not_hide_a_real_collapse() -> None:
    """Clamping the frontier costs recency, never the signal itself."""
    rows = [
        *_mixed_frontier_rows(),
        *[
            {
                "campaign_id": "dead",
                "campaign_name": "dead",
                "status": "ENABLED",
                "date": (TODAY - timedelta(days=offset)).isoformat(),
                "impressions": HEALTHY_IMPRESSIONS,
                "clicks": 3_500,
                "cost": 120_000.0,
            }
            for offset in reversed(range(15, 15 + HISTORY_DAYS))
        ],
    ]

    series = delivery_series_from_rows(
        rows, platform="tiktok_ads", reported_through=TODAY - timedelta(days=3)
    )
    signals = {s.campaign_id: s for s in detect_delivery_collapses(series, as_of=TODAY)}

    # Last row TODAY-15, frontier TODAY-3 -> the run is TODAY-14..TODAY-3.
    assert "dead" in signals
    assert signals["dead"].days_at_collapse == 12
    assert "b_lag2" not in signals
