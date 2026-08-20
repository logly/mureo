"""What the PLATFORMS are configured to spend this month (#656).

Rung 2 of :func:`mureo.context.monthly_budget.resolve_monthly_budget`. The
operator's ``## Custom: Monthly Budget`` (#652) is the agreed figure and still
wins; this module answers the neighbouring question — *what are the platforms
actually set to spend* — so the hand-written section is needed only where the
agreement differs from the configuration, rather than once per client and
again on every change.

Two halves, because one route cannot carry both
-----------------------------------------------
**The figure travels as data.** A campaign's monthly budget is per-campaign
and changes on every sync, so it rides in
:attr:`~mureo.context.models.CampaignSnapshot.monthly_budget`, beside
``daily_budget``, written by whichever collector syncs that platform. What is
never written is a TOTAL: the sum is computed here, on read, because a cached
total is stale the moment one campaign's budget changes — the defect shape
of #631 / #636 / #638 / #647.

**The concept travels as a declaration.** :func:`register_monthly_budget_support`
is how a provider, bridge or plugin states that its platform has a monthly
budget at all. It answers a question no campaign row can: whether an absent
figure is a GAP or simply a field that platform does not have. Google Ads and
Meta campaigns are configured per day, so their ``monthly_budget`` is empty
and always will be; a platform that has the concept and is missing a figure
for one campaign is an incomplete set, and summing it would understate the
client's budget. Without the declaration those two absences are the same
absence, and the incompleteness rule below could not be enforced at all.

mureo core declares no platform, the same honesty rule
:mod:`mureo.policy.learning_rules` and :mod:`mureo.policy.platform_model`
apply: where mureo cannot quote a first-party source it says nothing rather
than guessing, and it does not pre-empt a platform's own account of itself.
Registration is first-wins, matching
:meth:`mureo.core.providers.registry.Registry.register`, so a plugin
installed after a legitimate one cannot take the slot. A wrong declaration
cannot invent a figure — every number comes from STATE.json — its only effect
is to make mureo refuse a sum it would otherwise have taken.

An incomplete set is not a smaller budget
-----------------------------------------
If mureo holds three of a client's five campaigns, summing three is not the
client's budget. So the sum is taken only from a set mureo can vouch for, and
a platform is unusable when any of the following holds:

- a campaign it holds carries no readable monthly budget — mureo has the
  campaign but not its figure;
- it holds no campaigns at all — there is nothing to sum, and ``0`` would be
  a confident lie;
- its last collection failed (:attr:`~mureo.context.models.PlatformState.
  not_collected`, #638) — the set may be stale or short.

One unusable platform withholds the WHOLE total, not just its own part: a
cross-platform figure that silently drops a platform is the same defect one
level up. The keys are returned in
:attr:`~mureo.context.monthly_budget.MonthlyBudget.incomplete_platforms` so
the caller states the gap instead of rendering a smaller number — the same
rule #638 established for stale rollups, applied to a total.

Whether a paused or removed campaign "counts" is deliberately not decided
here: status vocabularies are per-platform, and mureo does not read one
platform's words with another's dictionary. Every campaign the document holds
for a declaring platform contributes, and every one of them must have a
figure.
"""

from __future__ import annotations

import logging
import math
import warnings
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import TYPE_CHECKING

from mureo.context.monthly_budget import (
    SOURCE_PLATFORM_CONFIGURED_SUM,
    MonthlyBudget,
)

# Not a policy rule, but the same Evidence record: a claim about how a
# platform's API works is exactly what ``learning_rules`` requires a
# first-party source for, and one repository should not have two shapes for
# "where did this fact come from".
from mureo.policy.learning_rules import Evidence

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.models import PlatformState

logger = logging.getLogger(__name__)


class MonthlyBudgetSupportWarning(UserWarning):
    """Emitted when a declaration is dropped because the slot is taken.

    A :class:`UserWarning` subclass so operators can fail closed with
    ``warnings.filterwarnings("error", category=MonthlyBudgetSupportWarning)``,
    the same opt-in
    :class:`~mureo.policy.platform_model.PlatformModelWarning` offers.
    """


@dataclass(frozen=True)
class MonthlyBudgetSupport:
    """One platform's statement that its campaigns carry a monthly budget.

    ``platform`` is the STATE.json ``platforms`` key the declaring provider
    writes its campaigns under — the key this reader matches against, so a
    declaration under any other name simply never applies to anything.

    ``evidence`` names the first-party source the claim rests on (the
    platform's own API reference), the date it was read and the sentence it
    rests on, so a reviewer can check "does this platform really accept a
    monthly budget?" without re-deriving it.
    """

    platform: str
    evidence: Evidence


_SUPPORTED: dict[str, MonthlyBudgetSupport] = {}


def _require_text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"monthly budget support needs a non-empty {what}")
    return value


