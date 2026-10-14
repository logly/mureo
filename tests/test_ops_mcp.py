"""``expected`` / ``decision_id`` on mutating tools, end to end (#848).

The dispatcher splits both parameters off the call, binds them to the task
for the action-log choke point, and — when the workspace switched ops
history on — refuses a change that does not say why and what should move.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.types import TextContent

from mureo.context.decisions import DecisionRecord
from mureo.context.expected import EXPECTED_DIRECTIONS, EXPECTED_METRICS
from mureo.context.models import StateDocument
from mureo.context.settings import set_ops_history_enabled
from mureo.context.state import read_state_file, write_state_file
from mureo.mcp import journal
from mureo.mcp._ops_history_param import (
    DECISION_ID_PARAM,
    EXPECTED_PARAM,
    EXPECTED_REQUIRED,
    REASON_REQUIRED,
    split_ops_params,
)

pytestmark = pytest.mark.unit

STATUS_TOOL = "google_ads_campaigns_update_status"
BUDGET_TOOL = "google_ads_budget_update"
CPA_DOWN = [{"metric": "cpa", "direction": "down"}]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace with an empty STATE.json, and a fake platform."""
    from mureo.core.runtime_context import reset_runtime_context
    from mureo.mcp import server

    monkeypatch.chdir(tmp_path)
    reset_runtime_context()
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "J.jsonl")
    monkeypatch.setattr(server, "_evaluate_policy_gates", lambda n, a: None)
    monkeypatch.setattr(
        server, "capture_before_state", AsyncMock(return_value="PAUSED")
    )
    write_state_file(tmp_path / "STATE.json", StateDocument(version="2"))
    return tmp_path


