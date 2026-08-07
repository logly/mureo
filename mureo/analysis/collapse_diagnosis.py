"""Delivery-collapse diagnosis — change x metric timeline + elimination ladder.

Second half of #546. Detection says *a campaign died*; this says what is
known about *why*, and — the part that matters — what is still not known.

Why this refuses to promise a cause
-----------------------------------
In the incident that motivated the issue, an agent with complete API
access ran campaign diagnosis, budget, ad approval, billing, bidding and
change-history checks and still could not close the question of why two
campaigns died on the same day. A workflow that answers "most likely
cause: X" on that evidence would be fabricating. So the output is
deliberately three-part:

- what was **checked and ruled out**,
- what is **implicated**, if anything, with the evidence attached,
- what is **unresolved** — every ladder step nobody could check, plus
  the standing :data:`LIMITATIONS` describing questions no read API on
  any supported platform can answer at all.

``most_likely_cause`` is ``None`` and ``confidence`` is
:attr:`DiagnosisConfidence.UNDETERMINED` unless a check actually
implicates something. Seven passing checks is an honest "undetermined",
not a diagnosis.

This module is pure: the caller gathers the change feed and the
per-cause evidence (those lookups are the only platform-specific part
of the workflow) and hands both in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from mureo.analysis.delivery_collapse import CollapseSignal, DeliverySeries

#: The standard elimination path, in the order an operator walks it.
#: Cheapest and most common causes first; the ones that need the most
#: interpretation last.
ELIMINATION_LADDER: tuple[str, ...] = (
    "ad_approval_policy",
    "billing",
    "budget",
    "bid_competitiveness",
    "targeting_and_exclusions",
    "learning_state",
    "campaign_flight_dates",
)

DEFAULT_CHANGE_LOOKBACK_DAYS = 3
DEFAULT_TIMELINE_DAYS = 21

#: What this workflow cannot answer, on ANY platform. Returned verbatim
#: on every diagnosis so a reader never mistakes "nothing implicated"
#: for "nothing was wrong".
LIMITATIONS: tuple[str, ...] = (
    "Serving-side suppression — the platform choosing not to enter a "
    "campaign into auctions — is not exposed by any read API mureo has on "
    "any supported platform. mureo can rule causes out; it cannot read the "
    "platform's own delivery decision.",
    "No supported platform exposes billing or payment state through an API "
    "mureo integrates. Billing is only ever settled here by evidence the "
    "operator supplies from the platform UI.",
    "Learning-phase internals (Google Ads bid-strategy learning, Meta ad-set "
    "learning) are not readable through mureo's clients; a learning reset is "
    "inferred from a change event, never observed directly.",
    "Change feeds reaching mureo are incomplete: Google Ads change history "
    "omits system-initiated changes and retains ~30 days; Meta publishes an "
    "account activity log but mureo does not fetch it yet, so Meta changes "
    "reach this timeline only via action_log; and manual work done outside "
    "mureo reaches action_log only if it was imported. A cliff with no "
    "change in the window is therefore weak evidence, not exoneration — and "
    "for Meta the gap is mureo's, not the platform's.",
    "Several campaigns collapsing on the same day is reported as a "
    "correlation only. A shared account-level cause (account review, "
    "payment hold, inventory-side policy action) is not attributable from "
    "campaign-scoped data.",
    "Two blind spots in DETECTION, both from refusing to assume what the "
    "platform has not said. A campaign with no rows anywhere in the window "
    "is invisible: with no first row there is no series, and inventing one "
    "would fabricate the baseline. And when EVERY campaign stops reporting "
    "on the same day, nothing proves those days were covered, so no signal "
    "fires — a total account outage and a platform reporting failure are "
    "indistinguishable from here. The second is reported as "
    "`unreported_days` rather than hidden; the first needs a longer window "
    "or the platform UI.",
)

#: Per-platform evidence lookups — the ONLY platform-specific part of
#: the ladder. An empty string means mureo has no tool for that step on
#: that platform, which is reported as such rather than papered over.
SUGGESTED_TOOLS: dict[str, dict[str, str]] = {
    "google_ads": {
        "ad_approval_policy": "google_ads_ads_policy_details",
        "billing": "",
        "budget": "google_ads_budget_get",
        "bid_competitiveness": "google_ads_auction_insights_get",
        "targeting_and_exclusions": "google_ads_campaigns_diagnose",
        "learning_state": "",
        "campaign_flight_dates": "google_ads_campaigns_get",
    },
    "meta_ads": {
        "ad_approval_policy": "meta_ads_ads_list",
        "billing": "",
        "budget": "meta_ads_campaigns_get",
        "bid_competitiveness": "",
        "targeting_and_exclusions": "meta_ads_ad_sets_get",
        "learning_state": "",
        "campaign_flight_dates": "meta_ads_campaigns_get",
    },
}


class CheckOutcome(str, Enum):
    """What one elimination-ladder step concluded."""

    IMPLICATED = "implicated"
    RULED_OUT = "ruled_out"
    UNAVAILABLE = "unavailable"
    INCONCLUSIVE = "inconclusive"


class DiagnosisConfidence(str, Enum):
    """How much weight the caller may put on ``most_likely_cause``."""

    CONFIRMED = "confirmed"
    LIKELY = "likely"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class ChangeEvent:
    """One entry from a change feed, normalised across sources.

    ``occurred_at`` is an ISO date or datetime string; only its date part
    is used for timeline bucketing.
    """

    occurred_at: str
    source: str
    resource_type: str
    summary: str
    actor: str = ""


@dataclass(frozen=True)
class EvidenceCheck:
    """The result of one elimination-ladder step, supplied by the caller."""

    name: str
    outcome: CheckOutcome
    detail: str = ""


@dataclass(frozen=True)
class TimelinePoint:
    """One day of delivery with the changes recorded against it."""

    date: str
    impressions: int
    cost: float
    changes: tuple[ChangeEvent, ...] = ()


@dataclass(frozen=True)
class CollapseDiagnosis:
    """Everything known — and not known — about one collapse."""

    platform: str
    campaign_id: str
    campaign_name: str
    collapse_start_date: str
    evaluated_through: str
    timeline: tuple[TimelinePoint, ...]
    changes_before_cliff: tuple[ChangeEvent, ...]
    checks: tuple[EvidenceCheck, ...]
    checks_passed: int
    most_likely_cause: str | None
    confidence: DiagnosisConfidence
    unresolved: tuple[str, ...]
    next_checks: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...] = LIMITATIONS


def diagnose_collapse(
    signal: CollapseSignal,
    series: DeliverySeries,
    *,
    changes: Iterable[ChangeEvent] = (),
    checks: Iterable[EvidenceCheck] = (),
    change_lookback_days: int = DEFAULT_CHANGE_LOOKBACK_DAYS,
    timeline_days: int = DEFAULT_TIMELINE_DAYS,
) -> CollapseDiagnosis:
    """Overlay ``changes`` on ``series`` and fold in the ladder ``checks``.

    Raises :class:`ValueError` for a check naming a step outside
    :data:`ELIMINATION_LADDER` — a typo'd step would otherwise be
    silently dropped and read as "not checked".
    """
    validated = _validate_checks(checks)
    dated, unreadable = _bucket_changes(changes)
    cliff = date.fromisoformat(signal.collapse_start_date)
    before_cliff = _changes_before_cliff(dated, cliff, change_lookback_days)
    implicated = [c for c in _in_ladder_order(validated) if c.outcome is _IMPLICATED]

    unresolved = _unresolved(
        validated,
        platform=series.platform,
        has_implicated=bool(implicated),
        has_changes=bool(before_cliff),
        cliff=cliff,
        change_lookback_days=change_lookback_days,
        unreadable_changes=unreadable,
    )
    return CollapseDiagnosis(
        platform=series.platform,
        campaign_id=series.campaign_id,
        campaign_name=series.campaign_name,
        collapse_start_date=signal.collapse_start_date,
        evaluated_through=signal.evaluated_through,
        timeline=_timeline(series, dated, timeline_days),
        changes_before_cliff=before_cliff,
        checks=_in_ladder_order(validated),
        checks_passed=sum(1 for c in validated if c.outcome is CheckOutcome.RULED_OUT),
        most_likely_cause=implicated[0].name if implicated else None,
        confidence=_confidence(implicated, unresolved),
        unresolved=unresolved,
        next_checks=_next_checks(validated, series.platform),
    )


_IMPLICATED = CheckOutcome.IMPLICATED
_SETTLED = frozenset({CheckOutcome.IMPLICATED, CheckOutcome.RULED_OUT})


def _validate_checks(checks: Iterable[EvidenceCheck]) -> tuple[EvidenceCheck, ...]:
    """Reject unknown step names; last check per step wins."""
    by_name: dict[str, EvidenceCheck] = {}
    for check in checks:
        if check.name not in ELIMINATION_LADDER:
            raise ValueError(
                f"unknown elimination-ladder step {check.name!r}; "
                f"expected one of {', '.join(ELIMINATION_LADDER)}"
            )
        by_name[check.name] = check
    return tuple(by_name.values())


def _in_ladder_order(checks: Sequence[EvidenceCheck]) -> tuple[EvidenceCheck, ...]:
    by_name = {c.name: c for c in checks}
    return tuple(by_name[name] for name in ELIMINATION_LADDER if name in by_name)


def _bucket_changes(
    changes: Iterable[ChangeEvent],
) -> tuple[dict[date, tuple[ChangeEvent, ...]], int]:
    """Group changes by day. Returns ``(by_day, unreadable_count)``.

    A change feed is external data; an unreadable timestamp is counted
    and surfaced as an open question rather than crashing the diagnosis
    or vanishing from it.
    """
    by_day: dict[date, list[ChangeEvent]] = {}
    unreadable = 0
    for change in changes:
        day = _change_date(change.occurred_at)
        if day is None:
            unreadable += 1
            continue
        by_day.setdefault(day, []).append(change)
    return {day: tuple(events) for day, events in by_day.items()}, unreadable


def _change_date(occurred_at: str) -> date | None:
    """Date part of an ISO date/datetime string, or ``None``."""
    text = (occurred_at or "").strip()
    for candidate in (text, text[:10]):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            continue
    return None


def _changes_before_cliff(
    dated: dict[date, tuple[ChangeEvent, ...]],
    cliff: date,
    lookback_days: int,
) -> tuple[ChangeEvent, ...]:
    """Changes in ``[cliff - lookback, cliff]``, oldest first.

    "What changed immediately before the cliff?" — the window includes
    the cliff day itself because a change made in the morning kills
    delivery the same day.
    """
    window_start = cliff - timedelta(days=max(0, lookback_days))
    out: list[ChangeEvent] = []
    for day in sorted(dated):
        if window_start <= day <= cliff:
            out.extend(dated[day])
    return tuple(out)


def _timeline(
    series: DeliverySeries,
    dated: dict[date, tuple[ChangeEvent, ...]],
    timeline_days: int,
) -> tuple[TimelinePoint, ...]:
    """The trailing ``timeline_days`` of delivery with changes attached."""
    days = sorted(series.daily, key=lambda d: d.date)[-max(1, timeline_days) :]
    return tuple(
        TimelinePoint(
            date=day.date.isoformat(),
            impressions=day.impressions,
            cost=day.cost,
            changes=dated.get(day.date, ()),
        )
        for day in days
    )


def _unresolved(
    checks: Sequence[EvidenceCheck],
    *,
    platform: str,
    has_implicated: bool,
    has_changes: bool,
    cliff: date,
    change_lookback_days: int,
    unreadable_changes: int,
) -> tuple[str, ...]:
    """Every question this diagnosis leaves open, in ladder order first."""
    by_name = {c.name: c for c in checks}
    out: list[str] = []
    for name in ELIMINATION_LADDER:
        check = by_name.get(name)
        if check is None:
            out.append(f"{name}: not checked — no evidence was supplied")
        elif check.outcome is CheckOutcome.UNAVAILABLE:
            out.append(
                f"{name}: could not be checked — "
                f"{check.detail or 'no readable evidence on this platform'}"
            )
        elif check.outcome is CheckOutcome.INCONCLUSIVE:
            out.append(
                f"{name}: checked but inconclusive — "
                f"{check.detail or 'the evidence did not settle it'}"
            )
    if not has_implicated and not has_changes:
        out.append(
            f"No recorded change in the {change_lookback_days} day(s) before "
            f"{cliff.isoformat()}. On a hand-operated account the change may "
            f"exist but never have reached action_log, and a platform-side "
            f"change is not published at all — absence here is not evidence."
        )
    if platform not in SUGGESTED_TOOLS:
        out.append(
            f"{platform}: mureo has no evidence-lookup tools for this "
            f"platform, so every ladder step must be checked in the "
            f"platform's own MCP or UI and supplied back as evidence."
        )
    if unreadable_changes:
        out.append(
            f"{unreadable_changes} change event(s) had an unreadable "
            f"timestamp and were left out of the timeline."
        )
    return tuple(out)


def _confidence(
    implicated: Sequence[EvidenceCheck], unresolved: Sequence[str]
) -> DiagnosisConfidence:
    """CONFIRMED only for one implicated cause with nothing left open."""
    if not implicated:
        return DiagnosisConfidence.UNDETERMINED
    if len(implicated) == 1 and not unresolved:
        return DiagnosisConfidence.CONFIRMED
    return DiagnosisConfidence.LIKELY


def _next_checks(
    checks: Sequence[EvidenceCheck], platform: str
) -> tuple[tuple[str, str], ...]:
    """``(step, tool)`` for every step still open. ``""`` = no mureo tool."""
    settled = {c.name for c in checks if c.outcome in _SETTLED}
    tools = SUGGESTED_TOOLS.get(platform, {})
    return tuple(
        (name, tools.get(name, ""))
        for name in ELIMINATION_LADDER
        if name not in settled
    )


__all__ = [
    "DEFAULT_CHANGE_LOOKBACK_DAYS",
    "DEFAULT_TIMELINE_DAYS",
    "ELIMINATION_LADDER",
    "LIMITATIONS",
    "SUGGESTED_TOOLS",
    "ChangeEvent",
    "CheckOutcome",
    "CollapseDiagnosis",
    "DiagnosisConfidence",
    "EvidenceCheck",
    "TimelinePoint",
    "diagnose_collapse",
]
