"""Tests for the pure :func:`score_budget_efficiency` scorer."""

from __future__ import annotations

from typing import Any

import pytest

from mureo.analytics.builtin._budget_efficiency import (
    EFFICIENT_THRESHOLD,
    INEFFICIENT_THRESHOLD,
    score_budget_efficiency,
)


@pytest.mark.unit
def test_scorer_handles_empty_rows() -> None:
    result = score_budget_efficiency(
        [],
        platform="google_ads",
        account_id="acct",
    )
    assert result.per_campaign_score == ()
    assert "no campaigns" in result.rebalance_suggestion


@pytest.mark.unit
def test_scorer_normalises_relative_to_top_performer() -> None:
    rows: list[dict[str, Any]] = [
        {"campaign_id": "best", "metrics": {"cost": 100, "conversions": 10}},
        {"campaign_id": "mid", "metrics": {"cost": 100, "conversions": 5}},
        {"campaign_id": "worst", "metrics": {"cost": 100, "conversions": 1}},
    ]
    result = score_budget_efficiency(rows, platform="google_ads", account_id="acct")
    scores = dict(result.per_campaign_score)
    assert scores["best"] == 1.0
    assert scores["mid"] == pytest.approx(0.5, abs=0.01)
    assert scores["worst"] == pytest.approx(0.1, abs=0.01)


@pytest.mark.unit
def test_scorer_suggests_reallocation_when_split_clear() -> None:
    rows: list[dict[str, Any]] = [
        {"campaign_id": "high", "metrics": {"cost": 100, "conversions": 10}},
        {"campaign_id": "low", "metrics": {"cost": 100, "conversions": 1}},
    ]
    result = score_budget_efficiency(rows, platform="google_ads", account_id="acct")
    assert "reallocate" in result.rebalance_suggestion
    assert "low" in result.rebalance_suggestion
    assert "high" in result.rebalance_suggestion


@pytest.mark.unit
def test_scorer_flags_no_efficient_when_all_inefficient() -> None:
    """All campaigns at similar low rates → balanced (top scores 1.0
    by definition; the others trail close behind). Specifically test
    the case where the spread is too small to suggest reallocation.
    """
    rows: list[dict[str, Any]] = [
        {"campaign_id": "a", "metrics": {"cost": 100, "conversions": 5}},
        {"campaign_id": "b", "metrics": {"cost": 100, "conversions": 5.5}},
    ]
    result = score_budget_efficiency(rows, platform="google_ads", account_id="acct")
    # No clear split → no reallocation suggestion
    assert "no reallocation" in result.rebalance_suggestion


@pytest.mark.unit
def test_scorer_zero_conversions_returns_tracking_warning() -> None:
    rows: list[dict[str, Any]] = [
        {"campaign_id": "a", "metrics": {"cost": 100, "conversions": 0}},
        {"campaign_id": "b", "metrics": {"cost": 200, "conversions": 0}},
    ]
    result = score_budget_efficiency(rows, platform="google_ads", account_id="acct")
    assert "tracking" in result.rebalance_suggestion
    assert result.unused_budget_amount == 300.0


@pytest.mark.unit
def test_scorer_drops_rows_with_zero_cost() -> None:
    rows: list[dict[str, Any]] = [
        {"campaign_id": "paused", "metrics": {"cost": 0, "conversions": 0}},
        {"campaign_id": "active", "metrics": {"cost": 100, "conversions": 10}},
    ]
    result = score_budget_efficiency(rows, platform="google_ads", account_id="acct")
    scores = dict(result.per_campaign_score)
    assert "paused" not in scores
    assert "active" in scores


@pytest.mark.unit
def test_scorer_accepts_byod_flat_google_shape() -> None:
    """BYOD Google rows have metrics at the top level, not nested.
    Even with ``nested_metrics=True`` the scorer must fall back.
    """
    rows: list[dict[str, Any]] = [
        {"campaign_id": "c", "cost": 100, "conversions": 5},
    ]
    result = score_budget_efficiency(
        rows, platform="google_ads", account_id="acct", nested_metrics=True
    )
    assert dict(result.per_campaign_score) == {"c": 1.0}


@pytest.mark.unit
def test_scorer_meta_sums_actions_when_flat_conversions_zero() -> None:
    rows: list[dict[str, Any]] = [
        {
            "campaign_id": "c",
            "spend": 100,
            "conversions": 0,
            "actions": [
                {"action_type": "offsite_conversion.fb_pixel_lead", "value": 10},
            ],
        },
    ]
    result = score_budget_efficiency(
        rows,
        platform="meta_ads",
        account_id="act",
        spend_key="spend",
        nested_metrics=False,
    )
    assert dict(result.per_campaign_score) == {"c": 1.0}


@pytest.mark.unit
def test_thresholds_are_stable_module_constants() -> None:
    # Constants are referenced by skill prompts as well — keep them
    # stable. A future tweak should bump tests deliberately.
    assert INEFFICIENT_THRESHOLD == 0.3
    assert EFFICIENT_THRESHOLD == 0.7
