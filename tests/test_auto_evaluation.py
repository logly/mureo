"""Automatic observation closure (#758 phase 5).

A past-due ``action_log`` entry whose outcome is fully determined by data
already in STATE.json — a campaign-level action with a numeric baseline, on
a platform whose campaign metrics were collected after the window closed —
is closed by mureo itself. These tests pin the decision (one case per skip
reason, in rule order), the single locked write, and the two properties the
feature lives or dies by: it never writes when it has nothing to close, and
it never writes when the host's policy gates would refuse the append.
"""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.outcome_eval import MetricOutcome, OutcomeReport, Verdict
from mureo.context import auto_evaluation
from mureo.context.actor_stamp import stamp_actor
from mureo.context.auto_evaluation import (
    AUTO_EVALUATION_ACTION,
    AutoSkip,
    close_due_observations,
    due_candidates,
    plan_closure,
)
from mureo.context.models import ActionLogEntry
from mureo.context.state import append_action_log, read_state_file
from mureo.core.actor import ACTION_REASON_MAX_CHARS

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)

#: Metrics as a collector stores them: the figures plus the two bookkeeping
#: keys that are not metrics at all.
CURRENT_METRICS: dict[str, Any] = {
    "cpa": 5000,
    "conversions": 10,
    "period": "LAST_30_DAYS",
    "fetched_at": "2026-09-18T09:00:00+09:00",
}

BASELINE: dict[str, Any] = {"cpa": 10000, "conversions": 5}


def _log_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "timestamp": "2026-09-01T10:00:00+09:00",
        "action": "budget_increase",
        "platform": "google_ads",
        "campaign_id": "camp_1",
        "metrics_at_action": dict(BASELINE),
        "observation_due": "2026-09-10",
    }
    entry.update(overrides)
    return entry


