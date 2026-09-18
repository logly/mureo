"""The date-sensitive skills must establish "today" from ``server_now`` (#460).

``/daily-check`` (and ``sync-state`` / ``budget-pacing``) used to run with a
stale notion of today: the agent read STATE.json, saw old dates
(``reports.daily.period``, ``last_synced_at``, ``action_log`` timestamps) and
concluded "today's data is already fetched — re-displaying", using a days-old
date. The MCP side now injects ``server_now`` into the read responses; these
skills must be told to treat that value as the ONLY source of the current
date. Shelling out to ``date`` is not an option — ``/daily-check`` must run in
Bash-less headless hosts.

The same discipline then rolled out to every remaining skill that derives a
date from "today" — the reporting-window skills (``weekly-report``,
``monthly-report``), the deadline/window-gate skills (``goal-review``,
``experiment``, ``incident-postmortem``) and the skills that write an
``observation_due`` counted forward from today (``budget-rebalance``,
``creative-refresh``, ``search-term-cleanup``, ``audience-review``,
``ad-fatigue-check``, ``rescue``, ``tracking-health``). A stale date is not
cosmetic in any of them: it mislabels a report's period, flips an
on-track/off-track verdict, or schedules an outcome review for the wrong day.

Pinned here, in BOTH the packaged copy (``mureo/_data/skills``) and the
repo-root mirror (``skills/``), kept byte-identical.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = _ROOT / "mureo" / "_data" / "skills"
_MIRROR = _ROOT / "skills"

_SKILLS = (
    # #469 — the first three.
    "daily-check",
    "sync-state",
    "budget-pacing",
    # #460 follow-up — every remaining skill that derives a date from today.
    "weekly-report",
    "monthly-report",
    "goal-review",
    "experiment",
    "incident-postmortem",
    "budget-rebalance",
    "creative-refresh",
    "search-term-cleanup",
    "audience-review",
    "ad-fatigue-check",
    "rescue",
    "tracking-health",
)

#: Skills whose ``observation_due`` is counted forward from *today*. Writing
#: it off a stale date schedules the outcome review for the wrong day, which
#: silently defeats the whole evidence pipeline (``_mureo-learning``).
_OBSERVATION_DUE_SKILLS = (
    "budget-rebalance",
    "creative-refresh",
    "search-term-cleanup",
    "audience-review",
    "ad-fatigue-check",
    "rescue",
    "tracking-health",
)


def _packaged(name: str) -> Path:
    return _PACKAGED / name / "SKILL.md"


def _mirror(name: str) -> Path:
    return _MIRROR / name / "SKILL.md"


def _body(name: str) -> str:
    return _packaged(name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", _SKILLS)
def test_copies_are_byte_identical(name: str) -> None:
    assert (
        _packaged(name).read_bytes() == _mirror(name).read_bytes()
    ), f"{name}: packaged and mirror copies differ"


@pytest.mark.parametrize("name", _SKILLS)
def test_server_now_is_the_clock_source(name: str) -> None:
    """The skill must name the tool that carries the clock AND the field."""
    body = _body(name)
    assert "mureo_state_get" in body, f"{name}: must name the tool carrying the clock"
    assert "server_now" in body
    assert (
        "only source of the current date" in body
    ), f"{name}: must declare server_now the ONLY source of today"


@pytest.mark.parametrize("name", _SKILLS)
def test_state_json_dates_are_history_not_today(name: str) -> None:
    """The three date fields the failure mode came from must be named as
    history so a future edit cannot quietly reintroduce "read the date from
    STATE.json"."""
    body = _body(name)
    assert "history" in body
    for field in ("last_synced_at", "action_log"):
        assert field in body, f"{name}: must name {field} as history, not today"


@pytest.mark.parametrize("name", _SKILLS)
def test_server_now_is_never_written_into_state(name: str) -> None:
    """``server_now`` is a response envelope field; persisting it recreates
    the stale-date bug for the next reader."""
    # Case-insensitive: the sentence opens the rule in some skills and
    # closes it in others — the prohibition is what matters, not the casing.
    assert "never write `server_now`" in _body(name).lower()


