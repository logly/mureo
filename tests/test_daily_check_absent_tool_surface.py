"""/daily-check must not invent figures for a platform whose tools are absent.

Field report (#586): a hosted connector was disconnected host-side, so none
of its tools existed in the session at all — there was no call to make and no
error envelope to catch. The run enumerated the platform anyway (its key is
in STATE.json ``platforms``), emitted a one-line disclaimer, and then printed
a KPI table for it — target, actual, attainment %, pass/fail icons — shaped
exactly like the sections built from real data, with figures extrapolated
from whatever numbers the run still held. Budget and bid recommendations were
layered on top.

This is #580's hole with a different cause. #580 keys on a tool result
(``{"status": "auth_error", ...}``); an absent tool returns nothing to
inspect, so the check has to happen *before* the report, in what the skill is
told to confirm. This suite pins that branch — and pins that it reuses
#580's partial-report treatment rather than growing a second vocabulary for
"I could not see this platform".

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = _ROOT / "mureo" / "_data" / "skills" / "daily-check" / "SKILL.md"
_MIRROR = _ROOT / "skills" / "daily-check" / "SKILL.md"
_SHARED_PACKAGED = _ROOT / "mureo" / "_data" / "skills" / "_mureo-shared" / "SKILL.md"
_SHARED_MIRROR = _ROOT / "skills" / "_mureo-shared" / "SKILL.md"

#: The notice the skill emits for a platform whose tool surface is absent.
#: It follows the file's existing ``<condition>_for_<platform>`` convention
#: (``analytics_not_available_for_``, ``delivery_collapse_not_checkable_for_``)
#: so one reader vocabulary covers every "not checked" notice.
_NOTICE = "tools_absent_for_<platform>"


def _body() -> str:
    return _PACKAGED.read_text(encoding="utf-8")


def _shared_body() -> str:
    return _SHARED_PACKAGED.read_text(encoding="utf-8")


def _lines_containing(needle: str) -> list[str]:
    lowered = needle.lower()
    return [ln for ln in _body().splitlines() if lowered in ln.lower()]


def test_copies_are_byte_identical() -> None:
    assert _PACKAGED.read_bytes() == _MIRROR.read_bytes()
    assert _SHARED_PACKAGED.read_bytes() == _SHARED_MIRROR.read_bytes()


def test_stays_readable_under_the_size_budget() -> None:
    """The branch has to fit the prompt's budget, not grow a manual.

    Raised by exactly what each persistence step costs and no more — #690's
    two lines, then #706's fifteen for the display-contract step. The reason
    the number is what it is lives with the same pin in
    ``test_daily_check_incremental``; the two are deliberately kept equal, so
    a budget raised in one file and forgotten in the other fails here.
    """
    assert len(_body().splitlines()) <= 172


def test_names_the_absent_tool_surface_condition() -> None:
    """A platform configured in STATE.json whose tools are not in the session
    needs a name of its own, or the report has nothing to carry."""
    assert _NOTICE in _body()


def test_the_check_happens_before_the_report_not_after_a_failed_call() -> None:
    """An absent tool cannot report itself: there is no call and no error.
    The skill must say to confirm a tool of the platform's own was actually
    called and answered."""
    notice_lines = _lines_containing("tools_absent")
    assert notice_lines, "no absent-tool-surface branch in the skill"
    joined = " ".join(notice_lines).lower()
    assert "before you report" in joined
    assert "session" in joined


def test_reuses_580s_partial_report_treatment() -> None:
    """Not a second vocabulary — the same partial-report paragraph that
    handles an auth failure must also handle an absent tool surface."""
    partial_lines = [ln for ln in _body().splitlines() if "**partial**" in ln.lower()]
    assert partial_lines, "no partial-report rule in the skill"
    partial = " ".join(partial_lines)
    assert "auth_error" in partial
    assert "tools_absent" in partial


def test_forbids_a_kpi_table_for_a_platform_that_was_not_checked() -> None:
    """The exact shape #586 reported: a table with target/actual columns, an
    attainment percentage and pass/fail icons, indistinguishable from a
    measured section."""
    partial = " ".join(
        ln for ln in _body().splitlines() if "**partial**" in ln.lower()
    ).lower()
    assert "no kpi table" in partial
    assert "attainment" in partial
    assert "pass/fail" in partial


def test_forbids_estimated_or_extrapolated_figures() -> None:
    """The words the skill never had — the run improvised them, so the skill
    has to name and refuse them."""
    partial = " ".join(
        ln for ln in _body().splitlines() if "**partial**" in ln.lower()
    ).lower()
    assert "estimate" in partial
    assert "extrapolate" in partial


def test_a_one_line_disclaimer_is_not_enough() -> None:
    """What the run already did: it *did* disclaim, in one line, and then
    printed the table anyway."""
    partial = " ".join(
        ln for ln in _body().splitlines() if "**partial**" in ln.lower()
    ).lower()
    assert "disclaimer" in partial


def test_does_not_contradict_the_native_tools_fallback() -> None:
    """`:51-52` / `:69-70` already handle a different tool-surface case —
    mureo's own tools absent, fall back to the official hosted MCP. The new
    branch must fire only after those fallbacks are exhausted, or it would
    call a platform unchecked that a fallback could still read."""
    body = _body()
    assert "fall back to the official `google-ads-official` MCP" in body
    notice_lines = _lines_containing("tools_absent")
    joined = " ".join(notice_lines).lower()
    assert "fallback" in joined
    assert "no surface" in joined


def test_unchecked_platform_numbers_are_not_persisted() -> None:
    """Steps 12-13 write the figures tomorrow's incremental run diffs against.
    An invented number persisted there becomes the next run's baseline."""
    body = _body()
    kpi_lines = [ln for ln in body.splitlines() if "`kpis`:" in ln]
    assert kpi_lines, "step 12's kpis convention is gone"
    assert "measured only" in kpi_lines[0].lower()
    period_lines = [ln for ln in body.splitlines() if "Honest scope / cost" in ln]
    assert period_lines, "step 13's honest-scope rule is gone"
    assert "tools_absent" in period_lines[0]


def test_discovery_records_whether_the_tools_are_actually_there() -> None:
    """Step 2 enumerates a hosted connector from STATE.json alone, so the
    platform stays in scope while disconnected — that is where presence has
    to be recorded."""
    discovery = [ln for ln in _body().splitlines() if ln.startswith("2. **Discover")]
    assert discovery, "step 2 is gone"
    assert "callable in this session" in discovery[0]


def test_does_not_abort_the_whole_run() -> None:
    """#440's rule is untouched: the report degrades, it never stops."""
    notice_lines = _lines_containing("tools_absent")
    assert any("keep going" in ln.lower() for ln in notice_lines)


def test_shared_skill_says_a_missing_hosted_tool_is_reported_as_unchecked() -> None:
    """`_mureo-shared` is the line every workflow reads: it said "never fail
    the whole workflow ... report it and continue", which forbids aborting but
    never forbade substituting numbers."""
    shared_lines = [
        ln
        for ln in _shared_body().splitlines()
        if "never fail the whole workflow because a hosted tool is missing" in ln
    ]
    assert shared_lines, "the hosted-connector honest-scope line is gone"
    line = shared_lines[0].lower()
    assert "not checked" in line
    assert "estimate" in line
