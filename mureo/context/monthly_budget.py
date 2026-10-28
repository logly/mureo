"""Read the operator's monthly budget target from STRATEGY.md (#652).

``## Custom: Monthly Budget`` is where an operator's monthly spend target
already lives — ``skills/budget-pacing/SKILL.md`` reads it, and offers to
persist one in that shape when it is missing. Until this module there was no
code path to it, so monthly pacing could only appear where that skill was
running. This is the twin of
:func:`mureo.policy.guardrails.guardrails_from_entries` for the
neighbouring section, and it deliberately stops at reading: the figure stays
in STRATEGY.md, its single home, and is not copied into STATE.json for a
reader's convenience — a number in two places is a number that will disagree
with itself.

**This is not a guardrail, and the distinction is the point.**
:class:`~mureo.policy.guardrails.Guardrails` carries ceilings — values
whose job is to REFUSE an operation that exceeds them. A monthly budget target
is the intended spend: underspending it is a problem too, and no operation
should be blocked for approaching it. Hence a separate type and a separate
function; putting the target into ``Guardrails`` would make an intended figure
look enforceable.

Four answers, and each has to stay distinguishable from the other three
(:data:`SOURCE_NOT_SET` / :data:`SOURCE_STRATEGY_SECTION` /
:data:`SOURCE_PLATFORM_CONFIGURED_SUM` / :data:`SOURCE_IMPLIED_DAILY_CEILING`):

- **The operator wrote a target.** It wins, whatever the guardrails say —
  including a target of ``0``, which is a real instruction to spend nothing.
- **No target, but the platforms hold monthly budgets of their own** (#656).
  Summed, they are what the platforms are *configured* to spend, which is a
  real figure and not a derivation — and still not what the client agreed to.
  It is returned only with :attr:`MonthlyBudget.is_platform_configured` set,
  so a display cannot state it as an agreement nobody made. See
  :mod:`mureo.context.platform_monthly_budget`.
- **No target, but a ``max_total_daily_budget`` ceiling.** ``ceiling × days in
  month`` is an *implied cap*, never a plan. It is returned only with
  :attr:`MonthlyBudget.is_derived` set, so a caller cannot render it as
  something the operator asked for.
- **None of those.** "Not set", carrying ``total=None`` — never ``0``, never a
  percentage, never "on pace". The skill's answer here is to ask the operator,
  and a caller cannot ask a question it was not told to ask.

The precedence above is ``skills/budget-pacing/SKILL.md`` step 3, which is the
specification this module matches rather than replaces;
``tests/test_monthly_budget.py`` pins the agreement so the two cannot drift.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from mureo.context.monthly_budget_models import (
    SOURCE_IMPLIED_DAILY_CEILING,
    SOURCE_NOT_SET,
    SOURCE_PLATFORM_CONFIGURED_SUM,
    SOURCE_STRATEGY_SECTION,
    MonthlyBudget,
)
from mureo.context.platform_monthly_budget import platform_configured_monthly_budget
from mureo.context.strategy import parse_strategy
from mureo.policy.guardrails import GUARDRAILS_BULLET_RE, guardrails_from_entries

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.models import PlatformState

#: The (case-insensitive) STRATEGY.md section title carrying the target. The
#: skill writes it as ``## Custom: Monthly Budget``, which ``strategy.py``
#: parses into a ``custom`` entry titled "Monthly Budget"; a bare
#: ``## Monthly Budget`` round-trips as a raw-heading entry with the same
#: title, and is read too. Matching on the title alone mirrors
#: :func:`mureo.policy.guardrails.guardrails_from_entries`.
MONTHLY_BUDGET_HEADING: Final = "monthly budget"

#: The bullet naming the whole-month figure; every other numeric bullet is a
#: per-platform sub-target. Not restricted to mureo's built-in platform keys:
#: the skill paces hosted-connector and plugin platforms too.
_TOTAL_KEY: Final = "total"

#: Longest a calendar month can be — the bound on ``days_in_month``.
_MAX_DAYS_IN_MONTH: Final = 31


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
        match = GUARDRAILS_BULLET_RE.match(line)
        if match is not None:
            found[match.group(1).lower()] = match.group(2).strip()
    return found


def parse_monthly_budget(content: str) -> MonthlyBudget:
    """Parse a ``## Custom: Monthly Budget`` body into :class:`MonthlyBudget`.

    ``- total:`` is required — a section without a readable one is malformed
    and degrades to "not set" rather than to a sum of whatever sub-targets
    happen to be there, which would be a figure the operator never wrote. An
    unreadable sub-target drops only itself, mirroring
    :func:`~mureo.policy.guardrails.parse_guardrails`. Never raises: this
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


def resolve_monthly_budget(
    text: str,
    *,
    days_in_month: int,
    platforms: Mapping[str, PlatformState] | None = None,
) -> MonthlyBudget:
    """The monthly target for a month of ``days_in_month`` days.

    Applies ``skills/budget-pacing/SKILL.md`` step 3 in order: an explicit
    ``## Custom: Monthly Budget`` wins; failing that, the per-campaign monthly
    budgets of the platforms that have that concept, summed and marked
    :attr:`MonthlyBudget.is_platform_configured`; failing that,
    ``## Guardrails`` → ``max_total_daily_budget`` × ``days_in_month`` as an
    implied cap with :attr:`MonthlyBudget.is_derived` set; failing all three,
    "not set".

    ``days_in_month`` belongs to the caller because pacing's "today" comes
    from ``server_now``, never from this machine's clock. It is validated
    here rather than defaulted — a wrong month length silently mis-states
    the cap.

    Omitting ``platforms`` skips the platform rung entirely and answers
    exactly what this function answered before that rung existed. Passing it
    can only *add* an answer between the two the caller already had; it never
    changes what an explicit section resolves to.

    Where the platform rung is possible but its campaign set is incomplete,
    no sum is returned — the answer falls through to the remaining rungs,
    carrying :attr:`MonthlyBudget.incomplete_platforms` so the caller can say
    that a platform figure exists and was not trustworthy, rather than
    rendering a smaller number.

    Args:
        text: Full STRATEGY.md text.
        days_in_month: Length of the pacing month, 1..31.
        platforms: STATE.json's ``platforms`` map, when the caller has it.
            The legacy top-level ``campaigns`` list is not consulted: its
            entries carry no platform key, so nothing can say whether the
            platform they belong to has a monthly budget at all.

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

    configured = platform_configured_monthly_budget(platforms)
    if configured.is_set:
        return configured
    # Whatever answers instead has to carry the reason the sum did not.
    incomplete = configured.incomplete_platforms

    # ``mureo.policy.guardrails`` owns the guardrail section's parsing so the
    # two readers cannot drift onto different spellings of the same rule.
    ceiling = guardrails_from_entries(parse_strategy(text)).max_total_daily_budget
    if ceiling is None or not math.isfinite(ceiling) or ceiling < 0:
        return MonthlyBudget(incomplete_platforms=incomplete)
    return MonthlyBudget(
        total=ceiling * days_in_month,
        source=SOURCE_IMPLIED_DAILY_CEILING,
        incomplete_platforms=incomplete,
    )


__all__ = [
    "MONTHLY_BUDGET_HEADING",
    "SOURCE_IMPLIED_DAILY_CEILING",
    "SOURCE_NOT_SET",
    "SOURCE_PLATFORM_CONFIGURED_SUM",
    "SOURCE_STRATEGY_SECTION",
    "MonthlyBudget",
    "monthly_budget_from_strategy_text",
    "parse_monthly_budget",
    "resolve_monthly_budget",
]
