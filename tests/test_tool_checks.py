"""``writes_to_platform`` and ``check_tool_call`` (#983, #984).

Both answer, before a stored call is dispatched, what dispatch would decide:
whether the tool can change a platform account, and whether the call would
be rejected as a caller error. The table below pins every built-in tool, so
a tool that is added, removed or reclassified fails here with a readable
diff; the parity cases pin that the pre-check raises dispatch's own message.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from mureo.context.models import StateDocument
from mureo.context.settings_store import set_ops_history_enabled
from mureo.context.state import write_state_file
from mureo.core.actor import ACTION_REASON_MAX_CHARS
from mureo.core.runtime_context import reset_runtime_context
from mureo.mcp import check_tool_call, journal, server, writes_to_platform
from mureo.mcp._ops_history_param import EXPECTED_REQUIRED
from mureo.mcp._plugin_tables import _PLUGIN_DISPATCH, _PLUGIN_SEMANTICS
from mureo.mcp._tools_settings import SWITCH_OFF_REFUSED
from mureo.mcp.plugin_semantics import ToolSemantics

pytestmark = [
    pytest.mark.unit,
    # A family switched off by MUREO_DISABLE_* is not served, so its tools are
    # unknown to the predicate and the pinned table cannot be compared.
    pytest.mark.skipif(
        any(key.startswith("MUREO_DISABLE_") for key in os.environ),
        reason="a MUREO_DISABLE_* variable is set",
    ),
]

TABLE = Path(__file__).parent / "data" / "tool_platform_writes.txt"
STATUS_TOOL = "google_ads_campaigns_update_status"
LIST_TOOL = "google_ads_campaigns_list"
CPA_DOWN = [{"metric": "cpa", "direction": "down"}]
BAD_APPROVAL = {"reference": "TICKET-1"}


def _table() -> dict[str, bool]:
    rows = [line.split("\t") for line in TABLE.read_text().splitlines() if line]
    assert all(kind in ("write", "read") for _, kind in rows)
    return {name: kind == "write" for name, kind in rows}


def _builtin_names() -> list[str]:
    return sorted(
        t.name for t in server._ALL_TOOLS if t.name not in server._PLUGIN_NAMES
    )


class TestWritesToPlatformTable:
    def test_every_builtin_tool_is_pinned(self) -> None:
        actual = {name: writes_to_platform(name) for name in _builtin_names()}
        assert actual == _table()

    def test_the_table_is_sorted(self) -> None:
        names = list(_table())
        assert names == sorted(names)


class TestWritesToPlatform:
    @pytest.mark.parametrize(
        "name",
        [
            "search_console_sitemaps_submit",
            STATUS_TOOL,
            "meta_ads_lead_forms_duplicate",
            "rollback_apply",
        ],
    )
    def test_platform_writes(self, name: str) -> None:
        assert writes_to_platform(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "rollback_plan_get",
            "mureo_state_upsert_campaign",
            "mureo_strategy_set",
            "mureo_batch_begin",
            "creative_studio_generate_visual",
            LIST_TOOL,
        ],
    )
    def test_not_platform_writes(self, name: str) -> None:
        assert writes_to_platform(name) is False

    def test_an_unknown_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Unknown tool"):
            writes_to_platform("google_ads_campaigns_lsit")


def _add_plugin(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(server, "_PLUGIN_NAMES", server._PLUGIN_NAMES | {name})
    monkeypatch.setitem(_PLUGIN_DISPATCH, name, object())


class TestWritesToPlatformPlugins:
    def test_a_plugin_declaring_a_read_does_not_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add_plugin(monkeypatch, "probe_reports_get")
        monkeypatch.setitem(
            _PLUGIN_SEMANTICS, "probe_reports_get", ToolSemantics(mutating=False)
        )
        assert writes_to_platform("probe_reports_get") is False

    def test_a_plugin_without_semantics_counts_as_writing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add_plugin(monkeypatch, "probe_reports_get")
        assert writes_to_platform("probe_reports_get") is True


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A workspace with an empty STATE.json, bound as the server's cwd."""
    monkeypatch.chdir(tmp_path)
    reset_runtime_context()
    write_state_file(tmp_path / "STATE.json", StateDocument(version="2"))
    return tmp_path


