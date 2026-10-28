"""The ops history join and its two read surfaces (#848).

``build_ops_history`` (the dashboard feed) and the ``decisions`` /
``ops_history`` sources of ``mureo_history_query`` return the same items:
one per decision with its changes and their evaluation, plus one per change
no decision covers, each with a DERIVED state.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.outcome_note import note_parts
from mureo.context.ops_history_view import build_ops_history_items
from mureo.context.state_codec import parse_state
from mureo.mcp import journal

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 14)


def _decision(decision_id: str, status: str, day: str, **extra: Any) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "recorded_at": f"{day}T10:00:00+09:00",
        "status": status,
        "title": f"Decision {decision_id}",
        "rationale": "Because.",
        **extra,
    }


def _action(**extra: Any) -> dict[str, Any]:
    return {
        "timestamp": "2026-10-01T10:00:00+09:00",
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        "campaign_id": "c1",
        **extra,
    }


def _document() -> dict[str, Any]:
    table = {"overall": "regressed", "basis": "default", "metrics": []}
    return {
        "version": "2",
        "decisions": [
            _decision("A", "proposed", "2026-10-10"),
            _decision("B", "proposed", "2026-10-02"),
            _decision("B2", "rejected", "2026-10-03", supersedes="B"),
            _decision(
                "C",
                "adopted",
                "2026-10-05",
                expected=[{"metric": "cpa", "direction": "down"}],
            ),
            _decision("D", "adopted", "2026-09-20"),
            _decision("E", "adopted", "2026-09-01"),
        ],
        "action_log": [
            # 0: C, still inside its window.
            _action(decision_id="C", observation_due="2026-10-20"),
            # 1: D, evaluated (2) and rolled back (3).
            _action(
                decision_id="D",
                observation_due="2026-10-01",
                metrics_at_action={"cpa": 100},
                reversible_params={
                    "operation": "google_ads_budget_update",
                    "params": {"budget_id": "b1", "amount": 10000},
                },
                reason="Capped daily.",
            ),
            _action(
                action="outcome_evaluated",
                evaluation_of=1,
                decision_id="D",
                evaluation=table,
            ),
            _action(action="rollback", rollback_of=1),
            # 4: E, nothing to observe.
            _action(decision_id="E", timestamp="2026-09-01T10:00:00+09:00"),
            # 5: no decision, past due, no baseline -> skipped.
            _action(
                timestamp="2026-09-15T10:00:00+09:00", observation_due="2026-09-22"
            ),
        ],
    }


def _items(**kwargs: Any) -> dict[str, dict[str, Any]]:
    doc = parse_state(json.dumps(_document()))
    items = build_ops_history_items(doc, today=TODAY, **kwargs)
    return {
        (item["decision"]["decision_id"] if item["decision"] else "orphan"): item
        for item in items
    }


def _items_of(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    doc = parse_state(json.dumps(document))
    return {
        (i["decision"]["decision_id"] if i["decision"] else "orphan"): i
        for i in build_ops_history_items(doc, today=TODAY)
    }


class TestDerivedState:
    def test_every_state(self) -> None:
        items = _items()
        assert items["A"]["state"] == "proposed"
        assert items["B"]["state"] == "rejected"
        assert items["C"]["state"] == "observing"
        assert items["D"]["state"] == "evaluated"
        assert items["D"]["verdict"] == "regressed"
        assert items["E"]["state"] == "executed"
        assert items["orphan"]["state"] == "skipped"

    def test_rolled_back_is_a_flag(self) -> None:
        items = _items()
        assert items["D"]["rolled_back"] is True
        assert items["C"]["rolled_back"] is False
        assert items["D"]["actions"][0]["rolled_back_by"] == 3

    def test_the_skip_reason_is_given(self) -> None:
        action = _items()["orphan"]["actions"][0]
        assert action["skipped_reason"] == "no_baseline"

    def test_the_action_row(self) -> None:
        action = _items()["D"]["actions"][0]
        assert action["index"] == 1
        assert action["before"] == {"amount": 10000}
        assert action["reason"] == "Capped daily."
        assert action["metrics_at_action"] == {"cpa": 100}
        assert action["evaluation"]["index"] == 2
        assert action["evaluation"]["overall"] == "regressed"
        assert "command" not in action

    def test_the_decision_chain(self) -> None:
        decision = _items()["B"]["decision"]
        assert decision["decision_id"] == "B"
        assert decision["status"] == "rejected"
        assert [h["status"] for h in decision["history"]] == ["proposed", "rejected"]
        assert _items()["C"]["decision"]["expected"] == [
            {"metric": "cpa", "direction": "down"}
        ]

    def test_evaluation_and_rollback_entries_are_not_items(self) -> None:
        doc = parse_state(json.dumps(_document()))
        items = build_ops_history_items(doc, today=TODAY)
        indices = [a["index"] for item in items for a in item["actions"]]
        assert sorted(indices) == [0, 1, 4, 5]

    def test_newest_first(self) -> None:
        doc = parse_state(json.dumps(_document()))
        items = build_ops_history_items(doc, today=TODAY)
        firsts = [i["decision"]["decision_id"] if i["decision"] else "o" for i in items]
        assert firsts == ["A", "C", "B", "D", "o", "E"]

    def test_window(self) -> None:
        from mureo.context.ops_history_query import ops_history_items

        doc = parse_state(json.dumps(_document()))
        items = ops_history_items(
            doc, today=TODAY, since=date(2026, 10, 1), until=date(2026, 10, 5)
        )
        assert {i["decision"]["decision_id"] for i in items} == {"B", "C"}

    def test_related_actions_link_an_unstamped_change(self) -> None:
        document = _document()
        document["decisions"].append(
            _decision("F", "adopted", "2026-09-16", related_actions=[5])
        )
        doc = parse_state(json.dumps(document))
        items = build_ops_history_items(doc, today=TODAY)
        by_id = {i["decision"]["decision_id"]: i for i in items if i["decision"]}
        assert [a["index"] for a in by_id["F"]["actions"]] == [5]
        assert all(i["decision"] is not None for i in items)

    def test_a_stamped_change_stays_under_its_own_decision(self) -> None:
        document = _document()
        document["decisions"].append(
            _decision("F", "adopted", "2026-09-16", related_actions=[0, 2, 5])
        )
        doc = parse_state(json.dumps(document))
        items = build_ops_history_items(doc, today=TODAY)
        by_id = {i["decision"]["decision_id"]: i for i in items if i["decision"]}
        assert [a["index"] for a in by_id["F"]["actions"]] == [5]
        assert [a["index"] for a in by_id["C"]["actions"]] == [0]
        indices = [a["index"] for item in items for a in item["actions"]]
        assert len(indices) == len(set(indices))

    def test_before_and_after(self) -> None:
        document = _document()
        document["action_log"][1]["applied_params"] = {
            "budget_id": "b1",
            "amount": 12000,
        }
        doc = parse_state(json.dumps(document))
        items = build_ops_history_items(doc, today=TODAY)
        action = next(a for i in items for a in i["actions"] if a["index"] == 1)
        assert action["before"] == {"amount": 10000}
        assert action["after"] == {"amount": 12000}
        assert (
            next(a for i in items for a in i["actions"] if a["index"] == 0)["after"]
            is None
        )

    def test_newest_first_by_the_full_timestamp(self) -> None:
        document = {
            "version": "2",
            "action_log": [
                _action(timestamp="2026-10-01T09:00:00+00:00", summary="early"),
                _action(timestamp="2026-10-01T18:00:00+00:00", summary="late"),
            ],
        }
        items = build_ops_history_items(parse_state(json.dumps(document)), today=TODAY)
        assert [i["actions"][0]["summary"] for i in items] == ["late", "early"]

    def test_the_items_are_copies(self) -> None:
        document = _document()
        document["decisions"][4]["metrics"] = {"cpa": 100}
        doc = parse_state(json.dumps(document))
        item = next(
            i
            for i in build_ops_history_items(doc, today=TODAY)
            if i["decision"] and i["decision"]["decision_id"] == "D"
        )
        action = item["actions"][0]
        action["metrics_at_action"]["cpa"] = 0
        action["evaluation"]["table"]["overall"] = "x"
        item["decision"]["metrics"]["cpa"] = 0
        assert doc.action_log[1].metrics_at_action == {"cpa": 100}
        assert doc.action_log[2].evaluation["overall"] == "regressed"
        assert doc.decisions[4].metrics == {"cpa": 100}

    def test_a_decision_carried_out_by_a_call_is_executed(self) -> None:
        document = _document()
        document["decisions"].append(
            _decision(
                "G",
                "adopted",
                "2026-10-12",
                applied_params={"budget_id": "b1", "amount": 12000},
                journal_call_id="call-1",
            )
        )
        items = _items_of(document)
        assert items["G"]["state"] == "executed"
        assert items["G"]["decision"]["applied_params"] == {
            "budget_id": "b1",
            "amount": 12000,
        }
        assert items["G"]["decision"]["journal_call_id"] == "call-1"

    def test_an_empty_document(self) -> None:
        assert build_ops_history_items(parse_state("{}"), today=TODAY) == []


def _duplicated_pair(record_at: str, call_at: str) -> dict[str, Any]:
    """A ``mureo_decision_record`` chain (R) and a reasoned change's (K)."""
    target = {"platform": "google_ads", "campaign_id": "c1"}
    record = _decision("R", "proposed", "2026-10-01", **target)
    adopted = _decision("R2", "adopted", "2026-10-01", supersedes="R", **target)
    call = _decision("K", "adopted", "2026-10-01", journal_call_id="call-k", **target)
    record["recorded_at"] = adopted["recorded_at"] = record_at
    call["recorded_at"] = call_at
    return {
        "version": "2",
        "decisions": [record, adopted, call],
        "action_log": [_action(timestamp=call_at, decision_id="K")],
    }


