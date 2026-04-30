"""MCP tool tests for rollback_apply and rollback_plan_get.

Locks in that the tools are registered in the aggregate MCP server
tool list, and that the handlers wire through to the executor /
planner with the expected dispatching behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state import read_state_file, write_state_file
from mureo.mcp.server import handle_list_tools
from mureo.mcp.tools_rollback import TOOLS, handle_tool


def _write_state(path: Path, entries: list[ActionLogEntry]) -> None:
    write_state_file(path, StateDocument(version="2", action_log=tuple(entries)))


@pytest.fixture
def sandboxed_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Run each test under ``tmp_path`` so the handler's path-sandboxing
    accepts a relative ``STATE.json`` argument."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _budget_entry() -> ActionLogEntry:
    return ActionLogEntry(
        timestamp="2026-04-15T10:00:00",
        action="google_ads_budget_update",
        platform="google_ads",
        campaign_id="100",
        reversible_params={
            "operation": "google_ads_budget_update",
            "params": {"budget_id": "B1", "amount_micros": 5_000_000_000},
        },
    )


@pytest.mark.unit
class TestToolRegistration:
    @pytest.mark.asyncio
    async def test_tools_registered_in_server(self) -> None:
        all_tools = await handle_list_tools()
        names = {t.name for t in all_tools}
        assert "rollback_apply" in names
        assert "rollback_plan_get" in names

    def test_tool_names_in_module_list(self) -> None:
        names = {t.name for t in TOOLS}
        assert names == {"rollback_apply", "rollback_plan_get"}

    def test_apply_requires_confirm_in_schema(self) -> None:
        apply_tool = next(t for t in TOOLS if t.name == "rollback_apply")
        schema = apply_tool.inputSchema
        assert "confirm" in schema.get("required", [])
        assert "index" in schema.get("required", [])


@pytest.mark.unit
class TestPlanGetHandler:
    @pytest.mark.asyncio
    async def test_returns_plan_json(self, sandboxed_cwd: Path) -> None:
        _write_state(sandboxed_cwd / "STATE.json", [_budget_entry()])

        result = await handle_tool(
            "rollback_plan_get",
            {"state_file": "STATE.json", "index": 0},
        )
        payload = json.loads(result[0].text)
        assert payload["status"] == "supported"
        assert payload["operation"] == "google_ads_budget_update"
        assert payload["params"] == {
            "budget_id": "B1",
            "amount_micros": 5_000_000_000,
        }

    @pytest.mark.asyncio
    async def test_read_only_entry_returns_null_plan(
        self, sandboxed_cwd: Path
    ) -> None:
        _write_state(
            sandboxed_cwd / "STATE.json",
            [
                ActionLogEntry(
                    timestamp="t",
                    action="list_campaigns",
                    platform="google_ads",
                )
            ],
        )
        result = await handle_tool(
            "rollback_plan_get",
            {"state_file": "STATE.json", "index": 0},
        )
        payload = json.loads(result[0].text)
        assert payload["plan"] is None
        assert "read-only" in payload["reason"].lower()


@pytest.mark.unit
class TestApplyHandler:
    @pytest.mark.asyncio
    async def test_apply_without_confirm_returns_error(
        self, sandboxed_cwd: Path
    ) -> None:
        _write_state(sandboxed_cwd / "STATE.json", [_budget_entry()])

        result = await handle_tool(
            "rollback_apply",
            {"state_file": "STATE.json", "index": 0, "confirm": False},
        )
        payload = json.loads(result[0].text)
        assert payload["status"] == "refused"
        assert "confirm" in payload["error"].lower()

        doc = read_state_file(sandboxed_cwd / "STATE.json")
        assert len(doc.action_log) == 1  # unchanged

    @pytest.mark.asyncio
    async def test_apply_dispatches_through_injected_dispatcher(
        self, sandboxed_cwd: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Apply must re-dispatch through server.handle_call_tool so the
        rollback call re-enters the same policy gate as forward actions."""
        _write_state(sandboxed_cwd / "STATE.json", [_budget_entry()])

        calls: list[tuple[str, dict[str, Any]]] = []

        async def _fake_dispatcher(
            name: str, arguments: dict[str, Any]
        ) -> list[Any]:
            calls.append((name, dict(arguments)))
            return [{"ok": True}]

        monkeypatch.setattr(
            "mureo.mcp._handlers_rollback._get_dispatcher",
            lambda: _fake_dispatcher,
        )

        result = await handle_tool(
            "rollback_apply",
            {"state_file": "STATE.json", "index": 0, "confirm": True},
        )
        payload = json.loads(result[0].text)
        assert payload["status"] == "applied"
        assert payload["dispatched_tool"] == "google_ads_budget_update"
        assert calls == [
            (
                "google_ads_budget_update",
                {"budget_id": "B1", "amount_micros": 5_000_000_000},
            )
        ]

        doc = read_state_file(sandboxed_cwd / "STATE.json")
        assert doc.action_log[1].rollback_of == 0

    @pytest.mark.asyncio
    async def test_path_traversal_refused(self, sandboxed_cwd: Path) -> None:
        """A state_file argument that resolves outside CWD must be rejected."""
        # Write a valid STATE.json outside the sandbox.
        outside = sandboxed_cwd.parent / "rogue_STATE.json"
        _write_state(outside, [_budget_entry()])

        result = await handle_tool(
            "rollback_apply",
            {
                "state_file": str(outside),
                "index": 0,
                "confirm": True,
            },
        )
        payload = json.loads(result[0].text)
        # Path validation raises ValueError -> surfaces in response
        assert (
            "inside the current working directory"
            in payload.get("error", "")
            or payload.get("status") == "refused"
        )

    @pytest.mark.asyncio
    async def test_truthy_non_bool_confirm_refused(
        self, sandboxed_cwd: Path
    ) -> None:
        """confirm must be the literal True, not a truthy non-bool."""
        _write_state(sandboxed_cwd / "STATE.json", [_budget_entry()])

        result = await handle_tool(
            "rollback_apply",
            {"state_file": "STATE.json", "index": 0, "confirm": 1},
        )
        payload = json.loads(result[0].text)
        assert payload["status"] == "refused"
        assert "confirm" in payload["error"].lower()
