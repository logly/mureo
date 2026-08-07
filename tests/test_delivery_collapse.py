"""Delivery-collapse detection — the inverse of cost_increase_investigate (#546).

The detector's whole value is that it can be left running unattended, so
the tests weight false-positive suppression at least as heavily as
detection: a detector that fires on every weekend gets muted, and a muted
detector is worth nothing.

Marks: unit — pure, no network, no filesystem.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mureo.analysis.delivery_collapse import (
    BASELINE_SOURCE,
    BaselineMethod,
    CollapseSeverity,
    CollapseThresholds,
    DailyDelivery,
    DeliverySeries,
    collapse_thresholds_from_strategy_text,
    delivery_series_from_rows,
    detect_delivery_collapse,
    detect_delivery_collapses,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# The motivating incident: two Display campaigns at ~350k impressions/day
# went to zero while still ENABLED.
NORMAL_IMPRESSIONS = 350_000
NORMAL_COST = 120_000.0
AS_OF = date(2026, 6, 1)  # a Monday; "today", therefore never complete


def _weekday_pattern(day: date) -> int:
    """Weekday ~350k, weekend ~15k — a 96% same-day swing.

    Deliberately steeper than the 90% collapse threshold so an
    all-days baseline WOULD fire on every Saturday. Only a
    weekday-aware baseline survives this.
    """
    return 15_000 if day.weekday() >= 5 else NORMAL_IMPRESSIONS


def _series(
    *,
    days: list[DailyDelivery],
    status: str = "ENABLED",
    end_date: date | None = None,
) -> DeliverySeries:
    return DeliverySeries(
        platform="google_ads",
        campaign_id="c-1",
        campaign_name="Display / Prospecting",
        status=status,
        daily=tuple(days),
        end_date=end_date,
    )


def _flat_history(
    n: int,
    *,
    impressions: int = NORMAL_IMPRESSIONS,
    end: date = AS_OF - timedelta(days=1),
) -> list[DailyDelivery]:
    """``n`` complete days ending at ``end`` (inclusive), all identical."""
    return [
        DailyDelivery(
            date=end - timedelta(days=offset),
            impressions=impressions,
            clicks=impressions // 100,
            cost=NORMAL_COST,
        )
        for offset in reversed(range(n))
    ]


def _weekly_history(
    n: int, *, end: date = AS_OF - timedelta(days=1)
) -> list[DailyDelivery]:
    """``n`` complete days ending at ``end``, following the weekday pattern."""
    out: list[DailyDelivery] = []
    for offset in reversed(range(n)):
        day = end - timedelta(days=offset)
        impressions = _weekday_pattern(day)
        out.append(
            DailyDelivery(
                date=day,
                impressions=impressions,
                clicks=impressions // 100,
                cost=NORMAL_COST * impressions / NORMAL_IMPRESSIONS,
            )
        )
    return out


def _zero_days(n: int, *, end: date = AS_OF - timedelta(days=1)) -> list[DailyDelivery]:
    return [
        DailyDelivery(date=end - timedelta(days=offset), impressions=0, cost=0.0)
        for offset in reversed(range(n))
    ]


# ---------------------------------------------------------------------------
# Detection — the signal we exist to raise
# ---------------------------------------------------------------------------


def test_enabled_campaign_whose_impressions_went_to_zero_is_detected() -> None:
    """The motivating incident: ENABLED, ~350k/day, then zero."""
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    series = _series(days=[*history, *_zero_days(1)])

    signal = detect_delivery_collapse(series, as_of=AS_OF)

    assert signal is not None
    assert signal.campaign_id == "c-1"
    assert signal.severity is CollapseSeverity.CRITICAL
    assert signal.current_impressions == 0
    assert signal.baseline_impressions == pytest.approx(NORMAL_IMPRESSIONS)
    assert signal.drop_pct == pytest.approx(100.0)
    assert signal.days_at_collapse == 1
    assert signal.collapse_start_date == (AS_OF - timedelta(days=1)).isoformat()


def test_multi_day_collapse_reports_the_full_run_and_its_start() -> None:
    """Detection ~1.5 days late in the incident; a week of zeros must
    still report the cliff date rather than only 'today is zero'."""
    history = _flat_history(28, end=AS_OF - timedelta(days=7))
    series = _series(days=[*history, *_zero_days(6)])

    signal = detect_delivery_collapse(series, as_of=AS_OF)

    assert signal is not None
    assert signal.days_at_collapse == 6
    assert signal.collapse_start_date == (AS_OF - timedelta(days=6)).isoformat()
    # The baseline must be the pre-cliff normal, not dragged down by the
    # zero days that follow it.
    assert signal.baseline_impressions == pytest.approx(NORMAL_IMPRESSIONS)


def test_a_collapse_longer_than_the_baseline_window_is_still_detected() -> None:
    """The failure mode that silences a detector exactly when it matters.

    If each day were judged against the window immediately preceding it,
    a collapse that outlives half the 28-day window would drag that
    window's median to zero — nothing would look like a drop any more and
    the alert would stop. The baseline must come from before the cliff.
    """
    history = _flat_history(28, end=AS_OF - timedelta(days=21))
    series = _series(days=[*history, *_zero_days(20)])

    signal = detect_delivery_collapse(series, as_of=AS_OF)

    assert signal is not None
    assert signal.days_at_collapse == 20
    assert signal.baseline_impressions == pytest.approx(NORMAL_IMPRESSIONS)
    assert signal.collapse_start_date == (AS_OF - timedelta(days=20)).isoformat()


def test_severe_but_nonzero_drop_is_high_not_critical() -> None:
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    crashed = DailyDelivery(
        date=AS_OF - timedelta(days=1), impressions=5_000, clicks=40, cost=1_500.0
    )
    series = _series(days=[*history, crashed])

    signal = detect_delivery_collapse(series, as_of=AS_OF)

    assert signal is not None
    assert signal.severity is CollapseSeverity.HIGH
    assert signal.drop_pct == pytest.approx(100 * (1 - 5_000 / NORMAL_IMPRESSIONS))


# ---------------------------------------------------------------------------
# False positives — the reason a detector survives contact with operators
# ---------------------------------------------------------------------------


def test_weekend_dip_is_not_flagged() -> None:
    """A 96% Saturday dip on a weekday/weekend account is normal.

    The baseline has to be weekday-aware; an all-days median would make
    every Saturday a CRITICAL alert and the operator would mute the
    detector by the second weekend.
    """
    # 35 complete days ending on a Saturday.
    saturday = date(2026, 5, 30)
    assert saturday.weekday() == 5
    series = _series(days=_weekly_history(35, end=saturday))

    assert detect_delivery_collapse(series, as_of=saturday + timedelta(days=1)) is None


def test_weekend_baseline_still_catches_a_real_saturday_collapse() -> None:
    """Weekday-awareness must not blind the detector on weekends."""
    saturday = date(2026, 5, 30)
    history = _weekly_history(34, end=saturday - timedelta(days=1))
    series = _series(
        days=[*history, DailyDelivery(date=saturday, impressions=0, cost=0.0)]
    )

    signal = detect_delivery_collapse(series, as_of=saturday + timedelta(days=1))

    assert signal is not None
    assert signal.baseline_method is BaselineMethod.SAME_WEEKDAY_MEDIAN
    # ~15k, the Saturday norm — not the ~350k weekday norm.
    assert signal.baseline_impressions == pytest.approx(15_000)


def test_partial_current_day_is_never_evaluated() -> None:
    """Today is half-elapsed by definition; budget pacing means the
    day's impressions arrive unevenly. Only complete days count."""
    history = _flat_history(28, end=AS_OF - timedelta(days=1))
    partial_today = DailyDelivery(
        date=AS_OF, impressions=4_000, clicks=30, cost=1_200.0
    )
    series = _series(days=[*history, partial_today])

    assert detect_delivery_collapse(series, as_of=AS_OF) is None


