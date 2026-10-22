"""Filling an action's baseline from STATE.json (#890).

``baseline_from_state`` is the pure half: given the document, the entry
and today, it returns the campaign snapshot's metrics as a baseline — whole,
with ``period``, ``fetched_at`` and the day count — or the reason it cannot.
``with_baseline`` decides whether an entry is filled at all and says where
its baseline came from. The append path that calls it is pinned in
tests/test_action_baseline_append.py.
"""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from typing import Any

import pytest

from mureo.context.action_baseline import (
    BASELINE_MAX_AGE_DAYS,
    BASELINE_MAX_LEAD_DAYS,
    BASELINE_STALE,
    baseline_from_state,
    with_baseline,
)
from mureo.context.auto_evaluation import (
    SKIP_CAMPAIGN_NOT_IN_STATE,
    SKIP_CURRENT_METRICS_UNDATED,
    SKIP_NO_CURRENT_METRICS,
    SKIP_PLATFORM_NOT_IN_STATE,
)
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state_codec import parse_state

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)

SNAPSHOT_METRICS: dict[str, Any] = {
    "cpa": 5000,
    "conversions": 100,
    "result_indicator": "actions:offsite_conversion",
    "period": "LAST_30_DAYS",
    "fetched_at": "2026-09-18T09:00:00+09:00",
}


def _doc(
    metrics: dict[str, Any] | None = None,
    *,
    platform: str = "google_ads",
    campaign_id: str = "camp_1",
) -> StateDocument:
    campaign: dict[str, Any] = {
        "campaign_id": campaign_id,
        "campaign_name": "Brand",
        "status": "ENABLED",
    }
    if metrics is not None:
        campaign["metrics"] = metrics
    document = {
        "version": "2",
        "platforms": {platform: {"account_id": "acct-1", "campaigns": [campaign]}},
        "action_log": [],
    }
    return parse_state(json.dumps(document))


def _entry(**overrides: Any) -> ActionLogEntry:
    fields: dict[str, Any] = {
        "timestamp": "2026-09-19T10:00:00+09:00",
        "action": "budget_increase",
        "platform": "google_ads",
        "campaign_id": "camp_1",
        "observation_due": "2026-10-03",
    }
    fields.update(overrides)
    return ActionLogEntry(**fields)


