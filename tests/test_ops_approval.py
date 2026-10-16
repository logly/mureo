"""The external approval reference a change carries out (#854).

``approval`` says which human sign-off outside mureo a change executed:
a reference, who approved it and when. mureo records and shows it and
verifies nothing about it. These tests pin the value's bounds, its place
on an ``action_log`` entry and on a decision record, and the codec rule
every optional field follows: an old document parses unchanged and gains
no key on the next write.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mureo.context.approval import (
    APPROVAL_BY_MAX_CHARS,
    APPROVAL_REFERENCE_MAX_CHARS,
    ApprovalRef,
    approval_to_dict,
    parse_approval,
)
from mureo.context.decisions import DecisionRecord
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state import append_action_log, read_state_file, write_state_file
from mureo.context.state_codec import parse_state, render_state

pytestmark = pytest.mark.unit

STAMP = "2026-10-17T09:30:00+09:00"


def _approval(**extra: Any) -> dict[str, Any]:
    return {
        "reference": "REQ-2026.10_17-a",
        "approved_by": "Jane Operator",
        "approved_at": STAMP,
        **extra,
    }


def _entry(**extra: Any) -> ActionLogEntry:
    fields: dict[str, Any] = {
        "timestamp": "2026-10-17T10:00:00+09:00",
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        **extra,
    }
    return ActionLogEntry(**fields)


def _record(**extra: Any) -> DecisionRecord:
    fields: dict[str, Any] = {
        "decision_id": "dec-1",
        "recorded_at": "2026-10-17T10:00:00+09:00",
        "status": "adopted",
        "title": "Raise budget b1",
        "rationale": "Capped by noon for a week.",
        **extra,
    }
    return DecisionRecord(**fields)


class TestParse:
    def test_none_is_no_approval(self) -> None:
        assert parse_approval(None) is None

    def test_a_valid_object(self) -> None:
        ref = parse_approval(_approval())
        assert ref == ApprovalRef(
            reference="REQ-2026.10_17-a",
            approved_by="Jane Operator",
            approved_at=STAMP,
        )

    def test_an_approval_ref_passes_through(self) -> None:
        ref = ApprovalRef(reference="r1", approved_by="A", approved_at=STAMP)
        assert parse_approval(ref) is ref

    def test_the_round_trip(self) -> None:
        assert approval_to_dict(parse_approval(_approval())) == _approval()

    def test_approved_by_is_stripped(self) -> None:
        ref = parse_approval(_approval(approved_by="  Jane  "))
        assert ref is not None
        assert ref.approved_by == "Jane"

    def test_approved_at_keeps_its_original_spelling(self) -> None:
        ref = parse_approval(_approval(approved_at="2026-10-17T00:30:00Z"))
        assert ref is not None
        assert ref.approved_at == "2026-10-17T00:30:00Z"

    def test_a_date_is_iso_8601(self) -> None:
        ref = parse_approval(_approval(approved_at="2026-10-17"))
        assert ref is not None
        assert ref.approved_at == "2026-10-17"

    def test_non_ascii_names_count_code_points(self) -> None:
        name = "承" * APPROVAL_BY_MAX_CHARS
        ref = parse_approval(_approval(approved_by=name))
        assert ref is not None
        assert ref.approved_by == name

    def test_the_limits_themselves_are_accepted(self) -> None:
        ref = parse_approval(
            _approval(
                reference="r" * APPROVAL_REFERENCE_MAX_CHARS,
                approved_by="b" * APPROVAL_BY_MAX_CHARS,
            )
        )
        assert ref is not None

    @pytest.mark.parametrize(
        ("extra", "field"),
        [
            ({"reference": ""}, "approval.reference"),
            ({"reference": "r" * (APPROVAL_REFERENCE_MAX_CHARS + 1)}, "reference"),
            ({"reference": "REQ 1"}, "approval.reference"),
            ({"reference": "REQ/1"}, "approval.reference"),
            ({"reference": "REQ-1\n"}, "approval.reference"),
            ({"reference": "参照1"}, "approval.reference"),
            ({"reference": 12}, "approval.reference"),
            ({"approved_by": ""}, "approval.approved_by"),
            ({"approved_by": "   "}, "approval.approved_by"),
            ({"approved_by": "b" * (APPROVAL_BY_MAX_CHARS + 1)}, "approved_by"),
            ({"approved_by": "Jane\x00Doe"}, "approval.approved_by"),
            ({"approved_by": "Jane\nDoe"}, "approval.approved_by"),
            ({"approved_by": "Jane\x1bDoe"}, "approval.approved_by"),
            ({"approved_by": "Jane\x85Doe"}, "approval.approved_by"),
            ({"approved_by": None}, "approval.approved_by"),
            ({"approved_at": "yesterday"}, "approval.approved_at"),
            ({"approved_at": "2026-13-01"}, "approval.approved_at"),
            ({"approved_at": ""}, "approval.approved_at"),
            ({"approved_at": " 2026-10-17"}, "approval.approved_at"),
            ({"approved_at": 20261017}, "approval.approved_at"),
        ],
    )
    def test_out_of_bounds_is_refused_naming_the_field(
        self, extra: dict[str, Any], field: str
    ) -> None:
        with pytest.raises(ValueError, match=field):
            parse_approval(_approval(**extra))

    @pytest.mark.parametrize(
        "stamp",
        [
            # Accepted by ``fromisoformat`` on 3.11+ only; refused everywhere.
            "20261017",
            "2026-W42-1",
            "2026-10-17x09:30",
            # Outside the profile on every version.
            "2026-10-17T09",
            "2026-10-17T09:30:00.1234567",
            "2026-10-17T09:30+0900",
            "2026-10-17T09:30:00Z\n",
            "２０２６-10-17",
        ],
    )
    def test_approved_at_outside_the_profile_is_refused(self, stamp: str) -> None:
        with pytest.raises(ValueError, match="approval.approved_at"):
            parse_approval(_approval(approved_at=stamp))

    @pytest.mark.parametrize(
        "stamp",
        [
            "2026-10-17",
            "2026-10-17T09:30",
            "2026-10-17 09:30:00",
            "2026-10-17T09:30:00.5+09:00",
            "2026-10-17T09:30:00.123456Z",
            "2026-10-17T09:30:00-05:00",
        ],
    )
    def test_approved_at_inside_the_profile_is_accepted(self, stamp: str) -> None:
        ref = parse_approval(_approval(approved_at=stamp))
        assert ref is not None
        assert ref.approved_at == stamp

    @pytest.mark.parametrize(
        "stamp", ["2026-02-30", "2026-10-17T25:00", "2026-10-17T09:30+24:00"]
    )
    def test_approved_at_must_be_on_the_calendar(self, stamp: str) -> None:
        with pytest.raises(ValueError, match="approval.approved_at"):
            parse_approval(_approval(approved_at=stamp))

    def test_an_approved_at_refusal_does_not_echo_the_value(self) -> None:
        with pytest.raises(ValueError) as caught:
            parse_approval(_approval(approved_at="secret-time"))
        assert "secret" not in str(caught.value)

    @pytest.mark.parametrize(
        "char",
        [
            "\u202e",  # right-to-left override (Cf)
            "\u2028",  # line separator (Zl)
            "\u200b",  # zero-width space (Cf)
            "\u2029",  # paragraph separator (Zp)
            "\ue000",  # private use (Co)
        ],
    )
    def test_approved_by_refuses_invisible_and_layout_characters(
        self, char: str
    ) -> None:
        with pytest.raises(ValueError, match="approval.approved_by"):
            parse_approval(_approval(approved_by=f"Jane{char}Doe"))

    def test_approved_by_refuses_a_lone_surrogate(self) -> None:
        with pytest.raises(ValueError, match="approval.approved_by"):
            parse_approval(_approval(approved_by="Jane\ud800Doe"))

    def test_an_unknown_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown key.*note"):
            parse_approval(_approval(note="ok"))

    @pytest.mark.parametrize("missing", ["reference", "approved_by", "approved_at"])
    def test_a_missing_key_is_refused(self, missing: str) -> None:
        value = _approval()
        del value[missing]
        with pytest.raises(ValueError, match=missing):
            parse_approval(value)

    @pytest.mark.parametrize("value", ["REQ-1", ["REQ-1"], 1, True])
    def test_a_non_object_is_refused(self, value: Any) -> None:
        with pytest.raises(ValueError, match="approval must be an object"):
            parse_approval(value)

    def test_the_value_object_validates_itself(self) -> None:
        with pytest.raises(ValueError, match="approval.reference"):
            ApprovalRef(reference="a b", approved_by="A", approved_at=STAMP)


class TestModels:
    def test_an_entry_has_none_by_default(self) -> None:
        assert _entry().approval is None

    def test_an_entry_normalises_a_dict(self) -> None:
        entry = _entry(approval=_approval(approved_by=" Jane "))
        assert entry.approval == ApprovalRef(
            reference="REQ-2026.10_17-a", approved_by="Jane", approved_at=STAMP
        )

    def test_an_entry_refuses_a_bad_value(self) -> None:
        with pytest.raises(ValueError, match="approval.approved_at"):
            _entry(approval=_approval(approved_at="soon"))

    def test_a_record_has_none_by_default(self) -> None:
        assert _record().approval is None

    def test_a_record_normalises_a_dict(self) -> None:
        record = _record(approval=_approval())
        assert record.approval == parse_approval(_approval())

    def test_a_record_refuses_a_bad_value(self) -> None:
        with pytest.raises(ValueError, match="approval"):
            _record(approval="REQ-1")


def _document(entry: dict[str, Any], record: dict[str, Any]) -> str:
    return json.dumps(
        {"version": "2", "action_log": [entry], "decisions": [record]},
        ensure_ascii=False,
    )


def _entry_dict(**extra: Any) -> dict[str, Any]:
    return {
        "timestamp": "2026-10-17T10:00:00+09:00",
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        **extra,
    }


def _record_dict(**extra: Any) -> dict[str, Any]:
    return {
        "decision_id": "dec-1",
        "recorded_at": "2026-10-17T10:00:00+09:00",
        "status": "adopted",
        "title": "Raise budget b1",
        "rationale": "Capped by noon for a week.",
        **extra,
    }


class TestCodec:
    def test_both_round_trip(self) -> None:
        text = _document(
            _entry_dict(approval=_approval()), _record_dict(approval=_approval())
        )
        doc = parse_state(text)
        assert doc.action_log[0].approval == parse_approval(_approval())
        assert doc.decisions[0].approval == parse_approval(_approval())
        written = json.loads(render_state(doc))
        assert written["action_log"][0]["approval"] == _approval()
        assert written["decisions"][0]["approval"] == _approval()
        assert parse_state(render_state(doc)) == doc

    def test_an_old_document_gains_no_key(self) -> None:
        doc = parse_state(_document(_entry_dict(), _record_dict()))
        assert doc.action_log[0].approval is None
        assert doc.decisions[0].approval is None
        written = json.loads(render_state(doc))
        assert "approval" not in written["action_log"][0]
        assert "approval" not in written["decisions"][0]

    def test_a_malformed_stored_value_is_refused_by_the_writer_contract(
        self,
    ) -> None:
        text = _document(_entry_dict(approval={"reference": "x"}), _record_dict())
        with pytest.raises(ValueError, match="approval"):
            parse_state(text)

    def test_the_read_only_view_keeps_the_entry_without_it(self) -> None:
        text = _document(_entry_dict(approval={"reference": "x"}), _record_dict())
        doc = parse_state(text, strict=False)
        assert len(doc.action_log) == 1
        assert doc.action_log[0].action == "google_ads_budget_update"
        assert doc.action_log[0].approval is None
        assert len(doc.decisions) == 1

    def test_the_read_only_view_keeps_the_decision_without_it(self) -> None:
        text = _document(_entry_dict(), _record_dict(approval="REQ-1"))
        doc = parse_state(text, strict=False)
        assert len(doc.decisions) == 1
        assert doc.decisions[0].rationale == "Capped by noon for a week."
        assert doc.decisions[0].approval is None
        assert len(doc.action_log) == 1

    def test_the_read_only_view_does_not_log_the_value(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        bad = _approval(approved_at="secret-time")
        text = _document(_entry_dict(approval=bad), _record_dict(approval=bad))
        with caplog.at_level("DEBUG"):
            parse_state(text, strict=False)
        assert "secret" not in caplog.text

    def test_the_writer_contract_still_refuses_a_bad_decision_value(self) -> None:
        text = _document(_entry_dict(), _record_dict(approval="REQ-1"))
        with pytest.raises(ValueError, match="approval"):
            parse_state(text)


class TestAppend:
    def test_an_explicit_approval_is_written(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        write_state_file(path, StateDocument(version="2"))
        append_action_log(path, _entry(approval=_approval()))
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["action_log"][0]["approval"] == _approval()
        assert read_state_file(path).action_log[0].approval == parse_approval(
            _approval()
        )

    def test_no_approval_writes_no_key(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        write_state_file(path, StateDocument(version="2"))
        append_action_log(path, _entry(reason="Capped."))
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert "approval" not in stored["action_log"][0]
        assert "approval" not in stored["decisions"][0]
