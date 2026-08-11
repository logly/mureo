"""The learning-period reset pre-flight check (#548).

The decision half of the feature; the per-platform facts and their sources
live in :mod:`mureo.policy.learning_rules`. Three questions, answered
separately so a missing answer to one cannot fake an answer to another:

1. **Is the pending change reset-triggering?** — :func:`classify_change`,
   pure, table-driven, argument-aware (a campaign rename and a bid-strategy
   switch are the same tool).
2. **Is the campaign in a learning period right now?** —
   :func:`read_learning_state`, reading the platform's own status string out
   of the STATE.json campaign snapshot. A gate runs on every tool call and
   must not do network I/O, so this is deliberately a local read; when there
   is nothing local to read it answers UNKNOWN, never STEADY.
3. **Does the operator's STRATEGY.md refuse this?** —
   :func:`learning_reset_denial`, which the one built-in
   :class:`~mureo.policy.strategy_gate.StrategyPolicyGate` turns into a real
   pre-dispatch refusal.

What is enforced and what is only surfaced
------------------------------------------
MCP has no interposed confirmation step: mureo either runs a tool call or
refuses it. So the three surfaces differ in strength, and the difference is
deliberate rather than glossed:

- **Refusal (hard).** Only when the operator wrote ``block_learning_resets``
  or ``block_learning_resets_during_incident`` in STRATEGY.md
  ``## Guardrails``. This runs before dispatch and blocks the call. The gate
  stays fail-open by default: with no such rule, nothing is refused.
- **Pre-flight tool (before the change).** ``mureo_learning_reset_preflight``
  answers all three questions for a change the agent is *about* to make, so
  the operator's confirmation step has the facts. It is a tool the agent has
  to call — the SKILL requires it — so it is as strong as the agent's
  compliance, which is exactly the weakness that made prose insufficient.
- **Notice (after dispatch).** :func:`preflight_notice` is appended by the
  dispatcher to the result of a reset-triggering call, so the *next* change
  in a troubleshooting sequence is made with the reset already visible. This
  is after the fact for the call it rides on, and is not a substitute for the
  first two.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mureo.core.strategy_reminder import is_mutating_builtin_tool
from mureo.core.tool_names import is_read_only_tool_name
from mureo.policy.learning_rules import (
    Evidence,
    LearningState,
    PlatformLearningRules,
    ResetRisk,
    platform_learning_rules,
    rules_for_tool,
)

logger = logging.getLogger(__name__)

#: Tool-name prefixes mureo owns. For these, the pinned mutating-tool
#: classifier in :mod:`mureo.core.strategy_reminder` is authoritative, so a
#: name it does not recognise is a read rather than an unknown mutation.
_BUILTIN_PREFIXES = ("google_ads_", "meta_ads_", "search_console_", "mureo_")

#: The argument key a campaign-scoped mutation carries. Tools keyed on
#: something else (``google_ads_budget_update`` takes a ``budget_id``) yield
#: no campaign, hence an UNKNOWN learning state — which is the honest answer,
#: not a defect to be papered over with a guess.
_CAMPAIGN_ID_KEY = "campaign_id"


@dataclass(frozen=True)
class LearningReading:
    """What mureo knows about one campaign's learning period right now."""

    state: LearningState
    detail: str
    source: str
    evidence: Evidence | None = None

    def is_known_not_learning(self) -> bool:
        """True only for a positively observed non-learning state.

        UNKNOWN and UNREPORTABLE are both False on purpose: a caller asking
        "is it safe to stack another reset?" must not read absence of evidence
        as evidence of absence.
        """
        return self.state is LearningState.STEADY

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": str(self.state),
            "detail": self.detail,
            "source": self.source,
            "evidence": _evidence_dict(self.evidence),
        }


@dataclass(frozen=True)
class ChangeAssessment:
    """Whether the pending change is in the reset-triggering class."""

    platform: str
    risk: ResetRisk
    change_class: str
    detail: str
    evidence: Evidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk": str(self.risk),
            "change_class": self.change_class,
            "detail": self.detail,
            "evidence": _evidence_dict(self.evidence),
        }


@dataclass(frozen=True)
class LearningPreflight:
    """The full pre-flight answer for one pending tool call."""

    tool_name: str
    platform: str
    campaign_id: str | None
    change: ChangeAssessment
    learning: LearningReading

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "platform": self.platform,
            "campaign_id": self.campaign_id,
            "reset_risk": str(self.change.risk),
            "change_class": self.change.change_class,
            "reset_verdict": self.change.to_dict(),
            "learning_state": self.learning.to_dict(),
        }


