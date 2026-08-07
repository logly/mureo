"""Per-platform learning-period rules, and where each one comes from (#548).

Every automated-bidding system has a learning period, and a change that
restarts it costs days of delivery. mureo used to carry that as prose in
``_mureo-shared/SKILL.md`` — "warn before changes that reset the learning
period" — which is advice to a model, not a check. This module is the data
half of the check: what *counts* as a reset-triggering change on each
platform, and how mureo can observe whether a campaign is in a learning
period right now.

Evidence, not folklore
----------------------
"Which changes reset learning" is a per-platform fact that changes over
time, so every entry here carries an :class:`Evidence` record naming the
**first-party** source it was read from (platform help / API reference), the
date it was retrieved, and the sentence it rests on. Nothing is listed on
recollection: where mureo has no first-party enumeration, the platform is
marked ``triggers_are_enumerated=False`` and every mutation on it is
classified :data:`ResetRisk.UNKNOWN` rather than guessed either way. A false
"this resets nothing" is worse than no answer, because it turns a missing
warning into implied approval.

The same discipline applies to the *state* read. A platform mureo cannot ask
"are you learning right now?" reports :data:`LearningState.UNREPORTABLE`, and
a platform it can ask but has no observation for reports
:data:`LearningState.UNKNOWN`. Neither is ``STEADY``.

Where mureo reads the state from
--------------------------------
A :class:`~mureo.core.policy.PolicyGate` runs on every tool call and must be
pure and fast, so the pre-flight cannot make a network call to ask the
platform. It reads what mureo already has locally: the campaign snapshot in
STATE.json, written by the operator's sync/daily-check workflow through
``mureo_state_upsert_campaign``. :class:`StateObservation` names the
``bidding_details`` key that carries the platform's own status string and how
to read its values.

Plugins and bridges
-------------------
Third-party platforms register their own rules through
:func:`register_platform_learning_rules`, the same shape the built-ins use
and the same registry pattern as
:func:`mureo.policy.declarations.register_budget_declaration`. mureo core
ships rules only for the platforms it can source first-party evidence for;
everything else is honestly unknown until its plugin says otherwise.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:  # pragma: no cover - exercised on 3.10 only

    class StrEnum(str, Enum):
        """Minimal 3.10 shim, mirroring
        :class:`mureo.core.providers.capabilities.StrEnum`."""

        def __str__(self) -> str:
            return str(self._value_)


class LearningState(StrEnum):
    """What mureo knows about a campaign's current learning period."""

    #: The platform (or mureo's local snapshot of it) reports an active
    #: learning / adjustment period.
    LEARNING = "learning"
    #: The platform reports a non-learning status.
    STEADY = "steady"
    #: mureo *can* read this platform's learning state, but has no
    #: observation for this campaign. Not "safe".
    UNKNOWN = "unknown"
    #: mureo has no way to read this platform's learning state at all.
    #: Not "safe" either — see the module docstring.
    UNREPORTABLE = "unreportable"


class ResetRisk(StrEnum):
    """Whether the pending change is in the reset-triggering class."""

    RESETS = "resets"
    NO_RESET = "no_reset"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Evidence:
    """Where a rule in this module comes from.

    ``source`` is a first-party URL (the platform's own API reference or help
    centre). ``retrieved`` is the ISO date it was read. ``quote`` is the
    sentence the rule rests on, kept verbatim so a reviewer can check the
    rule against the source without re-deriving it.
    """

    source: str
    retrieved: str
    quote: str


@dataclass(frozen=True)
class ResetTrigger:
    """One class of change that restarts a platform's learning period.

    ``tools`` are the exact mureo tool names that perform the change.
    ``requires_arguments`` narrows the match to calls that actually carry the
    field: ``google_ads_campaigns_update`` resets learning when it changes the
    bidding strategy and does not when it only renames the campaign, and the
    two are the same tool. ``argument_equals`` narrows further to a specific
    value (re-enabling a campaign restarts learning; pausing it does not).
    """

    change_class: str
    tools: frozenset[str]
    evidence: Evidence
    requires_arguments: frozenset[str] = frozenset()
    argument_equals: tuple[str, frozenset[str]] | None = None

    def matches(self, tool_name: str, arguments: dict[str, object]) -> bool:
        """Does this trigger apply to ``tool_name(arguments)``?"""
        if tool_name not in self.tools:
            return False
        if self.requires_arguments and not any(
            arguments.get(key) is not None for key in self.requires_arguments
        ):
            return False
        if self.argument_equals is not None:
            key, accepted = self.argument_equals
            value = arguments.get(key)
            if not isinstance(value, str) or value.upper() not in accepted:
                return False
        return True


