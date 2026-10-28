"""The possible-duplicate hint between two decision chains (#851 item 3).

Recording a decision with ``mureo_decision_record`` and then making the
change with only a ``reason`` leaves two chains for one change. Nothing
joins them; :func:`possible_duplicates` only names the pair so the
dashboard can say so.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

from mureo.context.ops_history_duplicates import (
    DUPLICATE_DECISION_WINDOW,
    possible_duplicates,
)
from mureo.context.state_codec import parse_state

pytestmark = pytest.mark.unit

_TARGET = {"platform": "google_ads", "campaign_id": "c1"}


def _decision(decision_id: str, status: str, at: str, **extra: Any) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "recorded_at": at,
        "status": status,
        "title": f"Decision {decision_id}",
        "rationale": "Because.",
        **extra,
    }


def _action(**extra: Any) -> dict[str, Any]:
    return {
        "timestamp": "2026-10-10T10:10:00+09:00",
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        "campaign_id": "c1",
        **extra,
    }


def _recorded(
    decision_id: str = "R", at: str = "2026-10-10T10:00:00+09:00", **target: Any
) -> list[dict[str, Any]]:
    """A ``mureo_decision_record`` chain: proposed, then adopted."""
    named = target if target else _TARGET
    return [
        _decision(decision_id, "proposed", at, **named),
        _decision(f"{decision_id}2", "adopted", at, supersedes=decision_id, **named),
    ]


def _called(
    decision_id: str = "C", at: str = "2026-10-10T10:10:00+09:00", **extra: Any
) -> dict[str, Any]:
    """A chain opened by a reasoned change."""
    fields = {**_TARGET, "journal_call_id": f"call-{decision_id}", **extra}
    return _decision(decision_id, "adopted", at, **fields)


def _hints(
    decisions: list[dict[str, Any]], action_log: list[dict[str, Any]] | None = None
) -> dict[str, str]:
    document = {"version": "2", "decisions": decisions, "action_log": action_log or []}
    doc = parse_state(json.dumps(document))
    return dict(possible_duplicates(doc))


def test_the_window_is_a_day() -> None:
    assert timedelta(hours=24) == DUPLICATE_DECISION_WINDOW


def test_a_record_then_a_reasoned_change_is_a_possible_duplicate() -> None:
    log = [_action(decision_id="C")]
    assert _hints([*_recorded(), _called()], log) == {"R": "C"}


def test_a_change_more_than_a_day_later_is_not() -> None:
    late = _called(at="2026-10-11T11:00:00+09:00")
    assert _hints([*_recorded(), late]) == {}


def test_a_change_before_the_record_is_not() -> None:
    early = _called(at="2026-10-10T09:50:00+09:00")
    assert _hints([*_recorded(), early]) == {}


def test_a_record_naming_no_target_never_matches() -> None:
    bare = [_decision("R", "proposed", "2026-10-10T10:00:00+09:00")]
    assert _hints([*bare, _called()]) == {}


def test_a_rejected_record_is_not_a_duplicate() -> None:
    rejected = [
        _decision("R", "proposed", "2026-10-10T10:00:00+09:00", **_TARGET),
        _decision("R2", "rejected", "2026-10-10T10:01:00+09:00", supersedes="R"),
    ]
    assert _hints([*rejected, _called()]) == {}


def test_a_record_that_owns_a_change_is_not_a_duplicate() -> None:
    log = [_action(decision_id="R"), _action(decision_id="C")]
    assert _hints([*_recorded(), _called()], log) == {}


def test_a_record_that_claims_a_change_by_related_actions_is_not() -> None:
    chain = _recorded()
    chain[1]["related_actions"] = [0]
    assert _hints([*chain, _called()], [_action()]) == {}


def test_a_batch_decision_is_not_a_call_opened_chain() -> None:
    batched = _called(batch_id="batch-1")
    document = {
        "version": "2",
        "batches": [
            {
                "batch_id": "batch-1",
                "started_at": "2026-10-10T10:05:00+09:00",
                "label": "bulk",
            }
        ],
        "decisions": [*_recorded(), batched],
    }
    doc = parse_state(json.dumps(document))
    assert dict(possible_duplicates(doc)) == {}


def test_a_call_that_wrote_no_entry_opens_a_chain_too() -> None:
    tool_only = _decision(
        "C", "adopted", "2026-10-10T10:10:00+09:00", journal_tool="x", **_TARGET
    )
    assert _hints([*_recorded(), tool_only]) == {"R": "C"}


def test_the_nearest_call_chain_wins() -> None:
    far = _called("C1", at="2026-10-10T10:20:00+09:00")
    near = _called("C2", at="2026-10-10T10:05:00+09:00")
    assert _hints([*_recorded(), far, near]) == {"R": "C2"}


def test_a_call_chain_is_named_by_the_earlier_record_only() -> None:
    first = _recorded("R", at="2026-10-10T09:00:00+09:00")
    second = _recorded("S", at="2026-10-10T09:30:00+09:00")
    assert _hints([*second, *first, _called()]) == {"R": "C"}


def test_a_different_entity_on_the_same_campaign_is_not() -> None:
    record = _recorded(**_TARGET, entity_type="ad_group", entity_id="g1")
    call = _called(entity_type="ad_group", entity_id="g2")
    assert _hints([*record, call]) == {}


def test_the_same_entity_matches_without_a_campaign() -> None:
    record = _recorded(platform="google_ads", entity_type="budget", entity_id="b1")
    call = _decision(
        "C",
        "adopted",
        "2026-10-10T10:10:00+09:00",
        platform="google_ads",
        entity_type="budget",
        entity_id="b1",
        journal_call_id="call-C",
    )
    assert _hints([*record, call]) == {"R": "C"}


def test_a_different_platform_is_not() -> None:
    call = _called(platform="meta_ads")
    assert _hints([*_recorded(), call]) == {}


def test_a_platform_alone_is_not_a_target() -> None:
    record = _recorded(platform="google_ads")
    call = _decision(
        "C",
        "adopted",
        "2026-10-10T10:10:00+09:00",
        platform="google_ads",
        journal_call_id="call-C",
    )
    assert _hints([*record, call]) == {}


def test_a_naive_timestamp_is_read_as_utc() -> None:
    record = _recorded(at="2026-10-10T01:00:00")
    after = _called(at="2026-10-10T10:30:00+09:00")  # 01:30 UTC
    before = _called(at="2026-10-10T09:30:00+09:00")  # 00:30 UTC
    assert _hints([*record, after]) == {"R": "C"}
    assert _hints([*record, before]) == {}


def test_the_inputs_are_not_touched() -> None:
    document = {"version": "2", "decisions": [*_recorded(), _called()]}
    doc = parse_state(json.dumps(document))
    before = (doc.decisions, doc.action_log)
    hints = possible_duplicates(doc)
    assert type(hints) is dict
    assert (doc.decisions, doc.action_log) == before


@pytest.mark.parametrize(
    "written",
    [
        {"batch_id": "batch-1"},
        {"applied_params": {"budget_id": "b1", "amount": 12000}},
    ],
)
def test_a_record_mureo_wrote_for_a_change_is_not_record_only(
    written: dict[str, Any],
) -> None:
    chain = _recorded()
    chain[0].update(written)
    document = {
        "version": "2",
        "batches": [
            {
                "batch_id": "batch-1",
                "started_at": "2026-10-10T09:55:00+09:00",
                "label": "bulk",
            }
        ],
        "decisions": [*chain, _called()],
    }
    doc = parse_state(json.dumps(document))
    assert len(doc.decisions) == 3
    assert dict(possible_duplicates(doc)) == {}


def test_a_record_a_call_adopted_is_not_record_only() -> None:
    adopted_by_call = [
        _decision("R", "proposed", "2026-10-10T10:00:00+09:00", **_TARGET),
        _decision(
            "R2",
            "adopted",
            "2026-10-10T10:05:00+09:00",
            supersedes="R",
            journal_call_id="call-R",
            journal_tool="google_ads_budget_update",
            **_TARGET,
        ),
    ]
    later = _called(at="2026-10-10T10:55:00+09:00")
    assert _hints([*adopted_by_call, later]) == {}


def test_a_taken_nearest_call_chain_gives_no_hint() -> None:
    first = _recorded("R")
    second = _recorded("S")
    near = _called("C", at="2026-10-10T10:10:00+09:00")
    far = _called("C2", at="2026-10-10T10:20:00+09:00")
    assert _hints([*first, *second, near, far]) == {"R": "C"}


@pytest.mark.parametrize("status", ["rejected", "deferred"])
def test_a_call_chain_no_longer_adopted_is_not_a_match(status: str) -> None:
    closed = [
        _called(),
        _decision("C2", status, "2026-10-10T10:12:00+09:00", supersedes="C"),
    ]
    assert _hints([*_recorded(), *closed]) == {}
