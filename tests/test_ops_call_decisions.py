"""Decisions for changes that write no ``action_log`` entry, and the only
joins mureo makes without an explicit id (#848).

A budget, bid, keyword or creative change on a native platform writes no
``action_log`` entry of its own, so the action-log choke point never sees
it. The dispatcher records its decision after the call succeeded instead,
links it to the call's journal record, and stores the parameters the call
actually sent.

A change is never attached to an earlier decision by guesswork: a wrong
link is worse than a visible duplicate. Without an explicit id, the one
join is an agent's own ``action_log`` entry for a no-entry call, matched
exactly on session, tool and every target id the call sent.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.types import TextContent

from mureo.context.decisions import DecisionRecord
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.settings_store import set_ops_history_enabled
from mureo.context.state import append_action_log, read_state_file, write_state_file
from mureo.mcp import journal

pytestmark = pytest.mark.unit

STATUS_TOOL = "google_ads_campaigns_update_status"
BUDGET_TOOL = "google_ads_budget_update"
CPA_DOWN = [{"metric": "cpa", "direction": "down"}]
SPEND_UP = [{"metric": "spend", "direction": "up"}]


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


def _journal(workspace: Path) -> list[dict[str, Any]]:
    lines = (workspace / "J.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _budget(**extra: Any) -> dict[str, Any]:
    return {"budget_id": "b1", "amount": 12000, **extra}


def _status(**extra: Any) -> dict[str, Any]:
    return {"campaign_id": "123", "status": "ENABLED", **extra}


def _session() -> str:
    from mureo.core.actor import session_id

    return session_id()


def _write_decisions(path: Path, *records: DecisionRecord) -> None:
    doc = read_state_file(path)
    write_state_file(path, replace(doc, decisions=(*doc.decisions, *records)))


def _record(decision_id: str, status: str, **extra: Any) -> DecisionRecord:
    fields: dict[str, Any] = {
        "decision_id": decision_id,
        "recorded_at": "2026-10-13T10:00:00+00:00",
        "status": status,
        "title": f"Decision {decision_id}",
        "rationale": "Because.",
        **extra,
    }
    return DecisionRecord(**fields)


class TestNoEntryCall:
    async def test_one_budget_call_records_its_decision(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            BUDGET_TOOL,
            _budget(reason="Capped by 11:00 for nine days.", expected=SPEND_UP),
        )
        assert handler == [_budget()]
        doc = read_state_file(workspace / "STATE.json")
        assert doc.action_log == ()
        assert len(doc.decisions) == 1
        record = doc.decisions[0]
        assert record.status == "adopted"
        assert record.rationale == "Capped by 11:00 for nine days."
        assert record.title == "google_ads_budget_update budget b1: amount 12,000"
        assert record.applied_params == {"budget_id": "b1", "amount": 12000}
        assert [e.metric for e in record.expected] == ["spend"]
        assert record.platform == "google_ads"
        assert record.journal_tool == BUDGET_TOOL

    async def test_the_journal_record_and_the_decision_name_each_other(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=SPEND_UP))
        record = read_state_file(workspace / "STATE.json").decisions[0]
        line = _journal(workspace)[-1]
        assert line["decision_id"] == record.decision_id
        assert line["call_id"] == record.journal_call_id
        assert record.journal_call_id

    async def test_a_call_without_a_reason_records_nothing(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(expected=SPEND_UP))
        assert read_state_file(workspace / "STATE.json").decisions == ()
        line = _journal(workspace)[-1]
        assert "decision_id" not in line
        assert "call_id" not in line

    async def test_a_failed_call_records_nothing(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp import server

        async def _error(name: str, arguments: dict[str, Any]) -> list[Any]:
            return [TextContent(type="text", text="API error: PERMISSION_DENIED")]

        monkeypatch.setattr(server, "handle_google_ads_tool", _error)
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=SPEND_UP))
        assert read_state_file(workspace / "STATE.json").decisions == ()

    async def test_no_state_file_is_created(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        (workspace / "STATE.json").unlink()
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=SPEND_UP))
        assert handler == [_budget()]
        assert not (workspace / "STATE.json").exists()

    def test_secrets_in_the_parameters_are_masked(self) -> None:
        from mureo.mcp._ops_history_param import applied_params_of

        applied = applied_params_of({"budget_id": "b1", "developer_token": "x"})
        assert applied == {"budget_id": "b1", "developer_token": "***"}

    def test_oversized_parameters_are_not_stored(self) -> None:
        from mureo.mcp._ops_history_param import (
            APPLIED_PARAMS_MAX_CHARS,
            applied_params_of,
        )

        keys = {f"k{i}": "v" * 200 for i in range(APPLIED_PARAMS_MAX_CHARS // 100)}
        assert applied_params_of(keys) is None
        assert applied_params_of({}) is None

    async def test_one_decision_per_batch(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            "mureo_batch_begin",
            {"label": "Budgets", "reason": "Weekly pass.", "expected": SPEND_UP},
        )
        await _call(BUDGET_TOOL, _budget(reason="One.", expected=SPEND_UP))
        await _call(
            BUDGET_TOOL,
            {"budget_id": "b2", "amount": 9000, "reason": "Two.", "expected": SPEND_UP},
        )
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 1
        assert doc.decisions[0].title == "Batch: Budgets"
        lines = _journal(workspace)
        assert lines[-1]["decision_id"] == doc.decisions[0].decision_id
        assert lines[-2]["decision_id"] == doc.decisions[0].decision_id

    async def test_an_entry_call_is_still_linked_once(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(STATUS_TOOL, _status(reason="Fixed.", expected=CPA_DOWN))
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 1
        assert doc.action_log[0].decision_id == doc.decisions[0].decision_id
        assert doc.decisions[0].journal_call_id == _journal(workspace)[-1]["call_id"]


class TestAppliedParams:
    async def test_an_entry_carries_what_was_sent(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(STATUS_TOOL, _status(reason="Fixed.", expected=CPA_DOWN))
        entry = read_state_file(workspace / "STATE.json").action_log[0]
        assert entry.applied_params == _status()
        assert entry.reversible_params is not None

    async def test_an_entry_outside_a_call_has_none(self, workspace: Path) -> None:
        path = workspace / "STATE.json"
        append_action_log(
            path,
            ActionLogEntry(
                timestamp="2026-10-13T10:00:00+00:00",
                action="x",
                platform="google_ads",
            ),
        )
        assert read_state_file(path).action_log[0].applied_params is None


def _metrics(doc: StateDocument, decision_id: str | None) -> list[str]:
    record = next(r for r in doc.decisions if r.decision_id == decision_id)
    return [e.metric for e in record.expected]


class TestNoGuessedJoin:
    """A reasoned change gets its own decision unless it names one."""

    async def test_a_budget_decision_does_not_absorb_an_unrelated_change(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="Scale.", expected=SPEND_UP))
        await _call(
            STATUS_TOOL,
            {"campaign_id": "999", "status": "PAUSED", "reason": "Unrelated."}
            | {"expected": CPA_DOWN},
        )
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 2
        stamped = doc.action_log[0].decision_id
        assert stamped == doc.decisions[1].decision_id
        assert _metrics(doc, stamped) == ["cpa"]
        assert _journal(workspace)[-1]["decision_id"] == stamped

    async def test_an_adopted_record_does_not_absorb_a_change_on_its_campaign(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            "mureo_decision_record",
            {"status": "adopted", "title": "Raise budget c123", "rationale": "R."}
            | {"platform": "google_ads", "campaign_id": "123"}
            | {"expected": CPA_DOWN},
        )
        cost_down = [{"metric": "cost", "direction": "down"}]
        await _call(
            STATUS_TOOL, _status(reason="Policy violation.", expected=cost_down)
        )
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 2
        stamped = doc.action_log[0].decision_id
        assert stamped != doc.decisions[0].decision_id
        assert _metrics(doc, stamped) == ["cost"]

    async def test_a_platform_wide_record_does_not_absorb_a_budget_call(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            "mureo_decision_record",
            {"status": "adopted", "title": "Account-wide tweak", "rationale": "R."}
            | {"platform": "google_ads", "expected": CPA_DOWN},
        )
        await _call(
            BUDGET_TOOL,
            {"budget_id": "b9", "amount": 5, "reason": "Different thing."}
            | {"expected": SPEND_UP},
        )
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 2
        own = _journal(workspace)[-1]["decision_id"]
        assert own == doc.decisions[1].decision_id
        assert doc.decisions[1].supersedes is None
        assert _metrics(doc, own) == ["spend"]

    async def test_the_old_workflow_records_the_change_separately(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        session = _session()
        target = {"platform": "google_ads", "campaign_id": "123"}
        _write_decisions(
            path,
            _record("dec-p", "proposed", session_id=session, **target),
            _record(
                "dec-a", "adopted", supersedes="dec-p", session_id=session, **target
            ),
        )
        await _call(STATUS_TOOL, _status(reason="Approved.", expected=CPA_DOWN))
        doc = read_state_file(path)
        assert len(doc.decisions) == 3
        assert doc.action_log[0].decision_id == doc.decisions[2].decision_id

    async def test_a_carried_out_decision_is_not_joined_again(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        await _call(STATUS_TOOL, _status(reason="First.", expected=CPA_DOWN))
        await _call(STATUS_TOOL, _status(reason="Second.", expected=CPA_DOWN))
        doc = read_state_file(path)
        assert len(doc.decisions) == 2
        assert doc.action_log[0].decision_id != doc.action_log[1].decision_id


def _entry(**extra: Any) -> dict[str, Any]:
    """The agent's own entry for the budget change ``_budget()`` made."""
    return {
        "entry": {
            "action": BUDGET_TOOL,
            "platform": "google_ads",
            "entity_type": "budget",
            "entity_id": "b1",
            "reason": "Capped.",
            "metrics_at_action": {"spend": 10000},
            **extra,
        }
    }


