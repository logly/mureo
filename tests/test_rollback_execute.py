"""Rollback executor tests.

Covers the safety contract of ``execute_rollback``: the function that
loads STATE.json, re-plans an entry, re-dispatches the reversal
through the MCP handler map, and appends an ``ActionLogEntry`` with
``rollback_of`` populated on success.

The executor must never bypass the planner's allow-list — these tests
lock that in by asserting which dispatches happen and which are
refused.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state import read_state_file, write_state_file

# The module under test does not exist yet — this import is the RED
# that drives implementation.
from mureo.rollback.executor import (  # noqa: I001
    RollbackExecutionError,
    execute_rollback,
)


Dispatcher = Callable[[str, dict[str, Any]], Awaitable[list[Any]]]


def _write_state(path: Path, entries: list[ActionLogEntry]) -> None:
    write_state_file(path, StateDocument(version="2", action_log=tuple(entries)))


def _budget_update_entry(
    *,
    timestamp: str = "2026-04-15T10:00:00",
    campaign_id: str = "100",
    budget_id: str = "B1",
    amount_micros: int = 5_000_000_000,
) -> ActionLogEntry:
    return ActionLogEntry(
        timestamp=timestamp,
        action="google_ads_budget_update",
        platform="google_ads",
        campaign_id=campaign_id,
        summary="Increased budget for traffic test",
        reversible_params={
            "operation": "google_ads_budget_update",
            "params": {"budget_id": budget_id, "amount_micros": amount_micros},
        },
    )


class _FakeDispatcher:
    """Records every dispatch call and returns a canned result."""

    def __init__(
        self,
        *,
        return_value: list[Any] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._return_value = (
            return_value if return_value is not None else [{"ok": True}]
        )
        self._raise_exc = raise_exc

    async def __call__(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        self.calls.append((name, dict(arguments)))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._return_value


@pytest.mark.unit
class TestExecuteRollback:
    @pytest.mark.asyncio
    async def test_executes_supported_plan_and_appends_log(
        self, tmp_path: Path
    ) -> None:
        """A supported plan is dispatched with the planner's params, and a
        new ActionLogEntry tagged rollback_of=<index> is appended."""
        state_file = tmp_path / "STATE.json"
        entry = _budget_update_entry()
        _write_state(state_file, [entry])
        dispatcher = _FakeDispatcher()

        result = await execute_rollback(
            state_file=state_file,
            index=0,
            confirm=True,
            dispatcher=dispatcher,
        )

        assert result["status"] == "applied"
        assert result["dispatched_tool"] == "google_ads_budget_update"
        assert dispatcher.calls == [
            (
                "google_ads_budget_update",
                {"budget_id": "B1", "amount_micros": 5_000_000_000},
            )
        ]

        doc = read_state_file(state_file)
        assert len(doc.action_log) == 2
        new_entry = doc.action_log[1]
        assert new_entry.action == "google_ads_budget_update"
        assert new_entry.platform == "google_ads"
        assert new_entry.rollback_of == 0
        # Rollback of a rollback must not be chained by default.
        assert new_entry.reversible_params is None

    @pytest.mark.asyncio
    async def test_confirm_false_refuses(self, tmp_path: Path) -> None:
        state_file = tmp_path / "STATE.json"
        _write_state(state_file, [_budget_update_entry()])
        dispatcher = _FakeDispatcher()

        with pytest.raises(RollbackExecutionError, match="confirm"):
            await execute_rollback(
                state_file=state_file,
                index=0,
                confirm=False,
                dispatcher=dispatcher,
            )

        assert dispatcher.calls == []
        doc = read_state_file(state_file)
        assert len(doc.action_log) == 1  # unchanged

    @pytest.mark.asyncio
    async def test_out_of_range_index(self, tmp_path: Path) -> None:
        state_file = tmp_path / "STATE.json"
        _write_state(state_file, [_budget_update_entry()])
        dispatcher = _FakeDispatcher()

        with pytest.raises(RollbackExecutionError, match="out of range"):
            await execute_rollback(
                state_file=state_file,
                index=5,
                confirm=True,
                dispatcher=dispatcher,
            )
        assert dispatcher.calls == []

    @pytest.mark.asyncio
    async def test_read_only_entry_refused(self, tmp_path: Path) -> None:
        state_file = tmp_path / "STATE.json"
        _write_state(
            state_file,
            [
                ActionLogEntry(
                    timestamp="t",
                    action="list_campaigns",
                    platform="google_ads",
                )
            ],
        )
        dispatcher = _FakeDispatcher()

        with pytest.raises(RollbackExecutionError, match="nothing to roll back"):
            await execute_rollback(
                state_file=state_file,
                index=0,
                confirm=True,
                dispatcher=dispatcher,
            )
        assert dispatcher.calls == []

    @pytest.mark.asyncio
    async def test_not_supported_refused(self, tmp_path: Path) -> None:
        state_file = tmp_path / "STATE.json"
        entry = ActionLogEntry(
            timestamp="t",
            action="google_ads_campaigns_delete",
            platform="google_ads",
            reversible_params={
                "operation": "google_ads_campaigns_delete",
                "params": {"campaign_id": "100"},
            },
        )
        _write_state(state_file, [entry])
        dispatcher = _FakeDispatcher()

        with pytest.raises(RollbackExecutionError, match="not supported"):
            await execute_rollback(
                state_file=state_file,
                index=0,
                confirm=True,
                dispatcher=dispatcher,
            )
        assert dispatcher.calls == []

    @pytest.mark.asyncio
    async def test_dispatch_failure_does_not_append_log(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / "STATE.json"
        _write_state(state_file, [_budget_update_entry()])
        dispatcher = _FakeDispatcher(raise_exc=RuntimeError("API exploded"))

        with pytest.raises(RuntimeError, match="API exploded"):
            await execute_rollback(
                state_file=state_file,
                index=0,
                confirm=True,
                dispatcher=dispatcher,
            )

        doc = read_state_file(state_file)
        assert len(doc.action_log) == 1  # no rollback entry appended

    @pytest.mark.asyncio
    async def test_double_rollback_refused(self, tmp_path: Path) -> None:
        """Applying a rollback twice for the same index must be rejected."""
        state_file = tmp_path / "STATE.json"
        _write_state(state_file, [_budget_update_entry()])
        dispatcher = _FakeDispatcher()

        # First rollback: succeeds.
        await execute_rollback(
            state_file=state_file,
            index=0,
            confirm=True,
            dispatcher=dispatcher,
        )

        # Second rollback of the same index: refused.
        with pytest.raises(RollbackExecutionError, match="already rolled back"):
            await execute_rollback(
                state_file=state_file,
                index=0,
                confirm=True,
                dispatcher=dispatcher,
            )

        # Dispatcher called exactly once.
        assert len(dispatcher.calls) == 1

    @pytest.mark.asyncio
    async def test_missing_state_file_refused(self, tmp_path: Path) -> None:
        state_file = tmp_path / "does_not_exist.json"
        dispatcher = _FakeDispatcher()

        with pytest.raises(RollbackExecutionError, match="not found"):
            await execute_rollback(
                state_file=state_file,
                index=0,
                confirm=True,
                dispatcher=dispatcher,
            )
        assert dispatcher.calls == []

    @pytest.mark.asyncio
    async def test_partial_rollback_surfaces_caveats(self, tmp_path: Path) -> None:
        """A PARTIAL plan still applies but caveats are returned to caller."""
        state_file = tmp_path / "STATE.json"
        entry = ActionLogEntry(
            timestamp="t",
            action="google_ads_budget_update",
            platform="google_ads",
            reversible_params={
                "operation": "google_ads_budget_update",
                "params": {"budget_id": "B1", "amount_micros": 1_000_000_000},
                "caveats": ["Spend already incurred cannot be refunded."],
            },
        )
        _write_state(state_file, [entry])
        dispatcher = _FakeDispatcher()

        result = await execute_rollback(
            state_file=state_file,
            index=0,
            confirm=True,
            dispatcher=dispatcher,
        )

        assert result["status"] == "applied"
        assert result["caveats"] == [
            "Spend already incurred cannot be refunded."
        ]


@pytest.mark.unit
class TestExecutorWiringContract:
    """Contract tests that lock in how the executor integrates with STATE.json."""

    @pytest.mark.asyncio
    async def test_new_log_entry_references_original_action(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / "STATE.json"
        original = _budget_update_entry(
            timestamp="2026-04-15T10:00:00",
            campaign_id="CID-42",
        )
        _write_state(state_file, [original])
        dispatcher = _FakeDispatcher()

        await execute_rollback(
            state_file=state_file,
            index=0,
            confirm=True,
            dispatcher=dispatcher,
        )

        doc = read_state_file(state_file)
        new_entry = doc.action_log[1]
        assert new_entry.campaign_id == "CID-42"
        assert "Rolled back" in (new_entry.summary or "")
        assert "0" in (new_entry.summary or "")

    @pytest.mark.asyncio
    async def test_state_file_is_valid_json_after_success(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / "STATE.json"
        _write_state(state_file, [_budget_update_entry()])
        dispatcher = _FakeDispatcher()

        await execute_rollback(
            state_file=state_file,
            index=0,
            confirm=True,
            dispatcher=dispatcher,
        )

        # Atomically written and re-parseable.
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["action_log"][1]["rollback_of"] == 0
