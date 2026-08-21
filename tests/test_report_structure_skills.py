"""Every skill that writes a report must fill the structure (#662).

The schema refuses a paragraph, but a refusal an agent meets mid-run is the
expensive way to learn a rule. The skill is where the report is composed, so
the division of labour is stated there: figures in ``totals``, findings in
``flags``, and ``narrative`` for the judgement and the proposal only.

Pinned for every skill that calls ``mureo_state_report_set``, in BOTH the
packaged copy and the repo-root mirror (kept byte-identical, the convention
in ``tests/test_daily_check_structured_flags.py``):

- the canonical metric vocabulary and the raw-number rule;
- the bound, and that exceeding it is refused rather than truncated;
- that numbers and findings do not go in the paragraph.

``daily-check`` additionally carries the worked before/after — the report
#662 was filed about, and what it looks like split up. One example, in the
skill that produced the wall.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent

#: Every skill whose report step calls ``mureo_state_report_set``.
_SKILLS = (
    "ad-fatigue-check",
    "audience-review",
    "budget-pacing",
    "daily-check",
    "experiment",
    "goal-review",
    "monthly-report",
    "tracking-health",
    "weekly-report",
)

#: Stated the same way everywhere: one rule an agent can carry between
#: skills, not nine paraphrases of it.
_REQUIRED = (
    "using the canonical metric vocabulary",
    "`spend`, `conversions`, `cpa`, `ctr`, `clicks`, `impressions`",
    "at most 400 characters",
    "refuses a longer one rather than truncating it",
    "numbers belong in `totals`, findings in `flags`",
)


def _packaged(skill: str) -> Path:
    return _ROOT / "mureo" / "_data" / "skills" / skill / "SKILL.md"


def _mirror(skill: str) -> Path:
    return _ROOT / "skills" / skill / "SKILL.md"


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_two_copies_are_byte_identical(skill: str) -> None:
    assert _packaged(skill).read_bytes() == _mirror(skill).read_bytes()


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_report_step_states_the_division_of_labour(skill: str) -> None:
    body = _packaged(skill).read_text(encoding="utf-8")
    assert "mureo_state_report_set" in body, "skill list is stale"
    for phrase in _REQUIRED:
        assert phrase in body, f"{skill}: missing {phrase!r}"


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_raw_number_rule_is_shown_not_just_named(skill: str) -> None:
    """A figure written as ``"¥773,957"`` renders as nothing — the observed
    failure — so the rule is shown with the string it refuses."""
    body = _packaged(skill).read_text(encoding="utf-8")
    assert "773957" in body
    assert "¥773,957" in body


def test_the_shared_schema_states_the_bound_once() -> None:
    """``_mureo-strategy`` is where the STATE.json schema is described for
    every skill, so the bound is stated there too — including that reports
    already on disk are not touched by it."""
    packaged = _packaged("_mureo-strategy")
    assert packaged.read_bytes() == _mirror("_mureo-strategy").read_bytes()
    body = packaged.read_text(encoding="utf-8")
    assert "at most 400 characters" in body
    assert "refuses a longer one rather than truncating it" in body
    assert "the bound applies to new writes only" in body


def test_the_worked_example_shows_the_paragraph_and_the_split() -> None:
    """The before/after: the ~700-character report #662 reported, and the
    same content as ``totals`` / ``flags`` / a two-sentence ``narrative``.

    It lives with the schema rather than in ``daily-check``, which is held to
    a line budget (``tests/test_daily_check_incremental.py``) because a skill
    is a prompt, not a manual — and one example there serves every skill that
    writes a report.
    """
    body = _packaged("_mureo-strategy").read_text(encoding="utf-8")
    assert "**Before** (what #662 reported" in body
    assert "**After**" in body
    # The before is the real thing, not a sanitized stand-in.
    assert "日次チェック(EFFICIENCY_STABILIZE)" in body
    # ...and the after states the same numbers as figures and flags.
    assert '"spend": 773957' in body
    assert '"code": "invalid_traffic_suspected"' in body
    # The example is one click away from the skill that produced the wall.
    daily = _packaged("daily-check").read_text(encoding="utf-8")
    assert "`../_mureo-strategy/SKILL.md` → *Reports section*" in daily