def test_shared_tool_selection_documents_the_clock() -> None:
    """``_mureo-shared`` owns the host-portability table every skill reads.
    Its "Read STATE.json -> `Read` tool" row is misleading for date-sensitive
    work, so the clock rule has to live next to it — otherwise a skill not
    edited for #460 keeps inferring today from the file it just read."""
    packaged = _PACKAGED / "_mureo-shared" / "SKILL.md"
    mirror = _MIRROR / "_mureo-shared" / "SKILL.md"
    assert packaged.read_bytes() == mirror.read_bytes()
    body = packaged.read_text(encoding="utf-8")
    assert "| Establish the current date |" in body
    assert "server_now" in body
    assert "only** source of today" in body
    assert "on EVERY host, including Code" in body
    assert "never write `server_now` back into STATE.json" in body


# ---------------------------------------------------------------------------
# #767 — a verdict about "the last check" is only checkable if the report
# names the STATE.json it was computed from.
# ---------------------------------------------------------------------------


def test_daily_check_opens_its_report_with_the_workspace_it_read() -> None:
    """An operator whose scheduled card ran in one workspace and whose
    terminal opened another has to see the mismatch in the report header,
    not deduce it from a wrong "N days since the last check"."""
    header = [ln for ln in _body("daily-check").splitlines() if "Workspace:" in ln]
    assert header, "daily-check must keep its report header"
    # Pinned on the header LINE, not on the body: a `path` mention elsewhere in
    # the skill must not be able to satisfy this.
    line = header[0]
    assert "workspace_id:" in line, "the header must show the workspace_id too"
    assert "`path`" in line
    assert "`workspace_id`" in line
    assert "`notices`" in line


def test_daily_check_names_the_file_behind_a_stale_verdict() -> None:
    """The deep trigger and the missing-summary fallback are the two places
    that declare the stored report old or absent — both must name the file."""
    body = _body("daily-check")
    deep = [ln for ln in body.splitlines() if "older than 7 days" in ln]
    assert deep, "daily-check must keep its deep trigger"
    assert any("`path`" in ln for ln in deep)
    missing = [ln for ln in body.splitlines() if "summary is **missing**" in ln]
    assert missing, "daily-check must keep its missing-summary fallback"
    assert any("`path`" in ln for ln in missing)


def test_daily_check_stops_on_runtime_notices() -> None:
    """A notice means the runtime does not consider this session to be on the
    workspace it should be on. Making the mismatch visible is not enough: the
    run must END at step 0, or the session still spends a full deep check
    diagnosing the wrong STATE.json and answers "the last check was 11 days
    ago". Pinned in the step-0 paragraph — a stop rule further down the file
    is read after the steps it is supposed to prevent."""
    paragraphs = [
        block
        for block in _body("daily-check").split("\n\n")
        if "0. **Establish today**" in block
    ]
    assert paragraphs, "daily-check must keep its step-0 paragraph"
    step_zero = paragraphs[0]
    assert "server_now" in step_zero
    assert "`notices` is non-empty, stop" in step_zero
    assert "do not run steps 1–15" in step_zero


def test_daily_check_never_persists_the_envelope_fields() -> None:
    """``path`` / ``workspace_id`` / ``notices`` are response fields, exactly
    like ``server_now``; a persisted copy is tomorrow's lie."""
    assert (
        "never write `path`, `workspace_id` or `notices` into state.json"
        in _body("daily-check").lower()
    )


def test_shared_tool_selection_names_the_file_the_read_tools_read() -> None:
    """``_mureo-shared`` owns the rule every skill reads, so the "which file
    did this come from" answer belongs next to the clock rule."""
    body = (_PACKAGED / "_mureo-shared" / "SKILL.md").read_text(encoding="utf-8")
    assert "name the file they read (`path`)" in body
    assert "`workspace_id`" in body
    assert "`notices`" in body


def test_daily_check_forbids_the_already_fetched_short_circuit() -> None:
    """The exact observed failure: "today's report is already fetched —
    re-displaying" against a days-old date."""
    body = _body("daily-check")
    assert "already fetched" in body
    assert "re-display" in body
    assert "reports.daily.period" in body or "reports.*.period" in body


def test_budget_pacing_derives_elapsed_days_from_server_now() -> None:
    """Pacing math is date arithmetic — the month, elapsed days and remaining
    days must all come off ``server_now``, not off STATE.json history."""
    body = _body("budget-pacing")
    elapsed_lines = [ln for ln in body.splitlines() if "Elapsed days" in ln]
    assert elapsed_lines, "budget-pacing must keep its elapsed-days step"
    assert any(
        "server_now" in ln for ln in elapsed_lines
    ), "elapsed-days math must derive from server_now"
    remaining_lines = [ln for ln in body.splitlines() if "days remaining" in ln]
    assert any(
        "server_now" in ln for ln in remaining_lines
    ), "remaining-days math must derive from server_now"