def _validate(support: MonthlyBudgetSupport) -> None:
    """Refuse a declaration that names no platform or no source."""
    _require_text(support.platform, "platform")
    evidence = support.evidence
    if not isinstance(evidence, Evidence):
        raise ValueError(
            f"monthly budget support for {support.platform!r} needs an "
            f"Evidence record naming the first-party source it rests on"
        )
    _require_text(evidence.source, "evidence.source")
    _require_text(evidence.quote, "evidence.quote")
    retrieved = _require_text(evidence.retrieved, "evidence.retrieved")
    try:
        date.fromisoformat(retrieved)
    except ValueError as exc:
        raise ValueError(
            f"monthly budget support for {support.platform!r} needs "
            f"evidence.retrieved as an ISO date (YYYY-MM-DD), got "
            f"{retrieved!r}"
        ) from exc


def register_monthly_budget_support(support: MonthlyBudgetSupport) -> None:
    """Declare that a platform's campaigns carry a monthly budget. First wins.

    The hook a provider, bridge or plugin uses to say that
    :attr:`~mureo.context.models.CampaignSnapshot.monthly_budget` means
    something on its platform. It hangs off ordinary module import — the same
    registry pattern as
    :func:`~mureo.policy.learning_rules.register_platform_learning_rules` — so
    no new entry-point group is involved.

    Raises :class:`ValueError` for a declaration with no platform key or no
    complete :class:`~mureo.policy.learning_rules.Evidence` record, so a
    plugin author sees the boundary at registration rather than shipping an
    unsourced claim about a platform's API.
    """
    _validate(support)
    existing = _SUPPORTED.get(support.platform)
    if existing is not None:
        warnings.warn(
            f"monthly budget support for {support.platform!r} is already "
            f"declared (source {existing.evidence.source!r}); the later "
            f"declaration is dropped (first wins)",
            MonthlyBudgetSupportWarning,
            stacklevel=2,
        )
        return
    _SUPPORTED[support.platform] = support


def reset_monthly_budget_support() -> None:
    """Restore the built-in registry (empty). Intended for tests."""
    _SUPPORTED.clear()


def supports_monthly_budget(platform: str) -> bool:
    """Has ``platform`` declared that its campaigns carry a monthly budget?"""
    return platform in _SUPPORTED


def platforms_with_monthly_budget() -> tuple[str, ...]:
    """Every platform key that declared the concept, sorted."""
    return tuple(sorted(_SUPPORTED))


def _readable_amount(value: object) -> float | None:
    """A campaign's monthly budget as a figure, or ``None`` when it is not one.

    STATE.json's schema says number, so anything else — a string, a bool, a
    list, a negative or a non-finite float — is treated as a figure mureo does
    not have, not as one it can repair. A gap must degrade to "this set is
    incomplete", never to a coerced number nobody wrote.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    amount = float(value)
    if not math.isfinite(amount) or amount < 0:
        return None
    return amount


def _platform_subtotal(state: PlatformState) -> float | None:
    """One platform's configured monthly spend, or ``None`` if unvouchable."""
    not_collected = getattr(state, "not_collected", None)
    if not_collected:
        return None
    campaigns = state.campaigns
    if not campaigns:
        return None
    subtotal = 0.0
    for campaign in campaigns:
        amount = _readable_amount(getattr(campaign, "monthly_budget", None))
        if amount is None:
            return None
        subtotal += amount
    return subtotal


def platform_configured_monthly_budget(
    platforms: Mapping[str, PlatformState] | None,
) -> MonthlyBudget:
    """Sum the monthly budgets the platforms are configured with.

    Only platforms that declared the concept
    (:func:`register_monthly_budget_support`) AND are present in ``platforms``
    are considered; everything else contributes nothing and is not counted as
    a gap. Returns:

    - a :data:`~mureo.context.monthly_budget.SOURCE_PLATFORM_CONFIGURED_SUM`
      budget, whose ``per_platform`` carries each platform's subtotal, when
      every considered platform's campaign set is complete;
    - "not set" naming every unusable platform in
      :attr:`~mureo.context.monthly_budget.MonthlyBudget.incomplete_platforms`
      when any one of them is not — the partial sum is never returned;
    - a plain "not set" when no declaring platform is present at all.

    Never raises: this is a read path, and a document mureo cannot read is
    reported as a set it cannot vouch for.
    """
    if not platforms:
        return MonthlyBudget()

    subtotals: dict[str, float] = {}
    incomplete: list[str] = []
    for platform in sorted(_SUPPORTED):
        state = platforms.get(platform)
        if state is None:
            continue
        subtotal = _platform_subtotal(state)
        if subtotal is None:
            incomplete.append(platform)
            continue
        subtotals[platform] = subtotal

    if incomplete:
        logger.debug(
            "monthly budget: no platform sum taken; incomplete campaign set " "for %s",
            ", ".join(incomplete),
        )
        return MonthlyBudget(incomplete_platforms=tuple(incomplete))
    if not subtotals:
        return MonthlyBudget()
    return MonthlyBudget(
        total=sum(subtotals.values()),
        per_platform=MappingProxyType(subtotals),
        source=SOURCE_PLATFORM_CONFIGURED_SUM,
    )


__all__ = [
    "MonthlyBudgetSupport",
    "MonthlyBudgetSupportWarning",
    "platform_configured_monthly_budget",
    "platforms_with_monthly_budget",
    "register_monthly_budget_support",
    "reset_monthly_budget_support",
    "supports_monthly_budget",
]