def _evidence_dict(evidence: Evidence | None) -> dict[str, str] | None:
    if evidence is None:
        return None
    return {
        "source": evidence.source,
        "retrieved": evidence.retrieved,
        "quote": evidence.quote,
    }


# ---------------------------------------------------------------------------
# (b) Is the pending change reset-triggering?
# ---------------------------------------------------------------------------


def _is_mutation(tool_name: str) -> bool:
    """Does ``tool_name`` change platform state?

    Reads are the one answer that needs no per-platform evidence: a read
    cannot restart a learning period on any platform. Getting this right is
    what keeps the check quiet — a check that fires on ``campaigns_list`` is
    a check that gets ignored.
    """
    if is_mutating_builtin_tool(tool_name):
        return True
    if tool_name.startswith(_BUILTIN_PREFIXES):
        return False
    return not is_read_only_tool_name(tool_name)


def classify_change(tool_name: str, arguments: dict[str, Any]) -> ChangeAssessment:
    """Classify ``tool_name(arguments)`` against the per-platform rules.

    ``NO_RESET`` is returned only for a read, or for a mutation on a platform
    whose trigger list mureo has first-party evidence is enumerable
    (``triggers_are_enumerated``). Everything else is ``UNKNOWN`` — mureo does
    not guess in either direction.
    """
    rules = rules_for_tool(tool_name)
    platform = rules.platform if rules is not None else ""
    if not _is_mutation(tool_name):
        return ChangeAssessment(
            platform=platform,
            risk=ResetRisk.NO_RESET,
            change_class="",
            detail="Read-only call; it cannot restart a learning period.",
        )
    if rules is not None:
        for trigger in rules.triggers:
            if trigger.matches(tool_name, arguments):
                return ChangeAssessment(
                    platform=platform,
                    risk=ResetRisk.RESETS,
                    change_class=trigger.change_class,
                    # The caveats travel with the RESETS verdict, not only
                    # with NO_RESET. The operator who is *blocked* by a false
                    # positive is the one person who needs to know the
                    # classification has known blind spots; putting the note
                    # only on the quiet path is honesty filed where nobody
                    # reads it.
                    detail=(
                        f"{tool_name} is a {trigger.change_class} on "
                        f"{platform}, which restarts the learning period. "
                        f"Known limits of this classification: {rules.notes}"
                    ),
                    evidence=trigger.evidence,
                )
        if rules.triggers_are_enumerated:
            return ChangeAssessment(
                platform=platform,
                risk=ResetRisk.NO_RESET,
                change_class="",
                detail=(
                    f"{tool_name} is not in mureo's evidence-backed list of "
                    f"{platform} reset-triggering changes. {rules.notes}"
                ),
            )
    return _unknown_change(tool_name, platform, rules)


def _unknown_change(
    tool_name: str, platform: str, rules: PlatformLearningRules | None
) -> ChangeAssessment:
    """The honest non-answer for a mutation mureo cannot classify."""
    if rules is None:
        detail = (
            f"{tool_name} belongs to a platform mureo has no learning-period "
            f"rules for, so mureo cannot say whether it restarts a learning "
            f"period. This is 'unknown', not 'safe'. A plugin or bridge can "
            f"register rules via "
            f"mureo.policy.learning_rules.register_platform_learning_rules."
        )
    else:
        detail = (
            f"mureo has no first-party enumeration of {platform}'s "
            f"reset-triggering changes, so {tool_name} is unclassified rather "
            f"than assumed safe. {rules.notes}"
        )
    return ChangeAssessment(
        platform=platform,
        risk=ResetRisk.UNKNOWN,
        change_class="",
        detail=detail,
        evidence=rules.unreportable_evidence if rules is not None else None,
    )


# ---------------------------------------------------------------------------
# (a) Is the campaign in a learning period right now?
# ---------------------------------------------------------------------------


def _snapshot_status(
    platform: str, campaign_id: str, doc: Any, snapshot_key: str
) -> str | None:
    """The platform's own learning-status string from the STATE.json snapshot."""
    platforms = getattr(doc, "platforms", None) or {}
    entry = platforms.get(platform)
    campaigns = tuple(getattr(entry, "campaigns", ()) if entry is not None else ())
    if not campaigns:
        campaigns = tuple(getattr(doc, "campaigns", ()) or ())
    for snapshot in campaigns:
        if str(getattr(snapshot, "campaign_id", "")) != str(campaign_id):
            continue
        details = getattr(snapshot, "bidding_details", None)
        if isinstance(details, dict):
            value = details.get(snapshot_key)
            if isinstance(value, str):
                return value
        return None
    return None


