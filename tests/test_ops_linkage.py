"""Automatic decision records from mutating calls (#848).

A change recorded with a reason gets a decision record of its own, created
in the same locked write as the ``action_log`` entry, and the entry carries
the decision's id. Nobody has to obtain an id first.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mureo.context.decision_chain import (
    chain_expected,
    chain_root,
    latest_in_chain,
)
from mureo.context.decisions import DECISION_TITLE_MAX_CHARS, DecisionRecord
from mureo.context.expected import ExpectedEffect, parse_expected
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.ops_intent import bind_ops_intent, current_ops_intent
from mureo.context.ops_linkage import (
    LinkRequest,
    check_linkable,
    derive_title,
    project_metrics,
    record_call_decision,
)
from mureo.context.state import (
    append_action_log,
    begin_batch,
    read_state_file,
    write_state_file,
)
from mureo.core.actor import bind_call_reason

pytestmark = pytest.mark.unit

CPA_DOWN = [{"metric": "cpa", "direction": "down"}]


def _entry(**overrides: Any) -> ActionLogEntry:
    values: dict[str, Any] = {
        "timestamp": "2026-10-14T10:00:00+09:00",
        "action": "google_ads_campaign_update_status",
        "platform": "google_ads",
        "campaign_id": "123",
        "metrics_at_action": {"cpa": 5200, "conversions": 45},
        "reversible_params": {
            "operation": "google_ads_campaign_update_status",
            "params": {"campaign_id": "123", "status": "PAUSED"},
        },
    }
    values.update(overrides)
    return ActionLogEntry(**values)


def _state(tmp_path: Path, decisions: tuple[DecisionRecord, ...] = ()) -> Path:
    path = tmp_path / "STATE.json"
    write_state_file(path, StateDocument(version="2", decisions=decisions))
    return path


def _proposal(status: str = "proposed", **overrides: Any) -> DecisionRecord:
    values: dict[str, Any] = {
        "decision_id": "dec-p",
        "recorded_at": "2026-10-13T10:00:00+09:00",
        "status": status,
        "title": "Resume campaign 123",
        "rationale": "Paused by mistake.",
        "expected": CPA_DOWN,
    }
    values.update(overrides)
    return DecisionRecord(**values)


class TestDecisionChain:
    def test_root_latest_and_expected(self) -> None:
        proposal = _proposal()
        adoption = _proposal(
            "adopted", decision_id="dec-a", supersedes="dec-p", expected=[]
        )
        doc = StateDocument(version="2", decisions=(proposal, adoption))
        assert chain_root(doc, "dec-a") == "dec-p"
        assert latest_in_chain(doc, "dec-p") == adoption
        assert chain_expected(doc, "dec-a") == (ExpectedEffect("cpa", "down"),)

    def test_a_cycle_does_not_loop(self) -> None:
        one = _proposal(decision_id="a", supersedes="b")
        two = _proposal(decision_id="b", supersedes="a")
        doc = StateDocument(version="2", decisions=(one, two))
        assert chain_root(doc, "a") in {"a", "b"}

    def test_an_unknown_id(self) -> None:
        doc = StateDocument(version="2")
        assert chain_root(doc, "nope") is None
        assert latest_in_chain(doc, "nope") is None
        assert chain_expected(doc, "nope") == ()


class TestOpsIntent:
    def test_unbound_is_none(self) -> None:
        assert current_ops_intent() is None

    def test_bound_and_reset(self) -> None:
        with bind_ops_intent(expected=parse_expected(CPA_DOWN)) as intent:
            assert current_ops_intent() is intent
        assert current_ops_intent() is None

    def test_arguments_are_copied(self) -> None:
        args = {"status": "ENABLED"}
        with bind_ops_intent(arguments=args) as intent:
            args["status"] = "PAUSED"
            assert intent.arguments == {"status": "ENABLED"}


class TestSingleCall:
    def test_a_reasoned_change_creates_an_adopted_decision(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)
        with (
            bind_call_reason("Recovered after the policy fix."),
            bind_ops_intent(
                expected=parse_expected(CPA_DOWN),
                arguments={"campaign_id": "123", "status": "ENABLED"},
            ),
        ):
            doc = append_action_log(path, _entry())
        assert len(doc.decisions) == 1
        record = doc.decisions[0]
        assert record.status == "adopted"
        assert record.rationale == "Recovered after the policy fix."
        assert record.expected == (ExpectedEffect("cpa", "down"),)
        assert record.metrics == {"cpa": 5200, "conversions": 45}
        assert record.platform == "google_ads"
        assert record.campaign_id == "123"
        assert "status PAUSED → ENABLED" in record.title
        assert doc.action_log[0].decision_id == record.decision_id

    def test_without_expected_the_decision_is_still_created(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)
        with bind_call_reason("Because."):
            doc = append_action_log(path, _entry())
        assert doc.decisions[0].expected == ()
        assert doc.action_log[0].decision_id == doc.decisions[0].decision_id

    def test_no_reason_no_decision(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        doc = append_action_log(path, _entry())
        assert doc.decisions == ()
        assert doc.action_log[0].decision_id is None

    def test_the_entry_s_own_reason_and_expected(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        doc = append_action_log(
            path, _entry(reason="Budget capped daily."), expected=CPA_DOWN
        )
        assert doc.decisions[0].rationale == "Budget capped daily."
        assert doc.decisions[0].expected == (ExpectedEffect("cpa", "down"),)

    def test_an_invalid_expected_kwarg_is_refused_before_writing(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)
        with pytest.raises(ValueError, match="metric"):
            append_action_log(
                path,
                _entry(reason="x"),
                expected=[{"metric": "cpa_7d", "direction": "down"}],
            )
        assert read_state_file(path).action_log == ()

    def test_two_entries_in_one_call_share_one_decision(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        with bind_call_reason("Pause both."), bind_ops_intent():
            append_action_log(path, _entry(campaign_id="1"))
            doc = append_action_log(path, _entry(campaign_id="2"))
        assert len(doc.decisions) == 1
        ids = {e.decision_id for e in doc.action_log}
        assert ids == {doc.decisions[0].decision_id}

    def test_separate_calls_get_separate_decisions(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        with bind_call_reason("One."), bind_ops_intent():
            append_action_log(path, _entry(campaign_id="1"))
        with bind_call_reason("Two."), bind_ops_intent():
            doc = append_action_log(path, _entry(campaign_id="2"))
        assert len(doc.decisions) == 2

    def test_an_external_change_gets_no_decision(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        with bind_call_reason("Import."):
            doc = append_action_log(path, _entry(origin="external"))
        assert doc.decisions == ()
        assert doc.action_log[0].decision_id is None

    def test_a_rollback_gets_no_decision(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        append_action_log(path, _entry())
        with bind_call_reason("Undo."):
            doc = append_action_log(path, _entry(rollback_of=0))
        assert doc.decisions == ()

    def test_an_evaluation_inherits_the_source_decision(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        with bind_call_reason("Change."):
            append_action_log(path, _entry())
        doc = append_action_log(
            path, _entry(action="evaluate", evaluation_of=0, reason="Looked.")
        )
        assert len(doc.decisions) == 1
        assert doc.action_log[1].decision_id == doc.decisions[0].decision_id


class TestBatch:
    def test_members_share_the_batch_decision(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        with (
            bind_call_reason("Weekly cleanup."),
            bind_ops_intent(expected=parse_expected(CPA_DOWN)),
        ):
            batch = begin_batch(path, label="Cleanup")
        doc = read_state_file(path)
        assert len(doc.decisions) == 1
        assert doc.decisions[0].batch_id == batch.batch_id
        assert doc.decisions[0].title == "Batch: Cleanup"
        with bind_call_reason("Pause A."), bind_ops_intent():
            append_action_log(path, _entry(campaign_id="1"))
        doc = append_action_log(path, _entry(campaign_id="2"))
        assert len(doc.decisions) == 1
        assert {e.decision_id for e in doc.action_log} == {doc.decisions[0].decision_id}

    def test_a_batch_without_a_reason_has_no_decision(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        begin_batch(path, label="Cleanup")
        with bind_call_reason("Pause A."):
            doc = append_action_log(path, _entry())
        # The member's own reason makes its own decision.
        assert len(doc.decisions) == 1
        assert doc.decisions[0].batch_id is None


class TestExplicitDecisionId:
    def test_a_proposal_becomes_adopted(self, tmp_path: Path) -> None:
        path = _state(tmp_path, (_proposal(),))
        with bind_call_reason("Approved."), bind_ops_intent(decision_id="dec-p"):
            doc = append_action_log(path, _entry())
        assert [r.status for r in doc.decisions] == ["proposed", "adopted"]
        adoption = doc.decisions[1]
        assert adoption.supersedes == "dec-p"
        assert adoption.expected == (ExpectedEffect("cpa", "down"),)
        assert doc.action_log[0].decision_id == "dec-p"

    def test_an_adopted_decision_is_joined_without_a_new_record(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path, (_proposal("adopted"),))
        doc = append_action_log(path, _entry(decision_id="dec-p"))
        assert len(doc.decisions) == 1
        assert doc.action_log[0].decision_id == "dec-p"

    def test_a_later_record_id_resolves_to_the_root(self, tmp_path: Path) -> None:
        adoption = _proposal("adopted", decision_id="dec-a", supersedes="dec-p")
        path = _state(tmp_path, (_proposal(), adoption))
        doc = append_action_log(path, _entry(decision_id="dec-a"))
        assert doc.action_log[0].decision_id == "dec-p"

    @pytest.mark.parametrize("status", ["rejected", "deferred"])
    def test_a_closed_decision_is_refused_on_the_entry(
        self, tmp_path: Path, status: str
    ) -> None:
        path = _state(tmp_path, (_proposal(status),))
        with pytest.raises(ValueError, match=status):
            append_action_log(path, _entry(decision_id="dec-p"))
        assert read_state_file(path).action_log == ()

    def test_an_unknown_id_is_refused_on_the_entry(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        with pytest.raises(ValueError, match="no recorded decision"):
            append_action_log(path, _entry(decision_id="dec-missing"))

    def test_a_stale_call_bound_id_never_loses_the_entry(self, tmp_path: Path) -> None:
        path = _state(tmp_path, (_proposal("rejected"),))
        with bind_ops_intent(decision_id="dec-p"):
            doc = append_action_log(path, _entry())
        assert len(doc.action_log) == 1
        assert doc.action_log[0].decision_id is None

    def test_check_linkable(self, tmp_path: Path) -> None:
        doc = StateDocument(version="2", decisions=(_proposal(),))
        assert check_linkable(doc, "dec-p") == "dec-p"
        with pytest.raises(ValueError, match="no recorded decision"):
            check_linkable(doc, "x")

    def test_a_call_without_an_entry_adopts_the_proposal(self, tmp_path: Path) -> None:
        path = _state(tmp_path, (_proposal(),))
        request = LinkRequest(
            reason=None, now="2026-10-14T01:00:00+00:00", explicit_id="dec-p"
        )
        assert record_call_decision(path, request, tool="x", platform=None) == "dec-p"
        written = path.stat().st_mtime_ns
        assert record_call_decision(path, request, tool="x", platform=None) == "dec-p"
        assert path.stat().st_mtime_ns == written
        doc = read_state_file(path)
        assert [r.status for r in doc.decisions] == ["proposed", "adopted"]

    def test_a_batch_begun_on_a_proposal_adopts_it(self, tmp_path: Path) -> None:
        path = _state(tmp_path, (_proposal(),))
        with bind_ops_intent(decision_id="dec-p"):
            batch = begin_batch(path, label="Resume")
        doc = append_action_log(path, _entry())
        assert doc.decisions[1].batch_id == batch.batch_id
        assert doc.action_log[0].decision_id == "dec-p"


class TestTitle:
    def test_before_and_after_with_separators(self) -> None:
        entry = _entry(
            action="google_ads_budget_update",
            reversible_params={
                "operation": "google_ads_budget_update",
                "params": {"budget_id": "b1", "amount": 10000},
            },
        )
        title = derive_title(entry, {"budget_id": "b1", "amount": 12000})
        assert "amount 10,000 → 12,000" in title
        assert "campaign 123" in title

    def test_falls_back_to_the_display_title(self) -> None:
        entry = _entry(reversible_params=None, display_title="Raise budget")
        assert derive_title(entry, {}).endswith("Raise budget")

    def test_is_bounded(self) -> None:
        entry = _entry(campaign_id="x" * 300, reversible_params=None)
        title = derive_title(entry, {})
        assert len(title) <= DECISION_TITLE_MAX_CHARS
        assert title.endswith("…")


class TestProjectMetrics:
    def test_keeps_flat_finite_scalars(self) -> None:
        raw: dict[str, Any] = {
            "cpa": 5200,
            "period": "LAST_7_DAYS",
            "nested": {"a": 1},
            "nan": float("nan"),
            "long": "x" * 500,
        }
        assert project_metrics(raw) == {"cpa": 5200, "period": "LAST_7_DAYS"}

    def test_bounded_in_keys(self) -> None:
        raw = {f"m{i}": i for i in range(40)}
        assert len(project_metrics(raw) or {}) == 20

    def test_none(self) -> None:
        assert project_metrics(None) is None
        assert project_metrics({}) is None


def test_old_documents_without_decision_ids_still_load(tmp_path: Path) -> None:
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
    assert read_state_file(path).action_log[0].decision_id is None