def test_ordinary_daily_variation_is_not_flagged() -> None:
    """Budget-pacing swings of 40% are ad ops, not an outage."""
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    slow_day = DailyDelivery(
        date=AS_OF - timedelta(days=1),
        impressions=int(NORMAL_IMPRESSIONS * 0.4),
        clicks=1_400,
        cost=48_000.0,
    )
    series = _series(days=[*history, slow_day])

    assert detect_delivery_collapse(series, as_of=AS_OF) is None


def test_paused_campaign_is_not_flagged() -> None:
    """An intentional pause is not a fault. The status-says-serving
    contradiction IS the signal."""
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    series = _series(days=[*history, *_zero_days(1)], status="PAUSED")

    assert detect_delivery_collapse(series, as_of=AS_OF) is None


def test_campaign_past_its_end_date_is_not_flagged() -> None:
    """A finished flight stops serving while its status stays ENABLED."""
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    series = _series(
        days=[*history, *_zero_days(1)],
        end_date=AS_OF - timedelta(days=2),
    )

    assert detect_delivery_collapse(series, as_of=AS_OF) is None


def test_low_volume_campaign_is_not_flagged() -> None:
    """A campaign averaging 80 impressions/day hits zero routinely."""
    history = _flat_history(28, impressions=80, end=AS_OF - timedelta(days=2))
    series = _series(days=[*history, *_zero_days(1)])

    assert detect_delivery_collapse(series, as_of=AS_OF) is None