def _write_state(
    path: Path,
    *,
    action_log: list[dict[str, Any]],
    metrics: dict[str, Any] | None = None,
    platform: str = "google_ads",
    campaign_id: str = "camp_1",
) -> None:
    campaign: dict[str, Any] = {
        "campaign_id": campaign_id,
        "campaign_name": "Brand",
        "status": "ENABLED",
    }
    if metrics is not None:
        campaign["metrics"] = metrics
    document = {
        "version": "2",
        "last_synced_at": "2026-09-18T09:00:00+09:00",
        "platforms": {
            platform: {"account_id": "acct-1", "campaigns": [campaign]},
        },
        "action_log": action_log,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _state_path(tmp_path: Path, **kwargs: Any) -> Path:
    path = tmp_path / "STATE.json"
    _write_state(path, **kwargs)
    return path


def _allow() -> str | None:
    return None


def _competing_close(path: Path) -> None:
    """Close observation 0 the way another session would — same lock."""
    append_action_log(
        path,
        ActionLogEntry(
            timestamp="2026-09-19T09:00:00+09:00",
            action="outcome_evaluated",
            platform="google_ads",
            campaign_id="camp_1",
            evaluation_of=0,
        ),
    )


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


class TestDueCandidates:
    def test_a_past_due_open_entry_is_a_candidate(self, tmp_path: Path) -> None:
        path = _state_path(tmp_path, action_log=[_log_entry()])
        assert due_candidates(read_state_file(path), TODAY) == [0]

    def test_a_future_due_entry_is_not(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path, action_log=[_log_entry(observation_due="2026-10-30")]
        )
        assert due_candidates(read_state_file(path), TODAY) == []

    def test_an_already_closed_entry_is_not(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[
                _log_entry(),
                _log_entry(
                    action="outcome_evaluated",
                    evaluation_of=0,
                    observation_due=None,
                ),
            ],
        )
        assert due_candidates(read_state_file(path), TODAY) == []

    def test_an_unparseable_due_date_is_not(self, tmp_path: Path) -> None:
        path = _state_path(tmp_path, action_log=[_log_entry(observation_due="soon")])
        assert due_candidates(read_state_file(path), TODAY) == []

    def test_candidates_are_in_document_order(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[
                _log_entry(),
                _log_entry(observation_due="2026-10-30"),
                _log_entry(observation_due="2026-09-05"),
            ],
        )
        assert due_candidates(read_state_file(path), TODAY) == [0, 2]


# ---------------------------------------------------------------------------
# The skip vocabulary, one case per reason, in rule order
# ---------------------------------------------------------------------------


class TestSkipReasons:
    def _skip(self, path: Path, index: int = 0) -> AutoSkip:
        plan = plan_closure(read_state_file(path), index, TODAY)
        assert isinstance(plan, AutoSkip)
        return plan

    def test_external_origin_wins_over_a_missing_baseline(self, tmp_path: Path) -> None:
        """First failing rule wins, so the reason is deterministic."""
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(origin="external", metrics_at_action=None)],
            metrics=CURRENT_METRICS,
        )
        assert self._skip(path).reason == "external_origin"

    def test_no_baseline(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(metrics_at_action={})],
            metrics=CURRENT_METRICS,
        )
        assert self._skip(path).reason == "no_baseline"

    def test_no_campaign_id(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(campaign_id=None)],
            metrics=CURRENT_METRICS,
        )
        assert self._skip(path).reason == "no_campaign_id"

    def test_platform_not_in_state(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(platform="meta_ads")],
            metrics=CURRENT_METRICS,
        )
        assert self._skip(path).reason == "platform_not_in_state"

    def test_campaign_not_in_state(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(campaign_id="camp_other")],
            metrics=CURRENT_METRICS,
        )
        assert self._skip(path).reason == "campaign_not_in_state"

    def test_no_current_metrics(self, tmp_path: Path) -> None:
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=None)
        assert self._skip(path).reason == "no_current_metrics"

    def test_current_metrics_undated(self, tmp_path: Path) -> None:
        """No ``fetched_at`` is not a licence to fall back on another date."""
        path = _state_path(
            tmp_path,
            action_log=[_log_entry()],
            metrics={"cpa": 5000, "conversions": 10},
        )
        assert self._skip(path).reason == "current_metrics_undated"

    def test_current_metrics_undated_when_fetched_at_is_unparseable(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry()],
            metrics={**CURRENT_METRICS, "fetched_at": "last Tuesday"},
        )
        assert self._skip(path).reason == "current_metrics_undated"

    def test_current_metrics_predate_window(self, tmp_path: Path) -> None:
        """Metrics collected before the window closed score the wrong period."""
        path = _state_path(
            tmp_path,
            action_log=[_log_entry()],
            metrics={**CURRENT_METRICS, "fetched_at": "2026-09-08"},
        )
        assert self._skip(path).reason == "current_metrics_predate_window"

    def test_metrics_fetched_on_the_due_date_itself_are_fresh_enough(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry()],
            metrics={**CURRENT_METRICS, "fetched_at": "2026-09-10"},
        )
        assert not isinstance(plan_closure(read_state_file(path), 0, TODAY), AutoSkip)

    def test_period_mismatch(self, tmp_path: Path) -> None:
        """Two windows are not a before and an after of the same thing."""
        path = _state_path(
            tmp_path,
            action_log=[
                _log_entry(metrics_at_action={**BASELINE, "period": "LAST_7_DAYS"})
            ],
            metrics=CURRENT_METRICS,
        )
        assert self._skip(path).reason == "period_mismatch"

    def test_the_same_period_spelled_differently_is_not_a_mismatch(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(
            tmp_path,
            action_log=[
                _log_entry(metrics_at_action={**BASELINE, "period": " last_30_days "})
            ],
            metrics=CURRENT_METRICS,
        )
        assert not isinstance(plan_closure(read_state_file(path), 0, TODAY), AutoSkip)

    def test_a_baseline_without_a_period_still_closes(self, tmp_path: Path) -> None:
        """Unstated is not mismatched — the manual path has the same limit."""
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)
        assert not isinstance(plan_closure(read_state_file(path), 0, TODAY), AutoSkip)

    def test_a_snapshot_without_a_period_still_closes(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[
                _log_entry(metrics_at_action={**BASELINE, "period": "LAST_7_DAYS"})
            ],
            metrics={"cpa": 5000, "conversions": 10, "fetched_at": "2026-09-18"},
        )
        assert not isinstance(plan_closure(read_state_file(path), 0, TODAY), AutoSkip)

    def test_no_comparable_metric(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(metrics_at_action={"roas": 3.2})],
            metrics=CURRENT_METRICS,
        )
        assert self._skip(path).reason == "no_comparable_metric"

    def test_unparseable_due_date(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(observation_due="soon")],
            metrics=CURRENT_METRICS,
        )
        assert self._skip(path).reason == "unparseable_due_date"


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


