"""Delivery-collapse diagnosis — change x metric timeline + elimination ladder (#546).

The post-mortem behind this issue is the specification: an agent with
complete API access ran every check and still could not say why the
campaigns died. So the contract under test is *not* "names the cause".
It is "reports what was checked, what it ruled out, and what remains
unknown" — and never promotes an unchecked step to a conclusion.

Marks: unit — pure, no network, no filesystem.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mureo.analysis.collapse_diagnosis import (
    ELIMINATION_LADDER,
    ChangeEvent,
    CheckOutcome,
    DiagnosisConfidence,
    EvidenceCheck,
    diagnose_collapse,
)
from mureo.analysis.delivery_collapse import (
    DailyDelivery,
    DeliverySeries,
    detect_delivery_collapse,
)

pytestmark = pytest.mark.unit

AS_OF = date(2026, 6, 1)
CLIFF = AS_OF - timedelta(days=1)
NORMAL_IMPRESSIONS = 350_000


def _series(status: str = "ENABLED") -> DeliverySeries:
    days = [
        DailyDelivery(
            date=CLIFF - timedelta(days=offset),
            impressions=NORMAL_IMPRESSIONS,
            clicks=3_500,
            cost=120_000.0,
        )
        for offset in reversed(range(1, 29))
    ]
    days.append(DailyDelivery(date=CLIFF, impressions=0, clicks=0, cost=0.0))
    return DeliverySeries(
        platform="google_ads",
        campaign_id="c-1",
        campaign_name="Display / Prospecting",
        status=status,
        daily=tuple(days),
    )


def _signal(series: DeliverySeries | None = None):
    resolved = series or _series()
    signal = detect_delivery_collapse(resolved, as_of=AS_OF)
    assert signal is not None
    return signal


# ---------------------------------------------------------------------------
# Change x metric timeline
# ---------------------------------------------------------------------------


def test_changes_immediately_before_the_cliff_are_surfaced() -> None:
    series = _series()
    changes = (
        ChangeEvent(
            occurred_at=(CLIFF - timedelta(days=1)).isoformat(),
            source="google_ads_change_history",
            resource_type="campaign_criterion",
            summary="1,842 placement exclusions added",
        ),
        ChangeEvent(
            occurred_at=(CLIFF - timedelta(days=20)).isoformat(),
            source="action_log",
            resource_type="campaign_budget",
            summary="daily budget raised to 150,000",
        ),
    )

    diagnosis = diagnose_collapse(_signal(series), series, changes=changes)

    assert [c.summary for c in diagnosis.changes_before_cliff] == [
        "1,842 placement exclusions added"
    ]
    # The far-older budget change is still in the timeline, just not
    # promoted as "what changed immediately before".
    dated = {point.date: point for point in diagnosis.timeline}
    assert dated[(CLIFF - timedelta(days=1)).isoformat()].changes
    assert dated[CLIFF.isoformat()].impressions == 0


def test_timeline_brackets_the_cliff() -> None:
    series = _series()

    diagnosis = diagnose_collapse(_signal(series), series)

    dates = [point.date for point in diagnosis.timeline]
    assert CLIFF.isoformat() in dates
    assert dates == sorted(dates)
    assert len(dates) <= 21


def test_no_recorded_change_is_reported_as_unresolved_not_as_a_cause() -> None:
    """The incident's actual shape: nothing in the change feed. That is
    an open question, never a conclusion."""
    series = _series()

    diagnosis = diagnose_collapse(_signal(series), series, changes=())

    assert diagnosis.changes_before_cliff == ()
    assert diagnosis.most_likely_cause is None
    assert diagnosis.confidence is DiagnosisConfidence.UNDETERMINED
    joined = " ".join(diagnosis.unresolved)
    assert "no recorded change" in joined.lower()


# ---------------------------------------------------------------------------
# Elimination ladder
# ---------------------------------------------------------------------------


def test_ladder_covers_the_documented_elimination_path() -> None:
    assert ELIMINATION_LADDER == (
        "ad_approval_policy",
        "billing",
        "budget",
        "bid_competitiveness",
        "targeting_and_exclusions",
        "learning_state",
        "campaign_flight_dates",
    )


def test_a_single_implicated_check_becomes_the_most_likely_cause() -> None:
    series = _series()
    checks = tuple(
        EvidenceCheck(
            name=name,
            outcome=(
                CheckOutcome.IMPLICATED
                if name == "ad_approval_policy"
                else CheckOutcome.RULED_OUT
            ),
            detail=(
                "every ad DISAPPROVED (destination not working)"
                if name == "ad_approval_policy"
                else "no issue found"
            ),
        )
        for name in ELIMINATION_LADDER
    )

    diagnosis = diagnose_collapse(_signal(series), series, checks=checks)

    assert diagnosis.most_likely_cause == "ad_approval_policy"
    assert diagnosis.confidence is DiagnosisConfidence.CONFIRMED
    assert diagnosis.unresolved == ()


def test_an_unavailable_check_keeps_confidence_below_confirmed() -> None:
    """mureo has no billing API. A conclusion drawn while billing was
    never readable is 'likely', not 'confirmed'."""
    series = _series()
    checks = tuple(
        EvidenceCheck(
            name=name,
            outcome=(
                CheckOutcome.IMPLICATED
                if name == "ad_approval_policy"
                else (
                    CheckOutcome.UNAVAILABLE
                    if name == "billing"
                    else CheckOutcome.RULED_OUT
                )
            ),
            detail="no billing API on this platform" if name == "billing" else "",
        )
        for name in ELIMINATION_LADDER
    )

    diagnosis = diagnose_collapse(_signal(series), series, checks=checks)

    assert diagnosis.most_likely_cause == "ad_approval_policy"
    assert diagnosis.confidence is DiagnosisConfidence.LIKELY
    assert any("billing" in item for item in diagnosis.unresolved)


def test_unchecked_ladder_steps_are_reported_as_unresolved() -> None:
    series = _series()
    checks = (
        EvidenceCheck(name="budget", outcome=CheckOutcome.RULED_OUT, detail="unspent"),
    )

    diagnosis = diagnose_collapse(_signal(series), series, checks=checks)

    unresolved = " ".join(diagnosis.unresolved)
    for name in ELIMINATION_LADDER:
        if name != "budget":
            assert name in unresolved
    assert "budget" not in {item.split(":")[0] for item in diagnosis.unresolved}


def test_everything_ruled_out_is_undetermined_not_solved() -> None:
    """The exact post-mortem outcome: seven passing checks, no cause."""
    series = _series()
    checks = tuple(
        EvidenceCheck(name=name, outcome=CheckOutcome.RULED_OUT, detail="clean")
        for name in ELIMINATION_LADDER
    )

    diagnosis = diagnose_collapse(_signal(series), series, checks=checks)

    assert diagnosis.most_likely_cause is None
    assert diagnosis.confidence is DiagnosisConfidence.UNDETERMINED
    assert diagnosis.checks_passed == len(ELIMINATION_LADDER)


def test_an_unknown_check_name_is_rejected() -> None:
    series = _series()
    checks = (EvidenceCheck(name="vibes", outcome=CheckOutcome.IMPLICATED),)

    with pytest.raises(ValueError, match="vibes"):
        diagnose_collapse(_signal(series), series, checks=checks)


# ---------------------------------------------------------------------------
# Honesty about the limits
# ---------------------------------------------------------------------------


def test_limitations_state_what_the_workflow_cannot_answer() -> None:
    series = _series()

    diagnosis = diagnose_collapse(_signal(series), series)

    text = " ".join(diagnosis.limitations).lower()
    # Serving-side suppression is not exposed by any read API — the
    # single reason full API access did not close the incident.
    assert "serving" in text
    assert "billing" in text
    assert diagnosis.limitations


def test_next_checks_name_a_tool_where_one_exists_and_stay_empty_otherwise() -> None:
    series = _series()

    diagnosis = diagnose_collapse(_signal(series), series)
    by_step = dict(diagnosis.next_checks)

    assert by_step["ad_approval_policy"] == "google_ads_ads_policy_details"
    # No mureo tool reads billing state on any platform. Advertising one
    # would be the fabrication this issue exists to avoid.
    assert by_step["billing"] == ""


def test_next_checks_are_empty_for_a_platform_without_a_tool_map() -> None:
    series = DeliverySeries(
        platform="plugin:acme:smartnews_ads",
        campaign_id="c-1",
        campaign_name="SmartNews",
        status="ENABLED",
        daily=_series().daily,
    )

    diagnosis = diagnose_collapse(_signal(series), series)

    assert {tool for _step, tool in diagnosis.next_checks} == {""}
    assert any("plugin:acme:smartnews_ads" in item for item in diagnosis.unresolved)


def test_a_step_already_settled_is_not_offered_as_a_next_check() -> None:
    series = _series()
    checks = (
        EvidenceCheck(name="budget", outcome=CheckOutcome.RULED_OUT),
        EvidenceCheck(name="ad_approval_policy", outcome=CheckOutcome.IMPLICATED),
    )

    diagnosis = diagnose_collapse(_signal(series), series, checks=checks)

    offered = {step for step, _tool in diagnosis.next_checks}
    assert "budget" not in offered
    assert "ad_approval_policy" not in offered
    assert "learning_state" in offered
