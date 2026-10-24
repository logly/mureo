"""Ops history on the recording tools and the settings tool (#848).

``mureo_state_action_log_append`` and ``mureo_decision_record`` carry
``expected`` (and the entry a ``decision_id``) in their own records, and
``mureo_state_settings_set`` is the MCP path to the switch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.expected_eval import build_evaluation
from mureo.context.settings import ops_history_enabled
from mureo.context.settings_store import set_ops_history_enabled
from mureo.context.state import read_state_file
from mureo.mcp import journal
from mureo.mcp._ops_history_records import (
    DECISION_EXPECTED_REQUIRED,
    ENTRY_EXPECTED_REQUIRED,
    ENTRY_REASON_REQUIRED,
)

pytestmark = pytest.mark.unit

CPA_DOWN = [{"metric": "cpa", "direction": "down"}]


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache():
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "J.jsonl")
    return tmp_path


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from mureo.mcp.server import handle_call_tool

    result = await handle_call_tool(name, arguments)
    return json.loads(result[0].text)


def _entry(**extra: Any) -> dict[str, Any]:
    return {
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        "campaign_id": "123",
        "metrics_at_action": {"cpa": 5200},
        **extra,
    }


async def _propose(expected: list[dict[str, Any]] | None = None) -> str:
    args: dict[str, Any] = {"status": "proposed", "title": "t", "rationale": "r"}
    if expected is not None:
        args["expected"] = expected
    payload = await _call("mureo_decision_record", args)
    return str(payload["decision"]["decision_id"])


class TestActionLogAppend:
    async def test_reason_and_expected_create_a_decision(self, workspace: Path) -> None:
        await _call(
            "mureo_state_action_log_append",
            {"entry": _entry(reason="Capped daily.", expected=CPA_DOWN)},
        )
        doc = read_state_file(workspace / "STATE.json")
        assert len(doc.decisions) == 1
        assert doc.decisions[0].expected[0].metric == "cpa"
        assert doc.action_log[0].decision_id == doc.decisions[0].decision_id

    async def test_an_explicit_decision_id_adopts_the_proposal(
        self, workspace: Path
    ) -> None:
        decision_id = await _propose(CPA_DOWN)
        await _call(
            "mureo_state_action_log_append",
            {"entry": _entry(decision_id=decision_id)},
        )
        doc = read_state_file(workspace / "STATE.json")
        assert [r.status for r in doc.decisions] == ["proposed", "adopted"]
        assert doc.action_log[0].decision_id == decision_id

    async def test_an_unknown_decision_id_is_refused(self, workspace: Path) -> None:
        with pytest.raises(ValueError, match="no recorded decision"):
            await _call(
                "mureo_state_action_log_append",
                {"entry": _entry(decision_id="dec-nope")},
            )

    async def test_an_invalid_expected_is_refused(self, workspace: Path) -> None:
        with pytest.raises(ValueError):
            await _call(
                "mureo_state_action_log_append",
                {"entry": _entry(reason="x", expected=[{"metric": "cpa"}])},
            )

    async def test_several_effects_without_a_primary_are_refused(
        self, workspace: Path
    ) -> None:
        expected = [*CPA_DOWN, {"metric": "ctr", "direction": "up"}]
        with pytest.raises(ValueError, match="expected_primary_required"):
            await _call(
                "mureo_state_action_log_append",
                {"entry": _entry(reason="x", expected=expected)},
            )

    @pytest.mark.parametrize(
        ("extra", "message"),
        [
            ({"expected": CPA_DOWN}, ENTRY_REASON_REQUIRED),
            ({"reason": "Capped."}, ENTRY_EXPECTED_REQUIRED),
        ],
    )
    async def test_enabled_requires_both_for_a_new_decision(
        self, workspace: Path, extra: dict[str, Any], message: str
    ) -> None:
        set_ops_history_enabled(workspace / "STATE.json", True)
        with pytest.raises(ValueError) as caught:
            await _call("mureo_state_action_log_append", {"entry": _entry(**extra)})
        assert str(caught.value) == message
        assert read_state_file(workspace / "STATE.json").action_log == ()

    async def test_enabled_does_not_require_them_on_an_evaluation(
        self, workspace: Path
    ) -> None:
        await _call(
            "mureo_state_action_log_append",
            {"entry": _entry(reason="r", expected=CPA_DOWN)},
        )
        set_ops_history_enabled(workspace / "STATE.json", True)
        await _call(
            "mureo_state_action_log_append",
            {
                "entry": _entry(
                    action="evaluated",
                    evaluation_of=0,
                    evaluation=build_evaluation(
                        {"cpa": 100}, {"cpa": 90}, (), window_from=None, window_to=None
                    ).table,
                )
            },
        )
        doc = read_state_file(workspace / "STATE.json")
        assert doc.action_log[1].decision_id == doc.action_log[0].decision_id


class TestDecisionRecord:
    async def test_expected_is_stored(self, workspace: Path) -> None:
        await _propose(CPA_DOWN)
        doc = read_state_file(workspace / "STATE.json")
        assert doc.decisions[0].expected[0].direction == "down"

    async def test_an_unknown_metric_is_refused_by_the_schema(
        self, workspace: Path
    ) -> None:
        with pytest.raises(ValueError):
            await _propose([{"metric": "cpa_7d", "direction": "down"}])

    async def test_several_effects_without_a_primary_are_refused(
        self, workspace: Path
    ) -> None:
        with pytest.raises(ValueError, match="expected_primary_required"):
            await _propose([*CPA_DOWN, {"metric": "ctr", "direction": "up"}])
        assert not (workspace / "STATE.json").exists() or (
            read_state_file(workspace / "STATE.json").decisions == ()
        )

    async def test_the_marked_primary_is_stored(self, workspace: Path) -> None:
        await _propose(
            [
                {"metric": "ctr", "direction": "up"},
                {"metric": "cpa", "direction": "down", "primary": True},
            ]
        )
        doc = read_state_file(workspace / "STATE.json")
        assert [e.primary for e in doc.decisions[0].expected] == [False, True]

    async def test_disabled_accepts_a_proposal_without_expected(
        self, workspace: Path
    ) -> None:
        await _propose()
        assert len(read_state_file(workspace / "STATE.json").decisions) == 1

    async def test_enabled_requires_expected_on_a_proposal(
        self, workspace: Path
    ) -> None:
        set_ops_history_enabled(workspace / "STATE.json", True)
        with pytest.raises(ValueError) as caught:
            await _propose()
        assert str(caught.value) == DECISION_EXPECTED_REQUIRED

    async def test_enabled_does_not_require_it_on_a_rejection(
        self, workspace: Path
    ) -> None:
        decision_id = await _propose(CPA_DOWN)
        set_ops_history_enabled(workspace / "STATE.json", True)
        await _call(
            "mureo_decision_record",
            {
                "status": "rejected",
                "title": "t",
                "rationale": "No.",
                "supersedes": decision_id,
            },
        )
        doc = read_state_file(workspace / "STATE.json")
        assert doc.decisions[-1].status == "rejected"


class TestSettingsSet:
    async def test_switches_it_on(self, workspace: Path) -> None:
        payload = await _call("mureo_state_settings_set", {"ops_history_enabled": True})
        assert payload == {"settings": {"ops_history": {"enabled": True}}}
        assert ops_history_enabled(read_state_file(workspace / "STATE.json"))

    async def test_switching_it_off_is_refused(self, workspace: Path) -> None:
        path = workspace / "STATE.json"
        set_ops_history_enabled(path, True)
        with pytest.raises(ValueError, match="mureo configure"):
            await _call("mureo_state_settings_set", {"ops_history_enabled": False})
        assert ops_history_enabled(read_state_file(path))
        line = (workspace / "J.jsonl").read_text().splitlines()[-1]
        assert json.loads(line)["outcome"] == "invalid_args"

    async def test_switching_it_off_creates_no_file(self, workspace: Path) -> None:
        with pytest.raises(ValueError, match="mureo configure"):
            await _call("mureo_state_settings_set", {"ops_history_enabled": False})
        assert not (workspace / "STATE.json").exists()

    async def test_repeating_the_value_writes_nothing(self, workspace: Path) -> None:
        path = workspace / "STATE.json"
        await _call("mureo_state_settings_set", {"ops_history_enabled": True})
        before = path.stat().st_mtime_ns
        await _call("mureo_state_settings_set", {"ops_history_enabled": True})
        assert path.stat().st_mtime_ns == before

    def test_an_unchanged_value_never_creates_the_file(self, workspace: Path) -> None:
        set_ops_history_enabled(workspace / "STATE.json", False)
        assert not (workspace / "STATE.json").exists()

    async def test_a_non_boolean_is_refused(self, workspace: Path) -> None:
        with pytest.raises(ValueError):
            await _call("mureo_state_settings_set", {"ops_history_enabled": "yes"})
        assert not (workspace / "STATE.json").exists()

    async def test_a_path_outside_the_workspace_is_refused(
        self, workspace: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        outside = tmp_path_factory.mktemp("outside") / "STATE.json"
        with pytest.raises(ValueError):
            await _call(
                "mureo_state_settings_set",
                {"ops_history_enabled": True, "path": str(outside)},
            )
        assert not outside.exists()

    async def test_it_is_a_write_that_takes_a_reason(self) -> None:
        from mureo.mcp import server

        assert "mureo_state_settings_set" in server._REASON_TOOLS
        assert "mureo_state_settings_set" not in server._OPS_TOOLS