class TestEntryForANoEntryCall:
    """Rule (b): the agent's own entry joins the call's decision only on an
    exact match of session, tool and every target id the call sent."""

    async def test_a_matching_entry_joins_the_calls_decision(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=SPEND_UP))
        await _call("mureo_state_action_log_append", _entry())
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 1
        assert doc.action_log[0].decision_id == doc.decisions[0].decision_id

    async def test_the_target_may_come_from_reversible_params(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=SPEND_UP))
        path = workspace / "STATE.json"
        append_action_log(
            path,
            ActionLogEntry(
                timestamp="2026-10-13T10:00:00+00:00",
                action=BUDGET_TOOL,
                platform="google_ads",
                reversible_params={
                    "operation": BUDGET_TOOL,
                    "params": {"budget_id": "b1", "amount": 10000},
                },
                session_id=_session(),
            ),
        )
        doc = read_state_file(path)
        assert len(doc.decisions) == 1
        assert doc.action_log[0].decision_id == doc.decisions[0].decision_id

    async def test_a_mismatching_target_id_gets_its_own_decision(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=SPEND_UP))
        await _call("mureo_state_action_log_append", _entry(entity_id="b2"))
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 2
        assert doc.action_log[0].decision_id == doc.decisions[1].decision_id

    async def test_another_tool_gets_its_own_decision(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=SPEND_UP))
        await _call("mureo_state_action_log_append", _entry(action=STATUS_TOOL))
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 2

    async def test_a_decision_that_has_an_entry_is_not_joined_again(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="Capped.", expected=SPEND_UP))
        await _call("mureo_state_action_log_append", _entry())
        await _call("mureo_state_action_log_append", _entry())
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 2
        assert doc.action_log[0].decision_id != doc.action_log[1].decision_id

    async def test_another_sessions_call_is_not_joined(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _write_decisions(
            path,
            _record(
                "dec-c",
                "adopted",
                session_id="other",
                journal_tool=BUDGET_TOOL,
                journal_call_id="call-0123456789abcdef",
                applied_params=_budget(),
            ),
        )
        await _call("mureo_state_action_log_append", _entry())
        assert read_state_file(path).action_log[0].decision_id != "dec-c"

    async def test_two_matching_calls_join_neither(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(BUDGET_TOOL, _budget(reason="One.", expected=SPEND_UP))
        await _call(BUDGET_TOOL, _budget(reason="Two.", expected=SPEND_UP))
        await _call("mureo_state_action_log_append", _entry())
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 3
        assert doc.action_log[0].decision_id == doc.decisions[2].decision_id

    async def test_a_call_naming_no_target_id_is_not_joined(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _write_decisions(
            path,
            _record(
                "dec-c",
                "adopted",
                session_id=_session(),
                journal_tool=BUDGET_TOOL,
                journal_call_id="call-0123456789abcdef",
                applied_params={"amount": 12000},
            ),
        )
        await _call("mureo_state_action_log_append", _entry())
        assert read_state_file(path).action_log[0].decision_id != "dec-c"


CAMPAIGN_TOOL = "google_ads_campaigns_update"


class TestEntryTargetMustBeNamedByTheCall:
    """The entry's own target must be among the ids the call sent: a call
    on campaign 1 is not joined by an entry about ad group 9 inside it."""

    @staticmethod
    def _campaign_call(path: Path) -> None:
        _write_decisions(
            path,
            _record(
                "dec-c",
                "adopted",
                session_id=_session(),
                journal_tool=CAMPAIGN_TOOL,
                journal_call_id="call-0123456789abcdef",
                applied_params={"campaign_id": "1", "status": "PAUSED"},
            ),
        )

    @staticmethod
    def _append(path: Path, **fields: Any) -> str | None:
        append_action_log(
            path,
            ActionLogEntry(
                timestamp="2026-10-13T10:00:00+00:00",
                action=CAMPAIGN_TOOL,
                platform="google_ads",
                session_id=_session(),
                **fields,
            ),
        )
        return read_state_file(path).action_log[-1].decision_id

    def test_an_entry_about_the_campaign_joins(self, workspace: Path) -> None:
        path = workspace / "STATE.json"
        self._campaign_call(path)
        assert self._append(path, campaign_id="1") == "dec-c"

    def test_an_entity_inside_the_campaign_is_not_joined(self, workspace: Path) -> None:
        path = workspace / "STATE.json"
        self._campaign_call(path)
        stamped = self._append(
            path, campaign_id="1", entity_type="ad_group", entity_id="9"
        )
        assert stamped != "dec-c"

    def test_an_extra_target_id_on_the_entry_is_not_joined(
        self, workspace: Path
    ) -> None:
        path = workspace / "STATE.json"
        self._campaign_call(path)
        stamped = self._append(
            path,
            campaign_id="1",
            reversible_params={
                "operation": CAMPAIGN_TOOL,
                "params": {"campaign_id": "1", "ad_group_id": "9"},
            },
        )
        assert stamped != "dec-c"


class TestNoWorkWithoutAReason:
    async def test_a_bare_call_reads_no_state(
        self,
        workspace: Path,
        handler: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mureo.context import ops_linkage

        calls: list[str] = []

        def _record(*args: Any, **kwargs: Any) -> None:
            calls.append(kwargs["tool"])

        monkeypatch.setattr(ops_linkage, "record_call_decision", _record)
        await _call(BUDGET_TOOL, _budget())
        assert handler == [_budget()]
        assert calls == []

    async def test_a_bare_call_in_a_batch_still_joins_it(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        await _call(
            "mureo_batch_begin",
            {"label": "Budgets", "reason": "Weekly pass.", "expected": SPEND_UP},
        )
        await _call(BUDGET_TOOL, _budget())
        doc = read_state_file(workspace / "STATE.json")
        assert _journal(workspace)[-1]["decision_id"] == doc.decisions[0].decision_id


class TestAdoptionNeedsExpected:
    async def test_a_proposal_without_expected_is_refused_when_on(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _write_decisions(path, _record("dec-p", "proposed"))
        set_ops_history_enabled(path, True)
        with pytest.raises(ValueError, match="expected"):
            await _call(STATUS_TOOL, _status(decision_id="dec-p"))
        assert handler == []
        assert _journal(workspace)[-1]["outcome"] == "invalid_args"

    async def test_the_call_may_supply_it(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _write_decisions(path, _record("dec-p", "proposed"))
        set_ops_history_enabled(path, True)
        await _call(STATUS_TOOL, _status(decision_id="dec-p", expected=CPA_DOWN))
        doc = read_state_file(path)
        assert doc.decisions[-1].status == "adopted"
        assert [e.metric for e in doc.decisions[-1].expected] == ["cpa"]

    async def test_off_it_is_not_required(
        self, workspace: Path, handler: list[dict[str, Any]]
    ) -> None:
        path = workspace / "STATE.json"
        _write_decisions(path, _record("dec-p", "proposed"))
        await _call(STATUS_TOOL, _status(decision_id="dec-p"))
        assert read_state_file(path).decisions[-1].status == "adopted"


class TestSlotTiming:
    def test_a_failed_write_leaves_the_slot_empty(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context import state_io
        from mureo.context.ops_intent import bind_ops_intent
        from mureo.core.actor import bind_call_reason

        def _fail(path: Path, doc: StateDocument, **kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(state_io, "write_state_file", _fail)
        entry = ActionLogEntry(
            timestamp="2026-10-13T10:00:00+00:00", action="x", platform="google_ads"
        )
        with bind_call_reason("Because."), bind_ops_intent() as intent:
            with pytest.raises(OSError):
                append_action_log(workspace / "STATE.json", entry)
            assert intent.slot.decision_id is None