class TestCloseDueObservations:
    def test_closes_a_past_due_entry(self, tmp_path: Path) -> None:
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)
        result = close_due_observations(path, today=TODAY, may_write=_allow)

        assert result.skipped == ()
        assert len(result.closed) == 1
        closure = result.closed[0]
        assert (closure.index, closure.evaluation_index) == (0, 1)
        assert closure.overall == "improved"

        log = read_state_file(path).action_log
        assert len(log) == 2
        appended = log[1]
        assert appended.action == AUTO_EVALUATION_ACTION
        assert appended.evaluation_of == 0
        assert appended.platform == "google_ads"
        assert appended.campaign_id == "camp_1"
        assert appended.summary == closure.summary
        assert appended.reason is not None
        assert appended.reason.startswith("Automatic observation closure")
        assert appended.session_id is not None
        assert appended.batch_id is None
        assert appended.display_title is None

    def test_the_stored_metrics_are_the_whole_snapshot(self, tmp_path: Path) -> None:
        """The record keeps ``period`` / ``fetched_at``: without them nobody
        reading it back can tell which days were scored. Only the call to
        ``evaluate_outcome`` strips them."""
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)
        close_due_observations(path, today=TODAY, may_write=_allow)
        appended = read_state_file(path).action_log[1]
        assert appended.metrics_at_action == CURRENT_METRICS

    def test_the_verdict_matches_evaluate_outcome(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(metrics_at_action={"cpa": 1000})],
            metrics=CURRENT_METRICS,
        )
        result = close_due_observations(path, today=TODAY, may_write=_allow)
        assert result.closed[0].overall == "regressed"
        assert "cpa" in result.closed[0].summary

    def test_the_closed_entry_leaves_the_pending_set(self, tmp_path: Path) -> None:
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)
        close_due_observations(path, today=TODAY, may_write=_allow)
        assert due_candidates(read_state_file(path), TODAY) == []

    def test_a_second_run_closes_nothing_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)
        close_due_observations(path, today=TODAY, may_write=_allow)
        before, mtime = path.read_bytes(), path.stat().st_mtime_ns

        result = close_due_observations(path, today=TODAY, may_write=_allow)

        assert (result.closed, result.skipped) == ((), ())
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime

    def test_two_due_entries_are_closed_in_one_write(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(), _log_entry(observation_due="2026-09-05")],
            metrics=CURRENT_METRICS,
        )
        result = close_due_observations(path, today=TODAY, may_write=_allow)

        assert [(c.index, c.evaluation_index) for c in result.closed] == [
            (0, 2),
            (1, 3),
        ]
        doc = read_state_file(path)
        assert [e.evaluation_of for e in doc.action_log] == [None, None, 0, 1]
        # Appending is not a sync: the freshness stamp is untouched.
        assert doc.last_synced_at == "2026-09-18T09:00:00+09:00"

    def test_nothing_due_leaves_the_file_byte_identical(self, tmp_path: Path) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(observation_due="2026-10-30")],
            metrics=CURRENT_METRICS,
        )
        before, mtime = path.read_bytes(), path.stat().st_mtime_ns

        result = close_due_observations(path, today=TODAY, may_write=_allow)

        assert (result.closed, result.skipped) == ((), ())
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime

    def test_an_absent_state_file_is_not_created(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        result = close_due_observations(path, today=TODAY, may_write=_allow)
        assert (result.closed, result.skipped) == ((), ())
        assert not path.exists()

    def test_a_skippable_candidate_is_reported_without_a_write(
        self, tmp_path: Path
    ) -> None:
        """A candidate mureo can never close must not churn STATE.json."""
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=None)
        before, mtime = path.read_bytes(), path.stat().st_mtime_ns

        result = close_due_observations(path, today=TODAY, may_write=_allow)

        assert result.closed == ()
        assert [(s.index, s.reason) for s in result.skipped] == [
            (0, "no_current_metrics")
        ]
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime

    def test_a_closable_and_a_skippable_candidate_in_one_run(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(), _log_entry(campaign_id=None)],
            metrics=CURRENT_METRICS,
        )
        result = close_due_observations(path, today=TODAY, may_write=_allow)
        assert [c.index for c in result.closed] == [0]
        assert [(s.index, s.reason) for s in result.skipped] == [(1, "no_campaign_id")]