@pytest.fixture
def ops_on(workspace: Path) -> Path:
    """The same workspace with operations history switched on."""
    set_ops_history_enabled(workspace / "STATE.json", True)
    return workspace


def _status_args(**extra: Any) -> dict[str, Any]:
    return {"campaign_id": "123", "status": "ENABLED", **extra}


def _files(*directories: Path) -> set[Path]:
    return {p for d in directories if d.is_dir() for p in d.rglob("*")}


class TestCheckToolCall:
    def test_an_unknown_name_is_refused(self, workspace: Path) -> None:
        with pytest.raises(ValueError, match="Unknown tool"):
            check_tool_call("nope_nope", {})

    def test_a_schema_violation_is_refused(self, workspace: Path) -> None:
        with pytest.raises(ValueError, match="status_filter"):
            check_tool_call(LIST_TOOL, {"status_filter": 7})

    def test_expected_is_required_while_ops_history_is_on(self, ops_on: Path) -> None:
        with pytest.raises(ValueError, match=re.escape(EXPECTED_REQUIRED)):
            check_tool_call(STATUS_TOOL, _status_args(reason="Paused by mistake."))

    def test_a_malformed_approval_is_refused(self, workspace: Path) -> None:
        with pytest.raises(ValueError, match="approval"):
            check_tool_call(STATUS_TOOL, _status_args(approval=BAD_APPROVAL))

    def test_switching_ops_history_off_is_refused(self, workspace: Path) -> None:
        with pytest.raises(ValueError, match=re.escape(SWITCH_OFF_REFUSED)):
            check_tool_call("mureo_state_settings_set", {"ops_history_enabled": False})

    def test_a_valid_call_passes_and_writes_nothing(self, ops_on: Path) -> None:
        state = ops_on / "STATE.json"
        before_bytes = state.read_bytes()
        journal_dir = journal.journal_path().parent
        before_files = _files(ops_on, journal_dir)
        check_tool_call(
            STATUS_TOOL, _status_args(reason="Paused by mistake.", expected=CPA_DOWN)
        )
        assert state.read_bytes() == before_bytes
        assert _files(ops_on, journal_dir) == before_files

    def test_the_caller_arguments_are_not_mutated(self, workspace: Path) -> None:
        arguments = _status_args(reason="Paused by mistake.", expected=CPA_DOWN)
        snapshot = dict(arguments)
        check_tool_call(STATUS_TOOL, arguments)
        assert arguments == snapshot


_BAD_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("nope_nope", {}),
    (LIST_TOOL, {"status_filter": 7}),
    (STATUS_TOOL, _status_args(approval=BAD_APPROVAL)),
    (STATUS_TOOL, _status_args(reason="x" * (ACTION_REASON_MAX_CHARS + 1))),
    (STATUS_TOOL, _status_args(reason="Paused by mistake.", expected={"bad": 1})),
    ("mureo_state_settings_set", {"ops_history_enabled": False}),
]


@pytest.mark.parametrize(
    ("name", "arguments"),
    _BAD_CALLS,
    ids=["unknown", "schema", "approval", "long_reason", "bad_expected", "switch_off"],
)
async def test_check_matches_dispatch(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    arguments: dict[str, Any],
) -> None:
    monkeypatch.setattr(journal, "journal_path", lambda: workspace / "J.jsonl")
    with pytest.raises(ValueError) as checked:
        check_tool_call(name, arguments)
    with pytest.raises(ValueError) as dispatched:
        await server.handle_call_tool(name, dict(arguments))
    assert str(checked.value) == str(dispatched.value)
