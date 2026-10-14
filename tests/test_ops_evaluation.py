"""The evaluation table (#848): stored on ``outcome_evaluated`` entries.

Before ops history the automatic closure kept a one-line summary; the
figures it judged on were thrown away. These tests pin the table's shape,
that a decision's ``expected`` metrics are the primary ones, and that the
closure entry inherits the evaluated action's ``decision_id``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.expected_eval import build_evaluation
from mureo.analysis.outcome_eval import evaluate_outcome
from mureo.context.auto_evaluation import close_due_observations
from mureo.context.expected import parse_expected
from mureo.context.state import read_state_file

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)


def _rows(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["metric"]: row for row in table["metrics"]}


class TestBuildEvaluationWithoutExpected:
    def test_the_shape(self) -> None:
        result = build_evaluation(
            {"cpa": 10000, "conversions": 5, "cost": 100},
            {"cpa": 5000, "conversions": 10, "cost": 100},
            (),
            window_from="2026-09-01",
            window_to="2026-09-18",
        )
        table = result.table
        assert set(table) == {"overall", "basis", "noise_pct", "window", "metrics"}
        assert table["window"] == {"from": "2026-09-01", "to": "2026-09-18"}
        assert table["basis"] == "default"
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
        before = {"cpa": 10000, "conversions": 5}
        after = {"cpa": 12000, "conversions": 10}
        result = build_evaluation(before, after, (), window_from=None, window_to=None)
        report = evaluate_outcome(before, after)
        assert result.overall == report.overall.value
        assert result.summary == report.summary
        assert result.table["overall"] == report.overall.value

    def test_directional_metrics_are_primary_and_volume_is_reference(self) -> None:
        result = build_evaluation(
            {"cpa": 100, "clicks": 10},
            {"cpa": 100, "clicks": 50},
            (),
            window_from=None,
            window_to=None,
        )
        rows = _rows(result.table)
        assert rows["cpa"]["role"] == "primary"
        assert rows["clicks"]["role"] == "reference"


class TestBuildEvaluationWithExpected:
    def test_expected_metrics_are_primary_and_decide(self) -> None:
        # CPA got worse, but the declared expectation was spend UP — which
        # happened. The verdict is on what the change was meant to do.
        result = build_evaluation(
            {"cpa": 100, "cost": 1000},
            {"cpa": 130, "cost": 1500},
            parse_expected([{"metric": "cost", "direction": "up"}]),
            window_from=None,
            window_to=None,
        )
        rows = _rows(result.table)
        assert rows["cost"]["role"] == "primary"
        assert rows["cost"]["verdict"] == "improved"
        assert rows["cpa"]["role"] == "reference"
        assert rows["cpa"]["verdict"] == "regressed"
        assert result.overall == "improved"
        assert result.table["basis"] == "expected"

    @pytest.mark.parametrize(
        ("direction", "after", "verdict"),
        [
            ("down", 80, "improved"),
            ("down", 120, "regressed"),
            ("down", 95, "inconclusive"),
            ("up", 120, "improved"),
            ("up", 80, "regressed"),
            ("hold", 95, "improved"),
            ("hold", 130, "regressed"),
        ],
    )
    def test_each_direction(self, direction: str, after: float, verdict: str) -> None:
        result = build_evaluation(
            {"cpa": 100},
            {"cpa": after},
            parse_expected([{"metric": "cpa", "direction": direction}]),
            window_from=None,
            window_to=None,
        )
        assert _rows(result.table)["cpa"]["verdict"] == verdict
        assert result.overall == verdict

    def test_a_target_is_reported_in_the_note(self) -> None:
        result = build_evaluation(
            {"cpa": 100},
            {"cpa": 80},
            parse_expected([{"metric": "cpa", "direction": "down", "target": 85}]),
            window_from=None,
            window_to=None,
        )
        assert "target 85 reached" in _rows(result.table)["cpa"]["note"]

    def test_a_declared_metric_with_no_figures_is_named(self) -> None:
        result = build_evaluation(
            {"cpa": 100},
            {"cpa": 80},
            parse_expected([{"metric": "roas", "direction": "up"}]),
            window_from=None,
            window_to=None,
        )
        assert result.table["expected_missing"] == ["roas"]
        # Nothing declared could be scored, so the verdict falls back to the
        # evaluator's own, and the table says so.
        assert result.table["basis"] == "default"
        assert result.overall == "improved"

    def test_metric_names_match_case_insensitively(self) -> None:
        result = build_evaluation(
            {"CPA": 100},
            {"CPA": 80},
            parse_expected([{"metric": "cpa", "direction": "down"}]),
            window_from=None,
            window_to=None,
        )
        assert _rows(result.table)["CPA"]["role"] == "primary"

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
            {stored: 100},
            {stored: 80 if direction == "down" else 120},
            parse_expected([{"metric": declared, "direction": direction}]),
            window_from=None,
            window_to=None,
        )
        assert result.table["basis"] == "expected"
        assert _rows(result.table)[stored]["role"] == "primary"
        assert "expected_missing" not in result.table
        assert result.overall == "improved"


# ---------------------------------------------------------------------------
# Integration with the automatic closure
# ---------------------------------------------------------------------------


def _write(
    path: Path, *, decisions: list[dict[str, Any]], entry: dict[str, Any]
) -> None:
    document = {
        "version": "2",
        "platforms": {
            "google_ads": {
                "account_id": "acct-1",
                "campaigns": [
                    {
                        "campaign_id": "camp_1",
                        "campaign_name": "Brand",
                        "status": "ENABLED",
                        "metrics": {
                            "cpa": 13000,
                            "cost": 150000,
                            "fetched_at": "2026-09-18T09:00:00+09:00",
                        },
                    }
                ],
            }
        },
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
        "metrics_at_action": {"cpa": 10000, "cost": 100000},
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
        assert closure.evaluation["basis"] == "expected"
        assert closure.evaluation["window"] == {
            "from": "2026-09-01",
            "to": "2026-09-18",
        }
        rows = _rows(closure.evaluation)
        assert rows["cost"]["role"] == "primary"
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
        assert _rows(closure.evaluation or {})["cost"]["role"] == "primary"

    def test_an_entry_with_no_decision_is_evaluated_as_before(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        _write(path, decisions=[], entry=_entry())
        result = close_due_observations(path, today=TODAY, may_write=lambda: None)
        closure = read_state_file(path).action_log[1]
        assert closure.decision_id is None
        assert closure.evaluation is not None
        assert closure.evaluation["basis"] == "default"
        assert result.closed[0].overall == "regressed"
