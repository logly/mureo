"""Tests for the ``## Custom: Monthly Budget`` reader (mureo.context.monthly_budget).

The monthly budget target is the operator's INTENDED monthly spend. It is not
a ceiling, so these tests pin the three properties that keep it from being
read as one:

- "not set" is a first-class answer, distinguishable from a target of ``0``;
- a figure derived from the ``## Guardrails`` daily ceiling is labelled as
  derived, never handed back as if the operator had written it;
- a malformed section degrades to "not set" instead of raising out of a read
  path.

``TestSkillPrecedenceAgreement`` pins the reader against
``skills/budget-pacing/SKILL.md``, which is the specification, so the skill
and the code cannot answer the same question two different ways.

Marks: unit — pure text parsing, no network and no filesystem writes.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

from mureo.context.monthly_budget import (
    MONTHLY_BUDGET_HEADING,
    SOURCE_IMPLIED_DAILY_CEILING,
    SOURCE_NOT_SET,
    SOURCE_STRATEGY_SECTION,
    MonthlyBudget,
    monthly_budget_from_strategy_text,
    parse_monthly_budget,
    resolve_monthly_budget,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED_SKILL = _ROOT / "mureo" / "_data" / "skills" / "budget-pacing" / "SKILL.md"
_MIRROR_SKILL = _ROOT / "skills" / "budget-pacing" / "SKILL.md"

_STRATEGY_WITH_TARGET = """# Strategy

## Persona
A shoe shop.

## Custom: Monthly Budget
- total: 300000
- google_ads: 180000
- meta_ads: 120000

## Guardrails
- max_total_daily_budget: 20000
"""

_STRATEGY_CEILING_ONLY = """# Strategy

