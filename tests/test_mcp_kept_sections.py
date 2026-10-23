"""The MCP tools over a ``decisions`` / ``action_log`` kept as written (#882).

A hand-written ``decisions`` or ``action_log`` that is not a list is kept in
STATE.json and rendered back exactly as found. The tools that count or
filter the rendered section read it as empty instead of failing, and leave
the file untouched; a call whose decision cannot be recorded over a kept
``decisions`` still succeeds, and says why in one line, without a traceback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.types import TextContent

from mureo.mcp import journal

pytestmark = pytest.mark.unit

_KEPT_VALUES: list[Any] = [5, "see the weekly sheet", {"0": {"action": "x"}}]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from mureo.core.runtime_context import reset_runtime_context

    monkeypatch.chdir(tmp_path)
    reset_runtime_context()
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "J.jsonl")
    yield tmp_path
    reset_runtime_context()


def _write(workspace: Path, **sections: Any) -> Path:
    path = workspace / "STATE.json"
    data = {"version": "2", "platforms": {}, "action_log": [], **sections}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from mureo.mcp.server import handle_call_tool

    result = await handle_call_tool(name, arguments)
    payload: dict[str, Any] = json.loads(result[0].text)
    return payload


class TestStateGet:
    @pytest.mark.parametrize("value", _KEPT_VALUES)
    async def test_a_kept_log_reads_as_empty_in_full(
        self, workspace: Path, value: Any
    ) -> None:
        path = _write(workspace, action_log=value)
        before = path.read_bytes()

        state = await _call("mureo_state_get", {"action_log": "all"})

        assert state["action_log"] == []
        assert "action_log_total" not in state
        assert path.read_bytes() == before

    @pytest.mark.parametrize("value", _KEPT_VALUES)
    async def test_a_kept_log_has_nothing_pending(
        self, workspace: Path, value: Any
    ) -> None:
        path = _write(workspace, action_log=value)
        before = path.read_bytes()

        state = await _call("mureo_state_get", {"action_log": "pending"})

        assert state["action_log"] == []
        assert state["action_log_total"] == 0
        assert state["action_log_scope"] == "pending"
        assert path.read_bytes() == before

    @pytest.mark.parametrize("value", _KEPT_VALUES)
    async def test_a_kept_log_counts_as_empty_when_dropped(
        self, workspace: Path, value: Any
    ) -> None:
        path = _write(workspace, action_log=value)
        before = path.read_bytes()

        state = await _call("mureo_state_get", {"action_log": "none"})

        assert "action_log" not in state
        assert state["action_log_total"] == 0
        assert path.read_bytes() == before

    @pytest.mark.parametrize("scope", ["all", "none"])
    @pytest.mark.parametrize("value", _KEPT_VALUES)
    async def test_kept_decisions_read_as_none_recorded(
        self, workspace: Path, value: Any, scope: str
    ) -> None:
        path = _write(workspace, decisions=value)
        before = path.read_bytes()

        state = await _call("mureo_state_get", {"decisions": scope})

        assert "decisions" not in state
        assert "decisions_total" not in state
        assert "decisions_scope" not in state
        assert path.read_bytes() == before


class TestHistoryQuery:
    @pytest.mark.parametrize("value", _KEPT_VALUES)
    async def test_a_kept_log_has_no_entries(self, workspace: Path, value: Any) -> None:
        path = _write(workspace, action_log=value)
        before = path.read_bytes()

        result = await _call("mureo_history_query", {})

        assert result["action_log"]["entries"] == []
        assert result["action_log"]["matched"] == 0
        assert path.read_bytes() == before


class TestCallDecisionOverKeptDecisions:
    async def test_the_call_succeeds_and_logs_one_line(
        self,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from mureo.mcp import server

        async def _handle(name: str, arguments: dict[str, Any]) -> list[Any]:
            return [TextContent(type="text", text=json.dumps({"ok": True}))]

        monkeypatch.setattr(server, "_evaluate_policy_gates", lambda n, a: None)
        monkeypatch.setattr(
            server, "capture_before_state", AsyncMock(return_value="PAUSED")
        )
        monkeypatch.setattr(server, "handle_google_ads_tool", _handle)
        path = _write(workspace, decisions={"dec-1": "an object, not a list"})
        before = path.read_bytes()

        with caplog.at_level(logging.WARNING, logger="mureo.mcp._ops_history_param"):
            result = await _call(
                "google_ads_budget_update",
                {"budget_id": "b1", "amount": 12000, "reason": "Capped by noon."},
            )

        assert result == {"ok": True}
        assert path.read_bytes() == before
        (record,) = [
            r
            for r in caplog.records
            if r.getMessage().startswith("could not record the decision")
        ]
        assert record.exc_info is None
        assert "'decisions' is not a list" in record.getMessage()