def read_learning_state(
    platform: str, campaign_id: str | None, doc: Any
) -> LearningReading:
    """Read ``platform``/``campaign_id``'s current learning state from ``doc``.

    ``doc`` is a :class:`~mureo.context.models.StateDocument`. Local by
    design — see the module docstring. Never returns STEADY on absence.
    """
    rules = platform_learning_rules(platform) if platform else None
    if rules is None or rules.observation is None:
        return _unreportable(platform, rules)
    observation = rules.observation
    source = (
        f"STATE.json platforms.{platform}.campaigns[].bidding_details."
        f"{observation.snapshot_key}"
    )
    if not campaign_id:
        return LearningReading(
            state=LearningState.UNKNOWN,
            detail=(
                "This call names no campaign_id, so mureo cannot look up the "
                "campaign's learning state. Unknown, not steady."
            ),
            source=source,
            evidence=observation.evidence,
        )
    raw = _snapshot_status(platform, campaign_id, doc, observation.snapshot_key)
    if raw is None or not raw.strip():
        return LearningReading(
            state=LearningState.UNKNOWN,
            detail=(
                f"No {observation.snapshot_key} recorded for campaign "
                f"{campaign_id} in STATE.json. Refresh it (sync-state / "
                f"daily-check) to get a real answer; until then this is "
                f"unknown, not steady."
            ),
            source=source,
            evidence=observation.evidence,
        )
    return _classify_status(raw, observation, campaign_id, source)


def _classify_status(
    raw: str, observation: Any, campaign_id: str, source: str
) -> LearningReading:
    value = raw.strip().upper()
    if value in observation.unknown_values:
        state = LearningState.UNKNOWN
    elif value in observation.unreportable_values:
        state = LearningState.UNREPORTABLE
    elif value in observation.learning_values or value.startswith(
        observation.learning_prefixes or ()
    ):
        state = LearningState.LEARNING
    else:
        state = LearningState.STEADY
    return LearningReading(
        state=state,
        detail=(
            f"Campaign {campaign_id} last recorded "
            f"{observation.snapshot_key}={raw.strip()} in STATE.json."
        ),
        source=source,
        evidence=observation.evidence,
    )