def test_thin_history_yields_no_signal() -> None:
    """A campaign three days old has no baseline to fall off."""
    history = _flat_history(3, end=AS_OF - timedelta(days=2))
    series = _series(days=[*history, *_zero_days(1)])

    assert detect_delivery_collapse(series, as_of=AS_OF) is None


def test_campaign_that_never_delivered_is_not_flagged() -> None:
    series = _series(days=_zero_days(30))

    assert detect_delivery_collapse(series, as_of=AS_OF) is None


# ---------------------------------------------------------------------------
# Baseline provenance — must be the platform's own delivery data
# ---------------------------------------------------------------------------


def test_baseline_is_taken_from_platform_delivery_data() -> None:
    """The generic anomaly path baselines off ``action_log``, which is
    empty on hand-operated accounts. This detector never reads it: the
    only input is the platform's own daily delivery series."""
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    series = _series(days=[*history, *_zero_days(1)])

    signal = detect_delivery_collapse(series, as_of=AS_OF)

    assert signal is not None
    assert signal.baseline_source == BASELINE_SOURCE == "platform_daily_delivery"
    assert signal.baseline_days_used == 28


def test_baseline_is_a_median_so_one_outlier_day_cannot_move_it() -> None:
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    # One freak day at 20x — a mean baseline would be inflated by ~68%.
    history[10] = DailyDelivery(
        date=history[10].date, impressions=NORMAL_IMPRESSIONS * 20, cost=NORMAL_COST
    )
    series = _series(days=[*history, *_zero_days(1)])

    signal = detect_delivery_collapse(series, as_of=AS_OF)

    assert signal is not None
    assert signal.baseline_impressions == pytest.approx(NORMAL_IMPRESSIONS)


def test_detector_signature_takes_no_action_log() -> None:
    """Structural pin: the entry point accepts a series and thresholds
    only. Re-introducing an ``action_log`` parameter would silently
    reinstate the empty-history failure mode this issue is about."""
    import inspect

    params = set(inspect.signature(detect_delivery_collapse).parameters)
    assert params == {"series", "thresholds", "as_of"}


# ---------------------------------------------------------------------------
# Thresholds from STRATEGY.md ## Guardrails
# ---------------------------------------------------------------------------


def test_thresholds_default_when_strategy_has_no_guardrails() -> None:
    assert (
        collapse_thresholds_from_strategy_text("# Strategy\n") == CollapseThresholds()
    )


def test_thresholds_are_read_from_the_guardrails_section() -> None:
    text = (
        "# Strategy\n\n"
        "## Guardrails\n"
        "- max_daily_budget_per_campaign: 50000\n"
        "- delivery_collapse_drop_pct: 70\n"
        "- delivery_collapse_min_baseline_impressions: 200\n"
        "- delivery_collapse_baseline_days: 14\n"
        "- delivery_collapse_consecutive_days: 2\n"
    )

    thresholds = collapse_thresholds_from_strategy_text(text)

    assert thresholds.drop_pct == pytest.approx(70.0)
    assert thresholds.min_baseline_impressions == 200
    assert thresholds.baseline_days == 14
    assert thresholds.consecutive_days == 2