@pytest.fixture
def handler(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the Google Ads handler; record what it was called with."""
    from mureo.mcp import server

    seen: list[dict[str, Any]] = []

    async def _handle(name: str, arguments: dict[str, Any]) -> list[Any]:
        seen.append(dict(arguments))
        return [TextContent(type="text", text=json.dumps({"ok": True}))]

    monkeypatch.setattr(server, "handle_google_ads_tool", _handle)
    return seen


async def _call(name: str, arguments: dict[str, Any]) -> list[Any]:
    from mureo.mcp.server import handle_call_tool

    return await handle_call_tool(name, arguments)


def _status_args(**extra: Any) -> dict[str, Any]:
    return {"campaign_id": "123", "status": "ENABLED", **extra}


def _proposal(path: Path) -> None:
    doc = read_state_file(path)
    record = DecisionRecord(
        decision_id="dec-p",
        recorded_at="2026-10-13T10:00:00+09:00",
        status="proposed",
        title="Resume campaign 123",
        rationale="Paused by mistake.",
        expected=CPA_DOWN,
    )
    from dataclasses import replace

    write_state_file(path, replace(doc, decisions=(record,)))


class TestSchema:
    def _served(self) -> dict[str, Any]:
        from mureo.mcp import server

        return {tool.name: tool for tool in server._ALL_TOOLS}

    def test_change_tools_declare_both(self) -> None:
        from mureo.mcp import server

        served = self._served()
        assert STATUS_TOOL in server._OPS_TOOLS
        for name in server._OPS_TOOLS:
            properties = served[name].inputSchema["properties"]
            assert EXPECTED_PARAM in properties
            assert DECISION_ID_PARAM in properties

    def test_batch_begin_is_in_scope(self) -> None:
        from mureo.mcp import server

        assert "mureo_batch_begin" in server._OPS_TOOLS

    @pytest.mark.parametrize(
        "name",
        [
            "rollback_apply",
            "mureo_state_display_set",
            "mureo_batch_end",
            "mureo_state_action_log_append",
            "google_ads_campaigns_list",
        ],
    )
    def test_out_of_scope(self, name: str) -> None:
        from mureo.mcp import server

        assert name not in server._OPS_TOOLS

    def test_the_injected_expected_has_no_item_schema(self) -> None:
        schema = self._served()[STATUS_TOOL].inputSchema["properties"]
        assert schema[EXPECTED_PARAM]["type"] == "array"
        assert "items" not in schema[EXPECTED_PARAM]

    def test_the_description_states_the_shape_and_vocabulary(self) -> None:
        text = self._served()[STATUS_TOOL].inputSchema["properties"][EXPECTED_PARAM][
            "description"
        ]
        assert "[{metric, direction, target?, horizon_days?}]" in text
        for word in (*EXPECTED_METRICS, *EXPECTED_DIRECTIONS):
            assert word in text, word
        assert text.count(". ") == 0

    def test_the_decision_id_description_is_one_short_sentence(self) -> None:
        schema = self._served()[STATUS_TOOL].inputSchema["properties"]
        text = schema[DECISION_ID_PARAM]["description"]
        assert len(text) <= 120
        assert text.count(". ") == 0

    def test_the_recording_tools_keep_the_full_item_schema(self) -> None:
        tool = self._served()["mureo_decision_record"]
        items = tool.inputSchema["properties"][EXPECTED_PARAM]["items"]
        assert "cpa" in items["properties"]["metric"]["enum"]
        assert items["properties"]["direction"]["enum"] == ["up", "down", "hold"]
        assert items["additionalProperties"] is False


class TestSplit:
    def test_both_are_popped_from_a_copy(self) -> None:
        args = _status_args(expected=CPA_DOWN, decision_id="dec-1")
        params, rest = split_ops_params(STATUS_TOOL, args, {STATUS_TOOL})
        assert rest == _status_args()
        assert "expected" in args
        assert params.decision_id == "dec-1"
        assert params.expected[0].metric == "cpa"

    def test_outside_scope_is_untouched(self) -> None:
        args = {"expected": "x"}
        params, rest = split_ops_params("other", args, {STATUS_TOOL})
        assert rest is args
        assert params.expected == ()

    @pytest.mark.parametrize(
        ("value", "match"),
        [
            ({"expected": [{"metric": "cpa_7d", "direction": "down"}]}, "cpa_7d"),
            ({"expected": "cpa"}, "array"),
            ({"decision_id": " "}, "decision_id"),
            ({"decision_id": 5}, "decision_id"),
        ],
    )
    def test_malformed_is_refused(self, value: dict[str, Any], match: str) -> None:
        with pytest.raises(ValueError, match=match):
            split_ops_params(STATUS_TOOL, _status_args(**value), {STATUS_TOOL})


class TestAutoDecision:
    async def test_a_reasoned_change_creates_a_decision(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            STATUS_TOOL,
            _status_args(reason="Policy issue fixed.", expected=CPA_DOWN),
        )
        assert handler == [_status_args()]
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 1
        record = doc.decisions[0]
        assert record.status == "adopted"
        assert record.rationale == "Policy issue fixed."
        assert "status PAUSED → ENABLED" in record.title
        assert doc.action_log[0].decision_id == record.decision_id

    async def test_disabled_accepts_a_bare_change(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(STATUS_TOOL, _status_args())
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.action_log) == 1
        assert doc.decisions == ()


class TestEnabled:
    @pytest.mark.parametrize(
        ("extra", "message"),
        [
            ({"expected": CPA_DOWN}, REASON_REQUIRED),
            ({"reason": "Because."}, EXPECTED_REQUIRED),
        ],
    )
    async def test_a_missing_parameter_is_refused(
        self,
        workspace: Path,
        handler: list[dict[str, Any]],
        extra: dict[str, Any],
        message: str,
    ) -> None:
        set_ops_history_enabled(workspace / "STATE.json", True)
        with pytest.raises(ValueError) as caught:
            await _call(STATUS_TOOL, _status_args(**extra))
        assert str(caught.value) == message
        assert handler == []
        assert read_state_file(workspace / "STATE.json").action_log == ()
        record = json.loads((workspace / "J.jsonl").read_text().splitlines()[-1])
        assert record["outcome"] == "invalid_args"

    @pytest.mark.parametrize(
        "item",
        [
            {"metric": "cpa_7d", "direction": "down"},
            {"metric": "cpa", "direction": "lower"},
            {"metric": "cpa", "direction": "down", "horizon": 7},
            "cpa",
        ],
    )
    async def test_a_malformed_item_is_refused_by_the_server(
        self, workspace: Path, handler: list[dict[str, Any]], item: Any
    ) -> None:
        with pytest.raises(ValueError):
            await _call(STATUS_TOOL, _status_args(reason="R.", expected=[item]))
        assert handler == []
        record = json.loads((workspace / "J.jsonl").read_text().splitlines()[-1])
        assert record["outcome"] == "invalid_args"

    async def test_both_given_is_accepted(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        set_ops_history_enabled(workspace / "STATE.json", True)
        await _call(STATUS_TOOL, _status_args(reason="Fixed.", expected=CPA_DOWN))
        assert len(handler) == 1

    async def test_a_batch_member_joins_the_batch_decision(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        set_ops_history_enabled(workspace / "STATE.json", True)
        await _call(
            "mureo_batch_begin",
            {"label": "Cleanup", "reason": "Weekly pass.", "expected": CPA_DOWN},
        )
        await _call(STATUS_TOOL, _status_args())
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 1
        assert doc.action_log[0].decision_id == doc.decisions[0].decision_id

    async def test_a_batch_begin_needs_both(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        set_ops_history_enabled(workspace / "STATE.json", True)
        with pytest.raises(ValueError, match="expected is required"):
            await _call("mureo_batch_begin", {"label": "x", "reason": "y"})

    async def test_an_explicit_decision_satisfies_the_requirement(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _proposal(path)
        set_ops_history_enabled(path, True)
        await _call(STATUS_TOOL, _status_args(decision_id="dec-p"))
        doc = read_state_file(path)
        assert [r.status for r in doc.decisions] == ["proposed", "adopted"]
        assert doc.action_log[0].decision_id == "dec-p"


class TestExplicitDecisionId:
    async def test_an_unknown_id_is_refused_before_the_handler(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        with pytest.raises(ValueError, match="no recorded decision"):
            await _call(STATUS_TOOL, _status_args(decision_id="dec-missing"))
        assert handler == []

    async def test_a_change_with_no_entry_still_adopts_the_proposal(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _proposal(path)
        await _call(
            BUDGET_TOOL,
            {"budget_id": "b1", "amount": 12000, "decision_id": "dec-p"},
        )
        doc = read_state_file(path)
        assert [r.status for r in doc.decisions] == ["proposed", "adopted"]
        assert doc.action_log == ()

    async def test_a_failed_change_adopts_nothing(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp import server

        async def _error(name: str, arguments: dict[str, Any]) -> list[Any]:
            return [TextContent(type="text", text="API error: PERMISSION_DENIED")]

        monkeypatch.setattr(server, "handle_google_ads_tool", _error)
        path = workspace / "STATE.json"
        _proposal(path)
        await _call(
            BUDGET_TOOL,
            {"budget_id": "b1", "amount": 12000, "decision_id": "dec-p"},
        )
        assert len(read_state_file(path).decisions) == 1


class TestUnreadableState:
    """A STATE.json that cannot be read must not block changes that were
    accepted before ops history existed; the setting cannot be on for a
    document nobody can read. An explicit decision_id still cannot be
    checked against it, so that call is refused."""

    async def test_a_change_goes_through(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        (workspace / "STATE.json").write_text("{not json", encoding="utf-8")
        await _call(BUDGET_TOOL, {"budget_id": "b1", "amount": 12000})
        assert handler == [{"budget_id": "b1", "amount": 12000}]

    @pytest.mark.parametrize(
        "content",
        [
            b"[]",
            b'{"platforms": []}',
            b'{"platforms": {"google_ads": "x"}}',
            b'{"version": "2", "action_log": [], "note": "\xff\xfe"}',
        ],
        ids=["list", "platforms-list", "platform-string", "invalid-utf8"],
    )
    async def test_a_malformed_document_does_not_block_a_change(
        self, workspace: Path, handler: list[dict[str, Any]], content: bytes
    ) -> None:
        (workspace / "STATE.json").write_bytes(content)
        await _call(BUDGET_TOOL, {"budget_id": "b1", "amount": 12000})
        assert handler == [{"budget_id": "b1", "amount": 12000}]
        record = json.loads((workspace / "J.jsonl").read_text().splitlines()[-1])
        assert record["outcome"] == "ok"

    @pytest.mark.parametrize("content", [b"[]", b"\xff\xfe{}"])
    async def test_a_malformed_document_refuses_a_decision_id(
        self, workspace: Path, handler: list[dict[str, Any]], content: bytes
    ) -> None:
        (workspace / "STATE.json").write_bytes(content)
        with pytest.raises(ValueError, match="could not be read"):
            await _call(
                BUDGET_TOOL,
                {"budget_id": "b1", "amount": 12000, "decision_id": "dec-p"},
            )
        assert handler == []

    async def test_an_explicit_decision_id_is_refused(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        (workspace / "STATE.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="could not be read"):
            await _call(
                BUDGET_TOOL,
                {"budget_id": "b1", "amount": 12000, "decision_id": "dec-p"},
            )
        assert handler == []
