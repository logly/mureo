"""A failed read in a ``google_ads_monitoring_*`` tool derives nothing (#865).

The figures a read would have returned are unknown, not zero: a failed
performance read must not report "impressions are 0", and a failed
conversion action read must not report "no active conversion actions".
The derived values are ``None``, the failed read is named in ``issues``, and
``status`` is ``"unknown"`` unless data that WAS read proves ``"critical"``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.test_google_ads_monitoring import _MockMonitoringClient
from tests.test_google_ads_partial_reads import _SECRET, _PlatformError


def _failing() -> AsyncMock:
    return AsyncMock(side_effect=_PlatformError(_SECRET))


def _perf(**metrics: Any) -> AsyncMock:
    return AsyncMock(return_value=[{"metrics": metrics}])


def _has_issue(result: dict[str, Any], text: str) -> bool:
    return any(text in issue for issue in result["issues"])


# ---------------------------------------------------------------------------
# evaluate_delivery_goal
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_delivery_goal_failed_performance_reports_no_zero_impressions() -> None:
    client = _MockMonitoringClient()
    client.get_campaign = AsyncMock(return_value={"status": "ENABLED"})
    client.get_performance_report = _failing()

    result = await client.evaluate_delivery_goal("123")

    assert result["performance"] is None
    assert not _has_issue(result, "impressions are 0")
    assert "Failed to retrieve previous day performance" in result["issues"]
    assert result["status"] == "unknown"
    assert "suggested_workflow" not in result
    assert _SECRET not in str(result)


@pytest.mark.unit
async def test_delivery_goal_failed_campaign_is_named_in_issues() -> None:
    client = _MockMonitoringClient()
    client.get_campaign = _failing()
    client.get_performance_report = _perf(impressions=1000)

    result = await client.evaluate_delivery_goal("123")

    assert result["campaign"] is None
    assert "Failed to retrieve campaign information" in result["issues"]
    assert result["status"] == "unknown"


@pytest.mark.unit
async def test_delivery_goal_critical_from_read_data_stays_critical() -> None:
    client = _MockMonitoringClient()
    client.get_campaign = AsyncMock(return_value={"status": "ENABLED"})
    client.diagnose_campaign_delivery = AsyncMock(
        return_value={"issues": ["Ad group has no ads"]}
    )
    client.get_performance_report = _failing()

    result = await client.evaluate_delivery_goal("123")

    assert result["status"] == "critical"
    assert not _has_issue(result, "impressions are 0")
    assert result["suggested_workflow"] == "delivery_fix"


# ---------------------------------------------------------------------------
# evaluate_cpa_goal / evaluate_cv_goal
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_cpa_goal_failed_performance_derives_nothing() -> None:
    client = _MockMonitoringClient()
    client.get_performance_report = _failing()

    result = await client.evaluate_cpa_goal("123", target_cpa=2000)

    assert result["current_cpa"] is None
    assert result["deviation_pct"] is None
    assert not _has_issue(result, "0 conversions")
    assert "Failed to retrieve performance report" in result["issues"]
    assert result["status"] == "unknown"
    assert "suggested_workflow" not in result


@pytest.mark.unit
async def test_cv_goal_failed_performance_derives_nothing() -> None:
    client = _MockMonitoringClient()
    client.get_performance_report = _failing()

    result = await client.evaluate_cv_goal("123", target_cv_daily=1.0)

    assert result["current_cv_daily"] is None
    assert result["deviation_pct"] is None
    assert result["bottleneck"] is None
    assert not _has_issue(result, "Daily CV")
    assert "Failed to retrieve performance report" in result["issues"]
    assert result["status"] == "unknown"
    assert "suggested_workflow" not in result


# ---------------------------------------------------------------------------
# diagnose_zero_conversions
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_zero_conversions_failed_actions_report_no_tracking_issue() -> None:
    client = _MockMonitoringClient()
    client.get_campaign = AsyncMock(return_value={"bidding_strategy": "TARGET_CPA"})
    client.list_conversion_actions = _failing()
    client.get_performance_report = _perf(impressions=100, clicks=5, conversions=0)

    result = await client.diagnose_zero_conversions("123")

    alignment = result["bidding_cv_alignment"]
    assert result["conversion_tracking"] is None
    assert alignment["cv_tracking_configured"] is None
    assert alignment["issue"] is None
    assert not _has_issue(result, "No active conversion actions")
    assert not _has_issue(result, "Smart bidding")
    assert "Failed to retrieve conversion action list" in result["issues"]
    actions = [a["action"] for a in result["recommended_actions"]]
    assert "fix_cv_tracking" not in actions
    assert "fix_bidding_strategy" not in actions
    assert result["status"] == "unknown"
    assert "suggested_workflow" not in result


@pytest.mark.unit
async def test_zero_conversions_failed_performance_has_no_funnel() -> None:
    client = _MockMonitoringClient()
    client.list_conversion_actions = AsyncMock(return_value=[{"status": "ENABLED"}])
    client.get_performance_report = _failing()

    result = await client.diagnose_zero_conversions("123")

    assert result["funnel"] is None
    assert not _has_issue(result, "are 0")
    assert "Failed to retrieve performance report" in result["issues"]
    assert result["status"] == "unknown"


@pytest.mark.unit
async def test_zero_conversions_failed_campaign_is_unknown() -> None:
    # The bidding vs tracking check rests on the campaign read: without it
    # the verdict is unknown, not healthy.
    client = _MockMonitoringClient()
    client.get_campaign = _failing()
    client.list_conversion_actions = AsyncMock(return_value=[{"status": "ENABLED"}])
    client.get_performance_report = _perf(impressions=100, clicks=5, conversions=2)

    result = await client.diagnose_zero_conversions("123")

    alignment = result["bidding_cv_alignment"]
    assert alignment["strategy"] is None
    assert alignment["is_smart_bidding"] is None
    assert alignment["cv_tracking_configured"] is True
    assert alignment["issue"] is None
    assert not _has_issue(result, "Smart bidding")
    assert "Failed to retrieve campaign information" in result["issues"]
    assert result["status"] == "unknown"
    assert "suggested_workflow" not in result


@pytest.mark.unit
async def test_zero_conversions_critical_from_read_data_stays_critical() -> None:
    client = _MockMonitoringClient()
    client.list_conversion_actions = _failing()
    client.get_performance_report = _perf(impressions=100, clicks=0)

    result = await client.diagnose_zero_conversions("123")

    assert result["funnel"]["bottleneck"] == "no_clicks"
    assert not _has_issue(result, "No active conversion actions")
    assert result["status"] == "critical"
    assert result["suggested_workflow"] == "cv_acquisition"