def test_malformed_guardrail_value_keeps_that_default() -> None:
    text = "## Guardrails\n- delivery_collapse_drop_pct: quite a lot\n"

    thresholds = collapse_thresholds_from_strategy_text(text)

    assert thresholds.drop_pct == CollapseThresholds().drop_pct


def test_out_of_range_guardrail_value_keeps_that_default() -> None:
    text = "## Guardrails\n- delivery_collapse_drop_pct: 250\n"

    assert (
        collapse_thresholds_from_strategy_text(text).drop_pct
        == CollapseThresholds().drop_pct
    )


def test_consecutive_days_guardrail_delays_the_alert() -> None:
    """An operator who wants two days of confirmation gets two days."""
    thresholds = CollapseThresholds(consecutive_days=2)
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    one_day = _series(days=[*history, *_zero_days(1)])

    assert detect_delivery_collapse(one_day, thresholds=thresholds, as_of=AS_OF) is None

    history2 = _flat_history(28, end=AS_OF - timedelta(days=3))
    two_days = _series(days=[*history2, *_zero_days(2)])
    assert (
        detect_delivery_collapse(two_days, thresholds=thresholds, as_of=AS_OF)
        is not None
    )


# ---------------------------------------------------------------------------
# Batch + normalisation
# ---------------------------------------------------------------------------


def test_detect_delivery_collapses_orders_critical_first() -> None:
    history = _flat_history(28, end=AS_OF - timedelta(days=2))
    dead = DeliverySeries(
        platform="google_ads",
        campaign_id="dead",
        campaign_name="Dead",
        status="ENABLED",
        daily=tuple([*history, *_zero_days(1)]),
    )
    dying = DeliverySeries(
        platform="google_ads",
        campaign_id="dying",
        campaign_name="Dying",
        status="ENABLED",
        daily=tuple(
            [
                *history,
                DailyDelivery(date=AS_OF - timedelta(days=1), impressions=5_000),
            ]
        ),
    )
    healthy = DeliverySeries(
        platform="google_ads",
        campaign_id="healthy",
        campaign_name="Healthy",
        status="ENABLED",
        daily=tuple(_flat_history(29, end=AS_OF - timedelta(days=1))),
    )

    signals = detect_delivery_collapses([dying, healthy, dead], as_of=AS_OF)

    assert [s.campaign_id for s in signals] == ["dead", "dying"]


def test_delivery_series_from_rows_normalises_a_platform_report() -> None:
    """The shared entry point for hosted connectors and bridges: any
    platform that can produce day-grain rows gets the same detector."""
    rows = [
        {
            "campaign_id": "42",
            "campaign_name": "Amazon SP / Brand",
            "status": "ENABLED",
            "date": "2026-05-30",
            "impressions": 1200,
            "clicks": 40,
            "cost": 900.5,
        },
        {
            "campaign_id": "42",
            "campaign_name": "Amazon SP / Brand",
            "status": "ENABLED",
            "date": "2026-05-31",
            "impressions": 0,
            "clicks": 0,
            "cost": 0,
        },
    ]

    series = delivery_series_from_rows(rows, platform="plugin:acme:amazon_ads")

    assert len(series) == 1
    assert series[0].platform == "plugin:acme:amazon_ads"
    assert series[0].campaign_id == "42"
    assert series[0].status == "ENABLED"
    assert [d.date for d in series[0].daily] == [date(2026, 5, 30), date(2026, 5, 31)]
    assert series[0].daily[1].impressions == 0


def test_delivery_series_from_rows_rejects_rows_without_a_campaign() -> None:
    rows = [{"date": "2026-05-30", "impressions": 5}]

    assert delivery_series_from_rows(rows, platform="tiktok_ads") == ()


def test_delivery_series_from_rows_rejects_an_unparseable_date() -> None:
    rows = [{"campaign_id": "1", "date": "not-a-date", "impressions": 5}]

    with pytest.raises(ValueError, match="date"):
        delivery_series_from_rows(rows, platform="tiktok_ads")