def _fetched(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat() + "T09:00:00+09:00"


# ---------------------------------------------------------------------------
# baseline_from_state — what is filled
# ---------------------------------------------------------------------------


def test_the_snapshot_is_copied_whole_with_its_day_count() -> None:
    baseline = baseline_from_state(_doc(dict(SNAPSHOT_METRICS)), _entry(), TODAY)

    assert baseline == {**SNAPSHOT_METRICS, "days": 30}


def test_an_existing_day_count_is_not_overwritten() -> None:
    metrics = {**SNAPSHOT_METRICS, "days": 28}

    baseline = baseline_from_state(_doc(metrics), _entry(), TODAY)

    assert isinstance(baseline, dict)
    assert baseline["days"] == 28


def test_no_day_count_is_added_when_the_period_is_unreadable() -> None:
    metrics = {**SNAPSHOT_METRICS, "period": "SOMETIME"}

    baseline = baseline_from_state(_doc(metrics), _entry(), TODAY)

    assert baseline == metrics
    assert isinstance(baseline, dict)
    assert "days" not in baseline


def test_no_day_count_is_added_when_there_is_no_period() -> None:
    metrics = {k: v for k, v in SNAPSHOT_METRICS.items() if k != "period"}

    baseline = baseline_from_state(_doc(metrics), _entry(), TODAY)

    assert baseline == metrics


def test_the_snapshot_is_not_modified() -> None:
    doc = _doc(dict(SNAPSHOT_METRICS))
    snapshot = doc.platforms["google_ads"].campaigns[0]
    before = copy.deepcopy(snapshot.metrics)

    baseline = baseline_from_state(doc, _entry(), TODAY)

    assert snapshot.metrics == before
    assert isinstance(baseline, dict)
    assert baseline is not snapshot.metrics
    baseline["cpa"] = 1
    assert snapshot.metrics == before


# ---------------------------------------------------------------------------
# baseline_from_state — why it cannot
# ---------------------------------------------------------------------------


def test_a_platform_not_in_the_document_is_reported() -> None:
    entry = _entry(platform="meta_ads")

    assert baseline_from_state(_doc(dict(SNAPSHOT_METRICS)), entry, TODAY) == (
        SKIP_PLATFORM_NOT_IN_STATE
    )


def test_a_campaign_not_in_the_document_is_reported() -> None:
    entry = _entry(campaign_id="camp_2")

    assert baseline_from_state(_doc(dict(SNAPSHOT_METRICS)), entry, TODAY) == (
        SKIP_CAMPAIGN_NOT_IN_STATE
    )


@pytest.mark.parametrize("metrics", [None, {}])
def test_a_snapshot_without_metrics_is_reported(
    metrics: dict[str, Any] | None,
) -> None:
    assert baseline_from_state(_doc(metrics), _entry(), TODAY) == (
        SKIP_NO_CURRENT_METRICS
    )


@pytest.mark.parametrize("fetched_at", [None, "", "yesterday", 20260918])
def test_an_undated_or_unreadable_fetched_at_is_reported(fetched_at: Any) -> None:
    metrics = {k: v for k, v in SNAPSHOT_METRICS.items() if k != "fetched_at"}
    if fetched_at is not None:
        metrics["fetched_at"] = fetched_at

    assert baseline_from_state(_doc(metrics), _entry(), TODAY) == (
        SKIP_CURRENT_METRICS_UNDATED
    )


def test_a_snapshot_exactly_at_the_age_limit_is_used() -> None:
    metrics = {**SNAPSHOT_METRICS, "fetched_at": _fetched(BASELINE_MAX_AGE_DAYS)}

    baseline = baseline_from_state(_doc(metrics), _entry(), TODAY)

    assert isinstance(baseline, dict)
    assert baseline["fetched_at"] == metrics["fetched_at"]


def test_a_snapshot_one_day_past_the_age_limit_is_stale() -> None:
    metrics = {**SNAPSHOT_METRICS, "fetched_at": _fetched(BASELINE_MAX_AGE_DAYS + 1)}

    assert baseline_from_state(_doc(metrics), _entry(), TODAY) == BASELINE_STALE


def test_a_snapshot_dated_one_day_ahead_is_used() -> None:
    # A collector in a timezone ahead of the server stamps tomorrow.
    metrics = {**SNAPSHOT_METRICS, "fetched_at": _fetched(-BASELINE_MAX_LEAD_DAYS)}

    baseline = baseline_from_state(_doc(metrics), _entry(), TODAY)

    assert isinstance(baseline, dict)
    assert baseline["fetched_at"] == metrics["fetched_at"]


def test_a_snapshot_dated_two_days_ahead_is_stale() -> None:
    # Further ahead is a mistyped date or a broken clock, not a timezone.
    lead = BASELINE_MAX_LEAD_DAYS + 1
    metrics = {**SNAPSHOT_METRICS, "fetched_at": _fetched(-lead)}

    assert baseline_from_state(_doc(metrics), _entry(), TODAY) == BASELINE_STALE


def test_the_stale_code_is_the_one_new_word() -> None:
    assert BASELINE_STALE == "baseline_stale"
    assert BASELINE_MAX_AGE_DAYS == 2
    assert BASELINE_MAX_LEAD_DAYS == 1


# ---------------------------------------------------------------------------
# with_baseline — which entries are filled, and the response fragment
# ---------------------------------------------------------------------------


def test_an_entry_without_a_baseline_is_filled_from_the_snapshot() -> None:
    entry = _entry()

    filled, fragment = with_baseline(_doc(dict(SNAPSHOT_METRICS)), entry, TODAY)

    assert filled.metrics_at_action == {**SNAPSHOT_METRICS, "days": 30}
    assert fragment == {"source": "state_snapshot"}
    # A new entry; the one passed in is untouched.
    assert entry.metrics_at_action is None


def test_an_empty_baseline_counts_as_none() -> None:
    filled, fragment = with_baseline(
        _doc(dict(SNAPSHOT_METRICS)), _entry(metrics_at_action={}), TODAY
    )

    assert filled.metrics_at_action == {**SNAPSHOT_METRICS, "days": 30}
    assert fragment == {"source": "state_snapshot"}


def test_a_caller_baseline_is_kept_as_given() -> None:
    given = {"mtd_spend": 120000, "period": "THIS_MONTH"}
    entry = _entry(metrics_at_action=given)

    filled, fragment = with_baseline(_doc(dict(SNAPSHOT_METRICS)), entry, TODAY)

    assert filled is entry
    assert filled.metrics_at_action == given
    assert fragment == {"source": "caller"}


def test_an_unfillable_entry_reports_the_reason() -> None:
    metrics = {**SNAPSHOT_METRICS, "fetched_at": _fetched(BASELINE_MAX_AGE_DAYS + 1)}
    entry = _entry()

    filled, fragment = with_baseline(_doc(metrics), entry, TODAY)

    assert filled is entry
    assert filled.metrics_at_action is None
    assert fragment == {"source": "none", "reason": BASELINE_STALE}


@pytest.mark.parametrize(
    "overrides",
    [
        {"origin": "external"},
        {"evaluation_of": 0},
        {"campaign_id": None},
        {"campaign_id": ""},
    ],
    ids=["external", "evaluation_record", "no_campaign_id", "blank_campaign_id"],
)
def test_entries_out_of_scope_are_not_filled_and_carry_no_reason(
    overrides: dict[str, Any],
) -> None:
    entry = _entry(**overrides)

    filled, fragment = with_baseline(_doc(dict(SNAPSHOT_METRICS)), entry, TODAY)

    assert filled is entry
    assert filled.metrics_at_action is None
    assert fragment == {"source": "none"}
