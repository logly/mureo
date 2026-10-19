"""A nonconforming ``action_log`` entry is kept in place, never refused (#859).

An entry written straight into STATE.json — not through
``mureo_state_action_log_append`` — may lack ``timestamp`` or ``platform`` and
carry keys mureo does not know. Such an entry used to raise inside the strict
read every writer performs, so ONE hand-authored entry blocked every write of
the whole document; and a whole-document write dropped the unknown keys of
every entry it re-emitted.

The contract pinned here:

- the entry is read (missing required fields as ``""``) at the index it
  occupies on disk — the log is append-only and ``rollback_of`` /
  ``evaluation_of`` are positional, so the strict and tolerant views must
  share one index space;
- it is written back verbatim: unknown keys survive, absent required keys
  stay absent, and a mutation mureo makes (``batch_id``) still lands;
- an entry the model refuses (a non-string ``reason``, a malformed
  ``approval``, ...) is kept OPAQUE — only its required keys are read — and
  written back verbatim, so no object entry can block a write;
- strict mode refuses only an entry that is not an object.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mureo.context.auto_evaluation import due_candidates, plan_closure
from mureo.context.models import ActionLogEntry
from mureo.context.ops_history_view import build_ops_history_items
from mureo.context.settings import set_ops_history_enabled
from mureo.context.state import (
    append_action_log,
    read_state_file,
    write_state_file,
)
from mureo.context.state_codec import parse_state, render_state
from mureo.mcp._handlers_history import _rendered_action_log
from mureo.web.ops_history_setting import write_setting

_CONFORMING_FIRST: dict[str, Any] = {
    "timestamp": "2026-09-01T09:00:00+09:00",
    "action": "google_ads_budget_update",
    "platform": "google_ads",
    "campaign_id": "C-1",
}

# The four shapes observed in real workspaces. Values are synthetic.
_NO_TIMESTAMP_A: dict[str, Any] = {
    "action": "budget_raise",
    "campaign": "Brand Search",
    "date": "2026-09-02",
    "observation_due": "2026-09-09",
    "platform": "google_ads",
    "rationale": "capped every afternoon",
    "pending": True,
    "metrics_at_action": {"cpa": 5200, "conversions": 45},
}
_NO_TIMESTAMP_B: dict[str, Any] = {
    "action": "pause_ad_group",
    "campaign_id": "C-2",
    "date": "2026-09-03",
    "platform": "meta_ads",
    "reason": "CPA three times the target",
    "observation_due": "2026-09-10",
    "outcome": "improved",
}
_NO_PLATFORM_A: dict[str, Any] = {
    "action": "daily_check",
    "summary": "all campaigns within target",
    "timestamp": "2026-09-04T08:00:00+09:00",
    "metrics_at_action": {"spend": 12000},
    "observation_due": "2026-09-11",
    "operation_mode": "maintain",
    "verdict": "healthy",
}
_NO_PLATFORM_B: dict[str, Any] = {
    "action": "weekly_review",
    "campaign_id": "C-3",
    "date": "2026-09-05",
    "timestamp": "2026-09-05T08:00:00+09:00",
    "metrics_at_action": {"clicks": 310},
    "observation_due": "2026-09-12",
    "operation_mode": "optimize",
    "summary": "two keywords proposed for removal",
    "critical_actions_pending": ["approve keyword removal"],
}
_CONFORMING_LAST: dict[str, Any] = {
    "timestamp": "2026-09-06T09:00:00+09:00",
    "action": "google_ads_keywords_add",
    "platform": "google_ads",
}

_PRESERVED: tuple[dict[str, Any], ...] = (
    _NO_TIMESTAMP_A,
    _NO_TIMESTAMP_B,
    _NO_PLATFORM_A,
    _NO_PLATFORM_B,
)
_PRESERVED_INDICES = (1, 2, 3, 4)


def _document() -> dict[str, Any]:
    """A document in the codec's own key order, so it round-trips as-is."""
    return {
        "version": "2",
        "last_synced_at": None,
        "customer_id": None,
        "campaigns": [],
        "platforms": None,
        "action_log": [
            _CONFORMING_FIRST,
            *_PRESERVED,
            _CONFORMING_LAST,
        ],
    }


def _text(data: dict[str, Any]) -> str:
    """Formatted exactly as ``render_state`` formats a document."""
    return json.dumps(data, ensure_ascii=False, indent=2)


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    path = tmp_path / "STATE.json"
    path.write_text(_text(_document()), encoding="utf-8")
    return path


def _on_disk_log(path: Path) -> list[Any]:
    log: list[Any] = json.loads(path.read_text(encoding="utf-8"))["action_log"]
    return log


def _assert_preserved_unchanged(path: Path) -> None:
    log = _on_disk_log(path)
    for index, original in zip(_PRESERVED_INDICES, _PRESERVED, strict=True):
        assert log[index] == original
        assert list(log[index]) == list(original), "key order changed"