@dataclass(frozen=True)
class StateObservation:
    """How mureo reads one platform's learning state out of STATE.json.

    ``snapshot_key`` is the key inside ``CampaignSnapshot.bidding_details``
    that carries the platform's own status string. The three value sets are
    matched case-insensitively in order: learning, unreportable, unknown;
    anything else that is a non-empty string counts as steady.
    """

    snapshot_key: str
    learning_values: frozenset[str]
    evidence: Evidence
    unreportable_values: frozenset[str] = frozenset()
    unknown_values: frozenset[str] = frozenset()
    learning_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlatformLearningRules:
    """Everything mureo knows about one platform's learning period.

    ``tool_prefix`` is how a tool name is attributed to this platform.
    ``triggers_are_enumerated`` is the honesty switch: ``True`` means the
    trigger list below is complete enough that a mutation *absent* from it can
    be reported as :data:`ResetRisk.NO_RESET`; ``False`` means mureo has no
    first-party enumeration for this platform, so every mutation on it is
    :data:`ResetRisk.UNKNOWN`.
    """

    platform: str
    tool_prefix: str
    observation: StateObservation | None
    triggers: tuple[ResetTrigger, ...]
    triggers_are_enumerated: bool
    notes: str
    #: Named when the platform HAS a learning-state concept mureo cannot read.
    #: Surfaced verbatim so "unreportable" says *why*, and names the field a
    #: future contributor would have to plumb through.
    unreportable_detail: str = ""
    unreportable_evidence: Evidence | None = field(default=None)


# ---------------------------------------------------------------------------
# Google Ads
# ---------------------------------------------------------------------------

#: Google publishes the reset causes as an ENUM, not as prose: every
#: ``LEARNING_*`` member of ``BiddingStrategySystemStatus`` names the change
#: class that caused the strategy to re-enter learning. That makes the enum
#: both the state read AND the trigger list, from one first-party source —
#: and the exact enum ships inside the ``google-ads`` client this repo already
#: depends on (``google.ads.googleads.v23.enums.types
#: .bidding_strategy_system_status``), so the quotes below are checkable
#: offline.
_GOOGLE_ENUM_URL = (
    "https://developers.google.com/google-ads/api/reference/rpc/v23/"
    "BiddingStrategySystemStatusEnum.BiddingStrategySystemStatus"
)
_GOOGLE_RETRIEVED = "2026-08-07"


def _google_evidence(quote: str) -> Evidence:
    return Evidence(source=_GOOGLE_ENUM_URL, retrieved=_GOOGLE_RETRIEVED, quote=quote)


GOOGLE_ADS_RULES = PlatformLearningRules(
    platform="google_ads",
    tool_prefix="google_ads_",
    observation=StateObservation(
        snapshot_key="bidding_strategy_system_status",
        learning_values=frozenset({"MULTIPLE_LEARNING"}),
        learning_prefixes=("LEARNING_",),
        unreportable_values=frozenset({"UNAVAILABLE"}),
        unknown_values=frozenset({"UNKNOWN", "UNSPECIFIED", ""}),
        evidence=_google_evidence(
            "UNAVAILABLE: This bid strategy currently does not support status "
            "reporting."
        ),
    ),
    triggers=(
        ResetTrigger(
            change_class="bidding_strategy_change",
            tools=frozenset({"google_ads_campaigns_update"}),
            requires_arguments=frozenset({"bidding_strategy"}),
            evidence=_google_evidence(
                "LEARNING_SETTING_CHANGE: The bid strategy is learning because "
                "of a recent setting change."
            ),
        ),
        ResetTrigger(
            change_class="budget_change",
            tools=frozenset({"google_ads_budget_update"}),
            evidence=_google_evidence(
                "LEARNING_BUDGET_CHANGE: The bid strategy is learning because "
                "of a recent budget change."
            ),
        ),
        ResetTrigger(
            change_class="composition_change",
            tools=frozenset(
                {
                    "google_ads_keywords_add",
                    "google_ads_keywords_remove",
                    "google_ads_ad_groups_create",
                }
            ),
            evidence=_google_evidence(
                "LEARNING_COMPOSITION_CHANGE: The bid strategy is learning "
                "because of recent change in number of campaigns, ad groups or "
                "keywords attached to it."
            ),
        ),
        ResetTrigger(
            change_class="conversion_settings_change",
            tools=frozenset(
                {
                    "google_ads_conversions_create",
                    "google_ads_conversions_update",
                    "google_ads_conversions_remove",
                }
            ),
            evidence=_google_evidence(
                "LEARNING_CONVERSION_SETTING_CHANGE: The bid strategy depends "
                "on conversion reporting and the customer recently changed "
                "their conversion settings."
            ),
        ),
        ResetTrigger(
            change_class="reactivation",
            tools=frozenset({"google_ads_campaigns_update_status"}),
            argument_equals=("status", frozenset({"ENABLED"})),
            evidence=_google_evidence(
                "LEARNING_NEW: The bid strategy is learning because it has been "
                "recently created or recently reactivated."
            ),
        ),
    ),
    triggers_are_enumerated=True,
    notes=(
        "Trigger classes are Google's own LEARNING_* enum members, mapped to "
        "the mureo tools that perform each change. Two limits are deliberate "
        "and not papered over: (1) LEARNING_SETTING_CHANGE says 'a recent "
        "setting change' without enumerating which settings, so mureo maps it "
        "only to the bidding-strategy field it can see in a tool argument — a "
        "campaign setting changed through another tool is not classified; "
        "(2) LEARNING_BUDGET_CHANGE names no magnitude threshold, so mureo "
        "applies none (the '>20%' figure the old SKILL prose used has no "
        "first-party source). Only campaigns on an automated bid strategy have "
        "a bid strategy to reset; mureo does not consult the campaign's "
        "strategy type before classifying, so a budget change on a manual-CPC "
        "campaign is reported as reset-triggering when it is not."
    ),
)


