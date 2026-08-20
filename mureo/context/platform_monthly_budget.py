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
level up. They are returned as :class:`IncompletePlatform` records in
:attr:`~mureo.context.monthly_budget.MonthlyBudget.incomplete_platforms` so
the caller states the gap instead of rendering a smaller number — the same
rule #638 established for stale rollups, applied to a total.

Each record says WHICH gap, because the fixes differ and only one of them is
permanent. A platform that declared the concept and carries no figure on any
campaign (:data:`REASON_NO_FIGURES`) is a declaration that does not match its
platform: this rung is off for every account there until the plugin is fixed,
and first-wins means no later registration can take the slot back. That is
the shape a mistaken declaration makes, and it is a subtraction rather than a
fabrication — a wrong declaration can only ever remove an answer, never
invent a figure, because every number comes from STATE.json. The remaining
reasons are ordinary and recoverable. Nothing here logs any of it: the record
IS the notification, it reaches whoever asked, and a log line saying the same
thing would be a second account of one fact.

Whether a paused or removed campaign "counts" is deliberately not decided
here: status vocabularies are per-platform, and mureo does not read one
platform's words with another's dictionary. Every campaign the document holds
for a declaring platform contributes, and every one of them must have a
figure.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

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


#: The platform holds campaigns and NOT ONE of them carries a monthly
#: budget. The shape a mistaken declaration makes: nothing will ever arrive,
#: so this rung stays off for every account on that platform until the
#: declaration is corrected — and first-wins means no later plugin can take
#: the slot back. Distinguished from :data:`REASON_MISSING_FIGURES` for
#: exactly that reason: one is a wiring fault, the other is a sync behind.
REASON_NO_FIGURES: Final = "no_monthly_budgets"
#: Some campaigns carry a monthly budget and some do not — a sync that has
#: not covered the whole account yet. Re-running the collection fixes it.
REASON_MISSING_FIGURES: Final = "missing_monthly_budgets"
#: mureo holds no campaigns at all for this platform. Nothing to sum, and
#: ``0`` would be a confident lie.
REASON_NO_CAMPAIGNS: Final = "no_campaigns"
#: The platform's last collection failed (#638). The set may be stale or
#: short; the figures it does hold are not wrong, they are older than they
#: should be.
REASON_NOT_COLLECTED: Final = "not_collected"

#: One operator-readable line per reason, ``{platform}`` substituted. Held
#: here rather than in each caller so the dashboard, the CLI and a skill
#: cannot give three different accounts of one fact — the same "one rule,
#: two surfaces" discipline :mod:`mureo.context.observations` follows.
_REASON_DETAIL: Final[dict[str, str]] = {
    REASON_NO_FIGURES: (
        "{platform}: declared as having monthly campaign budgets, but not one "
        "of its campaigns carries one — this rung stays off until the platform "
        "plugin writes them (or withdraws the declaration)."
    ),
    REASON_MISSING_FIGURES: (
        "{platform}: some campaigns have no monthly budget mureo can read, so "
        "the total would understate the account — re-run the platform sync."
    ),
    REASON_NO_CAMPAIGNS: (
        "{platform}: mureo holds no campaigns for it, so there is nothing to "
        "sum — re-run the platform sync."
    ),
    REASON_NOT_COLLECTED: (
        "{platform}: its last collection failed, so the campaign set may be "
        "stale or incomplete — see the platform's not_collected note."
    ),
}

#: What an unrecognised reason renders as. A read path states what it knows
#: rather than raising or, worse, saying nothing at all.
_UNKNOWN_DETAIL: Final = (
    "{platform}: mureo cannot vouch for its campaign set, so no monthly total "
    "was taken from it."
)


class MonthlyBudgetSupportWarning(UserWarning):
    """Emitted when a declaration is dropped because the slot is taken.

    A :class:`UserWarning` subclass so operators can fail closed with
    ``warnings.filterwarnings("error", category=MonthlyBudgetSupportWarning)``,
    the same opt-in
    :class:`~mureo.policy.platform_model.PlatformModelWarning` offers.
    """


@dataclass(frozen=True)
class IncompletePlatform:
    """A declaring platform whose campaign set mureo will not sum, and why.

    The ``why`` is load-bearing rather than decoration. The fixes differ —
    a wrong declaration needs the plugin author, a partial sync needs
    ``/sync-state``, a failed collection needs credentials — and an operator
    who only sees "no monthly budget available" cannot tell which they have.
    It travels in the answer itself so no surface has to read a debug log to
    explain a missing figure, and :attr:`detail` is the one wording every
    surface uses.
    """

    platform: str
    reason: str

    @property
    def detail(self) -> str:
        """One operator-readable line naming the platform and the next step."""
        template = _REASON_DETAIL.get(self.reason, _UNKNOWN_DETAIL)
        return template.format(platform=self.platform)


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


def _platform_subtotal(state: PlatformState) -> float | str:
    """One platform's configured monthly spend, or the reason there is none.

    Returns a ``float`` for a set mureo can vouch for, and one of the
    ``REASON_*`` codes otherwise. Two codes for one shape of gap on purpose:
    "not one campaign has a figure" is what a mistaken declaration looks
    like, and "some do, some do not" is a sync that is behind. They need
    different fixes, so they are not the same answer.
    """
    if getattr(state, "not_collected", None):
        return REASON_NOT_COLLECTED
    campaigns = state.campaigns
    if not campaigns:
        return REASON_NO_CAMPAIGNS
    subtotal = 0.0
    readable = 0
    for campaign in campaigns:
        amount = _readable_amount(getattr(campaign, "monthly_budget", None))
        if amount is not None:
            readable += 1
            subtotal += amount
    if readable == 0:
        return REASON_NO_FIGURES
    if readable < len(campaigns):
        return REASON_MISSING_FIGURES
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
    incomplete: list[IncompletePlatform] = []
    for platform in sorted(_SUPPORTED):
        state = platforms.get(platform)
        if state is None:
            continue
        subtotal = _platform_subtotal(state)
        if isinstance(subtotal, str):
            incomplete.append(IncompletePlatform(platform=platform, reason=subtotal))
            continue
        subtotals[platform] = subtotal

    if incomplete:
        # No log line here: the records ARE the notification, and they reach
        # the operator through whatever surface asked. A debug log saying the
        # same thing would be a second account of one fact.
        return MonthlyBudget(incomplete_platforms=tuple(incomplete))
    if not subtotals:
        return MonthlyBudget()
    return MonthlyBudget(
        total=sum(subtotals.values()),
        configured_per_platform=MappingProxyType(subtotals),
        source=SOURCE_PLATFORM_CONFIGURED_SUM,
    )


__all__ = [
    "REASON_MISSING_FIGURES",
    "REASON_NOT_COLLECTED",
    "REASON_NO_CAMPAIGNS",
    "REASON_NO_FIGURES",
    "IncompletePlatform",
    "MonthlyBudgetSupport",
    "MonthlyBudgetSupportWarning",
    "platform_configured_monthly_budget",
    "platforms_with_monthly_budget",
    "register_monthly_budget_support",
    "reset_monthly_budget_support",
    "supports_monthly_budget",
]
