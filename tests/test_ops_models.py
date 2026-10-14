"""Ops history data model (#848): the new optional fields and the setting.

Every field is optional on disk: a document written before ops history
existed must parse unchanged and gain no key on the next write.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mureo.context._decision_codec import decision_to_dict, parse_decisions
from mureo.context.decisions import DecisionRecord
from mureo.context.expected import ExpectedEffect
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.settings import (
    WorkspaceSettings,
    ops_history_enabled,
    parse_settings,
    set_ops_history_enabled,
    settings_to_dict,
)
from mureo.context.state import read_state_file, write_state_file
from mureo.context.state_codec import parse_state, render_state

pytestmark = pytest.mark.unit


def _record(**overrides: Any) -> DecisionRecord:
    values: dict[str, Any] = {
        "decision_id": "dec-1",
        "recorded_at": "2026-10-14T10:00:00+09:00",
        "status": "proposed",
        "title": "Raise the Brand budget",
        "rationale": "Capped every afternoon for nine days.",
    }
    values.update(overrides)
    return DecisionRecord(**values)


class TestDecisionExpected:
    def test_defaults_to_empty(self) -> None:
        assert _record().expected == ()

    def test_dicts_are_parsed_into_effects(self) -> None:
        record = _record(expected=[{"metric": "cpa", "direction": "down"}])
        assert record.expected == (ExpectedEffect(metric="cpa", direction="down"),)

    def test_an_unknown_metric_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cpa_7d"):
            _record(expected=[{"metric": "cpa_7d", "direction": "down"}])

    def test_codec_round_trip(self) -> None:
        record = _record(
            expected=[{"metric": "roas", "direction": "up", "target": 4}],
        )
        rendered = decision_to_dict(record)
        assert rendered["expected"] == [
            {"metric": "roas", "direction": "up", "target": 4}
        ]
        assert parse_decisions([rendered], strict=True) == (record,)

    def test_no_expected_means_no_key(self) -> None:
        assert "expected" not in decision_to_dict(_record())


class TestActionLogEntryFields:
    def test_both_default_to_none(self) -> None:
        entry = ActionLogEntry(timestamp="t", action="a", platform="google_ads")
        assert entry.decision_id is None
        assert entry.evaluation is None

    def test_a_blank_decision_id_is_refused(self) -> None:
        with pytest.raises(ValueError, match="decision_id"):
            ActionLogEntry(
                timestamp="t", action="a", platform="google_ads", decision_id=" "
            )

    def test_evaluation_is_copied(self) -> None:
        table = {"overall": "improved", "metrics": []}
        entry = ActionLogEntry(
            timestamp="t", action="a", platform="google_ads", evaluation=table
        )
        table["overall"] = "regressed"
        assert entry.evaluation == {"overall": "improved", "metrics": []}

    def test_a_non_object_evaluation_is_refused(self) -> None:
        with pytest.raises(ValueError, match="evaluation"):
            ActionLogEntry(
                timestamp="t", action="a", platform="google_ads", evaluation=[1]
            )


class TestSettingsCodec:
    def test_a_legacy_document_has_no_settings(self) -> None:
        doc = parse_state(json.dumps({"version": "2"}))
        assert doc.settings is None
        assert ops_history_enabled(doc) is False

    def test_a_legacy_document_gains_no_key(self) -> None:
        rendered = json.loads(render_state(parse_state(json.dumps({"version": "2"}))))
        assert "settings" not in rendered

    def test_enabled_round_trips(self) -> None:
        text = json.dumps(
            {"version": "2", "settings": {"ops_history": {"enabled": True}}}
        )
        doc = parse_state(text)
        assert ops_history_enabled(doc) is True
        assert json.loads(render_state(doc))["settings"] == {
            "ops_history": {"enabled": True}
        }

    @pytest.mark.parametrize(
        "raw",
        [
            "on",
            [],
            {"ops_history": "yes"},
            {"ops_history": {"enabled": "true"}},
            {"ops_history": {"enabled": 1}},
        ],
    )
    def test_anything_but_true_reads_as_disabled(self, raw: Any) -> None:
        assert parse_settings(raw).ops_history_enabled is False

    def test_absent_parses_to_none(self) -> None:
        assert parse_settings(None) is None

    def test_settings_to_dict(self) -> None:
        assert settings_to_dict(WorkspaceSettings(ops_history_enabled=False)) == {
            "ops_history": {"enabled": False}
        }


class TestSetOpsHistoryEnabled:
    def test_writes_the_setting(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        write_state_file(path, StateDocument(version="2"))
        doc = set_ops_history_enabled(path, True)
        assert ops_history_enabled(doc) is True
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["settings"] == {"ops_history": {"enabled": True}}

    def test_turning_it_off_is_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_ops_history_enabled(path, True)
        set_ops_history_enabled(path, False)
        assert ops_history_enabled(read_state_file(path)) is False

    def test_other_sections_are_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "action_log": [
                        {"timestamp": "t", "action": "a", "platform": "google_ads"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        doc = set_ops_history_enabled(path, True)
        assert len(doc.action_log) == 1

    @pytest.mark.parametrize("value", ["true", 1, None])
    def test_a_non_boolean_is_refused(self, tmp_path: Path, value: Any) -> None:
        with pytest.raises(ValueError, match="boolean"):
            set_ops_history_enabled(tmp_path / "STATE.json", value)
        assert not (tmp_path / "STATE.json").exists()
