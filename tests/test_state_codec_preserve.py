"""Refused decisions and document-level shapes are kept in place (#882).

#859 (``action_log``) and #881 (``platforms`` / ``campaigns`` / ``ads``)
stopped one hand-authored entry from blocking every STATE.json write. Two
shapes were left: a ``decisions`` record the model refuses, and a section
with no enclosing entry to be kept in — a top-level ``campaigns`` that is
not a list of objects, a ``platforms`` that is not an object, a platform
value that is not an object, a ``decisions`` that is not a list.

The contract pinned here:

- the strict (writer) parse succeeds on every such shape, and so does the
  read-only one, building the same document — except that the read-only
  one still reads the object entries of a mixed top-level ``campaigns``;
- the document round-trips through ``parse_state`` -> ``render_state``
  unchanged, key order included, and a decision record the model takes
  keeps keys the codec does not know;
- appending a decision, an ``action_log`` entry or a report with the public
  writers keeps the refused content where it was, and appending a decision
  over a ``decisions`` that is not a list is refused;
- an ``action_log`` that is not a list is kept by both parses and written
  back as found, every other writer still works, and only recording an
  entry over it is refused; a ``null`` one reads as empty;
- no writer records a decision over a kept ``decisions``: a reasoned entry
  or batch is recorded without one (one WARNING), and an explicit
  ``decision_id`` or a call's own decision is refused as
  ``append_decision`` is — and
  ``render_state`` refuses a document holding both a kept ``decisions`` /
  ``action_log`` and new records;
- no reader (``decision_by_id``, ``latest_decisions``, the ``supersedes``
  chain, the ops history view) returns an opaque record, yet the writer
  refuses a new record under an opaque record's id;
- each kept item is logged once at DEBUG (never WARNING), by type, never
  by content.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mureo.context._platform_codec import parse_platform
from mureo.context._preserve import is_opaque_decision
from mureo.context.decision_chain import chain_roots, latest_in_chain
from mureo.context.decision_store import append_decision
from mureo.context.decisions import (
    DecisionRecord,
    decision_by_id,
    latest_decisions,
    parsed_decisions,
)
from mureo.context.models import ActionLogEntry, CampaignSnapshot
from mureo.context.ops_history_view import build_ops_history_items
from mureo.context.ops_intent import bind_ops_intent
from mureo.context.ops_linkage import LinkRequest, record_call_decision
from mureo.context.state import (
    append_action_log,
    begin_batch,
    read_state_file,
    set_report,
    upsert_campaign,
)
from mureo.context.state_codec import parse_state, render_state
from mureo.core.actor import bind_call_reason

pytestmark = pytest.mark.unit

_SECRET = "api_key=sk-live-SECRET"

_VALID_RECORD: dict[str, Any] = {
    "decision_id": "dec-valid",
    "recorded_at": "2026-10-01T09:00:00+09:00",
    "status": "proposed",
    "title": "Raise the brand budget",
    "rationale": "Capped by noon every day.",
}
# A record the model refuses: no ``recorded_at``, an unknown status, and
# keys the codec does not know. Values are synthetic.
_REFUSED_RECORD: dict[str, Any] = {
    "decision_id": "dec-hand",
    "status": "maybe-later",
    "title": "Hand-written",
    "rationale": _SECRET,
    "note": "typed straight into STATE.json",
}
_NO_ID_RECORD: dict[str, Any] = {"title": "no id", "rationale": "r"}
_ACCOUNT = {"account_id": "111-222-3333", "campaigns": []}


def _document(**sections: Any) -> dict[str, Any]:
    """A document in the codec's own key order, so it round-trips as-is."""
    data: dict[str, Any] = {
        "version": "2",
        "last_synced_at": None,
        "customer_id": None,
        "campaigns": [],
        "platforms": None,
        "action_log": [],
    }
    decisions = sections.pop("decisions", None)
    data.update(sections)
    if decisions is not None:
        data["decisions"] = decisions
    return data