def _unreportable(
    platform: str, rules: PlatformLearningRules | None
) -> LearningReading:
    if rules is not None and rules.unreportable_detail:
        detail = rules.unreportable_detail
        evidence = rules.unreportable_evidence
    else:
        detail = (
            f"mureo has no way to read the current learning state for "
            f"{platform or 'this platform'}. Treat this as no answer, not as "
            f"'not learning'."
        )
        evidence = None
    return LearningReading(
        state=LearningState.UNREPORTABLE,
        detail=detail,
        source="mureo.policy.learning_rules",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def campaign_id_from(arguments: dict[str, Any]) -> str | None:
    """The campaign this call targets, when its arguments name one."""
    value = arguments.get(_CAMPAIGN_ID_KEY)
    return str(value) if isinstance(value, (str, int)) and str(value) else None


def build_preflight(
    tool_name: str,
    arguments: dict[str, Any],
    doc: Any,
    campaign_id: str | None = None,
) -> LearningPreflight:
    """Answer all three pre-flight questions for one pending call. Pure."""
    change = classify_change(tool_name, arguments)
    resolved = campaign_id or campaign_id_from(arguments)
    learning = read_learning_state(change.platform, resolved, doc)
    return LearningPreflight(
        tool_name=tool_name,
        platform=change.platform,
        campaign_id=resolved,
        change=change,
        learning=learning,
    )


# ---------------------------------------------------------------------------
# (d) The hard refusal, and the soft notice
# ---------------------------------------------------------------------------

_DENY_PREAMBLE = (
    "Refusing '{tool}': mureo classifies it as a learning-period reset "
    "({change_class}) on {platform}. {change_detail}"
)

_DENY_EVIDENCE = ' Source: {source} (retrieved {retrieved}) — "{quote}"'


def learning_reset_denial(
    pre: LearningPreflight, *, block_all: bool, block_during_incident: bool
) -> str | None:
    """The operator-facing refusal reason, or ``None`` to allow.

    ``block_all`` refuses every reset-triggering change, whatever the state
    and whether or not a campaign can be identified. It is a freeze, and it
    is honestly blunt.

    ``block_during_incident`` is narrower by name and must be narrower in
    fact: "during incident" names *a specific campaign that is known to be
    unstable*. So it refuses only when

    1. this call identifies a campaign at all, and
    2. that campaign is not positively known to be out of a learning period.

    (2) is fail-closed on purpose — UNKNOWN is refused, not assumed steady —
    but (1) is what keeps that from degenerating. Several reset-triggering
    tools are not campaign-scoped (``google_ads_conversions_*`` is
    account-level; ``google_ads_budget_update`` is keyed on a ``budget_id``),
    so their campaign is always unresolvable and their state always UNKNOWN.
    Without (1) this rule would refuse every one of those calls forever, with
    no relation to any incident or any campaign — the operator who followed
    mureo's own advice to declare it would find conversion actions
    permanently un-editable, and would turn the feature off. A rule with no
    subject has nothing to refuse.
    """
    if pre.change.risk is not ResetRisk.RESETS:
        return None
    if not (block_all or block_during_incident):
        return None
    if not block_all:
        if pre.campaign_id is None:
            return None
        if pre.learning.is_known_not_learning():
            return None
    rule = (
        "block_learning_resets"
        if block_all
        else "block_learning_resets_during_incident"
    )
    reason = _DENY_PREAMBLE.format(
        tool=pre.tool_name,
        change_class=pre.change.change_class,
        platform=pre.platform or "this platform",
        change_detail=pre.change.detail,
    )
    if pre.change.evidence is not None:
        reason += _DENY_EVIDENCE.format(
            source=pre.change.evidence.source,
            retrieved=pre.change.evidence.retrieved,
            quote=pre.change.evidence.quote,
        )
    reason += (
        f" Current learning state: {pre.learning.state} — {pre.learning.detail}"
        f" The STRATEGY.md Guardrails rule '{rule}' refuses this."
    )
    return reason


def preflight_notice(pre: LearningPreflight) -> str | None:
    """The dispatcher-appended notice for a reset-triggering call.

    Fires only on :data:`ResetRisk.RESETS`. UNKNOWN deliberately does not
    append a notice: it would fire on every mutation of every platform mureo
    has no trigger list for, and a warning that always fires is a warning
    nobody reads. The pre-flight tool still reports UNKNOWN honestly when
    asked.
    """
    if pre.change.risk is not ResetRisk.RESETS:
        return None
    lines = [
        "(LEARNING-PERIOD NOTICE: mureo classifies this call as a "
        f"learning-period reset — {pre.change.change_class} on "
        f"{pre.platform or 'this platform'}.",
        f"  Why: {pre.change.detail}",
    ]
    if pre.change.evidence is not None:
        lines.append(
            f"  Source: {pre.change.evidence.source} "
            f"(retrieved {pre.change.evidence.retrieved})"
        )
    lines.append(
        f"  Learning state before this call: {pre.learning.state} — "
        f"{pre.learning.detail}"
    )
    lines.append(
        "  Surface this to the operator before the NEXT change: stacking "
        "another reset while a campaign is re-learning delays recovery "
        "instead of speeding it up. Call "
        "mureo_learning_reset_preflight before the next change, and declare "
        "block_learning_resets / block_learning_resets_during_incident in "
        "STRATEGY.md ## Guardrails to make mureo refuse them outright.)"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O layer — the STATE.json read, TTL-cached like the guardrail read
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 5.0
_state_cache: dict[str, tuple[float, Any]] = {}


def _state_path() -> Path:
    try:
        from mureo.core.runtime_context import get_runtime_context

        store = get_runtime_context().state_store
        state_path = getattr(store, "state_path", None)
        if state_path is not None:
            return Path(state_path)
    except Exception:  # noqa: BLE001 — never let resolution break dispatch
        logger.debug("learning pre-flight: could not resolve STATE.json", exc_info=True)
    return Path.cwd() / "STATE.json"


def load_state_document() -> Any:
    """Read STATE.json (TTL-cached). Returns an empty document on any error."""
    from mureo.context.models import StateDocument

    path = _state_path()
    key = str(path)
    now = time.monotonic()
    cached = _state_cache.get(key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]
    try:
        from mureo.context.state import read_state_file

        doc = read_state_file(path) if path.exists() else StateDocument()
    except Exception:  # noqa: BLE001 — a pre-flight must never take mureo down
        logger.debug("learning pre-flight: could not read STATE.json", exc_info=True)
        doc = StateDocument()
    _state_cache[key] = (now, doc)
    return doc


def load_preflight(
    tool_name: str, arguments: dict[str, Any], campaign_id: str | None = None
) -> LearningPreflight:
    """:func:`build_preflight` against the workspace's STATE.json."""
    return build_preflight(tool_name, arguments, load_state_document(), campaign_id)


__all__ = [
    "ChangeAssessment",
    "LearningPreflight",
    "LearningReading",
    "build_preflight",
    "campaign_id_from",
    "classify_change",
    "learning_reset_denial",
    "load_preflight",
    "load_state_document",
    "preflight_notice",
    "read_learning_state",
]
