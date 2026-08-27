"""Every skill that writes a report also writes the display contract (#706).

Step 1 gave the dashboard a small, write-guarded surface and refused
everything that does not fit it. That is only half the fix: a guard an agent
meets mid-run is the expensive way to learn a rule, and a contract nobody
writes leaves the screen empty. So the nine report-writing skills each gain
a step that fills it, next to the report step they already have.

What this suite pins, in BOTH the packaged copy and the repo-root mirror:

**The step exists and is reachable.** ``mureo_state_display_set`` is called,
after the report write, in every skill that writes a report.

**The bounds are stated in the words the refusal will use.** Not a
paraphrase: :data:`~mureo.core.display_contract.DISPLAY_CONTRACT_RULE` is
pasted verbatim, so the sentence an agent reads while composing and the
sentence it gets back on a refusal cannot drift apart. That is #659's shape,
and asserting the whole string — rather than a handful of phrases — is what
makes the single source real rather than aspirational.

**The failure mode is named.** Over a bound the write is refused, so the
instruction is to *shorten and rewrite*. Without that, an agent's obvious
move is to trim a character and call again, which spends a run's context on
a bound one rewrite would have met.

**No new judgement happens here.** The step renders verdicts the skill
already reached. A skill that re-decided a campaign's state while writing
the screen would put two answers in one document.

**Prose stays out of the chip row.** ``stated_values`` is a caption and a
figure; a sentence there is the defect #706 was filed about, and the tool
refuses it. The skills say so, and say where a sentence goes instead.

**The action log gets its display line.** Every recording step instructs
``display_title`` / ``display_summary``, and says the full ``summary`` is
unchanged — the two add a rendering, they replace nothing.

**One writer per run**, stated in ``daily-check`` — the skill that writes
this most often, and the one whose steps another skill is most likely to run
beside.

**And the second writer's duty**, stated in all nine. ``display`` is
replaced whole and the last writer wins, so a weekly review's proposals can
be gone by the evening. That is the design — a screen is one moment — but it
is not free, so :data:`~mureo.core.display_contract.DISPLAY_OVERWRITE_RULE`
is pasted verbatim too: read the current contract first, carry over the
other skill's still-live ``proposals``, and carry nothing else. Alongside it,
every skill names itself in ``source``, so a card whose section a later run
replaced still says who last spoke.

**One tone table.** A chip is a severity in fewer characters, and mapped by
feel the same finding ends up amber on one client's card and red on
another's. :data:`~mureo.core.display_contract.HIGHLIGHT_TONE_RULE` is
pasted onto the ``highlights`` bullet of all nine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mureo.core.display_contract import (
    ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS,
    ACTION_LOG_DISPLAY_TITLE_MAX_CHARS,
    BREAKDOWN_STATES,
    DISPLAY_CONTRACT_RULE,
    DISPLAY_OVERWRITE_RULE,
    DISPLAY_SOURCE_MAX_CHARS,
    HIGHLIGHT_TONE_RULE,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent

#: The same nine skills ``tests/test_report_structure_skills.py`` holds to the
#: report structure. Kept as its own tuple rather than imported: a skill that
#: writes a report and does not write the screen is exactly the drift worth
#: failing on, and the cross-check below pins the two lists together.
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

#: Stated the same way in every skill — one rule an agent carries between
#: them, not nine paraphrases of it.
_REQUIRED = (
    "**Persist the display contract**",
    "`mureo_state_display_set`",
    "**reach no new verdict here**",
    "**Over a bound the write is REFUSED — shorten and rewrite, do not "
    "re-send the same sentence trimmed.**",
    "**No prose notes here.**",
)


def _packaged(skill: str) -> Path:
    return _ROOT / "mureo" / "_data" / "skills" / skill / "SKILL.md"


def _mirror(skill: str) -> Path:
    return _ROOT / "skills" / skill / "SKILL.md"


def _body(skill: str) -> str:
    return _packaged(skill).read_text(encoding="utf-8")


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_two_copies_are_byte_identical(skill: str) -> None:
    assert _packaged(skill).read_bytes() == _mirror(skill).read_bytes()


def test_the_skill_list_matches_the_report_writing_one() -> None:
    """Every skill that writes a report writes the screen, and vice versa.

    Two lists that drifted would be invisible: the dashboard would simply be
    empty for whichever skill ran, with nothing anywhere naming the gap.
    """
    from tests.test_report_structure_skills import _SKILLS as _REPORT_SKILLS

    assert set(_SKILLS) == set(_REPORT_SKILLS)


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_display_step_states_the_contract(skill: str) -> None:
    body = _body(skill)
    for phrase in _REQUIRED:
        assert phrase in body, f"{skill}: missing {phrase!r}"


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_bounds_are_pasted_verbatim_from_the_code(skill: str) -> None:
    """#659's shape: one text, shown wherever the rule has to be known.

    A paraphrase would pass a phrase-by-phrase check and still tell an agent
    a different number from the one the tool enforces the day either changes.
    """
    assert DISPLAY_CONTRACT_RULE in _body(skill)


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_overwrite_rule_is_pasted_verbatim(skill: str) -> None:
    """The half no schema can enforce, in every skill that could hit it.

    `display` is replaced whole and the last writer wins, so a weekly
    review's proposals can be gone by the evening. Whether another skill's
    proposal is still live is a judgement about today's findings — only the
    caller holds it — so the instruction has to reach the caller, verbatim,
    or the loss is silent.
    """
    assert DISPLAY_OVERWRITE_RULE in _body(skill)


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_skill_is_told_to_name_itself(skill: str) -> None:
    """Last-writer-wins costs a reader the ability to tell WHOSE answer
    survived; ``source`` is what pays that back, so every writer states it."""
    body = _body(skill)
    assert "- `source`: your own skill name" in body
    assert f"at most {DISPLAY_SOURCE_MAX_CHARS} characters" in body
    # …and the server owns the clock, as it does for every other timestamp
    # in this document (#460).
    assert "`generated_at` is stamped by the server — do not compute it" in body


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_tone_map_is_pasted_verbatim(skill: str) -> None:
    """A chip is a severity in fewer characters. Mapped by feel, the same
    finding ends up amber on one client's card and red on another's."""
    assert HIGHLIGHT_TONE_RULE in _body(skill)


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_tone_map_sits_on_the_highlights_bullet(skill: str) -> None:
    """Where the chips are composed, not stranded elsewhere in the step."""
    line = next(ln for ln in _body(skill).splitlines() if HIGHLIGHT_TONE_RULE in ln)
    assert "`highlights`" in line, f"{skill}: the tone map is not on the chips"


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_display_write_comes_after_the_report_write(skill: str) -> None:
    """The screen is rendered FROM the report, in the same pass.

    Ordering is the load-bearing part: the display step states that it
    reaches no new verdict, which is only true if the verdicts already exist
    when it runs.
    """
    body = _body(skill)
    assert body.index("mureo_state_report_set") < body.index(
        "mureo_state_display_set"
    ), f"{skill}: the display step is instructed before the report it renders"


@pytest.mark.parametrize("skill", _SKILLS)
def test_every_section_of_the_contract_is_instructed(skill: str) -> None:
    """All five, or the dashboard has a hole no refusal would ever report."""
    body = _body(skill)
    for section in (
        "`nav_message`",
        "`highlights`",
        "`breakdown.campaigns`",
        "`proposals`",
        "`stated_values`",
    ):
        assert section in body, f"{skill}: {section} is never instructed"


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_closed_row_state_vocabulary_is_shown(skill: str) -> None:
    """``state`` is rendered as a colour, so an invented value draws nothing.

    Shown in full rather than named, for the reason #659 gives: an agent that
    reached for a word outside the set needs to see what the alternatives
    ARE, before the call rather than in the refusal.
    """
    body = _body(skill)
    for state in BREAKDOWN_STATES:
        assert f"`{state}`" in body, f"{skill}: {state!r} missing from the set"


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_action_log_step_instructs_the_display_line(skill: str) -> None:
    body = _body(skill)
    assert "**Give every entry a display line**" in body
    assert f"at most {ACTION_LOG_DISPLAY_TITLE_MAX_CHARS} " in body
    assert f"at most {ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS}" in body
    # The two ADD a rendering; the work-journal note is unchanged. A skill
    # that read this as "write a shorter summary" would lose the detail the
    # next agent's evidence loop runs on.
    assert "the full `summary` is drill-down only" in body
    assert "as fully as the next agent needs" in body


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_display_line_instruction_sits_on_a_recording_step(skill: str) -> None:
    """Beside ``action_log``, not stranded in the display step.

    The bound fires on the append, so the instruction has to be where the
    append is written — a skill that only mentioned it under the display
    contract would have an agent read it after every entry was already
    written.
    """
    body = _body(skill)
    line = next(
        ln for ln in body.splitlines() if "**Give every entry a display line**" in ln
    )
    assert "action_log" in line, f"{skill}: the display line is not on a log step"


def test_the_shared_schema_describes_the_section_once() -> None:
    """``_mureo-strategy`` is where STATE.json is described for every skill,
    so the ``display`` section is described there too — beside ``reports``,
    which is the comparison that makes the split legible.

    The nine skills say how to FILL it for their own run; this says what it
    IS. Splitting it the other way round — nine copies of the schema — is how
    the nine would start describing nine slightly different sections.
    """
    packaged = _packaged("_mureo-strategy")
    assert packaged.read_bytes() == _mirror("_mureo-strategy").read_bytes()
    body = packaged.read_text(encoding="utf-8")
    assert "### Display contract section" in body
    assert "`mureo_state_display_set`" in body
    # The facts a writer cannot work out from the field list alone.
    assert "Every bound refuses the write; nothing is truncated" in body
    assert "**One writer per run — and last writer wins across the day.**" in body
    assert "carry over the\nother skill's `proposals` that are still live" in body
    # …and what is deliberately NOT writable, or an agent will try.
    assert "Do not write the KPI funnel or the daily chart" in body


def test_the_shared_schema_documents_the_action_log_display_line() -> None:
    """The field table is where a skill looks up what an entry may carry."""
    body = _packaged("_mureo-strategy").read_text(encoding="utf-8")
    assert "| `display_title` | string | No |" in body
    assert "| `display_summary` | string | No |" in body
    assert "the full `summary` is drill-down only" in body


def test_the_two_daily_check_size_budgets_agree() -> None:
    """``daily-check`` is held to a line budget by TWO modules, and #706
    raised one and not the other — the suite went red on the second.

    They are the same ceiling on the same file, so a number that differs
    between them means one was edited and the other forgotten. Asserted by
    running each pin against a body one line over the budget: whichever
    module has the lower ceiling fails first, and equal ceilings fail
    together.
    """
    from tests import test_daily_check_absent_tool_surface as absent
    from tests import test_daily_check_incremental as incremental

    over = "x\n" * (len(_body("daily-check").splitlines()) + 1)
    for module in (incremental, absent):
        module_over = pytest.MonkeyPatch()
        module_over.setattr(module, "_body", lambda: over)
        with pytest.raises(AssertionError):
            module.test_stays_readable_under_the_size_budget()
        module_over.undo()

    # …and neither is slack: today's file is within both.
    for module in (incremental, absent):
        module.test_stays_readable_under_the_size_budget()


def test_daily_check_states_the_one_writer_rule() -> None:
    """The step-2 design premise, in the skill most likely to meet it.

    ``mureo_state_display_set`` replaces the whole section, so two skills
    writing different sections in one run do not compose — the second wins
    outright. Stated where the contract is written most often.
    """
    body = _body("daily-check")
    assert "**One writer per run — and you may not be the first today.**" in body
    assert "REPLACES" in body
    assert "never call twice" in body