@pytest.mark.unit
class TestStrictReadKeepsEntriesInPlace:
    def test_strict_read_succeeds_with_every_entry_at_its_index(
        self, state_file: Path
    ) -> None:
        doc = read_state_file(state_file, strict=True)

        assert len(doc.action_log) == len(_document()["action_log"])
        assert doc.action_log[0].action == _CONFORMING_FIRST["action"]
        assert doc.action_log[-1].action == _CONFORMING_LAST["action"]
        for index, original in zip(_PRESERVED_INDICES, _PRESERVED, strict=True):
            assert doc.action_log[index].action == original["action"]

    def test_missing_required_fields_read_as_empty(self, state_file: Path) -> None:
        doc = read_state_file(state_file, strict=True)

        assert doc.action_log[1].timestamp == ""
        assert doc.action_log[2].timestamp == ""
        assert doc.action_log[3].platform == ""
        assert doc.action_log[4].platform == ""
        assert doc.action_log[1].platform == "google_ads"
        assert doc.action_log[3].timestamp == _NO_PLATFORM_A["timestamp"]

    def test_raw_is_kept_only_on_entries_the_codec_cannot_represent(
        self, state_file: Path
    ) -> None:
        doc = read_state_file(state_file, strict=True)

        assert doc.action_log[0].raw is None
        assert doc.action_log[-1].raw is None
        for index, original in zip(_PRESERVED_INDICES, _PRESERVED, strict=True):
            assert doc.action_log[index].raw == original

    def test_a_null_required_key_reads_as_empty_and_round_trips_as_null(
        self,
    ) -> None:
        data = _document()
        data["action_log"] = [{"timestamp": None, "action": "x", "platform": "g"}]
        text = _text(data)

        doc = parse_state(text)

        assert doc.action_log[0].timestamp == ""
        assert doc.action_log[0].raw is not None
        assert render_state(doc) == text

    def test_tolerant_read_yields_the_same_list(self, state_file: Path) -> None:
        strict = read_state_file(state_file, strict=True)
        tolerant = read_state_file(state_file, strict=False)

        assert tolerant.action_log == strict.action_log


@pytest.mark.unit
class TestVerbatimRoundTrip:
    def test_an_untouched_document_renders_byte_identically(self) -> None:
        text = _text(_document())

        assert render_state(parse_state(text)) == text

    def test_no_required_key_is_invented(self) -> None:
        rendered = json.loads(render_state(parse_state(_text(_document()))))
        log = rendered["action_log"]

        assert "timestamp" not in log[1]
        assert "timestamp" not in log[2]
        assert "platform" not in log[3]
        assert "platform" not in log[4]
        assert log[1]["rationale"] == "capped every afternoon"
        assert log[2]["outcome"] == "improved"
        assert log[3]["verdict"] == "healthy"
        assert log[4]["critical_actions_pending"] == ["approve keyword removal"]

    def test_unknown_key_on_a_conforming_entry_survives(self) -> None:
        entry = {
            "timestamp": "2026-09-07T09:00:00+09:00",
            "action": "x",
            "platform": "google_ads",
            "verdict": "ok",
        }
        data = _document()
        data["action_log"] = [entry]
        text = _text(data)

        doc = parse_state(text)

        assert doc.action_log[0].raw == entry
        assert render_state(doc) == text

    def test_a_mutation_lands_on_a_preserved_entry(self, state_file: Path) -> None:
        doc = read_state_file(state_file)
        log = list(doc.action_log)
        log[2] = dataclasses.replace(log[2], batch_id="b1")
        write_state_file(state_file, dataclasses.replace(doc, action_log=tuple(log)))

        stored = _on_disk_log(state_file)[2]

        assert stored["batch_id"] == "b1"
        assert stored["outcome"] == "improved"
        assert list(stored)[: len(_NO_TIMESTAMP_B)] == list(_NO_TIMESTAMP_B)
        assert "timestamp" not in stored
        assert read_state_file(state_file).action_log[2].batch_id == "b1"

    def test_a_cleared_known_field_stays_cleared(self) -> None:
        data = _document()
        data["action_log"] = [_NO_PLATFORM_A]
        doc = parse_state(_text(data))
        cleared = dataclasses.replace(doc.action_log[0], summary=None)

        rendered = json.loads(
            render_state(dataclasses.replace(doc, action_log=(cleared,)))
        )

        assert "summary" not in rendered["action_log"][0]
        assert rendered["action_log"][0]["verdict"] == "healthy"