@pytest.mark.parametrize("name", _SKILLS)
def test_the_clock_is_step_zero_not_a_footnote(name: str) -> None:
    """The rule only works if it runs *before* any date is used, so it is a
    literal step 0 in every skill — not an aside further down the file."""
    body = _body(name)
    assert "0. **Establish today**" in body, f"{name}: missing the step-0 heading"
    assert body.index("0. **Establish today**") < body.index(
        "\n1. "
    ), f"{name}: the clock step must precede step 1"


@pytest.mark.parametrize("name", _SKILLS)
def test_no_shelling_out_for_the_date(name: str) -> None:
    """These skills run in Bash-less headless hosts, so ``date`` is not a
    fallback — and offering one invites the host-dependent behaviour the
    injected clock exists to remove."""
    body = _body(name)
    assert (
        "shell out" in body or "shelling out" in body
    ), f"{name}: must forbid shelling out for the date"
    assert (
        "Bash-less headless hosts" in body
    ), f"{name}: must say why — Bash-less headless hosts"


@pytest.mark.parametrize("name", _OBSERVATION_DUE_SKILLS)
def test_observation_due_is_counted_from_server_now(name: str) -> None:
    """An ``observation_due`` written off a stale date schedules the outcome
    review for the wrong day — the evidence pipeline then evaluates a change
    before its window really closed."""
    body = _body(name)
    due_lines = [ln for ln in body.splitlines() if "observation_due" in ln]
    assert due_lines, f"{name} must keep its observation_due step"
    assert any(
        "server_now" in ln for ln in due_lines
    ), f"{name}: observation_due must be counted from server_now"


def test_weekly_report_derives_its_seven_day_window_from_server_now() -> None:
    """ "Last 7 days from today" was the literal wording — the window has to
    end on ``server_now``'s date or the whole report covers the wrong week."""
    body = _body("weekly-report")
    period_lines = [ln for ln in body.splitlines() if ln.startswith("3. **Period**")]
    assert period_lines, "weekly-report must keep its period step"
    assert "server_now" in period_lines[0]
    assert "from today" not in period_lines[0]


def test_monthly_report_names_the_reporting_month_from_server_now() -> None:
    """The default window is "the previous full calendar month" — which month
    that *is* comes off the clock, never off a stored ``reports.*.period``."""
    body = _body("monthly-report")
    window_lines = [
        ln for ln in body.splitlines() if ln.startswith("3. **Reporting window**")
    ]
    assert window_lines, "monthly-report must keep its reporting-window step"
    assert "server_now" in window_lines[0]
    # The MTD label and the MoM date range are the other two date computations.
    # Keyword co-occurrence (not verbatim prose) so innocuous copy-edits
    # do not break the pin: MTD cutoff and the MoM range must both be
    # anchored to server_now somewhere in the body.
    assert any("MTD" in ln and "server_now" in ln for ln in body.splitlines())
    assert any("two months" in ln and "server_now" in ln for ln in body.splitlines())


def test_goal_review_measures_days_remaining_from_server_now() -> None:
    """Deadline math decides on-track / at-risk / off-track, so a drifted
    date silently changes the verdict on every Goal."""
    body = _body("goal-review")
    remaining = [
        ln for ln in body.splitlines() if "days remaining until deadline" in ln
    ]
    assert remaining, "goal-review must keep its days-remaining calculation"
    assert any("server_now" in ln for ln in remaining)


def test_experiment_gates_evaluation_on_server_now() -> None:
    """The no-peeking rule is only enforceable if "has the window closed?" is
    asked against a real clock."""
    body = _body("experiment")
    closed = [ln for ln in body.splitlines() if "window has closed" in ln]
    assert closed, "experiment must keep its window-closed gate"
    assert any("server_now" in ln for ln in closed)
    assert any("future" in ln and "server_now" in ln for ln in body.splitlines())


def test_incident_postmortem_scores_only_closed_windows_against_server_now() -> None:
    """A postmortem that scores an action whose window has not really closed
    manufactures a verdict — the comparison must be against the clock."""
    body = _body("incident-postmortem")
    outcomes = [ln for ln in body.splitlines() if "has now closed" in ln]
    assert outcomes, "incident-postmortem must keep its outcome step"
    assert any("server_now" in ln for ln in outcomes)
