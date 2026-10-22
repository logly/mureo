"""The evaluation table (#848, rules 2 since #888): stored on ``outcome_evaluated``.

Before ops history the automatic closure kept a one-line summary; the
figures it judged on were thrown away. These tests pin the table's shape,
that ONE primary metric decides (a declared one first, then the campaign's
bidding target, then cpa), the hold / target rules, and that the closure
entry inherits the evaluated action's ``decision_id``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.expected_eval import (
    RULES_VERSION,
    build_evaluation,
    choose_primary,
)
from mureo.analysis.outcome_eval import evaluate_outcome
from mureo.context.auto_evaluation import close_due_observations
from mureo.context.expected import ExpectedEffect, parse_expected
from mureo.context.state import read_state_file

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)

#: Enough volume on both sides for every gate.
VOLUME: dict[str, Any] = {"conversions": 100, "impressions": 50_000, "clicks": 5_000}


def _rows(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["metric"]: row for row in table["metrics"]}


def _one(metric: str, direction: str, **extra: Any) -> tuple[ExpectedEffect, ...]:
    return parse_expected([{"metric": metric, "direction": direction, **extra}])


class TestBuildEvaluationWithoutExpected:
    def test_the_shape(self) -> None:
        result = build_evaluation(
            {"cpa": 10000, "conversions": 50, "cost": 100},
            {"cpa": 5000, "conversions": 100, "cost": 100},
            (),
            window_from="2026-09-01",
            window_to="2026-09-18",
        )
        table = result.table
        assert set(table) == {
            "rules",
            "overall",
            "basis",
            "primary",
            "noise_pct",
            "window",
            "metrics",
        }
        assert table["rules"] == RULES_VERSION == 2
        assert table["window"] == {"from": "2026-09-01", "to": "2026-09-18"}
        assert table["basis"] == "default"
        assert table["primary"] == "cpa"
        assert table["noise_pct"] == 10.0
        row = _rows(table)["cpa"]
        assert set(row) == {
            "metric",
            "before",
            "after",
            "delta_pct",
            "verdict",
            "note",
            "role",
        }

    def test_the_verdict_matches_the_evaluator(self) -> None:
        before = {"cpa": 10000, "conversions": 50}
        after = {"cpa": 12000, "conversions": 100}
        result = build_evaluation(before, after, (), window_from=None, window_to=None)
        report = evaluate_outcome(before, after)
        assert result.overall == report.overall.value == "regressed"
        assert result.summary == report.summary
        assert result.table["overall"] == report.overall.value

    def test_only_the_primary_is_primary(self) -> None:
        result = build_evaluation(
            {"cpa": 100, "ctr": 2.0, "clicks": 10, **VOLUME},
            {"cpa": 100, "ctr": 1.0, "clicks": 50, **VOLUME},
            (),
            window_from=None,
            window_to=None,
        )
        rows = _rows(result.table)
        assert rows["cpa"]["role"] == "primary"
        assert rows["ctr"]["role"] == "reference"
        assert rows["clicks"]["role"] == "reference"

    def test_cpa_down_and_ctr_down_is_improved(self) -> None:
        result = build_evaluation(
            {"cpa": 5000, "ctr": 2.0, **VOLUME},
            {"cpa": 3500, "ctr": 1.78, **VOLUME},
            (),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "improved"
        assert _rows(result.table)["ctr"]["verdict"] == "regressed"

    def test_an_inconclusive_table_names_its_reason(self) -> None:
        result = build_evaluation(
            {"cpa": 5000, "conversions": 3},
            {"cpa": 7500, "conversions": 2},
            (),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "inconclusive"
        assert result.table["reason"] == "insufficient_volume"
        assert result.summary == "Inconclusive: insufficient_volume on cpa."
        cpa = _rows(result.table)["cpa"]
        assert cpa["verdict"] == "inconclusive"
        assert "insufficient_volume" in cpa["note"]

    def test_no_primary_metric(self) -> None:
        result = build_evaluation(
            {"ctr": 2.0}, {"ctr": 3.0}, (), window_from=None, window_to=None
        )
        assert result.table["primary"] is None
        assert result.table["reason"] == "no_primary_metric"
        assert result.scored == 1


class TestBuildEvaluationWithExpected:
    def test_an_expected_metric_is_primary_and_decides(self) -> None:
        # CPA got worse, but the declared expectation was spend UP — which
        # happened. The verdict is on what the change was meant to do.
        result = build_evaluation(
            {"cpa": 100, "cost": 1000, "days": 7, **VOLUME},
            {"cpa": 130, "cost": 1500, "days": 7, **VOLUME},
            _one("cost", "up"),
            window_from=None,
            window_to=None,
        )
        rows = _rows(result.table)
        assert rows["spend"]["role"] == "primary"
        assert rows["spend"]["verdict"] == "improved"
        assert rows["cpa"]["role"] == "reference"
        assert rows["cpa"]["verdict"] == "regressed"
        assert result.overall == "improved"
        assert result.table["basis"] == "expected"
        assert result.table["primary"] == "spend"
        assert result.summary == "Improved on spend (primary)."

    def test_a_budget_cut_is_judged_on_spend_per_day(self) -> None:
        # Spend down as intended; conversions fell with it. The 7-day
        # baseline against a 30-day snapshot is compared per day.
        result = build_evaluation(
            {"spend": 7000, "conversions": 70, "days": 7},
            {"spend": 18000, "conversions": 240, "period": "LAST_30_DAYS"},
            _one("spend", "down"),
            window_from=None,
            window_to=None,
        )
        spend = _rows(result.table)["spend"]
        assert (spend["before"], spend["after"]) == (1000.0, 600.0)
        assert spend["delta_pct"] == -40.0
        assert spend["verdict"] == "improved"
        assert _rows(result.table)["conversions"]["verdict"] == "regressed"
        assert result.overall == "improved"

    def test_a_count_primary_without_day_counts_is_period_unknown(self) -> None:
        result = build_evaluation(
            {"cost": 1000},
            {"cost": 1500},
            _one("cost", "up"),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "inconclusive"
        assert result.table["reason"] == "period_unknown"
        assert result.table["primary"] == "spend"
        spend = _rows(result.table)["spend"]
        assert spend["verdict"] == "inconclusive"
        assert "period_unknown" in spend["note"]

    @pytest.mark.parametrize(
        ("direction", "after", "verdict"),
        [
            ("down", 80, "improved"),
            ("down", 120, "regressed"),
            ("down", 95, "inconclusive"),
            ("up", 120, "improved"),
            ("up", 80, "regressed"),
            ("hold", 95, "held"),
            ("hold", 130, "regressed"),
            ("hold", 75, "regressed"),
        ],
    )
    def test_each_direction(self, direction: str, after: float, verdict: str) -> None:
        result = build_evaluation(
            {"cpa": 100, **VOLUME},
            {"cpa": after, **VOLUME},
            _one("cpa", direction),
            window_from=None,
            window_to=None,
        )
        assert _rows(result.table)["cpa"]["verdict"] == verdict
        assert result.overall == verdict

    def test_inside_the_band_is_no_change(self) -> None:
        result = build_evaluation(
            {"cpa": 100, **VOLUME},
            {"cpa": 95, **VOLUME},
            _one("cpa", "down"),
            window_from=None,
            window_to=None,
        )
        assert result.table["reason"] == "no_change"

    def test_hold_is_held(self) -> None:
        result = build_evaluation(
            {"cpa": 100, **VOLUME},
            {"cpa": 104, **VOLUME},
            _one("cpa", "hold"),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "held"
        assert "reason" not in result.table
        assert result.summary == "Held cpa within the noise band."

    def test_a_target_is_reported_in_the_note(self) -> None:
        result = build_evaluation(
            {"cpa": 100, **VOLUME},
            {"cpa": 80, **VOLUME},
            _one("cpa", "down", target=85),
            window_from=None,
            window_to=None,
        )
        assert "target 85 reached" in _rows(result.table)["cpa"]["note"]
        assert result.overall == "improved"

    def test_a_target_reached_inside_the_band_is_improved(self) -> None:
        result = build_evaluation(
            {"cpa": 100, **VOLUME},
            {"cpa": 96, **VOLUME},
            _one("cpa", "down", target=97),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "improved"

    def test_a_target_missed_in_the_right_direction_is_not_reached(self) -> None:
        result = build_evaluation(
            {"cpa": 100, **VOLUME},
            {"cpa": 70, **VOLUME},
            _one("cpa", "down", target=60),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "inconclusive"
        assert result.table["reason"] == "target_not_reached"
        assert result.summary == "Inconclusive: target_not_reached on cpa."
        assert "target 60 not reached" in _rows(result.table)["cpa"]["note"]

    def test_a_target_missed_in_the_wrong_direction_is_regressed(self) -> None:
        result = build_evaluation(
            {"cpa": 100, **VOLUME},
            {"cpa": 130, **VOLUME},
            _one("cpa", "down", target=60),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "regressed"

    @pytest.mark.parametrize(
        ("after", "verdict"), [(4100, "held"), (5000, "regressed")]
    )
    def test_hold_with_a_target_is_judged_around_the_target(
        self, after: float, verdict: str
    ) -> None:
        result = build_evaluation(
            {"cpa": 4500, **VOLUME},
            {"cpa": after, **VOLUME},
            _one("cpa", "hold", target=4000),
            window_from=None,
            window_to=None,
        )
        assert result.overall == verdict

    def test_a_zero_baseline_names_its_reason(self) -> None:
        result = build_evaluation(
            {"cpa": 0, **VOLUME},
            {"cpa": 80, **VOLUME},
            _one("cpa", "down"),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "inconclusive"
        assert result.table["reason"] == "zero_baseline"
        assert result.summary == "Inconclusive: zero_baseline on cpa."
        cpa = _rows(result.table)["cpa"]
        assert cpa["verdict"] == "inconclusive"
        assert "zero_baseline" in cpa["note"]

    def test_a_reached_target_under_the_volume_floor_is_not_improved(self) -> None:
        # 0 -> 45 conversions reaches the target of 40, but the baseline
        # side is under the 30-conversion floor: the row must not say
        # improved while the table says inconclusive.
        result = build_evaluation(
            {"conversions": 0, "days": 7},
            {"conversions": 45, "days": 7},
            _one("conversions", "up", target=40),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "inconclusive"
        assert result.table["reason"] == "insufficient_volume"
        row = _rows(result.table)["conversions"]
        assert row["verdict"] == "inconclusive"
        assert "insufficient_volume" in row["note"]

    def test_a_target_is_still_judged_against_a_zero_baseline(self) -> None:
        result = build_evaluation(
            {"spend": 0, "days": 7},
            {"spend": 12000, "days": 30},
            _one("spend", "up", target=10000),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "improved"
        assert "reason" not in result.table

    def test_a_count_target_is_the_window_total(self) -> None:
        # 1,000 a day before, 1,033 a day after: inside the band per day,
        # but the 31,000 the window spent reaches the 10,000 target.
        result = build_evaluation(
            {"spend": 7000, "days": 7},
            {"spend": 31000, "days": 30},
            _one("spend", "up", target=10000),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "improved"
        note = _rows(result.table)["spend"]["note"]
        assert "target 10000 reached (window total 31000)" in note

    def test_a_count_target_missed_by_the_window_total(self) -> None:
        result = build_evaluation(
            {"spend": 7000, "days": 7},
            {"spend": 45000, "days": 30},
            _one("spend", "up", target=50000),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "inconclusive"
        assert result.table["reason"] == "target_not_reached"
        note = _rows(result.table)["spend"]["note"]
        assert "target 50000 not reached (window total 45000)" in note

    def test_hold_with_a_target_on_a_count_reads_the_window_total(self) -> None:
        result = build_evaluation(
            {"spend": 30000, "days": 30},
            {"spend": 29500, "days": 30},
            _one("spend", "hold", target=30000),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "held"

    def test_the_volume_gate_still_applies_to_an_expected_primary(self) -> None:
        result = build_evaluation(
            {"cpa": 100, "conversions": 3},
            {"cpa": 50, "conversions": 4},
            _one("cpa", "down"),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "inconclusive"
        assert result.table["reason"] == "insufficient_volume"
        assert result.table["basis"] == "expected"
        cpa = _rows(result.table)["cpa"]
        assert cpa["verdict"] == "inconclusive"
        assert "insufficient_volume" in cpa["note"]

    def test_a_declared_metric_with_no_figures_is_named(self) -> None:
        result = build_evaluation(
            {"cpa": 100, **VOLUME},
            {"cpa": 80, **VOLUME},
            _one("roas", "up"),
            window_from=None,
            window_to=None,
        )
        assert result.table["expected_missing"] == ["roas"]
        # The declared metric stays the primary: without its figures the
        # change cannot be judged, and cpa does not stand in for it.
        assert result.table["basis"] == "expected"
        assert result.table["primary"] == "roas"
        assert result.table["reason"] == "no_primary_metric"
        assert result.overall == "inconclusive"
        assert result.summary == "Inconclusive: no_primary_metric on roas."

    def test_a_budget_cut_without_spend_figures_is_not_judged_on_cpa(self) -> None:
        result = build_evaluation(
            {"cpa": 100, "conversions": 100, "days": 7},
            {"cpa": 60, "conversions": 100, "days": 7},
            _one("spend", "down"),
            window_from=None,
            window_to=None,
        )
        assert result.overall == "inconclusive"
        assert result.table["primary"] == "spend"
        assert result.table["basis"] == "expected"
        assert result.table["reason"] == "no_primary_metric"
        assert result.table["expected_missing"] == ["spend"]
        assert _rows(result.table)["cpa"]["role"] == "reference"

    def test_metric_names_match_case_insensitively(self) -> None:
        result = build_evaluation(
            {"CPA": 100, **VOLUME},
            {"CPA": 80, **VOLUME},
            _one("cpa", "down"),
            window_from=None,
            window_to=None,
        )
        assert _rows(result.table)["cpa"]["role"] == "primary"

    @pytest.mark.parametrize(
        ("stored", "declared"),
        [
            ("cost_per_conversion", "cpa"),
            ("cpa", "cpa"),
            ("conversion_rate", "cvr"),
            ("cvr", "cvr"),
            ("Cost_Per_Click", "cpc"),
        ],
    )
    def test_metric_aliases_match(self, stored: str, declared: str) -> None:
        direction = "up" if declared == "cvr" else "down"
        result = build_evaluation(
            {stored: 100, **VOLUME},
            {stored: 80 if direction == "down" else 120, **VOLUME},
            _one(declared, direction),
            window_from=None,
            window_to=None,
        )
        assert result.table["basis"] == "expected"
        assert _rows(result.table)[declared]["role"] == "primary"
        assert "expected_missing" not in result.table
        assert result.overall == "improved"

    def test_the_marked_primary_decides(self) -> None:
        expected = parse_expected(
            [
                {"metric": "ctr", "direction": "up"},
                {"metric": "cpa", "direction": "down", "primary": True},
            ]
        )
        result = build_evaluation(
            {"cpa": 100, "ctr": 2.0, **VOLUME},
            {"cpa": 80, "ctr": 1.0, **VOLUME},
            expected,
            window_from=None,
            window_to=None,
        )
        assert result.table["primary"] == "cpa"
        assert result.overall == "improved"
        assert _rows(result.table)["ctr"]["role"] == "reference"


class TestChoosePrimary:
    BEFORE: dict[str, Any] = {"cpa": 100, "roas": 3.0, **VOLUME}
    AFTER: dict[str, Any] = {"cpa": 90, "roas": 3.5, **VOLUME}

    def test_nothing_declared_and_no_target_is_none(self) -> None:
        assert choose_primary((), None, self.BEFORE, self.AFTER) is None

    def test_a_single_expected_effect_is_primary(self) -> None:
        choice = choose_primary(_one("roas", "up"), None, self.BEFORE, self.AFTER)
        assert choice is not None
        assert (choice.metric, choice.basis) == ("roas", "expected")
        assert choice.effect == ExpectedEffect(metric="roas", direction="up")

    def test_target_roas_makes_roas_primary(self) -> None:
        choice = choose_primary((), {"target_roas": 4.0}, self.BEFORE, self.AFTER)
        assert choice is not None
        assert (choice.metric, choice.basis, choice.effect) == (
            "roas",
            "bidding_target",
            None,
        )

    def test_target_cpa_makes_cpa_primary(self) -> None:
        choice = choose_primary((), {"target_cpa": 5000}, self.BEFORE, self.AFTER)
        assert choice is not None
        assert (choice.metric, choice.basis) == ("cpa", "bidding_target")

    def test_expected_wins_over_the_bidding_target(self) -> None:
        choice = choose_primary(
            _one("cpa", "down"), {"target_roas": 4.0}, self.BEFORE, self.AFTER
        )
        assert choice is not None
        assert choice.basis == "expected"

    def test_a_declared_metric_without_figures_stays_primary(self) -> None:
        choice = choose_primary(
            _one("ctr", "up"), {"target_roas": 4.0}, self.BEFORE, self.AFTER
        )
        assert choice is not None
        assert (choice.metric, choice.basis) == ("ctr", "expected")

    def test_a_marked_primary_without_figures_stays_primary(self) -> None:
        expected = parse_expected(
            [
                {"metric": "cpa", "direction": "down"},
                {"metric": "spend", "direction": "down", "primary": True},
            ]
        )
        choice = choose_primary(expected, None, self.BEFORE, self.AFTER)
        assert choice is not None
        assert (choice.metric, choice.basis) == ("spend", "expected")

    def test_a_zero_or_absent_target_is_ignored(self) -> None:
        assert choose_primary((), {"target_cpa": 0}, self.BEFORE, self.AFTER) is None
        assert choose_primary((), {"other": 1}, self.BEFORE, self.AFTER) is None

    def test_a_legacy_multi_declaration_without_primary_takes_the_first(
        self,
    ) -> None:
        legacy = (
            ExpectedEffect(metric="roas", direction="up"),
            ExpectedEffect(metric="cpa", direction="down"),
        )
        choice = choose_primary(legacy, None, self.BEFORE, self.AFTER)
        assert choice is not None
        assert choice.metric == "roas"

    def test_the_marked_one_wins(self) -> None:
        effects = (
            ExpectedEffect(metric="roas", direction="up"),
            ExpectedEffect(metric="cpa", direction="down", primary=True),
        )
        choice = choose_primary(effects, None, self.BEFORE, self.AFTER)
        assert choice is not None
        assert choice.metric == "cpa"

    def test_the_bidding_target_decides_the_verdict(self) -> None:
        result = build_evaluation(
            {"cpa": 100, "roas": 3.0, **VOLUME},
            {"cpa": 130, "roas": 4.0, **VOLUME},
            (),
            window_from=None,
            window_to=None,
            bidding_details={"target_roas": 4.0},
        )
        assert result.table["basis"] == "bidding_target"
        assert result.table["primary"] == "roas"
        assert result.overall == "improved"


# ---------------------------------------------------------------------------
# Integration with the automatic closure
# ---------------------------------------------------------------------------


def _write(
    path: Path,
    *,
    decisions: list[dict[str, Any]],
    entry: dict[str, Any],
    campaign: dict[str, Any] | None = None,
) -> None:
    snapshot: dict[str, Any] = {
        "campaign_id": "camp_1",
        "campaign_name": "Brand",
        "status": "ENABLED",
        "metrics": {
            "cpa": 13000,
            "cost": 150000,
            "period": "LAST_30_DAYS",
            "fetched_at": "2026-09-18T09:00:00+09:00",
        },
    }
    snapshot.update(campaign or {})
    document = {
        "version": "2",
        "platforms": {"google_ads": {"account_id": "acct-1", "campaigns": [snapshot]}},
        "action_log": [entry],
        "decisions": decisions,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "timestamp": "2026-09-01T10:00:00+09:00",
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        "campaign_id": "camp_1",
        "metrics_at_action": {"cpa": 10000, "cost": 100000, "days": 30},
        "observation_due": "2026-09-10",
    }
    entry.update(overrides)
    return entry


def _decision(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "decision_id": "dec-1",
        "recorded_at": "2026-09-01T10:00:00+09:00",
        "status": "adopted",
        "title": "Raise the Brand budget",
        "rationale": "Capped every afternoon.",
        "expected": [{"metric": "cost", "direction": "up"}],
    }
    record.update(overrides)
    return record


class TestClosureStoresTheTable:
    def test_the_table_and_decision_id_are_stored(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        _write(path, decisions=[_decision()], entry=_entry(decision_id="dec-1"))
        result = close_due_observations(path, today=TODAY, may_write=lambda: None)
        assert result.closed[0].overall == "improved"
        closure = read_state_file(path).action_log[1]
        assert closure.decision_id == "dec-1"
        assert closure.evaluation is not None
        assert closure.evaluation["rules"] == 2
        assert closure.evaluation["basis"] == "expected"
        assert closure.evaluation["primary"] == "spend"
        assert closure.evaluation["window"] == {
            "from": "2026-09-01",
            "to": "2026-09-18",
        }
        rows = _rows(closure.evaluation)
        assert rows["spend"]["role"] == "primary"
        assert rows["cpa"]["role"] == "reference"

    def test_expected_from_the_latest_record_in_the_chain(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        proposal = _decision(
            status="proposed", expected=[{"metric": "cpa", "direction": "down"}]
        )
        adoption = _decision(
            decision_id="dec-2",
            supersedes="dec-1",
            expected=[{"metric": "cost", "direction": "up"}],
        )
        _write(path, decisions=[proposal, adoption], entry=_entry(decision_id="dec-1"))
        close_due_observations(path, today=TODAY, may_write=lambda: None)
        closure = read_state_file(path).action_log[1]
        assert _rows(closure.evaluation or {})["spend"]["role"] == "primary"

    def test_an_entry_with_no_decision_and_no_conversions_has_no_primary(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        _write(path, decisions=[], entry=_entry())
        result = close_due_observations(path, today=TODAY, may_write=lambda: None)
        closure = read_state_file(path).action_log[1]
        assert closure.decision_id is None
        assert closure.evaluation is not None
        assert closure.evaluation["basis"] == "default"
        assert closure.evaluation["reason"] == "no_primary_metric"
        assert result.closed[0].overall == "inconclusive"

    def test_the_snapshot_bidding_target_is_the_primary(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        _write(
            path,
            decisions=[],
            entry=_entry(metrics_at_action={"roas": 3.0, "conversions": 80}),
            campaign={
                "bidding_strategy_type": "TARGET_ROAS",
                "bidding_details": {"target_roas": 4.0},
                "metrics": {
                    "roas": 4.0,
                    "conversions": 90,
                    "fetched_at": "2026-09-18T09:00:00+09:00",
                },
            },
        )
        result = close_due_observations(path, today=TODAY, may_write=lambda: None)
        closure = read_state_file(path).action_log[1]
        assert closure.evaluation is not None
        assert closure.evaluation["basis"] == "bidding_target"
        assert closure.evaluation["primary"] == "roas"
        assert result.closed[0].overall == "improved"

    def test_a_legacy_multi_declaration_is_read_and_uses_the_first(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        legacy = _decision(
            expected=[
                {"metric": "cost", "direction": "up"},
                {"metric": "cpa", "direction": "down"},
            ]
        )
        _write(path, decisions=[legacy], entry=_entry(decision_id="dec-1"))
        close_due_observations(path, today=TODAY, may_write=lambda: None)
        closure = read_state_file(path).action_log[1]
        assert closure.evaluation is not None
        assert closure.evaluation["primary"] == "spend"