def _text(data: dict[str, Any]) -> str:
    """Formatted exactly as ``render_state`` formats a document."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _assert_same_json(rendered: str, expected: dict[str, Any]) -> None:
    """Equal as JSON AND in key order at every level."""
    actual = json.loads(rendered)
    assert actual == expected
    assert _key_order(actual) == _key_order(expected)


def _key_order(value: Any) -> Any:
    if isinstance(value, dict):
        return [(key, _key_order(item)) for key, item in value.items()]
    if isinstance(value, list):
        return [_key_order(item) for item in value]
    return value


#: Every shape #882 keeps, by name, as the document that carries it.
_SHAPES: dict[str, dict[str, Any]] = {
    "decisions-not-a-list": _document(decisions={"dec-1": "an object, not a list"}),
    "refused-decision-record": _document(
        decisions=[_VALID_RECORD, _REFUSED_RECORD, _NO_ID_RECORD]
    ),
    "campaigns-not-a-list": _document(campaigns="see the weekly sheet"),
    "campaigns-with-a-non-object": _document(
        campaigns=[{"campaign_id": "c1", "campaign_name": "A", "status": "X"}, "x"]
    ),
    "platforms-not-an-object": _document(platforms=["google_ads", "meta_ads"]),
    "one-bad-platform-value": _document(
        platforms={"google_ads": _ACCOUNT, "meta_ads": "paused for the quarter"}
    ),
}


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "STATE.json"
    path.write_text(_text(data), encoding="utf-8")
    return path


def _on_disk(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _kept_sections(data: dict[str, Any]) -> dict[str, Any]:
    """The sections a shape lives in — everything a writer must not touch."""
    return {key: data.get(key) for key in ("campaigns", "platforms", "decisions")}


def _new_record(**overrides: Any) -> DecisionRecord:
    base: dict[str, Any] = {
        "decision_id": "dec-new",
        "recorded_at": "2026-10-02T09:00:00+09:00",
        "status": "proposed",
        "title": "A new decision",
        "rationale": "Because.",
    }
    base.update(overrides)
    return DecisionRecord(**base)


# ---------------------------------------------------------------------------
# Parse and round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.parametrize(
        "shape", sorted(set(_SHAPES) - {"campaigns-with-a-non-object"})
    )
    def test_both_modes_parse_and_build_the_same_document(self, shape: str) -> None:
        text = _text(_SHAPES[shape])

        assert parse_state(text, strict=True) == parse_state(text, strict=False)

    @pytest.mark.parametrize("shape", sorted(_SHAPES))
    def test_the_document_is_written_back_as_found(self, shape: str) -> None:
        text = _text(_SHAPES[shape])

        rendered = render_state(parse_state(text))

        _assert_same_json(rendered, _SHAPES[shape])
        assert rendered == text

    def test_a_refused_record_is_opaque_and_in_place(self) -> None:
        doc = parse_state(_text(_SHAPES["refused-decision-record"]))

        valid, hand, no_id = doc.decisions
        assert valid.raw is None
        assert (hand.decision_id, hand.status, hand.raw) == (
            "dec-hand",
            "",
            _REFUSED_RECORD,
        )
        assert (no_id.decision_id, no_id.raw) == ("", _NO_ID_RECORD)

    def test_a_padded_id_is_not_read(self) -> None:
        """Only an id the model would take unchanged is read — a stripped
        one would no longer be the on-disk value."""
        record = {**_REFUSED_RECORD, "decision_id": " dec-padded "}
        doc = parse_state(_text(_document(decisions=[record])))

        assert doc.decisions[0].decision_id == ""
        assert json.loads(render_state(doc))["decisions"] == [record]

    @pytest.mark.parametrize(
        ("shape", "raw"),
        [
            ("decisions-not-a-list", {"decisions": {"dec-1": "an object, not a list"}}),
            ("campaigns-not-a-list", {"campaigns": "see the weekly sheet"}),
            ("platforms-not-an-object", {"platforms": ["google_ads", "meta_ads"]}),
            (
                "one-bad-platform-value",
                {
                    "platforms": {
                        "google_ads": _ACCOUNT,
                        "meta_ads": "paused for the quarter",
                    }
                },
            ),
        ],
    )
    def test_the_section_is_kept_on_the_document(
        self, shape: str, raw: dict[str, Any]
    ) -> None:
        assert parse_state(_text(_SHAPES[shape])).raw == raw

    def test_an_accepted_record_keeps_its_unknown_keys(self) -> None:
        """The ``action_log`` rule: a record the model takes is read like any
        other and still writes back the keys the codec does not know."""
        record = {**_VALID_RECORD, "notes": "kept by hand"}
        data = _document(decisions=[record])
        text = _text(data)

        doc = parse_state(text)

        found = decision_by_id(doc, "dec-valid")
        assert found is not None and found.status == "proposed"
        assert parsed_decisions(doc) == doc.decisions
        rendered = render_state(doc)
        _assert_same_json(rendered, data)
        assert rendered == text

    def test_an_accepted_record_keeps_its_unknown_keys_through_a_write(
        self, tmp_path: Path
    ) -> None:
        record = {**_VALID_RECORD, "notes": "kept by hand"}
        path = _write(tmp_path, _document(decisions=[record]))

        append_decision(path, _new_record())

        assert _on_disk(path)["decisions"][0] == record

    def test_a_mixed_top_level_campaigns_list(self) -> None:
        """Ten objects and a stray int: the read-only view shows the ten, the
        writers read none, and the list is written back as found."""
        entries: list[Any] = [
            {"campaign_id": f"c{i}", "campaign_name": "A", "status": "ENABLED"}
            for i in range(10)
        ]
        data = _document(campaigns=[*entries[:5], 7, *entries[5:]])
        text = _text(data)

        tolerant = parse_state(text, strict=False)
        strict = parse_state(text, strict=True)

        assert [c.campaign_id for c in tolerant.campaigns] == [
            f"c{i}" for i in range(10)
        ]
        assert strict.campaigns == ()
        assert strict.raw == tolerant.raw == {"campaigns": data["campaigns"]}
        rendered = render_state(strict)
        _assert_same_json(rendered, data)
        assert rendered == text

    def test_a_kept_platform_value_keeps_its_position(self) -> None:
        data = _document(platforms={"a": _ACCOUNT, "b": 5, "c": _ACCOUNT})
        text = _text(data)

        doc = parse_state(text)

        assert doc.platforms is not None and list(doc.platforms) == ["a", "c"]
        rendered = render_state(doc)
        assert list(json.loads(rendered)["platforms"]) == ["a", "b", "c"]
        _assert_same_json(rendered, data)
        assert rendered == text

    def test_a_platform_a_writer_adds_follows_the_kept_ones(self) -> None:
        doc = parse_state(_text(_document(platforms={"a": _ACCOUNT, "b": 5})))
        assert doc.platforms is not None
        added = {**doc.platforms, "d": parse_platform("d", _ACCOUNT)}

        rendered = json.loads(render_state(dataclasses.replace(doc, platforms=added)))

        assert list(rendered["platforms"]) == ["a", "b", "d"]

    def test_only_a_refused_record_is_opaque(self) -> None:
        record = {**_VALID_RECORD, "notes": "kept by hand"}
        doc = parse_state(_text(_document(decisions=[record, _REFUSED_RECORD])))

        accepted, refused = doc.decisions
        assert accepted.raw is not None and not is_opaque_decision(accepted)
        assert is_opaque_decision(refused)
        assert not is_opaque_decision(_new_record())

    def test_a_document_mureo_writes_carries_no_raw(self) -> None:
        doc = parse_state(_text(_document(decisions=[_VALID_RECORD])))

        assert doc.raw is None
        assert doc.decisions[0].raw is None


# ---------------------------------------------------------------------------
# Writers keep what was kept
# ---------------------------------------------------------------------------


class TestWriters:
    @pytest.mark.parametrize(
        "shape",
        sorted(set(_SHAPES) - {"decisions-not-a-list"}),
    )
    def test_append_decision_keeps_the_shape(self, tmp_path: Path, shape: str) -> None:
        path = _write(tmp_path, _SHAPES[shape])

        _doc, index = append_decision(path, _new_record())

        written = _on_disk(path)
        before = _kept_sections(_SHAPES[shape])
        assert written["campaigns"] == before["campaigns"]
        assert written["platforms"] == before["platforms"]
        assert written["decisions"][:index] == (before["decisions"] or [])
        assert written["decisions"][index]["decision_id"] == "dec-new"

    @pytest.mark.parametrize("shape", sorted(_SHAPES))
    def test_append_action_log_keeps_the_shape(
        self, tmp_path: Path, shape: str
    ) -> None:
        path = _write(tmp_path, _SHAPES[shape])

        append_action_log(
            path,
            ActionLogEntry(
                timestamp="2026-10-02T09:00:00+09:00",
                action="google_ads_budget_update",
                platform="google_ads",
            ),
        )

        written = _on_disk(path)
        assert _kept_sections(written) == _kept_sections(_SHAPES[shape])
        assert len(written["action_log"]) == 1

    @pytest.mark.parametrize("shape", sorted(_SHAPES))
    def test_set_report_keeps_the_shape(self, tmp_path: Path, shape: str) -> None:
        path = _write(tmp_path, _SHAPES[shape])

        set_report(path, "weekly", {"narrative": "steady"})

        written = _on_disk(path)
        assert _kept_sections(written) == _kept_sections(_SHAPES[shape])
        assert written["reports"] == {"weekly": {"narrative": "steady"}}

    def test_a_decision_appended_over_a_non_list_section_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Appending would replace a value somebody wrote: refused, naming
        the section only, and nothing is written."""
        path = _write(tmp_path, _SHAPES["decisions-not-a-list"])
        before = path.read_bytes()

        with pytest.raises(
            ValueError,
            match="'decisions' is not a list; fix the file by hand before "
            "recording a decision",
        ) as info:
            append_decision(path, _new_record())

        assert "an object, not a list" not in str(info.value)
        assert path.read_bytes() == before
        assert read_state_file(path).raw == {
            "decisions": {"dec-1": "an object, not a list"}
        }

    def test_a_platform_written_over_a_kept_value_replaces_only_that_key(
        self,
    ) -> None:
        """A writer that now holds the kept key wins; other kept keys stay."""
        data = _document(platforms={"google_ads": _ACCOUNT, "x": 1, "meta_ads": "m"})
        doc = parse_state(_text(data))
        assert doc.platforms is not None
        filled = {**doc.platforms, "meta_ads": parse_platform("meta_ads", _ACCOUNT)}

        rendered = json.loads(render_state(dataclasses.replace(doc, platforms=filled)))

        assert rendered["platforms"]["meta_ads"]["account_id"] == "111-222-3333"
        assert rendered["platforms"]["x"] == 1

    def test_a_platforms_section_filled_by_a_writer_replaces_the_kept_value(
        self, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, _SHAPES["platforms-not-an-object"])

        upsert_campaign(
            path,
            CampaignSnapshot(campaign_id="c1", campaign_name="A", status="ENABLED"),
            platform="google_ads",
            account_id="111-222-3333",
        )

        written = _on_disk(path)
        assert list(written["platforms"]) == ["google_ads"]
        assert read_state_file(path).raw is None


