"""Decision records — the append-only reasoning trail (#758, phase 3).

Why a section of its own rather than a wider ``display.proposals``: that
field is REPLACED WHOLE on every ``mureo_state_display_set``, so a proposal
written on Monday is gone by Tuesday's write. These tests pin the three
properties that makes it unable to provide — a record survives the session,
a status change is a NEW record rather than an edit, and the figures the
decision was judged on are stored beside it.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

import pytest

from mureo.context._decision_codec import decision_to_dict, parse_decisions
from mureo.context.batch import BatchError
from mureo.context.decisions import (
    DECISION_METRIC_VALUE_MAX_CHARS,
    DECISION_METRICS_MAX_KEYS,
    DECISION_RATIONALE_MAX_CHARS,
    DECISION_RELATED_ACTIONS_MAX,
    DECISION_STATUSES,
    DECISION_TITLE_MAX_CHARS,
    DecisionRecord,
    append_decision,
    decision_by_id,
    latest_decisions,
    new_decision_id,
)
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state import (
    append_action_log,
    begin_batch,
    end_batch,
    parse_state,
    read_state_file,
    render_state,
    write_state_file,
)

pytestmark = pytest.mark.unit


_RECORDED_AT = "2026-09-19T10:12:33+09:00"


def _record(**overrides: object) -> DecisionRecord:
    """A minimal valid record; ``overrides`` replaces any field."""
    base: dict[str, object] = {
        "decision_id": "dec-20260919T101233-1f4c9a02",
        "recorded_at": _RECORDED_AT,
        "status": "proposed",
        "title": "Pause Search_Lead-Gen generic ad group",
        "rationale": "CPA has been 3x target for 14 days at 40 conversions.",
    }
    base.update(overrides)
    return DecisionRecord(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Model: the bounds and the refusals
# ---------------------------------------------------------------------------


class TestDecisionRecordModel:
    def test_minimal_record_is_accepted(self) -> None:
        record = _record()
        assert record.status == "proposed"
        assert record.related_actions == ()
        assert record.metrics is None

    def test_statuses_are_the_declared_four(self) -> None:
        assert DECISION_STATUSES == ("proposed", "adopted", "rejected", "deferred")
        for status in DECISION_STATUSES:
            assert _record(status=status).status == status

    def test_unknown_status_is_refused(self) -> None:
        with pytest.raises(ValueError, match="status"):
            _record(status="maybe")

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_title_is_refused(self, blank: str) -> None:
        with pytest.raises(ValueError, match="title"):
            _record(title=blank)

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_rationale_is_refused(self, blank: str) -> None:
        with pytest.raises(ValueError, match="rationale"):
            _record(rationale=blank)

    def test_over_long_title_is_refused_not_truncated(self) -> None:
        with pytest.raises(ValueError, match="title"):
            _record(title="x" * (DECISION_TITLE_MAX_CHARS + 1))
        assert (
            _record(title="x" * DECISION_TITLE_MAX_CHARS).title
            == "x" * DECISION_TITLE_MAX_CHARS
        )

    def test_over_long_rationale_is_refused_not_truncated(self) -> None:
        with pytest.raises(ValueError, match="rationale"):
            _record(rationale="x" * (DECISION_RATIONALE_MAX_CHARS + 1))
        assert (
            len(_record(rationale="x" * DECISION_RATIONALE_MAX_CHARS).rationale)
            == DECISION_RATIONALE_MAX_CHARS
        )

    def test_metrics_scalars_are_kept_and_deep_copied(self) -> None:
        metrics = {"cpa_7d": 5200, "conversions_7d": 45, "note": "n/a", "ok": True}
        record = _record(metrics=metrics)
        metrics["cpa_7d"] = 1
        assert record.metrics == {
            "cpa_7d": 5200,
            "conversions_7d": 45,
            "note": "n/a",
            "ok": True,
        }

    def test_nested_metrics_value_is_refused(self) -> None:
        with pytest.raises(ValueError, match="metrics"):
            _record(metrics={"window": {"cpa": 5200}})

    def test_metrics_list_value_is_refused(self) -> None:
        with pytest.raises(ValueError, match="metrics"):
            _record(metrics={"cpa_by_day": [1, 2, 3]})

    def test_too_many_metric_keys_are_refused(self) -> None:
        over = {f"k{i}": i for i in range(DECISION_METRICS_MAX_KEYS + 1)}
        with pytest.raises(ValueError, match="metrics"):
            _record(metrics=over)
        at_bound = {f"k{i}": i for i in range(DECISION_METRICS_MAX_KEYS)}
        assert _record(metrics=at_bound).metrics == at_bound

    def test_entity_pair_must_be_provided_together(self) -> None:
        with pytest.raises(ValueError, match="entity_type and entity_id"):
            _record(entity_type="ad_group")
        with pytest.raises(ValueError, match="entity_type and entity_id"):
            _record(entity_id="4711")
        record = _record(entity_type=" ad_group ", entity_id=" 4711 ")
        assert (record.entity_type, record.entity_id) == ("ad_group", "4711")

    def test_related_actions_are_coerced_to_a_tuple_of_indices(self) -> None:
        assert _record(related_actions=[0, 2]).related_actions == (0, 2)

    @pytest.mark.parametrize("bad", [[-1], [True], ["0"], [1.5], 3])
    def test_related_actions_refuse_anything_but_indices(self, bad: object) -> None:
        with pytest.raises(ValueError, match="related_actions"):
            _record(related_actions=bad)

    def test_record_is_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            _record().title = "other"  # type: ignore[misc]

    def test_secret_shaped_text_is_scrubbed_at_the_model_boundary(self) -> None:
        """Same rule and the same single scrubber as phase 2's rationale: a
        model that quotes the failing request into its reasoning must not
        leak the key into a file the operator commits."""
        record = _record(
            title="Retry after api_key=sk-live-ABCDEF was rejected",
            rationale="The call failed with Authorization: Bearer sk-live-XYZ123.",
        )
        assert "sk-live-ABCDEF" not in record.title
        assert "api_key=***" in record.title
        assert "sk-live-XYZ123" not in record.rationale
        assert "***" in record.rationale

    def test_a_secret_in_a_string_metric_is_scrubbed_too(self) -> None:
        record = _record(metrics={"note": "refresh_token=abcdef123456"})
        assert record.metrics == {"note": "refresh_token=***"}

    def test_control_characters_are_stripped_not_refused(self) -> None:
        """They are not content. Left in, a rationale read back in a
        terminal could clear the screen or spoof a prompt."""
        record = _record(
            title="a\x00b\x1bc",
            rationale="line\r\nnext\x07",
            metrics={"note": "x\x1by"},
        )
        assert record.title == "abc"
        assert record.rationale == "line\nnext"
        assert record.metrics == {"note": "xy"}

    def test_a_newline_survives_a_multi_line_rationale(self) -> None:
        """TAB and LF are kept: a rationale is allowed to be a short
        paragraph, and dropping the newline would join two words."""
        assert _record(rationale="first line\nsecond line").rationale == (
            "first line\nsecond line"
        )

    def test_a_title_of_only_control_characters_is_refused(self) -> None:
        with pytest.raises(ValueError, match="title"):
            _record(title="\x00\x1b\x07")

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_metric_values_are_refused(self, bad: float) -> None:
        """``NaN`` and the infinities have no JSON spelling: ``json.dumps``
        writes them as bare ``NaN`` / ``Infinity``, which is not JSON and
        which a stricter reader refuses — corrupting the whole file for
        one figure."""
        with pytest.raises(ValueError, match="metrics"):
            _record(metrics={"cpa_7d": bad})

    def test_an_over_long_string_metric_is_refused(self) -> None:
        over = {"note": "x" * (DECISION_METRIC_VALUE_MAX_CHARS + 1)}
        with pytest.raises(ValueError, match="metrics"):
            _record(metrics=over)
        at_bound = {"note": "x" * DECISION_METRIC_VALUE_MAX_CHARS}
        assert _record(metrics=at_bound).metrics == at_bound

    def test_too_many_related_actions_are_refused(self) -> None:
        over = list(range(DECISION_RELATED_ACTIONS_MAX + 1))
        with pytest.raises(ValueError, match="related_actions"):
            _record(related_actions=over)
        at_bound = tuple(range(DECISION_RELATED_ACTIONS_MAX))
        assert _record(related_actions=at_bound).related_actions == at_bound


class TestNewDecisionId:
    def test_id_carries_the_timestamp_and_a_random_suffix(self) -> None:
        minted = new_decision_id(_RECORDED_AT)
        assert minted.startswith("dec-20260919T101233-")
        assert len(minted.rsplit("-", 1)[1]) == 8

    def test_two_ids_in_the_same_second_differ(self) -> None:
        assert new_decision_id(_RECORDED_AT) != new_decision_id(_RECORDED_AT)

    def test_id_without_a_timestamp_is_still_usable(self) -> None:
        minted = new_decision_id("")
        assert minted.startswith("dec-")
        assert len(minted) == len("dec-") + 8


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _seed_action_log(path: Path, count: int) -> None:
    for i in range(count):
        append_action_log(
            path, ActionLogEntry(timestamp="", action=f"a{i}", platform="google_ads")
        )


class TestAppendDecision:
    def test_appends_and_returns_the_index(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        doc, index = append_decision(path, _record())
        assert index == 0
        assert len(doc.decisions) == 1
        doc, index = append_decision(path, _record(decision_id="dec-2"))
        assert index == 1
        assert [d.decision_id for d in doc.decisions] == [
            "dec-20260919T101233-1f4c9a02",
            "dec-2",
        ]

    def test_stamps_the_writing_session_and_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.core import actor

        monkeypatch.setattr(actor, "session_id", lambda: "sess-1")
        monkeypatch.setattr(actor, "client_info", lambda: "claude-code/1.2")
        doc, _ = append_decision(tmp_path / "STATE.json", _record())
        assert doc.decisions[0].session_id == "sess-1"
        assert doc.decisions[0].client == "claude-code/1.2"

    def test_an_explicit_identity_is_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.core import actor

        monkeypatch.setattr(actor, "session_id", lambda: "sess-1")
        doc, _ = append_decision(
            tmp_path / "STATE.json", _record(session_id="replayed", client="cli/1")
        )
        assert doc.decisions[0].session_id == "replayed"
        assert doc.decisions[0].client == "cli/1"

    def test_related_actions_must_point_at_existing_entries(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        _seed_action_log(path, 2)
        doc, _ = append_decision(path, _record(related_actions=[0, 1]))
        assert doc.decisions[0].related_actions == (0, 1)
        with pytest.raises(ValueError, match="related_actions"):
            append_decision(
                path, _record(decision_id="dec-second", related_actions=[2])
            )

    def test_a_refused_append_leaves_the_section_untouched(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        append_decision(path, _record())
        with pytest.raises(ValueError):
            append_decision(path, _record(decision_id="dec-2", related_actions=[0]))
        assert len(read_state_file(path).decisions) == 1

    def test_supersedes_must_name_an_existing_decision(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        first, _ = append_decision(path, _record())
        with pytest.raises(ValueError, match="supersedes"):
            append_decision(path, _record(decision_id="dec-2", supersedes="dec-nope"))
        doc, index = append_decision(
            path,
            _record(
                decision_id="dec-2",
                status="adopted",
                supersedes=first.decisions[0].decision_id,
            ),
        )
        assert index == 1
        assert doc.decisions[1].supersedes == first.decisions[0].decision_id
        # Append-only: the superseded record is still there, unchanged.
        assert doc.decisions[0].status == "proposed"

    def test_batch_id_must_name_a_declared_batch(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        with pytest.raises(BatchError, match="batch_id"):
            append_decision(path, _record(batch_id="batch-nope"))
        record = begin_batch(path, label="exclude placements")
        doc, _ = append_decision(path, _record(batch_id=record.batch_id))
        assert doc.decisions[0].batch_id == record.batch_id

    def test_a_closed_batch_may_still_be_named(self, tmp_path: Path) -> None:
        """Unlike an action_log append: a decision is routinely recorded
        AFTER the change set it judges was closed."""
        path = tmp_path / "STATE.json"
        opened = begin_batch(path, label="exclude placements")
        end_batch(path)
        doc, _ = append_decision(path, _record(batch_id=opened.batch_id))
        assert doc.decisions[0].batch_id == opened.batch_id

    def test_a_duplicate_decision_id_is_refused(self, tmp_path: Path) -> None:
        """Ids are what ``supersedes`` joins on. A second record under an id
        already on file would silently chain two unrelated decisions, and
        ``decision_by_id`` would answer with whichever came first."""
        path = tmp_path / "STATE.json"
        append_decision(path, _record())
        with pytest.raises(ValueError, match="decision_id"):
            append_decision(path, _record(title="A different decision"))
        assert len(read_state_file(path).decisions) == 1

    def test_the_scrubbed_text_is_what_reaches_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        append_decision(
            path, _record(rationale="retrying after api_key=sk-live-ABCDEF failed")
        )
        raw = path.read_text(encoding="utf-8")
        assert "sk-live-ABCDEF" not in raw
        assert "api_key=***" in raw

    def test_other_sections_are_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        write_state_file(
            path,
            StateDocument(version="2", last_synced_at="2026-09-18T09:00:00+09:00"),
        )
        _seed_action_log(path, 1)
        doc, _ = append_decision(path, _record())
        assert doc.last_synced_at == "2026-09-18T09:00:00+09:00"
        assert len(doc.action_log) == 1


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestCrossModuleImports:
    """The two names this feature reaches for across a module boundary.

    Both were private-by-underscore when it was written, and an underscore
    is a statement that a name may change without notice — so each is
    published rather than reached for behind the author's back.
    """

    def test_the_state_lock_helper_is_published(self) -> None:
        from mureo.context import state

        assert "_locked_state_mutation" in state.__all__

    def test_the_id_entropy_constant_is_published(self) -> None:
        from mureo.context.batch import ID_ENTROPY_BYTES, new_batch_id
        from mureo.context.decisions import new_decision_id

        assert ID_ENTROPY_BYTES > 0
        # Both id families are the same width, so neither reads as the
        # weaker one to an operator comparing them side by side.
        assert len(new_decision_id("").removeprefix("dec-")) == len(
            new_batch_id("").removeprefix("batch-")
        )


class TestQueries:
    def test_decision_by_id(self) -> None:
        doc = StateDocument(
            decisions=(_record(), _record(decision_id="dec-2", status="adopted"))
        )
        assert decision_by_id(doc, "dec-2").status == "adopted"  # type: ignore[union-attr]
        assert decision_by_id(doc, "dec-missing") is None

    def test_latest_decisions_returns_the_newest_last_written_first(self) -> None:
        doc = StateDocument(
            decisions=tuple(
                _record(decision_id=f"dec-{i}", title=f"t{i}") for i in range(5)
            )
        )
        assert [d.decision_id for d in latest_decisions(doc, limit=2)] == [
            "dec-4",
            "dec-3",
        ]
        assert len(latest_decisions(doc, limit=99)) == 5
        assert latest_decisions(doc, limit=0) == ()

    def test_latest_decisions_orders_by_write_position_not_timestamp(self) -> None:
        """The section is append-only, so position IS write order — and it
        stays right when a replayed or hand-edited ``recorded_at`` does not."""
        doc = StateDocument(
            decisions=(
                _record(decision_id="dec-old", recorded_at="2099-01-01T00:00:00+09:00"),
                _record(decision_id="dec-new", recorded_at="2020-01-01T00:00:00+09:00"),
            )
        )
        assert [d.decision_id for d in latest_decisions(doc, limit=2)] == [
            "dec-new",
            "dec-old",
        ]


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class TestDecisionCodec:
    def test_round_trip_preserves_every_field(self, tmp_path: Path) -> None:
        record = _record(
            metrics={"cpa_7d": 5200, "conversions_7d": 45},
            platform="google_ads",
            campaign_id="C-1",
            entity_type="ad_group",
            entity_id="4711",
            related_actions=(0, 1),
            supersedes="dec-0",
            batch_id="batch-1",
            session_id="sess-1",
            client="claude-code/1.2",
        )
        doc = StateDocument(decisions=(record,))
        assert parse_state(render_state(doc)).decisions == (record,)

    def test_absent_section_stays_absent_on_rewrite(self, tmp_path: Path) -> None:
        """An old STATE.json gains no ``decisions`` key on the next write."""
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps({"version": "2", "campaigns": [], "action_log": []}),
            encoding="utf-8",
        )
        doc = read_state_file(path)
        assert doc.decisions == ()
        write_state_file(path, doc)
        assert "decisions" not in json.loads(path.read_text(encoding="utf-8"))

    def test_optional_fields_are_omitted_when_unset(self) -> None:
        payload = decision_to_dict(_record())
        assert set(payload) == {
            "decision_id",
            "recorded_at",
            "status",
            "title",
            "rationale",
        }

    def test_strict_parse_raises_on_a_malformed_record(self) -> None:
        with pytest.raises(ValueError):
            parse_decisions([{"decision_id": "dec-1"}], strict=True)

    def test_tolerant_parse_skips_a_malformed_record(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        raw = [decision_to_dict(_record()), {"decision_id": "dec-broken"}]
        with caplog.at_level(logging.DEBUG, logger="mureo.context._decision_codec"):
            parsed = parse_decisions(raw, strict=False)
        assert [d.decision_id for d in parsed] == ["dec-20260919T101233-1f4c9a02"]
        assert "dec-broken" in caplog.text

    def test_the_skip_log_names_the_id_and_not_the_record(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The record is free text an agent wrote. Logging it whole would
        copy a rationale — and anything the scrubber has not seen yet,
        since a hand-edited file never crossed the write boundary — into
        a second file under different rules."""
        raw = [{"decision_id": "dec-broken", "rationale": "api_key=sk-live-SECRET"}]
        with caplog.at_level(logging.DEBUG, logger="mureo.context._decision_codec"):
            assert parse_decisions(raw, strict=False) == ()
        assert "dec-broken" in caplog.text
        assert "sk-live-SECRET" not in caplog.text

    def test_a_record_with_no_usable_id_still_logs_something(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="mureo.context._decision_codec"):
            assert parse_decisions(["not an object"], strict=False) == ()
        assert "skipping" in caplog.text
        assert "not an object" not in caplog.text

    @pytest.mark.parametrize("raw", [None, "nope", 7])
    def test_a_non_list_section_reads_as_empty_when_tolerant(self, raw: object) -> None:
        assert parse_decisions(raw, strict=False) == ()

    def test_a_non_list_section_raises_when_strict(self) -> None:
        with pytest.raises(ValueError, match="decisions"):
            parse_decisions("nope", strict=True)

    def test_missing_section_is_empty_in_strict_mode_too(self) -> None:
        assert parse_decisions(None, strict=True) == ()

    def test_state_get_shape_carries_the_section(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        append_decision(path, _record())
        rendered = json.loads(path.read_text(encoding="utf-8"))
        assert rendered["decisions"][0]["title"] == (
            "Pause Search_Lead-Gen generic ad group"
        )