# ---------------------------------------------------------------------------
# Meta Ads
# ---------------------------------------------------------------------------

_META_LEARNING_STAGE_URL = (
    "https://developers.facebook.com/docs/marketing-api/reference/"
    "ad-campaign-learning-stage-info/"
)

META_ADS_RULES = PlatformLearningRules(
    platform="meta_ads",
    tool_prefix="meta_ads_",
    # Meta exposes the state, mureo does not read it — see below.
    observation=None,
    triggers=(),
    triggers_are_enumerated=False,
    unreportable_detail=(
        "Meta reports an ad set's learning phase in the Marketing API field "
        "learning_stage_info (status: LEARNING / SUCCESS / FAIL). mureo does "
        "not read it: the field lives on the AD SET node while mureo's "
        "STATE.json snapshot is campaign-level, and mureo's Meta client does "
        "not request the field today. So mureo reports 'unreportable' rather "
        "than implying a Meta ad set is out of learning."
    ),
    unreportable_evidence=Evidence(
        source=_META_LEARNING_STAGE_URL,
        retrieved="2026-08-07",
        quote=(
            "status: Learning Phase progress for the ad set. Values: LEARNING "
            "- The ad set is still learning. SUCCESS - The ad set exited the "
            "learning phase. FAIL - The ad set isn't generating enough results "
            "to exit the learning phase."
        ),
    ),
    notes=(
        "Meta's own reference states that 'Significant edits cause ad sets to "
        "reenter the learning phase' and exposes last_sig_edit_ts, but does "
        "not enumerate which edits are significant, and the Business Help "
        "Centre article that does is not machine-readable. mureo therefore "
        "ships NO Meta trigger list and classifies every Meta mutation as "
        "unknown rather than inventing one. The same reference documents that "
        "learning_stage_info is returned only for active ad sets, never for "
        "Dynamic Creative ad sets, and not for every ad account — so even a "
        "future reader would have honest gaps to report."
    ),
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BUILTIN_RULES: tuple[PlatformLearningRules, ...] = (GOOGLE_ADS_RULES, META_ADS_RULES)

_RULES: dict[str, PlatformLearningRules] = {r.platform: r for r in _BUILTIN_RULES}


def register_platform_learning_rules(rules: PlatformLearningRules) -> None:
    """Register (or replace) one platform's learning rules.

    The hook a bridge or plugin uses to advertise learning-period support for
    a platform mureo core knows nothing about, mirroring
    :func:`mureo.policy.declarations.register_budget_declaration`. A plugin
    that registers rules with ``triggers_are_enumerated=False`` still helps:
    its mutations become "unknown" for a *named* platform instead of an
    anonymous one.
    """
    if not rules.platform:
        raise ValueError("platform learning rules need a non-empty platform key")
    if not rules.tool_prefix:
        raise ValueError("platform learning rules need a non-empty tool_prefix")
    _RULES[rules.platform] = rules


def reset_platform_learning_rules() -> None:
    """Restore the built-in registry. Intended for tests."""
    _RULES.clear()
    _RULES.update({r.platform: r for r in _BUILTIN_RULES})


def platform_learning_rules(platform: str) -> PlatformLearningRules | None:
    """Return the registered rules for ``platform``, or ``None``."""
    return _RULES.get(platform)


def rules_for_tool(tool_name: str) -> PlatformLearningRules | None:
    """Return the rules whose ``tool_prefix`` claims ``tool_name``.

    Longest prefix wins, so a plugin registering a more specific prefix than
    an existing one is not shadowed by it.
    """
    best: PlatformLearningRules | None = None
    for rules in _RULES.values():
        if not tool_name.startswith(rules.tool_prefix):
            continue
        if best is None or len(rules.tool_prefix) > len(best.tool_prefix):
            best = rules
    return best


def registered_platforms() -> tuple[str, ...]:
    """Every platform key with registered learning rules, sorted."""
    return tuple(sorted(_RULES))


__all__ = [
    "Evidence",
    "GOOGLE_ADS_RULES",
    "LearningState",
    "META_ADS_RULES",
    "PlatformLearningRules",
    "ResetRisk",
    "ResetTrigger",
    "StateObservation",
    "platform_learning_rules",
    "register_platform_learning_rules",
    "registered_platforms",
    "reset_platform_learning_rules",
    "rules_for_tool",
]
