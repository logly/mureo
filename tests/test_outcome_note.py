"""Reading a row note back into parts (mureo.analysis.outcome_note, #894).

Every note here is built by the real builders — ``evaluate_metric``,
``evaluate_outcome`` and ``build_evaluation`` — and read back with
:func:`note_parts`, so the two sides cannot drift apart unnoticed. A string
neither builder writes reads as ``None``.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.analysis.expected_eval import build_evaluation
from mureo.analysis.outcome_eval import (
    BASIS_EXPECTED,
    GATE_REASONS,
    NOTE_HELD_BACK,
    REASON_INSUFFICIENT_VOLUME,
    REASON_NO_PRIMARY_METRIC,
    REASON_PERIOD_UNKNOWN,
    REASON_VOLUME_UNKNOWN,
    REASON_ZERO_BASELINE,
    OutcomeThresholds,
    PrimaryChoice,
    evaluate_metric,
    evaluate_outcome,
)
from mureo.analysis.outcome_note import note_parts
from mureo.context.expected import ExpectedEffect

pytestmark = pytest.mark.unit

#: Enough volume on both sides for every gate.
VOLUME = {"conversions": 100, "impressions": 50_000, "clicks": 5_000}
WEEK = {"days": 7}


def _parts(**overrides: Any) -> dict[str, Any]:
    """The full shape, every key present, with ``overrides`` applied."""
    base: dict[str, Any] = {
        "kind": None,
        "direction": None,
        "noise_pct": None,
        "per_day": None,
        "raw_totals": False,
        "held_back": None,
        "target": None,
        "zero_baseline": False,
    }
    return {**base, **overrides}


def _rows(
    before: dict[str, Any],
    after: dict[str, Any],
    expected: list[ExpectedEffect] | None = None,
    thresholds: OutcomeThresholds | None = None,
) -> dict[str, dict[str, Any]]:
    extra = {} if thresholds is None else {"thresholds": thresholds}
    result = build_evaluation(
        before, after, expected or [], window_from=None, window_to=None, **extra
    )
    return {row["metric"]: row for row in result.table["metrics"]}


def _note_of(report_metrics: Any, metric: str) -> str:
    return str(next(o.note for o in report_metrics if o.metric == metric))


class TestMetricNotes:
    """The four notes :func:`evaluate_metric` writes."""

    def test_the_noise_band(self) -> None:
        note = evaluate_metric("cpa", 100, 105, noise_pct=12.5).note
        assert note_parts(note) == _parts(kind="band", noise_pct=12.5)

    @pytest.mark.parametrize(
        ("metric", "after", "direction"),
        [("cpa", 80, "lower_is_better"), ("ctr", 130, "higher_is_better")],
    )
    def test_a_direction(self, metric: str, after: float, direction: str) -> None:
        note = evaluate_metric(metric, 100, after).note
        assert note_parts(note) == _parts(kind="direction", direction=direction)

    def test_a_large_move_in_exponent_form(self) -> None:
        note = evaluate_metric("ctr", 0.0001, 500).note
        assert "e+" in note
        assert note_parts(note) == _parts(
            kind="direction", direction="higher_is_better"
        )

    def test_a_volume_metric(self) -> None:
        note = evaluate_metric("spend", 100, 200).note
        assert note_parts(note) == _parts(kind="neutral")

    def test_a_zero_baseline(self) -> None:
        note = evaluate_metric("cpa", 0, 80).note
        assert note_parts(note) == _parts(kind="zero_baseline", zero_baseline=True)


class TestReportNotes:
    """The suffixes and the held-back lead :func:`evaluate_outcome` adds."""

    def test_per_day(self) -> None:
        report = evaluate_outcome(
            {**VOLUME, "cpa": 100, "days": 7}, {**VOLUME, "cpa": 80, "days": 14}
        )
        note = _note_of(report.metrics, "clicks")
        assert note_parts(note) == _parts(
            kind="neutral", per_day={"before_days": 7, "after_days": 14}
        )

    def test_raw_totals(self) -> None:
        report = evaluate_outcome({**VOLUME, "cpa": 100}, {**VOLUME, "cpa": 80})
        note = _note_of(report.metrics, "conversions")
        assert note_parts(note) == _parts(kind="band", noise_pct=10.0, raw_totals=True)

    @pytest.mark.parametrize(
        ("before", "after", "reason"),
        [
            (
                {"cpa": 100, "conversions": 10},
                {"cpa": 80, "conversions": 45},
                REASON_INSUFFICIENT_VOLUME,
            ),
            ({"cpa": 100}, {"cpa": 80}, REASON_VOLUME_UNKNOWN),
        ],
    )
    def test_a_volume_gate_leads_the_primary_note(
        self, before: dict[str, Any], after: dict[str, Any], reason: str
    ) -> None:
        choice = PrimaryChoice(metric="cpa", basis=BASIS_EXPECTED, effect=None)
        report = evaluate_outcome(before, after, primary=choice)
        assert report.reason == reason
        assert reason in GATE_REASONS
        assert note_parts(_note_of(report.metrics, "cpa")) == _parts(
            kind="direction", direction="lower_is_better", held_back=reason
        )

    def test_a_period_gate_leads_the_primary_note(self) -> None:
        rows = _rows({"spend": 100}, {"spend": 180}, [ExpectedEffect("spend", "up")])
        assert note_parts(rows["spend"]["note"]) == _parts(
            kind="neutral", raw_totals=True, held_back=REASON_PERIOD_UNKNOWN
        )

    def test_a_zero_baseline_leads_the_primary_note(self) -> None:
        rows = _rows(
            {"spend": 0, **WEEK},
            {"spend": 50, **WEEK},
            [ExpectedEffect("spend", "up", target=100)],
        )
        assert note_parts(rows["spend"]["note"]) == _parts(
            kind="zero_baseline",
            per_day={"before_days": 7, "after_days": 7},
            held_back=REASON_ZERO_BASELINE,
            zero_baseline=True,
        )

    def test_no_primary_metric_through_the_builder_template(self) -> None:
        # No builder path leads a row with this code (there is no primary
        # row to lead), but the lead accepts every reason, so it is read.
        note = NOTE_HELD_BACK.format(
            reason=REASON_NO_PRIMARY_METRIC, note=evaluate_metric("cpa", 100, 80).note
        )
        assert note_parts(note) == _parts(
            kind="direction",
            direction="lower_is_better",
            held_back=REASON_NO_PRIMARY_METRIC,
        )


class TestExpectedNotes:
    """The notes :func:`build_evaluation` writes for a declared primary."""

    @pytest.mark.parametrize(
        ("direction", "after"), [("up", 1.3), ("down", 0.7), ("hold", 1.02)]
    )
    def test_each_direction(self, direction: str, after: float) -> None:
        rows = _rows(
            {**VOLUME, "ctr": 1.0},
            {**VOLUME, "ctr": after},
            [ExpectedEffect("ctr", direction)],
        )
        assert note_parts(rows["ctr"]["note"]) == _parts(
            kind="expected", direction=direction, noise_pct=10.0
        )

    def test_a_custom_noise_band(self) -> None:
        thresholds = OutcomeThresholds(
            noise_pct=7.5, min_conversions=1, min_impressions=1, min_clicks=1
        )
        rows = _rows(
            {**VOLUME, "ctr": 1.0},
            {**VOLUME, "ctr": 1.3},
            [ExpectedEffect("ctr", "up")],
            thresholds,
        )
        assert note_parts(rows["ctr"]["note"]) == _parts(
            kind="expected", direction="up", noise_pct=7.5
        )

    def test_per_day_and_a_missed_target_with_its_window_total(self) -> None:
        rows = _rows(
            {"spend": 100, **WEEK},
            {"spend": 180, **WEEK},
            [ExpectedEffect("spend", "up", target=1000)],
        )
        assert note_parts(rows["spend"]["note"]) == _parts(
            kind="expected",
            direction="up",
            noise_pct=10.0,
            per_day={"before_days": 7, "after_days": 7},
            target={"value": 1000.0, "reached": False, "window_total": 180.0},
        )

    def test_a_reached_target_on_a_ratio(self) -> None:
        rows = _rows(
            {**VOLUME, "cpa": 100},
            {**VOLUME, "cpa": 55},
            [ExpectedEffect("cpa", "down", target=60)],
        )
        assert note_parts(rows["cpa"]["note"]) == _parts(
            kind="expected",
            direction="down",
            noise_pct=10.0,
            target={"value": 60.0, "reached": True, "window_total": None},
        )

    def test_a_missed_target_on_a_ratio(self) -> None:
        rows = _rows(
            {**VOLUME, "cpa": 100},
            {**VOLUME, "cpa": 70},
            [ExpectedEffect("cpa", "down", target=60)],
        )
        assert note_parts(rows["cpa"]["note"]) == _parts(
            kind="expected",
            direction="down",
            noise_pct=10.0,
            target={"value": 60.0, "reached": False, "window_total": None},
        )

    def test_a_target_reached_from_a_zero_baseline(self) -> None:
        # The note carries the zero-baseline row inside it; the target
        # decided, so the parts say what was intended, that the change could
        # not be compared, and what was reached.
        rows = _rows(
            {"spend": 0, **WEEK},
            {"spend": 500, **WEEK},
            [ExpectedEffect("spend", "up", target=100)],
        )
        assert note_parts(rows["spend"]["note"]) == _parts(
            kind="expected",
            direction="up",
            per_day={"before_days": 7, "after_days": 7},
            target={"value": 100.0, "reached": True, "window_total": 500.0},
            zero_baseline=True,
        )

    def test_a_scored_expected_note_is_not_a_zero_baseline(self) -> None:
        rows = _rows(
            {"spend": 100, **WEEK},
            {"spend": 1300, **WEEK},
            [ExpectedEffect("spend", "up", target=1_000_000)],
        )
        parts = note_parts(rows["spend"]["note"])
        assert parts is not None
        assert parts["zero_baseline"] is False
        assert parts["noise_pct"] == 10.0

    def test_a_move_outside_the_band_names_the_band_it_was_judged_with(
        self,
    ) -> None:
        note = (
            "expected up; +30% (noise band ±10%); per day over 7d / 7d; "
            "target 1e+06 not reached (window total 1300)"
        )
        assert note_parts(note) == _parts(
            kind="expected",
            direction="up",
            noise_pct=10.0,
            per_day={"before_days": 7, "after_days": 7},
            target={"value": 1_000_000.0, "reached": False, "window_total": 1300.0},
        )

    def test_the_stored_zero_baseline_form(self) -> None:
        note = (
            "expected up; zero_baseline; baseline is zero/absent; change is not "
            "comparable; per day over 7d / 7d; target 1000 reached "
            "(window total 5000)"
        )
        assert note_parts(note) == _parts(
            kind="expected",
            direction="up",
            per_day={"before_days": 7, "after_days": 7},
            target={"value": 1000.0, "reached": True, "window_total": 5000.0},
            zero_baseline=True,
        )


class TestUnreadable:
    @pytest.mark.parametrize(
        "note",
        [
            "",
            "expected down",
            "moved a lot",
            "expected down; moved up",
            "within 10% noise band",
            "lower_is_better",
            "lower_is_better; -20%; trailing",
            "expected sideways; +5% (noise band ±10%)",
            "expected up; lower_is_better; -20%",
            "lower_is_better; -20%; target 5 reached",
            "within ±10% noise band; per day over 7d / 7",
        ],
    )
    def test_a_string_no_builder_writes(self, note: str) -> None:
        assert note_parts(note) is None

    def test_an_unknown_lead_reason(self) -> None:
        note = NOTE_HELD_BACK.format(
            reason="not_a_reason", note=evaluate_metric("cpa", 100, 80).note
        )
        assert note_parts(note) is None

    @pytest.mark.parametrize("value", [None, 5, ["within ±10% noise band"]])
    def test_not_a_string(self, value: Any) -> None:
        assert note_parts(value) is None