# ---------------------------------------------------------------------------
# An action_log that is not a list
# ---------------------------------------------------------------------------

_NON_LIST_LOGS: list[Any] = ["see the weekly sheet", {"0": {"action": "x"}}, 7]


def _entry() -> ActionLogEntry:
    return ActionLogEntry(
        timestamp="2026-10-02T09:00:00+09:00",
        action="google_ads_budget_update",
        platform="google_ads",
    )


class TestActionLogNotAList:
    @pytest.mark.parametrize("strict", [True, False])
    @pytest.mark.parametrize("value", _NON_LIST_LOGS)
    def test_both_parses_keep_it_and_log_only_at_debug(
        self, caplog: pytest.LogCaptureFixture, value: Any, strict: bool
    ) -> None:
        text = _text(_document(action_log=value))

        with caplog.at_level(logging.DEBUG):
            doc = parse_state(text, strict=strict)

        assert doc.action_log == ()
        assert doc.raw == {"action_log": value}
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        kept = [r for r in caplog.records if "'action_log'" in r.getMessage()]
        assert len(kept) == 1 and type(value).__name__ in kept[0].getMessage()
        assert "weekly sheet" not in caplog.text

    @pytest.mark.parametrize("value", _NON_LIST_LOGS)
    def test_the_document_is_written_back_as_found(self, value: Any) -> None:
        data = _document(action_log=value)
        text = _text(data)

        rendered = render_state(parse_state(text))

        _assert_same_json(rendered, data)
        assert rendered == text

    @pytest.mark.parametrize("value", _NON_LIST_LOGS)
    def test_another_writer_leaves_it_in_place(
        self, tmp_path: Path, value: Any
    ) -> None:
        path = _write(tmp_path, _document(action_log=value))

        set_report(path, "weekly", {"narrative": "steady"})

        written = _on_disk(path)
        assert written["action_log"] == value
        assert list(written).index("action_log") == 5
        assert written["reports"] == {"weekly": {"narrative": "steady"}}

    @pytest.mark.parametrize("strict", [True, False])
    def test_null_reads_as_an_empty_log(self, strict: bool) -> None:
        doc = parse_state(_text(_document(action_log=None)), strict=strict)

        assert doc.action_log == ()
        assert doc.raw is None

    def test_the_first_entry_over_null_writes_a_list(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _document(action_log=None))

        append_action_log(path, _entry())

        (entry,) = _on_disk(path)["action_log"]
        assert entry["action"] == "google_ads_budget_update"
        assert read_state_file(path).raw is None

    def test_an_entry_recorded_on_a_list_is_unaffected(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _document())

        append_action_log(path, _entry())

        assert len(_on_disk(path)["action_log"]) == 1
        assert read_state_file(path).raw is None

    @pytest.mark.parametrize("value", _NON_LIST_LOGS)
    def test_recording_an_entry_is_refused(self, tmp_path: Path, value: Any) -> None:
        path = _write(tmp_path, _document(action_log=value))
        before = path.read_bytes()

        with pytest.raises(
            ValueError,
            match="STATE.json: 'action_log' is not a list; fix the file by hand "
            "before recording an entry",
        ) as info:
            append_action_log(path, _entry())

        assert "weekly sheet" not in str(info.value)
        assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# Nothing records a decision over a kept ``decisions``
