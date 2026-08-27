"""/daily-check must default to a cheap INCREMENTAL run (context weight-reduction).

Field feedback: /daily-check consumed too much context (it pulled raw data
from every platform every run) and its report was too long (unchanged items
re-reported daily). The rewrite makes the DEFAULT run incremental — gather
compact analytics-first findings, load only the pending action_log, and report
only the deltas against the previous ``reports.daily`` summary — with ``deep``
as the full mode. This suite pins the load-bearing wording in BOTH the packaged
copy and the repo-root mirror, kept byte-identical.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = _ROOT / "mureo" / "_data" / "skills" / "daily-check" / "SKILL.md"
_MIRROR = _ROOT / "skills" / "daily-check" / "SKILL.md"


def _body() -> str:
    return _PACKAGED.read_text(encoding="utf-8")


def _lines_containing(needle: str) -> list[str]:
    lowered = needle.lower()
    return [ln for ln in _body().splitlines() if lowered in ln.lower()]


def test_copies_are_byte_identical() -> None:
    assert _PACKAGED.read_bytes() == _MIRROR.read_bytes()


def test_stays_readable_under_the_size_budget() -> None:
    """The rewrite must stay ~150 lines — the skill is a prompt, not a manual.

    Raised twice, each time by exactly what a persistence step costs and no
    more; the budget is a ceiling on prose, not a reason to leave a step out.

    - #690: two lines (a step and the blank line before it).
    - #706: fifteen — the display-contract step. Six of those are the section
      bullets and one is ``DISPLAY_CONTRACT_RULE`` pasted verbatim, which is
      the point of it: the bounds an agent is held to are stated where it
      composes, in the same words the refusal will use, rather than
      paraphrased into a shorter line that could drift from the code.
    - #706 review round: three more — the ``source`` bullet, and
      ``DISPLAY_OVERWRITE_RULE`` (also verbatim) with its blank line. That
      rule is the whole answer to "a later run replaced my proposals", and it
      cannot live anywhere but here: no schema can decide whether another
      skill's proposal is still live.
    """
    assert len(_body().splitlines()) <= 175


def test_two_modes_documented() -> None:
    """A Modes section names incremental (default) and deep, and the deep
    triggers (first-ever run, previous summary missing/older than 7 days)."""
    body = _body()
    assert "## Modes" in body
    assert "Incremental (default)" in body
    assert "Deep" in body
    assert "first-ever run" in body
    assert "older than 7 days" in body


def test_recommends_a_weekly_deep_run() -> None:
    body = _body().lower()
    assert "once a week" in body or "weekly" in body


def test_analytics_first_gathering_documented() -> None:
    """Incremental mode consults the analytics registry and consumes compact
    findings from mureo_analytics_run instead of raw rows."""
    body = _body()
    assert "Analytics-first" in body
    assert "mureo_analytics_modules_list" in body
    assert "mureo_analytics_run" in body
    assert "DETECT_ANOMALIES" in body
    assert "DIAGNOSE_PERFORMANCE" in body
    assert "compact findings" in body
    # Falls back to the raw pulls only for a platform with no analytics module.
    assert "no analytics module" in body
    # Looked up by the canonical platform key the skill already documents.
    assert "canonical platform key" in body


def test_state_load_scopes_action_log_to_pending() -> None:
    """Step 0/1 cite the new mureo_state_get action_log:"pending" parameter and
    that the scope marker means the shown log is a subset."""
    body = _body()
    assert 'action_log: "pending"' in body
    assert "action_log_scope" in body
    assert "subset" in body.lower()


def test_diff_first_report_contract() -> None:
    """Incremental mode's report is diff-first: verdict transitions, new/
    resolved findings, external changes, evidence-check verdicts that came due,
    and threshold/trend-flip goal moves only."""
    body = _body()
    assert "diff-first" in body.lower()
    assert "Verdict transitions" in body
    assert "resolved findings" in body.lower()
    assert "came due" in body.lower()
    # Everything unchanged collapses to a single line.
    assert "unchanged since yesterday" in body


def test_action_needed_is_always_reported_even_if_unchanged() -> None:
    """Safety rule: an Action-needed item is reported in full even when
    unchanged — an unresolved problem must never go quiet."""
    safety = _lines_containing("Safety rule")
    assert safety, "the diff-first report must carry an explicit safety rule"
    joined = "\n".join(safety)
    assert "Action needed" in joined
    assert "even when unchanged" in joined
    assert "never go quiet" in joined.lower()


def test_missing_previous_summary_falls_back_to_deep() -> None:
    """With no previous reports.daily summary the diff has no anchor, so the
    skill says so and falls back to the full report."""
    body = _body().lower()
    assert "missing" in body
    assert "fall back" in body


def test_output_discipline_forbids_raw_tables() -> None:
    """No raw tool tables in the report — verdict lines and deltas only."""
    body = _body()
    assert "Output discipline" in body
    assert "raw tool" in body


def test_incremental_still_persists_the_summary() -> None:
    """Persistence (steps 11-13) survives — it is what makes tomorrow's diff
    possible."""
    body = _body()
    assert "mureo_state_report_set" in body
    assert "mureo_state_platform_metrics_set" in body


def test_evidence_check_closes_the_observation_with_an_evaluation_record() -> None:
    """After evaluating a past-due entry the skill must APPEND an evaluation
    record (evaluation_of) so it leaves the pending set — mureo_outcome_evaluate
    is pure and closes nothing itself."""
    body = _body()
    assert "evaluation_of" in body
    # The append tool is named as the close mechanism.
    evidence = body[body.index("Evidence check") :]
    assert "mureo_state_action_log_append" in evidence
    lower = body.lower()
    assert "pending set" in lower
    # Uses the index carried on the pending entry.
    assert "`index`" in body


def test_evidence_check_skips_already_closed_entries() -> None:
    """Already-closed entries are done; in incremental mode the pending scope
    excludes them so they never even appear."""
    lower = _body().lower()
    assert "already closed" in lower


def test_step4_raw_pulls_are_tagged_as_deep_or_incremental_fallback() -> None:
    """The raw Google Ads / Meta Ads pull bullets must be tagged so a skimming
    agent cannot read them as unconditional and double-fetch."""
    lines = _body().splitlines()
    # The step-4 raw-diagnostics bullets (distinct from the step-3 sync bullets)
    # are the ones tagged with the built-in analytics module.
    google = next(
        ln for ln in lines if ln.strip().startswith("- **Google Ads** (built-in module")
    )
    meta = next(
        ln for ln in lines if ln.strip().startswith("- **Meta Ads** (built-in module")
    )
    for ln in (google, meta):
        assert "incremental fallback" in ln