# ---------------------------------------------------------------------------
# The write gate
# ---------------------------------------------------------------------------


class TestWriteDenied:
    def test_a_denial_writes_nothing_and_reports_every_candidate(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)
        before, mtime = path.read_bytes(), path.stat().st_mtime_ns

        result = close_due_observations(
            path, today=TODAY, may_write=lambda: "read-only mode"
        )

        assert result.closed == ()
        assert [(s.index, s.reason) for s in result.skipped] == [
            (0, "write_denied: read-only mode")
        ]
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime

    def test_the_gate_is_not_consulted_when_nothing_is_due(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(observation_due="2026-10-30")],
            metrics=CURRENT_METRICS,
        )
        calls: list[int] = []

        def _deny() -> str | None:
            calls.append(1)
            return "read-only mode"

        close_due_observations(path, today=TODAY, may_write=_deny)
        assert calls == []

    def test_the_gate_is_consulted_once_for_two_candidates(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(
            tmp_path,
            action_log=[_log_entry(), _log_entry(observation_due="2026-09-05")],
            metrics=CURRENT_METRICS,
        )
        calls: list[int] = []

        def _allow_counting() -> str | None:
            calls.append(1)
            return None

        close_due_observations(path, today=TODAY, may_write=_allow_counting)
        assert calls == [1]


# ---------------------------------------------------------------------------
# The machine-built rationale
# ---------------------------------------------------------------------------


class TestReasonBound:
    def test_a_long_summary_never_exceeds_the_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        long_summary = "x" * 5000
        report = OutcomeReport(
            metrics=(
                MetricOutcome(
                    metric="cpa",
                    before=10000.0,
                    after=5000.0,
                    delta_pct=-50.0,
                    verdict=Verdict.IMPROVED,
                    note="lower_is_better; -50%",
                ),
            ),
            overall=Verdict.IMPROVED,
            summary=long_summary,
        )
        monkeypatch.setattr(
            auto_evaluation, "evaluate_outcome", lambda **kwargs: report
        )
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)

        close_due_observations(path, today=TODAY, may_write=_allow)

        appended = read_state_file(path).action_log[1]
        assert appended.reason is not None
        assert len(appended.reason) == ACTION_REASON_MAX_CHARS
        assert appended.reason.startswith("Automatic observation closure (improved)")

    def test_an_evaluation_failure_propagates_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**kwargs: Any) -> OutcomeReport:
            raise RuntimeError("scoring is broken")

        monkeypatch.setattr(auto_evaluation, "evaluate_outcome", _boom)
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)
        before = path.read_bytes()

        with pytest.raises(RuntimeError, match="scoring is broken"):
            close_due_observations(path, today=TODAY, may_write=_allow)

        assert path.read_bytes() == before

    def test_the_reason_crosses_the_scrub_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Machine-built or not, a rationale is scrubbed like every other."""
        report = OutcomeReport(
            metrics=(
                MetricOutcome(
                    metric="cpa",
                    before=10000.0,
                    after=5000.0,
                    delta_pct=-50.0,
                    verdict=Verdict.IMPROVED,
                    note="lower_is_better; -50%",
                ),
            ),
            overall=Verdict.IMPROVED,
            summary="Improved on cpa (api_key=SECRETVALUE).",
        )
        monkeypatch.setattr(
            auto_evaluation, "evaluate_outcome", lambda **kwargs: report
        )
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)

        close_due_observations(path, today=TODAY, may_write=_allow)

        appended = read_state_file(path).action_log[1]
        assert appended.reason is not None
        assert "SECRETVALUE" not in appended.reason

    def test_a_secret_shaped_metric_name_never_reaches_the_reason(
        self, tmp_path: Path
    ) -> None:
        path = _state_path(
            tmp_path,
            action_log=[
                _log_entry(
                    metrics_at_action={**BASELINE, "api_key=SECRETVALUE": 1},
                )
            ],
            metrics={**CURRENT_METRICS, "api_key=SECRETVALUE": 2},
        )

        close_due_observations(path, today=TODAY, may_write=_allow)

        appended = read_state_file(path).action_log[1]
        assert appended.reason is not None
        assert "SECRETVALUE" not in appended.reason


# ---------------------------------------------------------------------------
# Two readers at once (#758 phase 5)
# ---------------------------------------------------------------------------


class TestConcurrentClosure:
    def test_a_candidate_closed_under_the_lock_is_not_rewritten(
        self, tmp_path: Path
    ) -> None:
        """The TOCTOU window: the pre-lock read says "due", the locked read
        says "already closed". The second reader must leave the file exactly
        as the first one wrote it — not rewrite an identical document.

        The competing close runs from ANOTHER thread, inside ``may_write``:
        that is precisely the moment after the un-locked read and before the
        lock, and doing it there makes the race deterministic instead of
        timing-dependent. The competing writer takes the real state lock, so
        the cross-thread serialisation is exercised too.
        """
        path = _state_path(tmp_path, action_log=[_log_entry()], metrics=CURRENT_METRICS)
        state: dict[str, Any] = {}

        def _close_from_another_thread() -> str | None:
            worker = threading.Thread(target=_competing_close, args=(path,))
            worker.start()
            worker.join()
            state["bytes"] = path.read_bytes()
            state["mtime"] = path.stat().st_mtime_ns
            return None

        result = close_due_observations(
            path, today=TODAY, may_write=_close_from_another_thread
        )

        assert result.closed == ()
        assert result.skipped == ()
        assert path.read_bytes() == state["bytes"]
        assert path.stat().st_mtime_ns == state["mtime"]
        assert len(read_state_file(path).action_log) == 2


# ---------------------------------------------------------------------------
# The extracted identity stamp (#758 phase 5, A)
# ---------------------------------------------------------------------------


class TestStampActor:
    def test_it_stamps_the_writing_session_when_unset(self) -> None:
        from mureo.core.actor import session_id

        stamped = stamp_actor(
            ActionLogEntry(timestamp="t", action="a", platform="google_ads"), "why"
        )
        assert stamped.session_id == session_id()
        assert stamped.reason == "why"

    def test_an_explicit_identity_is_kept(self) -> None:
        entry = ActionLogEntry(
            timestamp="t",
            action="a",
            platform="google_ads",
            session_id="imported-session",
            client="importer/1.0",
        )
        stamped = stamp_actor(entry, None)
        assert stamped.session_id == "imported-session"
        assert stamped.client == "importer/1.0"
        assert stamped.reason is None
