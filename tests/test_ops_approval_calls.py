"""``approval`` on mutating calls and on the recording tool (#854).

The dispatcher splits ``approval`` off a change-making call exactly as it
splits ``expected``, refuses a malformed one as ``invalid_args`` before the
platform is called, and never requires it. A call that writes an
``action_log`` entry puts it on the entry; a call that writes none puts it
on the decision recorded for the call.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.types import TextContent, Tool

from mureo.context.approval import parse_approval
from mureo.context.decisions import DecisionRecord
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.ops_linkage import LinkRequest, link_entry
from mureo.context.settings_store import set_ops_history_enabled
from mureo.context.state import read_state_file, write_state_file
from mureo.mcp import journal
from mureo.mcp._ops_history_param import (
    APPROVAL_PARAM,
    APPROVAL_PROPERTY,
    split_ops_params,
    with_ops_properties,
)

pytestmark = pytest.mark.unit

STATUS_TOOL = "google_ads_campaigns_update_status"
BUDGET_TOOL = "google_ads_budget_update"
CPA_DOWN = [{"metric": "cpa", "direction": "down"}]
APPROVAL = {
    "reference": "REQ-42",
    "approved_by": "Jane Operator",
    "approved_at": "2026-10-17T09:30:00+09:00",
}


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    yield tmp_path
    reset_runtime_context()


@pytest.fixture
def handler(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
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


def _last_journal(workspace: Path) -> dict[str, Any]:
    lines = (workspace / "J.jsonl").read_text(encoding="utf-8").splitlines()
    return dict(json.loads(lines[-1]))


def _status(**extra: Any) -> dict[str, Any]:
    return {"campaign_id": "123", "status": "ENABLED", **extra}


def _budget(**extra: Any) -> dict[str, Any]:
    return {"budget_id": "b1", "amount": 12000, **extra}


def _proposal(path: Path) -> None:
    record = DecisionRecord(
        decision_id="dec-p",
        recorded_at="2026-10-13T10:00:00+09:00",
        status="proposed",
        title="Raise budget b1",
        rationale="Capped by noon.",
        expected=CPA_DOWN,
    )
    doc = read_state_file(path)
    write_state_file(path, replace(doc, decisions=(record,)))


class TestSchema:
    def _served(self) -> dict[str, Tool]:
        from mureo.mcp import server

        return {tool.name: tool for tool in server._ALL_TOOLS}

    def test_every_tool_in_scope_declares_it(self) -> None:
        from mureo.mcp import server

        served = self._served()
        assert STATUS_TOOL in server._OPS_TOOLS
        assert "mureo_batch_begin" in server._OPS_TOOLS
        for name in server._OPS_TOOLS:
            assert APPROVAL_PARAM in served[name].inputSchema["properties"], name

    def test_its_shape(self) -> None:
        schema = self._served()[STATUS_TOOL].inputSchema
        prop = schema["properties"][APPROVAL_PARAM]
        assert prop["type"] == "object"
        assert sorted(prop["properties"]) == [
            "approved_at",
            "approved_by",
            "reference",
        ]
        for value in prop["properties"].values():
            assert value["type"] == "string"
        assert prop["required"] == ["reference", "approved_by", "approved_at"]
        assert prop["additionalProperties"] is False
        assert prop["description"] == (
            "External approval this change carries out "
            "(recorded and shown, never verified)"
        )
        assert APPROVAL_PARAM not in schema.get("required", [])

    @pytest.mark.parametrize(
        "name",
        [
            "rollback_apply",
            "mureo_state_display_set",
            "mureo_batch_end",
            "google_ads_campaigns_list",
        ],
    )
    def test_out_of_scope_tools_do_not(self, name: str) -> None:
        properties = self._served()[name].inputSchema.get("properties", {})
        assert APPROVAL_PARAM not in properties

    def test_each_tool_gets_its_own_copy(self) -> None:
        served = self._served()
        first = served[STATUS_TOOL].inputSchema["properties"][APPROVAL_PARAM]
        second = served[BUDGET_TOOL].inputSchema["properties"][APPROVAL_PARAM]
        assert first == second
        assert first is not second
        assert first["properties"] is not second["properties"]

    def test_a_tool_declaring_its_own_approval_is_left_alone(self) -> None:
        own = {"type": "string", "description": "The tool's own field."}
        tool = Tool(
            name="x_update",
            description="x",
            inputSchema={"type": "object", "properties": {APPROVAL_PARAM: own}},
        )
        assert with_ops_properties(tool) is tool
        assert tool.inputSchema["properties"] == {APPROVAL_PARAM: own}


class TestBounds:
    def test_the_schema_states_each_length_limit(self) -> None:
        props = APPROVAL_PROPERTY["properties"]
        assert props["reference"]["maxLength"] == 128
        assert props["approved_by"]["maxLength"] == 80
        assert props["approved_at"]["maxLength"] == 64

    def test_the_limits_match_the_server_side_bounds(self) -> None:
        from mureo.context.approval import (
            APPROVAL_AT_MAX_CHARS,
            APPROVAL_BY_MAX_CHARS,
            APPROVAL_REFERENCE_MAX_CHARS,
        )

        props = APPROVAL_PROPERTY["properties"]
        assert props["reference"]["maxLength"] == APPROVAL_REFERENCE_MAX_CHARS
        assert props["approved_by"]["maxLength"] == APPROVAL_BY_MAX_CHARS
        assert props["approved_at"]["maxLength"] == APPROVAL_AT_MAX_CHARS


class TestSplit:
    def test_it_is_popped_from_a_copy(self) -> None:
        args = _status(approval=APPROVAL)
        params, rest = split_ops_params(STATUS_TOOL, args, {STATUS_TOOL})
        assert rest == _status()
        assert APPROVAL_PARAM in args
        assert params.approval == parse_approval(APPROVAL)

    def test_absent_is_none(self) -> None:
        params, _ = split_ops_params(STATUS_TOOL, _status(), {STATUS_TOOL})
        assert params.approval is None

    def test_outside_scope_is_untouched(self) -> None:
        args = {APPROVAL_PARAM: "anything"}
        params, rest = split_ops_params("other", args, {STATUS_TOOL})
        assert rest is args
        assert params.approval is None

    def test_malformed_is_refused(self) -> None:
        bad = {**APPROVAL, "reference": "REQ 42"}
        with pytest.raises(ValueError, match="approval.reference"):
            split_ops_params(STATUS_TOOL, _status(approval=bad), {STATUS_TOOL})


class TestCallWithEntry:
    async def test_the_entry_carries_it(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            STATUS_TOOL,
            _status(reason="Policy fixed.", expected=CPA_DOWN, approval=APPROVAL),
        )
        assert handler == [_status()]
        doc = read_state_file(workspace / "STATE.json")
        assert doc.action_log[0].approval == parse_approval(APPROVAL)
        assert doc.decisions[0].approval == parse_approval(APPROVAL)
        assert "approval" not in (doc.action_log[0].applied_params or {})

    async def test_without_a_reason_the_entry_still_carries_it(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(STATUS_TOOL, _status(approval=APPROVAL))
        doc = read_state_file(workspace / "STATE.json")
        assert doc.action_log[0].approval == parse_approval(APPROVAL)
        assert doc.decisions == ()

    async def test_without_it_the_entry_has_none(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(STATUS_TOOL, _status(reason="Policy fixed."))
        stored = json.loads((workspace / "STATE.json").read_text(encoding="utf-8"))
        assert "approval" not in stored["action_log"][0]
        assert "approval" not in stored["decisions"][0]

    async def test_adopting_a_proposal_puts_it_on_the_adoption(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _proposal(path)
        await _call(STATUS_TOOL, _status(decision_id="dec-p", approval=APPROVAL))
        doc = read_state_file(path)
        assert [r.status for r in doc.decisions] == ["proposed", "adopted"]
        assert doc.decisions[0].approval is None
        assert doc.decisions[1].approval == parse_approval(APPROVAL)
        assert doc.action_log[0].approval == parse_approval(APPROVAL)


class TestCallWithoutEntry:
    async def test_the_decision_carries_it(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            BUDGET_TOOL,
            _budget(reason="Capped.", expected=CPA_DOWN, approval=APPROVAL),
        )
        assert handler == [_budget()]
        doc = read_state_file(workspace / "STATE.json")
        assert doc.action_log == ()
        assert doc.decisions[0].approval == parse_approval(APPROVAL)
        assert doc.decisions[0].applied_params == _budget()

    async def test_adopting_a_proposal_puts_it_on_the_adoption(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _proposal(path)
        await _call(BUDGET_TOOL, _budget(decision_id="dec-p", approval=APPROVAL))
        doc = read_state_file(path)
        assert [r.status for r in doc.decisions] == ["proposed", "adopted"]
        assert doc.decisions[1].approval == parse_approval(APPROVAL)

    async def test_without_a_reason_it_still_gets_a_decision(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(approval=APPROVAL))
        assert handler == [_budget()]
        doc = read_state_file(workspace / "STATE.json")
        assert doc.action_log == ()
        assert len(doc.decisions) == 1
        record = doc.decisions[0]
        assert record.status == "adopted"
        assert record.approval == parse_approval(APPROVAL)
        # A decision needs a rationale; with none stated, it says which
        # approval the change carried out, and nothing it cannot know.
        assert record.rationale == "Carried out under external approval REQ-42."
        assert record.journal_tool == BUDGET_TOOL
        assert record.applied_params == _budget()
        assert _last_journal(workspace)["decision_id"] == record.decision_id

    async def test_without_a_reason_or_an_approval_it_records_nothing(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget())
        assert read_state_file(workspace / "STATE.json").decisions == ()

    async def test_a_batch_opened_with_it_carries_it(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            "mureo_batch_begin",
            {
                "label": "Weekly pass",
                "reason": "Cleanup.",
                "expected": CPA_DOWN,
                "approval": APPROVAL,
            },
        )
        doc = read_state_file(workspace / "STATE.json")
        assert doc.decisions[0].approval == parse_approval(APPROVAL)


class TestRefusal:
    @pytest.mark.parametrize(
        "value",
        [
            {**APPROVAL, "reference": "REQ 42"},
            {**APPROVAL, "approved_at": "yesterday"},
            {**APPROVAL, "approved_by": "Jane\x00"},
            {**APPROVAL, "note": "extra"},
            {"reference": "REQ-42"},
            "REQ-42",
        ],
    )
    async def test_malformed_is_invalid_args_before_the_platform(
        self, workspace: Path, handler: list[dict[str, Any]], value: Any
    ) -> None:
        with pytest.raises(ValueError, match="approval"):
            await _call(BUDGET_TOOL, _budget(reason="Capped.", approval=value))
        assert handler == []
        assert _last_journal(workspace)["outcome"] == "invalid_args"
        doc = read_state_file(workspace / "STATE.json")
        assert doc.decisions == ()
        assert doc.action_log == ()

    async def test_never_required_while_ops_history_is_on(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        set_ops_history_enabled(workspace / "STATE.json", True)
        await _call(STATUS_TOOL, _status(reason="Fixed.", expected=CPA_DOWN))
        assert len(handler) == 1
        doc = read_state_file(workspace / "STATE.json")
        assert doc.action_log[0].approval is None


def _entry(**extra: Any) -> dict[str, Any]:
    return {
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        "campaign_id": "123",
        **extra,
    }


class TestActionLogAppend:
    async def test_the_entry_field_is_recorded(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            "mureo_state_action_log_append",
            {"entry": _entry(reason="Capped.", approval=APPROVAL)},
        )
        doc = read_state_file(workspace / "STATE.json")
        assert doc.action_log[0].approval == parse_approval(APPROVAL)
        assert doc.decisions[0].approval == parse_approval(APPROVAL)

    def test_the_schema_declares_it(self) -> None:
        from mureo.mcp import server

        tool = next(
            t for t in server._ALL_TOOLS if t.name == "mureo_state_action_log_append"
        )
        entry = tool.inputSchema["properties"]["entry"]
        prop = entry["properties"][APPROVAL_PARAM]
        assert prop["type"] == "object"
        assert prop["additionalProperties"] is False
        assert APPROVAL_PARAM not in tool.inputSchema["properties"]

    @pytest.mark.parametrize(
        "value",
        [{**APPROVAL, "reference": "REQ/42"}, {**APPROVAL, "approved_at": "soon"}],
    )
    async def test_a_malformed_entry_field_is_refused(
        self, workspace: Path, value: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="approval"):
            await _call(
                "mureo_state_action_log_append",
                {"entry": _entry(approval=value)},
            )
        assert read_state_file(workspace / "STATE.json").action_log == ()


class TestLinkEntry:
    NOW = "2026-10-17T10:00:00+09:00"

    def _entry(self, **extra: Any) -> ActionLogEntry:
        fields: dict[str, Any] = {
            "timestamp": self.NOW,
            "action": STATUS_TOOL,
            "platform": "google_ads",
            "campaign_id": "123",
            "reason": "Policy fixed.",
            **extra,
        }
        return ActionLogEntry(**fields)

    def test_the_entrys_own_approval_wins_on_entry_and_decision(self) -> None:
        own = parse_approval({**APPROVAL, "reference": "REQ-own"})
        call = parse_approval(APPROVAL)
        request = LinkRequest(reason="Policy fixed.", now=self.NOW, approval=call)
        doc, linked = link_entry(
            StateDocument(version="2"), self._entry(approval=own), request
        )
        assert linked.approval == own
        assert [r.approval for r in doc.decisions] == [own]

    def test_without_its_own_the_entry_takes_the_calls(self) -> None:
        call = parse_approval(APPROVAL)
        request = LinkRequest(reason="Policy fixed.", now=self.NOW, approval=call)
        doc, linked = link_entry(StateDocument(version="2"), self._entry(), request)
        assert linked.approval == call
        assert [r.approval for r in doc.decisions] == [call]


class TestJoiningACallsDecision:
    """Rule 6: an entry that records a no-entry call's change joins that
    call's decision. The decision was written by the call; an approval only
    the entry states stays on the entry (documented current behaviour)."""

    async def test_the_entrys_approval_is_not_added_to_the_decision(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=CPA_DOWN))
        await _call(
            "mureo_state_action_log_append",
            {
                "entry": {
                    "action": BUDGET_TOOL,
                    "platform": "google_ads",
                    "entity_type": "budget",
                    "entity_id": "b1",
                    "reason": "Capped.",
                    "approval": APPROVAL,
                }
            },
        )
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 1
        assert doc.action_log[0].decision_id == doc.decisions[0].decision_id
        assert doc.action_log[0].approval == parse_approval(APPROVAL)
        assert doc.decisions[0].approval is None