## Guardrails
- max_total_daily_budget: 20000
"""


class TestParseMonthlyBudget:
    def test_reads_total_and_per_platform_sub_targets(self) -> None:
        budget = parse_monthly_budget(
            "- total: 300,000\n- google_ads: 180000\n- meta_ads: 120000\n"
        )
        assert budget.total == 300000
        assert dict(budget.per_platform) == {
            "google_ads": 180000,
            "meta_ads": 120000,
        }
        assert budget.source == SOURCE_STRATEGY_SECTION
        assert budget.is_set
        assert not budget.is_derived

    def test_total_alone_is_enough(self) -> None:
        budget = parse_monthly_budget("- total: 300000\n")
        assert budget.total == 300000
        assert dict(budget.per_platform) == {}
        assert budget.is_set

    def test_zero_is_a_real_target_not_absence(self) -> None:
        budget = parse_monthly_budget("- total: 0\n")
        assert budget.total == 0.0
        assert budget.is_set
        assert budget.source == SOURCE_STRATEGY_SECTION

    def test_per_platform_mapping_is_read_only(self) -> None:
        budget = parse_monthly_budget("- total: 300000\n- google_ads: 180000\n")
        with pytest.raises(TypeError):
            budget.per_platform["google_ads"] = 1.0  # type: ignore[index]


class TestMalformedDegradesToNotSet:
    @pytest.mark.parametrize(
        "content",
        [
            "",
            "   \n\n",
            "The operator will tell us later.",
            "- total: not a number",
            "- total:\n",
            "- total: -100",
            "- google_ads: 180000",  # sub-targets without a total
        ],
    )
    def test_returns_not_set_without_raising(self, content: str) -> None:
        budget = parse_monthly_budget(content)
        assert not budget.is_set
        assert budget.total is None
        assert budget.source == SOURCE_NOT_SET

    def test_malformed_sub_target_drops_only_that_bullet(self) -> None:
        budget = parse_monthly_budget(
            "- total: 300000\n- google_ads: oops\n- meta_ads: -1\n- tiktok_ads: 5000\n"
        )
        assert budget.total == 300000
        assert dict(budget.per_platform) == {"tiktok_ads": 5000}


class TestMonthlyBudgetFromStrategyText:
    def test_reads_the_section_from_a_full_document(self) -> None:
        budget = monthly_budget_from_strategy_text(_STRATEGY_WITH_TARGET)
        assert budget.total == 300000
        assert dict(budget.per_platform) == {
            "google_ads": 180000,
            "meta_ads": 120000,
        }
        assert budget.source == SOURCE_STRATEGY_SECTION

    def test_absent_section_is_not_set_and_is_not_zero(self) -> None:
        budget = monthly_budget_from_strategy_text("# Strategy\n\n## Persona\nHi\n")
        assert not budget.is_set
        assert budget.total is None
        assert budget.total != 0
        assert budget.source == SOURCE_NOT_SET

    def test_heading_match_is_case_insensitive(self) -> None:
        budget = monthly_budget_from_strategy_text(
            "# Strategy\n\n## Custom: MONTHLY BUDGET\n- total: 1000\n"
        )
        assert budget.total == 1000

    def test_malformed_section_does_not_raise(self) -> None:
        budget = monthly_budget_from_strategy_text(
            "# Strategy\n\n## Custom: Monthly Budget\nask the operator\n"
        )
        assert not budget.is_set

    def test_empty_document_is_not_set(self) -> None:
        assert not monthly_budget_from_strategy_text("").is_set

    def test_reads_a_crlf_document(self) -> None:
        """A STRATEGY.md written on Windows must read the same."""
        budget = monthly_budget_from_strategy_text(
            _STRATEGY_WITH_TARGET.replace("\n", "\r\n")
        )
        assert budget.total == 300000
        assert dict(budget.per_platform) == {
            "google_ads": 180000,
            "meta_ads": 120000,
        }


class TestResolveMonthlyBudgetPrecedence:
    def test_explicit_section_wins_over_the_daily_ceiling(self) -> None:
        budget = resolve_monthly_budget(_STRATEGY_WITH_TARGET, days_in_month=31)
        assert budget.total == 300000
        assert budget.source == SOURCE_STRATEGY_SECTION
        assert not budget.is_derived

    def test_explicit_zero_still_wins_over_the_daily_ceiling(self) -> None:
        text = (
            "# Strategy\n\n## Custom: Monthly Budget\n- total: 0\n\n"
            "## Guardrails\n- max_total_daily_budget: 20000\n"
        )
        budget = resolve_monthly_budget(text, days_in_month=30)
        assert budget.total == 0.0
        assert budget.source == SOURCE_STRATEGY_SECTION

    def test_ceiling_only_is_derived_and_says_so(self) -> None:
        budget = resolve_monthly_budget(_STRATEGY_CEILING_ONLY, days_in_month=30)
        assert budget.total == 600000
        assert budget.is_set
        assert budget.is_derived
        assert budget.source == SOURCE_IMPLIED_DAILY_CEILING
        assert dict(budget.per_platform) == {}

    def test_derived_total_follows_the_length_of_the_month(self) -> None:
        february = resolve_monthly_budget(_STRATEGY_CEILING_ONLY, days_in_month=28)
        assert february.total == 560000

    def test_neither_present_is_not_set(self) -> None:
        budget = resolve_monthly_budget(
            "# Strategy\n\n## Persona\nHi\n", days_in_month=31
        )
        assert not budget.is_set
        assert not budget.is_derived
        assert budget.total is None

    def test_malformed_guardrail_ceiling_is_not_set(self) -> None:
        budget = resolve_monthly_budget(
            "# Strategy\n\n## Guardrails\n- max_total_daily_budget: oops\n",
            days_in_month=31,
        )
        assert not budget.is_set

    @pytest.mark.parametrize("days", [0, -1, 32, 365])
    def test_rejects_an_impossible_month_length(self, days: int) -> None:
        with pytest.raises(ValueError):
            resolve_monthly_budget(_STRATEGY_CEILING_ONLY, days_in_month=days)


class TestSkillPrecedenceAgreement:
    """The reader must answer what ``/budget-pacing`` answers (issue #652)."""

    def _skill_text(self) -> str:
        """The skill file, newline-normalised.

        Read as bytes so the packaged/mirror comparison stays exact, then
        normalised to ``\\n`` because a Windows checkout hands back CRLF and
        the multi-line pins below would silently stop matching.
        """
        packaged = _PACKAGED_SKILL.read_bytes()
        assert packaged == _MIRROR_SKILL.read_bytes(), (
            "budget-pacing: packaged skill and repo-root mirror have drifted; "
            "they must stay byte-identical."
        )
        return packaged.decode("utf-8").replace("\r\n", "\n")

    def test_skill_still_names_the_section_this_reader_reads(self) -> None:
        assert "## Custom: Monthly Budget" in self._skill_text()
        assert MONTHLY_BUDGET_HEADING == "monthly budget"

    def test_skill_still_states_the_precedence_the_reader_implements(self) -> None:
        text = self._skill_text()
        # 1. explicit section wins, and is a target rather than a ceiling.
        assert (
            "This wins; it is the intended monthly spend, not a safety ceiling" in text
        )
        # 2. the daily ceiling is an implied cap, used only in its absence.
        assert "max_total_daily_budget" in text
        assert "Multiply by the number of days in the current calendar month" in text
        assert "prefer it only when no explicit Monthly Budget exists" in text
        # 3. otherwise ask the operator — the reader's "not set".
        assert "ask the operator" in text

    def test_reader_parses_the_section_the_skill_persists(self) -> None:
        """The skill's own persist example must round-trip through the reader."""
        block = re.search(
            r"```markdown\n(\s*## Custom: Monthly Budget\n.*?)\s*```",
            self._skill_text(),
            re.DOTALL,
        )
        assert block is not None, "budget-pacing no longer shows the persist example"
        example = textwrap.dedent(block.group(1))
        budget = monthly_budget_from_strategy_text(f"# Strategy\n\n{example}")
        assert budget.total == 300000
        assert dict(budget.per_platform) == {
            "google_ads": 180000,
            "meta_ads": 120000,
        }
        assert budget.source == SOURCE_STRATEGY_SECTION

    def test_explicit_target_and_ceiling_together_resolve_the_skills_way(self) -> None:
        """Both present: the reader takes the target, not the ceiling×days."""
        budget = resolve_monthly_budget(_STRATEGY_WITH_TARGET, days_in_month=31)
        assert budget.total == 300000
        assert budget.total != 20000 * 31


class TestMonthlyBudgetDefaults:
    def test_default_instance_is_not_set(self) -> None:
        budget = MonthlyBudget()
        assert not budget.is_set
        assert not budget.is_derived
        assert budget.total is None
        assert dict(budget.per_platform) == {}
