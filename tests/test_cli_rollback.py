"""Rollback CLI tests.

Exercises ``mureo rollback list`` and ``mureo rollback show`` against
a temp STATE.json written with real action_log entries.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache():
    """Reset the resolver cache before and after every test so the
    workspace-aware ``_resolve_default_state_file`` rebuilds a
    :class:`FilesystemStateStore` with the (per-test) CWD instead of
    reusing a stale one cached during an earlier test or test module."""
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


def _make_state(path: Path, action_log: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps({"version": "2", "campaigns": [], "action_log": action_log}),
        encoding="utf-8",
    )


@pytest.fixture()
def state_file(tmp_path: Path) -> Path:
    state = tmp_path / "STATE.json"
    _make_state(
        state,
        [
            {
                "timestamp": "2026-04-15T10:00:00",
                "action": "update_budget",
                "platform": "google_ads",
                "campaign_id": "111",
                "summary": "Reduced daily budget",
                "reversible_params": {
                    "operation": "google_ads_budget_update",
                    "params": {"budget_id": "222", "amount": 10_000_000_000},
                },
            },
            {
                "timestamp": "2026-04-14T09:00:00",
                "action": "list_campaigns",
                "platform": "google_ads",
            },
            {
                "timestamp": "2026-04-13T12:00:00",
                "action": "update_status",
                "platform": "meta_ads",
                "campaign_id": "abc",
                "reversible_params": {
                    "operation": "meta_ads_campaigns_enable",
                    "params": {"campaign_id": "abc"},
                    "caveats": ["Spend during pause is not refundable."],
                },
            },
            {
                "timestamp": "2026-04-12T08:00:00",
                "action": "update_budget",
                "platform": "google_ads",
                "campaign_id": "222",
            },
        ],
    )
    return state


@pytest.mark.unit
class TestRollbackList:
    def test_lists_action_log_entries_with_status(self, state_file: Path) -> None:
        from mureo.cli.main import app

        result = runner.invoke(
            app, ["rollback", "list", "--state-file", str(state_file)]
        )
        assert result.exit_code == 0, result.output
        assert "update_budget" in result.output
        assert "supported" in result.output.lower()
        assert "partial" in result.output.lower()
        assert "not_supported" in result.output.lower()
        assert "list_campaigns" not in result.output

    def test_filter_by_platform(self, state_file: Path) -> None:
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            [
                "rollback",
                "list",
                "--state-file",
                str(state_file),
                "--platform",
                "meta_ads",
            ],
        )
        assert result.exit_code == 0
        assert "meta_ads" in result.output
        assert "google_ads" not in result.output

    def test_missing_state_file_exits_with_helpful_message(
        self, tmp_path: Path
    ) -> None:
        from mureo.cli.main import app

        missing = tmp_path / "nowhere" / "STATE.json"
        result = runner.invoke(app, ["rollback", "list", "--state-file", str(missing)])
        assert result.exit_code != 0
        assert "STATE.json" in result.output or "not found" in result.output.lower()

    def test_empty_action_log_exits_zero_with_notice(self, tmp_path: Path) -> None:
        from mureo.cli.main import app

        state = tmp_path / "STATE.json"
        _make_state(state, [])
        result = runner.invoke(app, ["rollback", "list", "--state-file", str(state)])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "empty" in result.output.lower()


@pytest.mark.unit
class TestRollbackShow:
    def test_show_index_prints_plan_details(self, state_file: Path) -> None:
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            ["rollback", "show", "--state-file", str(state_file), "0"],
        )
        assert result.exit_code == 0
        assert "google_ads_budget_update" in result.output
        assert "supported" in result.output.lower()

    def test_show_out_of_range_exits_nonzero(self, state_file: Path) -> None:
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            ["rollback", "show", "--state-file", str(state_file), "99"],
        )
        assert result.exit_code != 0

    def test_show_partial_status_includes_caveats(self, state_file: Path) -> None:
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            ["rollback", "show", "--state-file", str(state_file), "2"],
        )
        assert result.exit_code == 0
        assert "partial" in result.output.lower()
        assert "Spend during pause is not refundable." in result.output


@pytest.mark.unit
class TestSafeOutput:
    def test_ansi_escape_in_action_is_stripped(self, tmp_path: Path) -> None:
        from mureo.cli.main import app

        state = tmp_path / "STATE.json"
        # A malicious agent embeds an ANSI clear-screen sequence in the action
        # name. The CLI must not emit the raw escape to the terminal.
        _make_state(
            state,
            [
                {
                    "timestamp": "2026-04-15T10:00:00",
                    "action": "update_budget\x1b[2Jspoof",
                    "platform": "google_ads",
                    "reversible_params": {
                        "operation": "google_ads_budget_update",
                        "params": {"budget_id": "1", "amount": 1},
                    },
                },
            ],
        )
        result = runner.invoke(app, ["rollback", "list", "--state-file", str(state)])
        assert result.exit_code == 0
        assert "\x1b" not in result.output


@pytest.mark.unit
class TestRollbackGroupRegistered:
    def test_rollback_subcommand_registered(self) -> None:
        from mureo.cli.main import app

        group_names = [
            g.typer_instance.info.name
            for g in app.registered_groups
            if g.typer_instance
        ]
        assert "rollback" in group_names


@pytest.mark.unit
class TestStateFileDefault:
    """``--state-file`` is optional: when omitted the CLI resolves the
    path through ``mureo.core.runtime_context.get_runtime_context``, so
    an alternate backend registered via the
    ``mureo.runtime_context_factory`` entry-point group can redirect
    the read without each command growing its own flag."""

    def test_default_resolves_to_cwd_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No ``--state-file`` flag → STATE.json under CWD is read.

        The default ``FilesystemStateStore`` constructs its workspace
        from ``Path.cwd()`` at first resolver call; the autouse cache
        reset above guarantees the per-test ``chdir`` is observed.
        """
        monkeypatch.chdir(tmp_path)
        _make_state(
            tmp_path / "STATE.json",
            [
                {
                    "timestamp": "2026-04-15T10:00:00",
                    "action": "update_budget",
                    "platform": "google_ads",
                    "campaign_id": "111",
                    "reversible_params": {
                        "operation": "google_ads_budget_update",
                        "params": {"budget_id": "222", "amount": 1_000_000_000},
                    },
                },
            ],
        )
        from mureo.cli.main import app

        result = runner.invoke(app, ["rollback", "list"])
        assert result.exit_code == 0, result.output
        assert "update_budget" in result.output

    def test_default_resolves_via_injected_runtime_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An injected RuntimeContext (workspace ≠ CWD) must be honoured.

        Verifies the integration point that alternate backends use:
        register a custom ``RuntimeContext`` and the CLI follows it
        without touching the underlying flag plumbing."""
        from mureo.core.runtime_context import (
            RuntimeContext,
            default_runtime_context,
        )

        cwd_dir = tmp_path / "cwd"
        workspace_dir = tmp_path / "tenant"
        cwd_dir.mkdir()
        workspace_dir.mkdir()
        monkeypatch.chdir(cwd_dir)

        _make_state(
            workspace_dir / "STATE.json",
            [
                {
                    "timestamp": "2026-04-15T10:00:00",
                    "action": "from_workspace",
                    "platform": "meta_ads",
                    "campaign_id": "ws-1",
                    "reversible_params": {
                        "operation": "meta_ads_campaigns_enable",
                        "params": {"campaign_id": "ws-1"},
                    },
                },
            ],
        )
        # CWD STATE.json deliberately has a *different* action_log so we
        # can assert the CLI read the workspace one (not the CWD one).
        _make_state(cwd_dir / "STATE.json", [])

        base = default_runtime_context(workspace=workspace_dir)
        injected = RuntimeContext(
            secret_store=base.secret_store,
            state_store=base.state_store,
            knowledge_store=base.knowledge_store,
            throttle_store=base.throttle_store,
            workspace_id="injected",
        )
        monkeypatch.setattr("mureo.core.runtime_context._cached_context", injected)

        from mureo.cli.main import app

        result = runner.invoke(app, ["rollback", "list"])
        assert result.exit_code == 0, result.output
        assert "from_workspace" in result.output