@pytest.mark.unit
class TestWritersSucceed:
    def test_append_action_log(self, state_file: Path) -> None:
        append_action_log(
            state_file,
            ActionLogEntry(
                timestamp="2026-09-08T09:00:00+09:00",
                action="google_ads_status_update",
                platform="google_ads",
            ),
        )

        log = _on_disk_log(state_file)
        assert len(log) == len(_document()["action_log"]) + 1
        assert log[-1]["action"] == "google_ads_status_update"
        _assert_preserved_unchanged(state_file)

    def test_set_ops_history_enabled(self, state_file: Path) -> None:
        set_ops_history_enabled(state_file, True)

        _assert_preserved_unchanged(state_file)
        settings = read_state_file(state_file).settings
        assert settings is not None and settings.ops_history_enabled is True

    def test_dashboard_setting_write(self, state_file: Path) -> None:
        state = write_setting(state_file, True)

        assert state["enabled"] is True
        _assert_preserved_unchanged(state_file)


@pytest.mark.unit
class TestOnlyANonObjectEntryIsRefused:
    def test_a_non_object_entry_raises_in_strict_and_is_skipped_tolerantly(
        self,
    ) -> None:
        data = _document()
        data["action_log"] = [_CONFORMING_FIRST, "not an object"]
        text = _text(data)

        with pytest.raises(TypeError):
            parse_state(text, strict=True)
        tolerant = parse_state(text, strict=False)
        assert [e.action for e in tolerant.action_log] == [_CONFORMING_FIRST["action"]]

    def test_a_malformed_approval_is_kept_opaque_in_strict(self) -> None:
        bad = {
            **_CONFORMING_LAST,
            "campaign_id": "C-9",
            "approval": {"reference": "REQ-1"},
        }
        data = _document()
        data["action_log"] = [_CONFORMING_FIRST, bad]
        text = _text(data)

        doc = parse_state(text, strict=True)

        assert len(doc.action_log) == 2
        opaque = doc.action_log[1]
        assert opaque.action == bad["action"]
        assert opaque.approval is None
        assert opaque.campaign_id is None, "an opaque entry reads no optional field"
        assert opaque.raw == bad
        # The approval key, and every other key, is written back as found.
        assert render_state(doc) == text
        assert json.loads(render_state(doc))["action_log"][1]["approval"] == {
            "reference": "REQ-1"
        }
        # The tolerant view keeps the record and drops only the annotation
        # (unchanged behaviour, see ``tolerant_approval``).
        tolerant = parse_state(text, strict=False)
        assert len(tolerant.action_log) == 2
        assert tolerant.action_log[1].approval is None

    def test_a_value_the_model_refuses_is_kept_opaque(self, state_file: Path) -> None:
        refused = {**_CONFORMING_LAST, "campaign_id": "C-9", "reason": 123}
        data = _document()
        data["action_log"] = [_CONFORMING_FIRST, refused]
        text = _text(data)
        state_file.write_text(text, encoding="utf-8")

        doc = read_state_file(state_file, strict=True)

        assert [e.action for e in doc.action_log] == [
            _CONFORMING_FIRST["action"],
            refused["action"],
        ]
        assert doc.action_log[1].reason is None
        assert doc.action_log[1].raw == refused
        assert read_state_file(state_file, strict=False).action_log == doc.action_log
        assert render_state(doc) == text

        append_action_log(
            state_file,
            ActionLogEntry(
                timestamp="2026-09-08T09:00:00+09:00",
                action="google_ads_status_update",
                platform="google_ads",
            ),
        )
        log = _on_disk_log(state_file)
        assert len(log) == 3
        assert log[1] == refused
        assert list(log[1]) == list(refused)

    def test_a_non_string_required_value_reads_empty_and_round_trips(
        self,
    ) -> None:
        entry = {"timestamp": 123, "action": "x", "platform": "google_ads"}
        data = _document()
        data["action_log"] = [entry]
        text = _text(data)

        doc = parse_state(text)

        assert doc.action_log[0].timestamp == ""
        assert doc.action_log[0].raw == entry
        assert render_state(doc) == text
        assert json.loads(render_state(doc))["action_log"][0]["timestamp"] == 123


@pytest.mark.unit
class TestConsumersTolerateEmptyFields:
    def test_ops_history_items(self, state_file: Path) -> None:
        doc = read_state_file(state_file)

        items = build_ops_history_items(doc, today=date(2026, 10, 1))

        assert isinstance(items, list)

    def test_auto_evaluation_candidates_are_planned_without_raising(
        self, state_file: Path
    ) -> None:
        doc = read_state_file(state_file)
        today = date.today()

        candidates = due_candidates(doc, today)

        assert set(_PRESERVED_INDICES) <= set(candidates)
        for index in candidates:
            plan_closure(doc, index, today)

    def test_report_summary_lists_the_preserved_entries(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path
    ) -> None:
        from mureo.core.runtime_context import default_runtime_context
        from mureo.web.reports import build_report_summary

        ctx = default_runtime_context(workspace=state_file.parent)
        monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)

        actions = build_report_summary()["recent_actions"]

        assert len(actions) == len(_document()["action_log"])

    def test_history_query_indices_match_disk_positions(self, state_file: Path) -> None:
        rendered = _rendered_action_log(state_file)

        assert rendered == _on_disk_log(state_file)
