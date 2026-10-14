"""The ops history join and its two read surfaces (#848).

``build_ops_history`` (the dashboard feed) and the ``decisions`` /
``ops_history`` sources of ``mureo_history_query`` return the same items:
one per decision with its changes and their evaluation, plus one per change
no decision covers, each with a DERIVED state.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

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
        items = _items(since=date(2026, 10, 1), until=date(2026, 10, 5))
        assert set(items) == {"B", "C"}

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

    def test_an_empty_document(self) -> None:
        assert build_ops_history_items(parse_state("{}"), today=TODAY) == []


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
