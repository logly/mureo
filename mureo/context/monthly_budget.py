"""Read the operator's monthly budget target from STRATEGY.md (#652).

``## Custom: Monthly Budget`` is where an operator's monthly spend target
already lives — ``skills/budget-pacing/SKILL.md`` reads it, and offers to
persist one in that shape when it is missing. Until this module there was no
code path to it, so monthly pacing could only appear where that skill was
running. This is the twin of
:func:`mureo.policy.strategy_gate.guardrails_from_strategy_text` for the
neighbouring section, and it deliberately stops at reading: the figure stays
in STRATEGY.md, its single home, and is not copied into STATE.json for a
reader's convenience — a number in two places is a number that will disagree
with itself.

**This is not a guardrail, and the distinction is the point.**
:class:`~mureo.policy.strategy_gate.Guardrails` carries ceilings — values
whose job is to REFUSE an operation that exceeds them. A monthly budget target
is the intended spend: underspending it is a problem too, and no operation
should be blocked for approaching it. Hence a separate type and a separate
function; putting the target into ``Guardrails`` would make an intended figure
look enforceable.

Three answers, and each has to stay distinguishable from the other two
(:data:`SOURCE_NOT_SET` / :data:`SOURCE_STRATEGY_SECTION` /
:data:`SOURCE_IMPLIED_DAILY_CEILING`):

- **The operator wrote a target.** It wins, whatever the guardrails say —
  including a target of ``0``, which is a real instruction to spend nothing.
- **No target, but a ``max_total_daily_budget`` ceiling.** ``ceiling × days in
  month`` is an *implied cap*, never a plan. It is returned only with
  :attr:`MonthlyBudget.is_derived` set, so a caller cannot render it as
  something the operator asked for.
- **Neither.** "Not set", carrying ``total=None`` — never ``0``, never a
  percentage, never "on pace". The skill's answer here is to ask the operator,
  and a caller cannot ask a question it was not told to ask.

The precedence above is ``skills/budget-pacing/SKILL.md`` step 3, which is the
specification this module matches rather than replaces;
``tests/test_monthly_budget.py`` pins the agreement so the two cannot drift.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

from mureo.context.strategy import parse_strategy

#: The (case-insensitive) STRATEGY.md section title carrying the target. The
#: skill writes it as ``## Custom: Monthly Budget``, which ``strategy.py``
#: parses into a ``custom`` entry titled "Monthly Budget"; a bare
#: ``## Monthly Budget`` round-trips as a raw-heading entry with the same
#: title, and is read too. Matching on the title alone mirrors
#: :func:`mureo.policy.strategy_gate.guardrails_from_strategy_text`.
MONTHLY_BUDGET_HEADING: Final = "monthly budget"

#: No target anywhere. ``total`` is ``None`` — the caller must not render a
#: figure, a percentage, or a pacing verdict from this.
SOURCE_NOT_SET: Final = "not_set"
#: The operator's own figure, read from the STRATEGY.md section.
SOURCE_STRATEGY_SECTION: Final = "strategy_section"
#: Derived: ``## Guardrails`` → ``max_total_daily_budget`` × days in month. A
#: ceiling stretched over a month, not a plan. Label it as such wherever it
#: is shown.
SOURCE_IMPLIED_DAILY_CEILING: Final = "implied_daily_ceiling"

#: The bullet naming the whole-month figure; every other numeric bullet is a
#: per-platform sub-target. Not restricted to mureo's built-in platform keys:
#: the skill paces hosted-connector and plugin platforms too.
_TOTAL_KEY: Final = "total"

#: Longest a calendar month can be — the bound on ``days_in_month``.
_MAX_DAYS_IN_MONTH: Final = 31

# Same bullet shape the ``## Guardrails`` readers accept.
_BULLET_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*[-*]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$"
)

#: Shared read-only default so no instance allocates (or leaks) a mutable one.
_EMPTY_PER_PLATFORM: Final[Mapping[str, float]] = MappingProxyType({})


@dataclass(frozen=True)
class MonthlyBudget:
    """The operator's intended monthly spend, or the absence of one.

    Attributes:
        total: Whole-month figure, or ``None`` when no target is set.
            ``None`` and ``0.0`` are different answers: ``0.0`` is an
            operator who said "spend nothing", ``None`` is an operator who
            said nothing.
        per_platform: Read-only per-platform sub-targets, keyed by platform
            key (``google_ads``, ``meta_ads``, a plugin's own key). Empty
            when the section names none, and always empty for a derived
            total — a total ceiling says nothing about the split.
        source: Which of the three answers this is — one of
            :data:`SOURCE_NOT_SET`, :data:`SOURCE_STRATEGY_SECTION`,
            :data:`SOURCE_IMPLIED_DAILY_CEILING`.
    """

    total: float | None = None
    per_platform: Mapping[str, float] = field(
        default_factory=lambda: _EMPTY_PER_PLATFORM
    )
    source: str = SOURCE_NOT_SET

    @property
    def is_set(self) -> bool:
        """False when there is no target — the caller's cue to ask, not guess."""
        return self.source != SOURCE_NOT_SET

    @property
    def is_derived(self) -> bool:
        """True when ``total`` came from a ceiling, not from an operator."""
        return self.source == SOURCE_IMPLIED_DAILY_CEILING


def _amount(raw: str | None) -> float | None:
    """A non-negative finite bullet amount, or ``None`` when it is not one.

    Rejects rather than coerces: a bullet mureo cannot read must drop out, so
    a typo degrades to "not set" instead of becoming a figure nobody wrote.
    """
    if raw is None:
        return None
    try:
        number = float(raw.replace(",", "").replace("_", "").strip())
    except (AttributeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _bullets(content: str) -> dict[str, str]:
    """``- key: value`` bullets of a section body, last occurrence winning."""
    found: dict[str, str] = {}
    for line in content.splitlines():
        match = _BULLET_RE.match(line)
        if match is not None:
            found[match.group(1).lower()] = match.group(2).strip()
    return found


def parse_monthly_budget(content: str) -> MonthlyBudget:
    """Parse a ``## Custom: Monthly Budget`` body into :class:`MonthlyBudget`.

    ``- total:`` is required — a section without a readable one is malformed
    and degrades to "not set" rather than to a sum of whatever sub-targets
    happen to be there, which would be a figure the operator never wrote. An
    unreadable sub-target drops only itself, mirroring
    :func:`~mureo.policy.strategy_gate.parse_guardrails`. Never raises: this
    is a read path.
    """
    bullets = _bullets(content)
    total = _amount(bullets.get(_TOTAL_KEY))
    if total is None:
        return MonthlyBudget()

    per_platform: dict[str, float] = {}
    for key, raw in bullets.items():
        if key == _TOTAL_KEY:
            continue
        amount = _amount(raw)
        if amount is not None:
            per_platform[key] = amount

    return MonthlyBudget(
        total=total,
        per_platform=MappingProxyType(per_platform),
        source=SOURCE_STRATEGY_SECTION,
    )


def monthly_budget_from_strategy_text(text: str) -> MonthlyBudget:
    """The operator's explicit target from full STRATEGY.md text.

    "Not set" when the section is absent, empty or malformed. This reads only
    what the operator wrote — see :func:`resolve_monthly_budget` for the
    skill's full precedence, which may fall back to the guardrail ceiling.
    """
    for entry in parse_strategy(text):
        if entry.title.strip().lower() == MONTHLY_BUDGET_HEADING:
            return parse_monthly_budget(entry.content)
    return MonthlyBudget()


def resolve_monthly_budget(text: str, *, days_in_month: int) -> MonthlyBudget:
    """The monthly target for a month of ``days_in_month`` days.

    Applies ``skills/budget-pacing/SKILL.md`` step 3 in order: an explicit
    ``## Custom: Monthly Budget`` wins; failing that, ``## Guardrails`` →
    ``max_total_daily_budget`` × ``days_in_month`` is returned as an implied
    cap with :attr:`MonthlyBudget.is_derived` set; failing both, "not set".

    ``days_in_month`` belongs to the caller because pacing's "today" comes
    from ``server_now``, never from this machine's clock. It is validated
    here rather than defaulted — a wrong month length silently mis-states
    the cap.

    Args:
        text: Full STRATEGY.md text.
        days_in_month: Length of the pacing month, 1..31.

    Raises:
        ValueError: ``days_in_month`` is not a possible calendar-month
            length. Malformed STRATEGY.md content never raises.
    """
    if not 1 <= days_in_month <= _MAX_DAYS_IN_MONTH:
        raise ValueError(
            f"days_in_month must be between 1 and {_MAX_DAYS_IN_MONTH}, "
            f"got {days_in_month}"
        )

    explicit = monthly_budget_from_strategy_text(text)
    if explicit.is_set:
        return explicit

    # Local import: the ceiling is a guardrail, and this module stays out of
    # the policy package's import path for the (far more common) explicit
    # case. ``strategy_gate`` owns that section's parsing so the two readers
    # cannot drift onto different spellings of the same rule.
    from mureo.policy.strategy_gate import guardrails_from_strategy_text

    ceiling = guardrails_from_strategy_text(text).max_total_daily_budget
    if ceiling is None or not math.isfinite(ceiling) or ceiling < 0:
        return MonthlyBudget()
    return MonthlyBudget(
        total=ceiling * days_in_month,
        source=SOURCE_IMPLIED_DAILY_CEILING,
    )


__all__ = [
    "MONTHLY_BUDGET_HEADING",
    "SOURCE_IMPLIED_DAILY_CEILING",
    "SOURCE_NOT_SET",
    "SOURCE_STRATEGY_SECTION",
    "MonthlyBudget",
    "monthly_budget_from_strategy_text",
    "parse_monthly_budget",
    "resolve_monthly_budget",
]