class TestPossibleDuplicate:
    def test_the_record_item_names_the_call_chain(self) -> None:
        document = _duplicated_pair(
            "2026-10-05T10:00:00+09:00", "2026-10-05T10:10:00+09:00"
        )
        items = _items_of(document)
        assert items["R"]["decision"]["possible_duplicate_of"] == "K"
        assert items["K"]["decision"]["possible_duplicate_of"] is None

    def test_every_decision_carries_the_key(self) -> None:
        for item in _items().values():
            if item["decision"] is not None:
                assert "possible_duplicate_of" in item["decision"]
        assert "possible_duplicate_of" not in _items()["orphan"]

    def test_a_pair_across_the_window_edge_still_gets_the_hint(self) -> None:
        from mureo.context.ops_history_query import ops_history_items

        document = _duplicated_pair(
            "2026-10-05T23:50:00+09:00", "2026-10-06T00:10:00+09:00"
        )
        doc = parse_state(json.dumps(document))
        items = ops_history_items(
            doc, today=TODAY, since=date(2026, 10, 5), until=date(2026, 10, 5)
        )
        assert [i["decision"]["decision_id"] for i in items] == ["R"]
        assert items[0]["decision"]["possible_duplicate_of"] == "K"


def _two_evaluated(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Decision H with two observed changes, each closed by ``first`` / ``second``."""
    document = _document()
    document["decisions"].append(_decision("H", "adopted", "2026-10-12"))
    log = document["action_log"]
    for table in (first, second):
        index = len(log)
        log.append(
            _action(
                decision_id="H",
                observation_due="2026-10-13",
                metrics_at_action={"cpa": 100},
            )
        )
        log.append(
            _action(
                action="outcome_evaluated",
                evaluation_of=index,
                decision_id="H",
                evaluation=table,
            )
        )
    return document


def _table(overall: str) -> dict[str, Any]:
    return {
        "rules": 2,
        "overall": overall,
        "basis": "default",
        "primary": "cpa",
        "metrics": [],
    }


class TestVerdictOrder:
    """regressed > improved > held > inconclusive (#888)."""

    @pytest.mark.parametrize(
        ("first", "second", "verdict"),
        [
            ("held", "inconclusive", "held"),
            ("held", "improved", "improved"),
            ("regressed", "held", "regressed"),
            ("held", "held", "held"),
        ],
    )
    def test_the_item_verdict(self, first: str, second: str, verdict: str) -> None:
        items = _items_of(_two_evaluated(_table(first), _table(second)))
        assert items["H"]["state"] == "evaluated"
        assert items["H"]["verdict"] == verdict

    def test_a_table_without_rules_is_still_read(self) -> None:
        legacy = {"overall": "improved", "basis": "expected", "metrics": []}
        items = _items_of(_two_evaluated(legacy, _table("inconclusive")))
        assert items["H"]["verdict"] == "improved"
        evaluation = items["H"]["actions"][0]["evaluation"]
        assert evaluation["overall"] == "improved"
        assert "rules" not in evaluation["table"]


def _row(metric: str, note: Any, role: str = "reference") -> dict[str, Any]:
    return {
        "metric": metric,
        "before": 100.0,
        "after": 80.0,
        "delta_pct": -20.0,
        "verdict": "improved",
        "note": note,
        "role": role,
    }


def _served_table(metrics: Any) -> tuple[Any, Any]:
    """The table served for entry 2, and the one stored there afterwards."""
    document = _document()
    document["action_log"][2]["evaluation"] = {
        **_table("improved"),
        "metrics": metrics,
    }
    doc = parse_state(json.dumps(document))
    items = {
        i["decision"]["decision_id"]: i
        for i in build_ops_history_items(doc, today=TODAY)
        if i["decision"]
    }
    return items["D"]["actions"][0]["evaluation"]["table"], doc.action_log[2]


class TestNoteParts:
    """Each served row carries its note read back into parts (#894)."""

    def test_a_builder_note_is_read(self) -> None:
        note = "expected down; -20% (noise band ±10%); target 85 reached"
        table, _ = _served_table([_row("cpa", note, "primary")])
        (row,) = table["metrics"]
        assert row["note"] == note
        assert row["note_parts"] == note_parts(note)
        assert row["note_parts"]["kind"] == "expected"

    def test_a_note_no_builder_writes_reads_as_none(self) -> None:
        table, _ = _served_table([_row("cpa", "hand-written")])
        assert table["metrics"][0]["note_parts"] is None

    def test_a_note_that_is_not_a_string_reads_as_none(self) -> None:
        table, _ = _served_table([_row("cpa", 5), _row("ctr", None)])
        assert [r["note_parts"] for r in table["metrics"]] == [None, None]

    def test_a_row_that_is_not_an_object_is_passed_through(self) -> None:
        table, _ = _served_table(["junk", _row("cpa", "lower_is_better; -20%")])
        assert table["metrics"][0] == "junk"
        assert table["metrics"][1]["note_parts"]["kind"] == "direction"

    def test_rows_that_are_not_a_list_are_passed_through(self) -> None:
        table, _ = _served_table({"cpa": 1})
        assert table["metrics"] == {"cpa": 1}

    def test_the_stored_table_is_not_touched(self) -> None:
        rows = [_row("cpa", "lower_is_better; -20%", "primary")]
        document = _document()
        document["action_log"][2]["evaluation"] = {
            **_table("improved"),
            "metrics": rows,
        }
        doc = parse_state(json.dumps(document))
        stored = copy.deepcopy(doc.action_log[2].evaluation)
        build_ops_history_items(doc, today=TODAY)
        assert doc.action_log[2].evaluation == stored
        assert "note_parts" not in doc.action_log[2].evaluation["metrics"][0]

    def test_no_table_stays_none(self) -> None:
        action = _items()["C"]["actions"][0]
        assert action["evaluation"] is None


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from mureo.core import clock
    from mureo.core.runtime_context import reset_runtime_context

    monkeypatch.chdir(tmp_path)
    reset_runtime_context()
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "J.jsonl")
    monkeypatch.setattr(
        clock,
        "server_now",
        lambda: __import__("datetime").datetime(2026, 10, 14, 12, 0).astimezone(),
    )
    (tmp_path / "STATE.json").write_text(json.dumps(_document()), encoding="utf-8")
    yield tmp_path
    reset_runtime_context()


class TestBuildOpsHistory:
    def test_the_feed(self, workspace: Path) -> None:
        from mureo.web.reports import build_ops_history

        feed = build_ops_history(since="2026-10-01")
        assert feed["since"] == "2026-10-01"
        assert feed["until"] is None
        assert feed["enabled"] is False
        assert feed["server_today"] == "2026-10-14"
        ids = [i["decision"]["decision_id"] for i in feed["items"]]
        assert ids == ["A", "C", "B"]

    def test_a_bad_bound_is_refused(self, workspace: Path) -> None:
        from mureo.web.reports import build_ops_history

        with pytest.raises(ValueError, match="since"):
            build_ops_history(since="yesterday")
        with pytest.raises(ValueError, match="before"):
            build_ops_history(since="2026-10-05", until="2026-10-01")

    def test_a_missing_document_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.core.runtime_context import reset_runtime_context
        from mureo.web.reports import build_ops_history

        monkeypatch.chdir(tmp_path)
        reset_runtime_context()
        assert build_ops_history()["items"] == []
        reset_runtime_context()


class TestHistoryQuerySources:
    async def _query(self, **arguments: Any) -> dict[str, Any]:
        from mureo.mcp.server import handle_call_tool

        result = await handle_call_tool("mureo_history_query", arguments)
        return json.loads(result[0].text)

    async def test_ops_history_includes_uncovered_changes(
        self, workspace: Path
    ) -> None:
        payload = await self._query(sources=["ops_history"])
        section = payload["ops_history"]
        assert section["matched"] == 6
        assert any(item["decision"] is None for item in section["items"])

    async def test_decisions_only_has_decisions(self, workspace: Path) -> None:
        payload = await self._query(sources=["decisions"], limit=2)
        section = payload["decisions"]
        assert section["matched"] == 5
        assert section["returned"] == 2
        assert section["truncated"] is True
        assert all(item["decision"] for item in section["items"])

    async def test_filters_apply(self, workspace: Path) -> None:
        payload = await self._query(
            sources=["decisions"], campaign_id="c1", since="2026-09-15"
        )
        ids = [i["decision"]["decision_id"] for i in payload["decisions"]["items"]]
        assert ids == ["C", "D"]


class TestWindowMatchesActionLog:
    """The two ops sources bound by date exactly as ``action_log`` does."""

    @pytest.fixture
    def boundary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        from mureo.core.runtime_context import reset_runtime_context

        monkeypatch.chdir(tmp_path)
        reset_runtime_context()
        monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "J.jsonl")
        document = {
            "version": "2",
            "action_log": [_action(timestamp="2026-10-14T08:00:00+09:00")],
        }
        (tmp_path / "STATE.json").write_text(json.dumps(document), encoding="utf-8")
        yield tmp_path
        reset_runtime_context()

    @pytest.mark.parametrize("day", ["2026-10-13", "2026-10-14"])
    async def test_the_boundary(self, boundary: Path, day: str) -> None:
        from mureo.mcp.server import handle_call_tool

        result = await handle_call_tool(
            "mureo_history_query",
            {"sources": ["action_log", "ops_history"], "since": day, "until": day},
        )
        payload = json.loads(result[0].text)
        assert payload["ops_history"]["matched"] == payload["action_log"]["matched"]


def test_the_dashboard_feed_does_not_reach_into_the_mcp_layer() -> None:
    import ast
    import inspect

    from mureo.web import reports

    tree = ast.parse(inspect.getsource(reports))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(m.startswith("mureo.mcp") for m in modules)
