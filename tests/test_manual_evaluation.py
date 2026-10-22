"""A manual evaluation stores the same table as automatic closure (#889).

``mureo_outcome_evaluate`` returns the evaluation table under
``evaluation``, built by the chain automatic closure uses, and
``mureo_state_action_log_append`` requires that table beside
``evaluation_of`` and stores it in the same field. So ops history, its
counts and the dashboard feed read a manual evaluation exactly as they read
an automatic one. Reading stays lenient: a stored table that is malformed
never blocks a load or a write, and reads as no verdict.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.expected_eval import build_evaluation, validate_evaluation_table
from mureo.context.auto_evaluation import (
    SKIP_NO_COMPARABLE_METRIC,
    ClosurePlan,
    plan_closure,
)
from mureo.context.ops_history_counts import ops_history_counts
from mureo.context.ops_history_view import build_ops_history_items
from mureo.context.state import read_state_file
from mureo.mcp.tools_mureo_context import handle_tool
from mureo.web.server import ConfigureWizard
from tests.web_support import get_ok

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 14, 12, 0).astimezone()
TODAY = date(2026, 10, 14)

BASELINE: dict[str, Any] = {
    "cpa": 10000,
    "conversions": 50,
    "ctr": 2.0,
    "impressions": 5000,
}
CURRENT: dict[str, Any] = {
    "cpa": 5000,
    "conversions": 100,
    "ctr": 3.0,
    "impressions": 6000,
    "period": "LAST_30_DAYS",
    "fetched_at": "2026-10-12T09:00:00+09:00",
}


def _source_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "timestamp": "2026-10-01T10:00:00+09:00",
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        "campaign_id": "c1",
        "metrics_at_action": dict(BASELINE),
        "observation_due": "2026-10-08",
    }
    entry.update(overrides)
    return entry


def _document(
    action_log: list[dict[str, Any]],
    *,
    expected: list[dict[str, Any]] | None = None,
    bidding_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    campaign: dict[str, Any] = {
        "campaign_id": "c1",
        "campaign_name": "Brand",
        "status": "ENABLED",
        "metrics": dict(CURRENT),
    }
    if bidding_details is not None:
        campaign["bidding_details"] = bidding_details
    document: dict[str, Any] = {
        "version": "2",
        "settings": {"ops_history": {"enabled": True}},
        "platforms": {"google_ads": {"account_id": "acct-1", "campaigns": [campaign]}},
        "action_log": action_log,
    }
    if expected is not None:
        document["decisions"] = [
            {
                "decision_id": "dec-1",
                "recorded_at": "2026-10-01T10:00:00+09:00",
                "status": "adopted",
                "title": "Lift CTR",
                "rationale": "New copy.",
                "expected": expected,
            }
        ]
    return document


def _write(root: Path, document: dict[str, Any]) -> Path:
    path = root / "STATE.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from mureo.core import clock

    monkeypatch.setattr(clock, "server_now", lambda: NOW)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """cwd = ``tmp_path`` for the MCP tools, and the dashboard reads it too."""
    from mureo.core.runtime_context import (
        default_runtime_context,
        reset_runtime_context,
    )

    monkeypatch.chdir(tmp_path)
    reset_runtime_context()
    ctx = default_runtime_context(workspace=tmp_path)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
    yield tmp_path
    reset_runtime_context()


async def _evaluate(arguments: dict[str, Any]) -> dict[str, Any]:
    result = await handle_tool("mureo_outcome_evaluate", arguments)
    payload: dict[str, Any] = json.loads(result[0].text)
    return payload


async def _append(entry: dict[str, Any]) -> dict[str, Any]:
    result = await handle_tool("mureo_state_action_log_append", {"entry": entry})
    payload: dict[str, Any] = json.loads(result[0].text)
    return payload


def _auto_table(path: Path) -> dict[str, Any]:
    """What automatic closure would store for entry 0 of ``path``."""
    plan = plan_closure(read_state_file(path), 0, TODAY)
    assert isinstance(plan, ClosurePlan)
    assert plan.entry.evaluation is not None
    return plan.entry.evaluation


def _table() -> dict[str, Any]:
    return build_evaluation(
        {"cpa": 10000, "conversions": 50},
        {"cpa": 5000, "conversions": 100},
        (),
        window_from="2026-10-01",
        window_to="2026-10-12",
    ).table


# ---------------------------------------------------------------------------
# The shape validator
# ---------------------------------------------------------------------------


class TestValidateEvaluationTable:
    def test_a_built_table_passes(self) -> None:
        table = _table()
        assert validate_evaluation_table(table) == table

    def test_an_inconclusive_table_with_a_reason_passes(self) -> None:
        table = build_evaluation(
            {"cpa": 5000, "conversions": 3},
            {"cpa": 7500, "conversions": 2},
            (),
            window_from=None,
            window_to=None,
        ).table
        assert table["reason"] == "insufficient_volume"
        assert validate_evaluation_table(table) == table

    def test_not_an_object_is_refused(self) -> None:
        with pytest.raises(ValueError, match="evaluation must be an object"):
            validate_evaluation_table(["improved"])

    def test_wrong_rules_is_refused(self) -> None:
        with pytest.raises(ValueError, match="rules"):
            validate_evaluation_table({**_table(), "rules": 1})

    def test_missing_rules_is_refused(self) -> None:
        table = _table()
        del table["rules"]
        with pytest.raises(ValueError, match="rules"):
            validate_evaluation_table(table)

    def test_unknown_overall_is_refused(self) -> None:
        with pytest.raises(ValueError, match="overall"):
            validate_evaluation_table({**_table(), "overall": "better"})

    def test_unknown_basis_is_refused(self) -> None:
        with pytest.raises(ValueError, match="basis"):
            validate_evaluation_table({**_table(), "basis": "guess"})

    def test_a_primary_that_is_not_a_string_is_refused(self) -> None:
        with pytest.raises(ValueError, match="primary"):
            validate_evaluation_table({**_table(), "primary": 3})

    def test_a_null_primary_passes(self) -> None:
        table = {**_table(), "primary": None, "reason": "no_primary_metric"}
        assert validate_evaluation_table(table) == table

    def test_unknown_reason_is_refused(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            validate_evaluation_table({**_table(), "reason": "bad_luck"})

    def test_noise_pct_zero_is_refused(self) -> None:
        with pytest.raises(ValueError, match="noise_pct"):
            validate_evaluation_table({**_table(), "noise_pct": 0})

    def test_noise_pct_above_100_is_refused(self) -> None:
        with pytest.raises(ValueError, match="noise_pct"):
            validate_evaluation_table({**_table(), "noise_pct": 101})

    def test_metrics_not_a_list_is_refused(self) -> None:
        with pytest.raises(ValueError, match="metrics"):
            validate_evaluation_table({**_table(), "metrics": {"cpa": 1}})

    def test_no_rows_is_refused(self) -> None:
        # The literal in the validator is the automatic closure's skip word.
        with pytest.raises(ValueError, match=f"^{SKIP_NO_COMPARABLE_METRIC}: "):
            validate_evaluation_table({**_table(), "metrics": []})

    def test_a_row_with_an_unknown_key_is_refused(self) -> None:
        table = _table()
        table["metrics"][0]["extra"] = 1
        with pytest.raises(ValueError, match="metrics"):
            validate_evaluation_table(table)

    def test_a_row_missing_a_key_is_refused(self) -> None:
        table = _table()
        del table["metrics"][0]["role"]
        with pytest.raises(ValueError, match="metrics"):
            validate_evaluation_table(table)

    @pytest.mark.parametrize("key", ["overall", "basis", "reason", "primary"])
    @pytest.mark.parametrize("value", [["improved"], {"v": 1}, 3.5, True])
    def test_a_value_of_the_wrong_type_is_a_value_error(
        self, key: str, value: object
    ) -> None:
        with pytest.raises(ValueError, match=key):
            validate_evaluation_table({**_table(), key: value})

    def test_an_unknown_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="verdict_text"):
            validate_evaluation_table({**_table(), "verdict_text": "great"})


# ---------------------------------------------------------------------------
# mureo_outcome_evaluate returns the stored table
# ---------------------------------------------------------------------------


class TestOutcomeEvaluateTable:
    async def test_explicit_inputs_return_the_table(self, workspace: Path) -> None:
        payload = await _evaluate(
            {
                "before": {"cpa": 10000, "conversions": 50, "ctr": 2.0},
                "after": {"cpa": 5000, "conversions": 100, "ctr": 1.0},
                "expected": [{"metric": "cpa", "direction": "down"}],
            }
        )
        table = payload["evaluation"]
        assert table["rules"] == 2
        assert table["basis"] == "expected"
        assert table["primary"] == "cpa"
        assert table["overall"] == "improved"
        assert validate_evaluation_table(table) == table
        # The legacy keys read the same verdict.
        assert payload["overall"] == table["overall"]
        assert payload["primary"] == table["primary"]
        assert payload["basis"] == table["basis"]

    async def test_without_expected_the_table_matches_the_legacy_keys(
        self, workspace: Path
    ) -> None:
        payload = await _evaluate(
            {
                "before": {"cpa": 5000, "conversions": 40},
                "after": {"cpa": 4000, "conversions": 50},
            }
        )
        assert payload["overall"] == "improved"
        assert payload["evaluation"]["basis"] == "default"
        assert payload["evaluation"]["window"] == {"from": None, "to": None}
        assert [m["metric"] for m in payload["metrics"]] == [
            m["metric"] for m in payload["evaluation"]["metrics"]
        ]
        assert "role" not in payload["metrics"][0]

    async def test_evaluation_of_uses_the_chained_decision(
        self, workspace: Path
    ) -> None:
        path = _write(
            workspace,
            _document(
                [_source_entry(decision_id="dec-1")],
                expected=[{"metric": "ctr", "direction": "up"}],
            ),
        )
        payload = await _evaluate({"evaluation_of": 0, "after": dict(CURRENT)})
        table = payload["evaluation"]
        assert table["basis"] == "expected"
        assert table["primary"] == "ctr"
        assert table["window"] == {"from": "2026-10-01", "to": "2026-10-12"}
        # The same table automatic closure would store for the same entry.
        assert table == _auto_table(path)

    async def test_evaluation_of_reads_the_bidding_target(
        self, workspace: Path
    ) -> None:
        path = _write(
            workspace,
            _document(
                [
                    _source_entry(
                        metrics_at_action={**BASELINE, "roas": 2.0},
                    )
                ],
                bidding_details={"target_roas": 3.0},
            ),
        )
        after = {**CURRENT, "roas": 3.0}
        document = json.loads(path.read_text(encoding="utf-8"))
        document["platforms"]["google_ads"]["campaigns"][0]["metrics"] = after
        path.write_text(json.dumps(document), encoding="utf-8")
        payload = await _evaluate({"evaluation_of": 0, "after": after})
        assert payload["evaluation"]["basis"] == "bidding_target"
        assert payload["evaluation"]["primary"] == "roas"
        assert payload["evaluation"] == _auto_table(path)

    async def test_evaluation_of_takes_before_from_the_entry(
        self, workspace: Path
    ) -> None:
        _write(workspace, _document([_source_entry()]))
        payload = await _evaluate({"evaluation_of": 0, "after": dict(CURRENT)})
        cpa = next(m for m in payload["evaluation"]["metrics"] if m["metric"] == "cpa")
        assert cpa["before"] == 10000.0

    async def test_an_explicit_before_stands_in_for_a_missing_baseline(
        self, workspace: Path
    ) -> None:
        entry = _source_entry()
        del entry["metrics_at_action"]
        _write(workspace, _document([entry]))
        with pytest.raises(ValueError, match="before"):
            await _evaluate({"evaluation_of": 0, "after": dict(CURRENT)})
        payload = await _evaluate(
            {"evaluation_of": 0, "before": dict(BASELINE), "after": dict(CURRENT)}
        )
        assert payload["evaluation"]["primary"] == "cpa"
        assert payload["evaluation"]["window"]["from"] == "2026-10-01"

    async def test_before_beside_a_recorded_baseline_is_refused(
        self, workspace: Path
    ) -> None:
        _write(workspace, _document([_source_entry()]))
        with pytest.raises(ValueError, match="evaluation_of_conflicts_with_before"):
            await _evaluate(
                {
                    "evaluation_of": 0,
                    "before": {"cpa": 9000, "conversions": 45},
                    "after": dict(CURRENT),
                }
            )

    async def test_before_beside_an_empty_baseline_is_taken(
        self, workspace: Path
    ) -> None:
        _write(workspace, _document([_source_entry(metrics_at_action={})]))
        payload = await _evaluate(
            {"evaluation_of": 0, "before": dict(BASELINE), "after": dict(CURRENT)}
        )
        assert payload["evaluation"]["primary"] == "cpa"

    async def test_no_comparable_metric_is_refused(self, workspace: Path) -> None:
        _write(workspace, _document([_source_entry()]))
        after = {"roas": 3.0, "period": "LAST_30_DAYS"}
        with pytest.raises(ValueError, match="^no_comparable_metric: "):
            await _evaluate({"evaluation_of": 0, "after": after})

    async def test_a_count_primary_over_different_periods_is_refused(
        self, workspace: Path
    ) -> None:
        _write(
            workspace,
            _document(
                [
                    _source_entry(
                        decision_id="dec-1",
                        metrics_at_action={**BASELINE, "period": "LAST_7_DAYS"},
                    )
                ],
                expected=[{"metric": "conversions", "direction": "up"}],
            ),
        )
        with pytest.raises(ValueError, match="period_mismatch"):
            await _evaluate({"evaluation_of": 0, "after": dict(CURRENT)})

    async def test_evaluation_of_with_expected_is_refused(
        self, workspace: Path
    ) -> None:
        _write(workspace, _document([_source_entry()]))
        with pytest.raises(ValueError, match="evaluation_of_conflicts_with_expected"):
            await _evaluate(
                {
                    "evaluation_of": 0,
                    "after": dict(CURRENT),
                    "expected": [{"metric": "cpa", "direction": "down"}],
                }
            )

    async def test_an_out_of_range_evaluation_of_is_refused(
        self, workspace: Path
    ) -> None:
        _write(workspace, _document([_source_entry()]))
        with pytest.raises(ValueError, match="evaluation_of=5 is out of range"):
            await _evaluate({"evaluation_of": 5, "after": dict(CURRENT)})

    async def test_without_evaluation_of_before_is_required(
        self, workspace: Path
    ) -> None:
        with pytest.raises(ValueError, match="before"):
            await _evaluate({"after": dict(CURRENT)})


# ---------------------------------------------------------------------------
# The append carries the table
# ---------------------------------------------------------------------------


class TestAppendRequiresTheTable:
    async def test_evaluation_of_without_evaluation_is_refused(
        self, workspace: Path
    ) -> None:
        _write(workspace, _document([_source_entry()]))
        with pytest.raises(ValueError, match="evaluation_required") as info:
            await _append(
                {
                    "action": "Outcome evaluated",
                    "platform": "google_ads",
                    "evaluation_of": 0,
                }
            )
        assert "mureo_outcome_evaluate" in str(info.value)

    async def test_evaluation_without_evaluation_of_is_refused(
        self, workspace: Path
    ) -> None:
        _write(workspace, _document([_source_entry()]))
        with pytest.raises(ValueError, match="evaluation_without_target"):
            await _append(
                {
                    "action": "Outcome evaluated",
                    "platform": "google_ads",
                    "evaluation": _table(),
                }
            )

    async def test_a_malformed_table_is_refused(self, workspace: Path) -> None:
        _write(workspace, _document([_source_entry()]))
        with pytest.raises(ValueError, match="rules"):
            await _append(
                {
                    "action": "Outcome evaluated",
                    "platform": "google_ads",
                    "evaluation_of": 0,
                    "evaluation": {**_table(), "rules": 1},
                }
            )

    async def test_a_table_with_no_rows_is_refused(self, workspace: Path) -> None:
        path = _write(workspace, _document([_source_entry()]))
        # What the explicit-input path returns for maps sharing no metric.
        payload = await _evaluate({"before": {"cpa": 5000}, "after": {"roas": 3.0}})
        assert payload["evaluation"]["metrics"] == []
        with pytest.raises(ValueError, match="^no_comparable_metric: "):
            await _append(
                {
                    "action": "Outcome evaluated",
                    "platform": "google_ads",
                    "evaluation_of": 0,
                    "evaluation": payload["evaluation"],
                }
            )
        assert len(read_state_file(path).action_log) == 1

    async def test_the_table_is_stored_as_returned(self, workspace: Path) -> None:
        path = _write(workspace, _document([_source_entry()]))
        payload = await _evaluate({"evaluation_of": 0, "after": dict(CURRENT)})
        await _append(
            {
                "action": "Outcome evaluated",
                "platform": "google_ads",
                "campaign_id": "c1",
                "evaluation_of": 0,
                "evaluation": payload["evaluation"],
            }
        )
        stored = json.loads(path.read_text(encoding="utf-8"))["action_log"][1]
        assert stored["evaluation"] == payload["evaluation"]

    async def test_the_summary_is_built_from_the_table(self, workspace: Path) -> None:
        path = _write(
            workspace,
            _document(
                [_source_entry(decision_id="dec-1")],
                expected=[{"metric": "ctr", "direction": "up"}],
            ),
        )
        plan = plan_closure(read_state_file(path), 0, TODAY)
        assert isinstance(plan, ClosurePlan)
        payload = await _evaluate({"evaluation_of": 0, "after": dict(CURRENT)})
        await _append(
            {
                "action": "Outcome evaluated",
                "platform": "google_ads",
                "evaluation_of": 0,
                "summary": "Looks great to me.",
                "evaluation": payload["evaluation"],
            }
        )
        stored = read_state_file(path).action_log[1]
        assert stored.summary == payload["summary"] == plan.entry.summary

    async def test_an_inconclusive_summary_names_its_reason(
        self, workspace: Path
    ) -> None:
        path = _write(workspace, _document([_source_entry()]))
        result = build_evaluation(
            {"cpa": 5000, "conversions": 3},
            {"cpa": 7500, "conversions": 2},
            (),
            window_from=None,
            window_to=None,
        )
        await _append(
            {
                "action": "Outcome evaluated",
                "platform": "google_ads",
                "evaluation_of": 0,
                "evaluation": result.table,
            }
        )
        stored = read_state_file(path).action_log[1]
        assert stored.summary == result.summary
        assert "insufficient_volume" in result.summary

    async def test_the_record_inherits_the_evaluated_decision(
        self, workspace: Path
    ) -> None:
        path = _write(
            workspace,
            _document(
                [_source_entry(decision_id="dec-1")],
                expected=[{"metric": "ctr", "direction": "up"}],
            ),
        )
        payload = await _evaluate({"evaluation_of": 0, "after": dict(CURRENT)})
        await _append(
            {
                "action": "Outcome evaluated",
                "platform": "google_ads",
                "evaluation_of": 0,
                "decision_id": "dec-other",
                "evaluation": payload["evaluation"],
            }
        )
        doc = read_state_file(path)
        assert doc.action_log[1].decision_id == "dec-1"
        assert [r.decision_id for r in doc.decisions] == ["dec-1"]


# ---------------------------------------------------------------------------
# Ops history reads a manual evaluation as it reads an automatic one
# ---------------------------------------------------------------------------


async def _close_manually(workspace: Path) -> tuple[Path, dict[str, Any]]:
    """Evaluate entry 0 by hand and append the record; return the auto table."""
    path = _write(
        workspace,
        _document(
            [_source_entry(decision_id="dec-1")],
            expected=[{"metric": "ctr", "direction": "up"}],
        ),
    )
    auto = _auto_table(path)
    payload = await _evaluate({"evaluation_of": 0, "after": dict(CURRENT)})
    await _append(
        {
            "action": "Outcome evaluated",
            "platform": "google_ads",
            "campaign_id": "c1",
            "evaluation_of": 0,
            "evaluation": payload["evaluation"],
        }
    )
    return path, auto


class TestOpsHistoryReadsTheManualTable:
    async def test_the_view_shows_the_verdict(self, workspace: Path) -> None:
        path, auto = await _close_manually(workspace)
        items = build_ops_history_items(read_state_file(path), today=TODAY)
        assert len(items) == 1
        assert items[0]["state"] == "evaluated"
        assert items[0]["verdict"] == "improved"
        evaluation = items[0]["actions"][0]["evaluation"]
        assert evaluation["overall"] == "improved"
        assert evaluation["table"] == auto

    async def test_the_counts_show_the_verdict(self, workspace: Path) -> None:
        path, _ = await _close_manually(workspace)
        counts = ops_history_counts(read_state_file(path), today=TODAY)
        assert counts["improved"] == 1
        assert counts["changes"] == 1

    async def test_the_dashboard_feed_shows_it_as_an_automatic_one(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        _, auto = await _close_manually(workspace)
        body = get_ok(wizard, "/api/reports/ops-history")
        (item,) = body["items"]
        assert item["state"] == "evaluated"
        assert item["verdict"] == auto["overall"]
        assert item["actions"][0]["evaluation"]["table"] == auto


# ---------------------------------------------------------------------------
# Reading stays lenient
# ---------------------------------------------------------------------------


class TestLenientReading:
    def _malformed(self) -> list[dict[str, Any]]:
        return [
            _source_entry(),
            _source_entry(campaign_id="c2", timestamp="2026-10-02T10:00:00+09:00"),
            {
                "timestamp": "2026-10-09T10:00:00+09:00",
                "action": "Outcome evaluated",
                "platform": "google_ads",
                "evaluation_of": 0,
                "evaluation": {"rules": 99, "overall": "splendid"},
            },
            {
                "timestamp": "2026-10-09T11:00:00+09:00",
                "action": "Outcome evaluated",
                "platform": "google_ads",
                "evaluation_of": 1,
                "evaluation": "improved",
            },
        ]

    def test_a_malformed_table_still_loads_as_no_verdict(self, workspace: Path) -> None:
        path = _write(workspace, _document(self._malformed()))
        doc = read_state_file(path)
        assert len(doc.action_log) == 4
        items = build_ops_history_items(doc, today=TODAY)
        assert [item["state"] for item in items] == ["evaluated", "evaluated"]
        assert [item["verdict"] for item in items] == [None, None]
        counts = ops_history_counts(doc, today=TODAY)
        assert counts["improved"] == counts["regressed"] == 0
        assert counts["inconclusive"] == 2

    async def test_other_entries_still_write(self, workspace: Path) -> None:
        malformed = self._malformed()
        path = _write(workspace, _document(copy.deepcopy(malformed)))
        await _append(
            {
                "action": "Paused ad",
                "platform": "google_ads",
                "campaign_id": "c1",
                "reason": "The ad stopped converting.",
                "expected": [{"metric": "cpa", "direction": "down"}],
            }
        )
        stored = json.loads(path.read_text(encoding="utf-8"))["action_log"]
        assert len(stored) == 5
        assert stored[2]["evaluation"] == malformed[2]["evaluation"]
        assert stored[3]["evaluation"] == malformed[3]["evaluation"]