# ---------------------------------------------------------------------------

_DECISIONS_REFUSAL = (
    "'decisions' is not a list; fix the file by hand before recording a decision"
)
_KEPT_DECISIONS = {"dec-1": "an object, not a list"}


def _kept_decisions_file(tmp_path: Path) -> tuple[Path, bytes]:
    path = _write(tmp_path, _document(decisions=_KEPT_DECISIONS))
    return path, path.read_bytes()


def _assert_kept_decisions(path: Path) -> None:
    written = _on_disk(path)["decisions"]
    assert json.dumps(written) == json.dumps(_KEPT_DECISIONS)


def _unlinked_warnings(
    caplog: pytest.LogCaptureFixture, recorded: str
) -> list[logging.LogRecord]:
    message = (
        f"STATE.json: 'decisions' is kept as written; {recorded} recorded without "
        "a decision link; fix the file by hand"
    )
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert all(r.exc_info is None for r in warnings)
    return [r for r in warnings if r.getMessage() == message]


class TestLinkageOverKeptDecisions:
    def test_an_entry_with_a_reason_records_without_a_decision(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path, _ = _kept_decisions_file(tmp_path)

        with caplog.at_level(logging.DEBUG):
            append_action_log(path, dataclasses.replace(_entry(), reason="CPA high"))

        (entry,) = _on_disk(path)["action_log"]
        assert entry["reason"] == "CPA high"
        assert "decision_id" not in entry
        _assert_kept_decisions(path)
        assert len(_unlinked_warnings(caplog, "entry")) == 1
        assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1

    def test_an_entry_naming_a_decision_is_refused(self, tmp_path: Path) -> None:
        path, before = _kept_decisions_file(tmp_path)

        with pytest.raises(ValueError, match=_DECISIONS_REFUSAL):
            append_action_log(path, dataclasses.replace(_entry(), decision_id="dec-1"))

        assert path.read_bytes() == before

    def test_an_entry_without_a_decision_still_records(self, tmp_path: Path) -> None:
        path, _ = _kept_decisions_file(tmp_path)

        append_action_log(path, _entry())

        written = _on_disk(path)
        assert len(written["action_log"]) == 1
        assert written["decisions"] == _KEPT_DECISIONS
        assert json.dumps(written["decisions"]) == json.dumps(_KEPT_DECISIONS)

    def test_a_batch_opened_with_a_reason_starts_without_a_decision(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path, _ = _kept_decisions_file(tmp_path)

        with caplog.at_level(logging.DEBUG), bind_call_reason("One cleanup pass."):
            batch = begin_batch(path, label="Cleanup")

        assert [b.batch_id for b in read_state_file(path).batches] == [batch.batch_id]
        _assert_kept_decisions(path)
        assert len(_unlinked_warnings(caplog, "batch")) == 1
        assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1

    def test_a_batch_naming_a_decision_is_refused(self, tmp_path: Path) -> None:
        path, before = _kept_decisions_file(tmp_path)

        with (
            bind_ops_intent(decision_id="dec-1"),
            pytest.raises(ValueError, match=_DECISIONS_REFUSAL),
        ):
            begin_batch(path, label="Cleanup")

        assert path.read_bytes() == before

    def test_a_call_decision_is_refused(self, tmp_path: Path) -> None:
        path, before = _kept_decisions_file(tmp_path)
        request = LinkRequest(reason="CPA high", now="2026-10-14T01:00:00+00:00")

        with pytest.raises(ValueError, match=_DECISIONS_REFUSAL):
            record_call_decision(
                path, request, tool="google_ads_budget_update", platform="google_ads"
            )

        assert path.read_bytes() == before


class TestRenderGuard:
    def test_new_decisions_over_a_kept_value_are_refused(self) -> None:
        doc = parse_state(_text(_document(decisions=_KEPT_DECISIONS)))
        forced = dataclasses.replace(doc, decisions=(_new_record(),))

        with pytest.raises(ValueError, match="'decisions' was kept as written"):
            render_state(forced)

    def test_new_entries_over_a_kept_value_are_refused(self) -> None:
        doc = parse_state(_text(_document(action_log="see the weekly sheet")))
        forced = dataclasses.replace(doc, action_log=(_entry(),))

        with pytest.raises(
            ValueError, match="'action_log' was kept as written"
        ) as info:
            render_state(forced)

        assert "weekly sheet" not in str(info.value)


# ---------------------------------------------------------------------------
# Readers never match an opaque record
# ---------------------------------------------------------------------------


def _chained_document() -> dict[str, Any]:
    """A valid proposal, an opaque record superseding it, a valid adoption."""
    opaque_successor = {
        "decision_id": "dec-hand",
        "supersedes": "dec-valid",
        "status": "adopted",
        "title": "missing recorded_at",
        "rationale": "r",
    }
    return _document(decisions=[_VALID_RECORD, opaque_successor])


class TestReaders:
    def test_decision_by_id_skips_an_opaque_record(self) -> None:
        doc = parse_state(_text(_chained_document()))

        assert decision_by_id(doc, "dec-hand") is None
        assert decision_by_id(doc, "dec-valid") is not None

    def test_latest_decisions_skips_an_opaque_record(self) -> None:
        doc = parse_state(_text(_chained_document()))

        assert [d.decision_id for d in latest_decisions(doc)] == ["dec-valid"]
        assert parsed_decisions(doc) == (doc.decisions[0],)

    def test_the_chain_ignores_an_opaque_successor(self) -> None:
        doc = parse_state(_text(_chained_document()))

        assert chain_roots(doc) == {"dec-valid": "dec-valid"}
        latest = latest_in_chain(doc, "dec-valid")
        assert latest is not None and latest.status == "proposed"

    def test_the_ops_history_view_ignores_an_opaque_record(self) -> None:
        doc = parse_state(_text(_chained_document()))

        items = build_ops_history_items(doc, today=date(2026, 10, 3))

        ids = [item["decision"]["decision_id"] for item in items if item["decision"]]
        assert "dec-hand" not in ids
        assert "" not in ids

    def test_supersedes_cannot_name_an_opaque_record(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _chained_document())

        with pytest.raises(ValueError, match="supersedes"):
            append_decision(path, _new_record(supersedes="dec-hand"))

    def test_a_new_record_under_an_opaque_records_id_is_refused(
        self, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, _chained_document())
        before = path.read_bytes()

        with pytest.raises(ValueError, match="already on record"):
            append_decision(path, _new_record(decision_id="dec-hand"))
        assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestLogging:
    @pytest.mark.parametrize(
        ("shape", "type_name"),
        [
            ("decisions-not-a-list", "dict"),
            ("campaigns-not-a-list", "str"),
            ("campaigns-with-a-non-object", "list"),
            ("platforms-not-an-object", "list"),
            ("one-bad-platform-value", "str"),
        ],
    )
    def test_a_kept_section_logs_only_at_debug(
        self,
        caplog: pytest.LogCaptureFixture,
        shape: str,
        type_name: str,
    ) -> None:
        """One DEBUG line per kept section or platform value, by type, and
        no WARNING: the Reports view reads strictly on every poll."""
        with caplog.at_level(logging.DEBUG):
            parse_state(_text(_SHAPES[shape]), strict=True)

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        kept = [r for r in caplog.records if "as found" in r.getMessage()]
        assert len(kept) == 1
        assert kept[0].levelno == logging.DEBUG
        assert type_name in kept[0].getMessage()
        for secret in (_SECRET, "weekly sheet", "paused for the quarter", "dec-1"):
            assert secret not in caplog.text

    def test_a_kept_decision_record_warns_about_nothing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The Reports view reads strictly on every poll: a refused record is
        logged at DEBUG (by type), never at WARNING — as the #881 shapes are."""
        with caplog.at_level(logging.DEBUG):
            parse_state(_text(_SHAPES["refused-decision-record"]), strict=True)

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        debug = [
            r for r in caplog.records if "refused decisions record" in r.getMessage()
        ]
        assert len(debug) == 2
        assert all("ValueError" in r.getMessage() for r in debug)
        assert _SECRET not in caplog.text

    def test_a_skipped_campaigns_entry_logs_its_type_at_debug(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            parse_state(_text(_SHAPES["campaigns-with-a-non-object"]), strict=False)

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        skipped = [r for r in caplog.records if "non-object" in r.getMessage()]
        assert len(skipped) == 1
        assert "str" in skipped[0].getMessage()
