"""One shape for a failed partial read in Google Ads diagnostics (#865).

When one sub-query of a diagnostic / analysis / monitoring result fails, its
key is present with the value ``None`` and the module logs
``Failed to retrieve <what> (<ExceptionClass>)`` at WARNING. Never a sentinel
string, never a ``0`` / ``[]`` / ``{}`` that reads as a real empty result,
never the exception text (a GoogleAdsException carries request metadata,
#603). The rest of the result is still there.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.test_google_ads_analysis import MockAnalysisClient
from tests.test_google_ads_diagnostics import _MockDiagClient
from tests.test_google_ads_monitoring import _MockMonitoringClient

#: Stands in for the request metadata a platform exception can carry.
_SECRET = "developer-token-SECRET-1234"


class _PlatformError(Exception):
    """A failure whose text must never reach a log line."""


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise _PlatformError(_SECRET)


def _assert_warned(caplog: pytest.LogCaptureFixture, logger: str, what: str) -> None:
    """``what`` was logged at WARNING by ``logger`` with the class name only."""
    expected = f"Failed to retrieve {what} (_PlatformError)"
    messages = [
        r.getMessage()
        for r in caplog.records
        if r.name == logger and r.levelno == logging.WARNING
    ]
    assert expected in messages
    assert all(_SECRET not in r.getMessage() for r in caplog.records)
    assert all(r.exc_info is None for r in caplog.records)


# ---------------------------------------------------------------------------
# diagnose_campaign_delivery
# ---------------------------------------------------------------------------

_DIAG_LOGGER = "mureo.google_ads._diagnostics"


def _diag_campaign(strategy: str = "MAXIMIZE_CONVERSIONS") -> dict[str, Any]:
    return {
        "status": "ENABLED",
        "serving_status": "SERVING",
        "primary_status": "ELIGIBLE",
        "primary_status_reasons": [],
        "bidding_strategy_system_status": "",
        "start_date": "",
        "end_date": "",
        "budget_daily": 10000,
        "budget_status": "ENABLED",
        "bidding_details": {"strategy": strategy},
    }


def _diag_client(failing_query: str | None = None) -> _MockDiagClient:
    """A client whose GAQL search raises for the query naming ``failing_query``."""
    client = _MockDiagClient()
    client.get_campaign = AsyncMock(return_value=_diag_campaign())
    client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])
    client.get_performance_report = AsyncMock(
        return_value=[{"metrics": {"impressions": 10, "cost": 100, "conversions": 2}}]
    )
    client.list_sitelinks = AsyncMock(return_value=[{"id": "s1"}])

    async def _search(query: str) -> list[Any]:
        if failing_query is not None and failing_query in query:
            _boom()
        return []

    client._search = _search  # type: ignore[method-assign]
    return client


def _assert_rest_intact(result: dict[str, Any]) -> None:
    for key in ("campaign", "keywords_enabled_count", "ads_enabled_count"):
        assert key in result
    for key in ("issues", "warnings", "recommendations"):
        assert isinstance(result[key], list)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("failing_query", "key", "what"),
    [
        ("FROM billing_setup", "billing_setup", "billing setup"),
        (
            "FROM conversion_action",
            "active_conversion_actions",
            "active conversion actions",
        ),
        (
            "segments.conversion_action_name",
            "conversion_actions_detail",
            "conversion action performance",
        ),
        ("search_impression_share", "impression_share", "impression share"),
    ],
)
async def test_diagnose_failed_search_is_null_and_warned(
    caplog: pytest.LogCaptureFixture, failing_query: str, key: str, what: str
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _diag_client(failing_query)

    result = await client.diagnose_campaign_delivery("123")

    assert key in result
    assert result[key] is None
    _assert_warned(caplog, _DIAG_LOGGER, what)
    _assert_rest_intact(result)


@pytest.mark.unit
async def test_diagnose_failed_performance_is_null_and_skips_cpa_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _diag_client()
    client.get_performance_report = AsyncMock(side_effect=_PlatformError(_SECRET))

    result = await client.diagnose_campaign_delivery("123")

    assert result["performance_last_30_days"] is None
    # The per-action CPA is derived from the 30-day totals, so it is not
    # derivable either: null, not an empty list.
    assert result["conversion_actions_detail"] is None
    _assert_warned(caplog, _DIAG_LOGGER, "last-30-day performance")
    _assert_rest_intact(result)
    assert result["sitelinks_count"] == 1


@pytest.mark.unit
async def test_diagnose_failed_sitelinks_is_null_not_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _diag_client()
    client.list_sitelinks = AsyncMock(side_effect=_PlatformError(_SECRET))

    result = await client.diagnose_campaign_delivery("123")

    assert result["sitelinks_count"] is None
    _assert_warned(caplog, _DIAG_LOGGER, "sitelink count")
    _assert_rest_intact(result)
    assert result["performance_last_30_days"]["impressions"] == 10


@pytest.mark.unit
async def test_diagnose_failed_billing_adds_no_billing_issue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = await _diag_client("FROM billing_setup").diagnose_campaign_delivery("123")

    assert not any("billing" in issue.lower() for issue in result["issues"])


@pytest.mark.unit
async def test_diagnose_failed_cv_count_adds_no_cv_recommendation() -> None:
    client = _diag_client("FROM conversion_action")

    result = await client.diagnose_campaign_delivery("123")

    assert not any("conversion action" in r for r in result["recommendations"])
    assert not any("0 active conversion" in i for i in result["issues"])


@pytest.mark.unit
async def test_diagnose_impression_share_absent_when_no_rows() -> None:
    """No row is not a failure: the key stays absent, as before."""
    result = await _diag_client().diagnose_campaign_delivery("123")

    assert "impression_share" not in result
    assert result["billing_setup"] == "Not configured"
    assert result["active_conversion_actions"] == 0
    assert result["conversion_actions_detail"] == []


# ---------------------------------------------------------------------------
# _analysis_performance
# ---------------------------------------------------------------------------

_PERF_LOGGER = "mureo.google_ads._analysis_performance"


def _analysis_client() -> MockAnalysisClient:
    client = MockAnalysisClient()
    client.get_campaign.return_value = {"id": "123", "status": "ENABLED"}
    client.get_performance_report.return_value = [
        {"metrics": {"impressions": 10, "clicks": 2, "cost": 100, "conversions": 1}}
    ]
    client.get_search_terms_report.return_value = [
        {"search_term": "a", "metrics": {"cost": 10, "conversions": 0}}
    ]
    client.list_recommendations.return_value = [{"type": "KEYWORD"}]
    client.list_change_history.return_value = [{"resource_type": "CAMPAIGN"}]
    client.list_negative_keywords.return_value = []
    return client


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "keys", "what"),
    [
        (
            "get_performance_report",
            ("performance_current", "performance_previous", "changes"),
            "performance comparison",
        ),
        ("get_search_terms_report", ("top_search_terms",), "search terms report"),
        ("list_recommendations", ("recommendations_from_google",), "recommendations"),
        ("list_change_history", ("recent_changes",), "change history"),
    ],
)
async def test_analyze_performance_failed_part_is_null(
    caplog: pytest.LogCaptureFixture, method: str, keys: tuple[str, ...], what: str
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _analysis_client()
    getattr(client, method).side_effect = _PlatformError(_SECRET)

    result = await client.analyze_performance("123")

    for key in keys:
        assert key in result
        assert result[key] is None
    _assert_warned(caplog, _PERF_LOGGER, what)
    assert result["campaign"]["id"] == "123"
    for key in ("issues", "insights", "recommendations"):
        assert isinstance(result[key], list)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "keys", "what"),
    [
        (
            "get_performance_report",
            (
                "performance_current_7d",
                "performance_previous_7d",
                "changes",
                "cost_breakdown",
            ),
            "performance comparison",
        ),
        (
            "get_search_terms_report",
            ("new_search_terms", "wasteful_search_terms"),
            "search term changes",
        ),
        ("list_change_history", ("bid_budget_changes",), "change history"),
        (
            "list_negative_keywords",
            ("existing_negative_keywords_count", "negative_keyword_candidates"),
            "negative keyword candidates",
        ),
    ],
)
async def test_investigate_cost_increase_failed_part_is_null(
    caplog: pytest.LogCaptureFixture, method: str, keys: tuple[str, ...], what: str
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _analysis_client()
    getattr(client, method).side_effect = _PlatformError(_SECRET)

    result = await client.investigate_cost_increase("123")

    for key in keys:
        assert key in result
        assert result[key] is None
    _assert_warned(caplog, _PERF_LOGGER, what)
    assert "cost_breakdown" in result
    assert isinstance(result["findings"], list)


@pytest.mark.unit
async def test_investigate_failed_terms_leave_negative_candidates_null() -> None:
    client = _analysis_client()
    client.get_search_terms_report.side_effect = _PlatformError(_SECRET)

    result = await client.investigate_cost_increase("123")

    assert "negative_keyword_candidates" in result
    assert result["negative_keyword_candidates"] is None
    assert result["existing_negative_keywords_count"] == 0


@pytest.mark.unit
async def test_health_check_failed_diagnosis_is_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _analysis_client()
    client.list_campaigns.return_value = [
        {"id": "7", "name": "C7", "status": "ENABLED", "primary_status": "LIMITED"}
    ]
    client.diagnose_campaign_delivery.side_effect = _PlatformError(_SECRET)

    result = await client.health_check_all_campaigns()

    assert result["detailed_diagnostics"] == [
        {
            "campaign_id": "7",
            "name": "C7",
            "issues": None,
            "warnings": None,
            "recommendations": None,
        }
    ]
    _assert_warned(caplog, _PERF_LOGGER, "detailed diagnostics for campaign 7")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "what"),
    [
        ("get_campaign", "target CPA from the bidding strategy for campaign 123"),
        ("get_performance_report", "actual CPA for campaign 123"),
    ],
)
async def test_resolve_target_cpa_failure_is_warned(
    caplog: pytest.LogCaptureFixture, method: str, what: str
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _analysis_client()
    client.get_campaign.return_value = {"bidding_details": {}}
    getattr(client, method).side_effect = _PlatformError(_SECRET)

    await client._resolve_target_cpa("123")

    _assert_warned(caplog, _PERF_LOGGER, what)


# ---------------------------------------------------------------------------
# _analysis_budget
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_reallocation_failed_budget_is_null_and_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = MockAnalysisClient()
    client.list_campaigns.return_value = [
        {"id": "1", "name": "Efficient", "status": "ENABLED"},
        {"id": "2", "name": "Inefficient", "status": "ENABLED"},
        {"id": "3", "name": "Efficient too", "status": "ENABLED"},
    ]
    client.get_performance_report.side_effect = [
        [{"metrics": {"cost": 3000, "conversions": 10}}],
        [{"metrics": {"cost": 7000, "conversions": 2}}],
        [{"metrics": {"cost": 3000, "conversions": 10}}],
    ]
    client.get_budget.side_effect = [
        {"daily_budget": 5000, "id": "b1"},
        {"daily_budget": 10000, "id": "b2"},
        _PlatformError(_SECRET),
    ]

    result = await client.suggest_budget_reallocation()

    failed = next(c for c in result["campaigns"] if c["campaign_id"] == "3")
    assert failed["current_daily_budget"] is None
    assert failed["budget_id"] is None
    _assert_warned(caplog, "mureo.google_ads._analysis_budget", "budget for campaign 3")
    plan = result["reallocation_plan"]
    # The campaign whose budget is unknown gets no INCREASE line: a
    # proposal needs a current budget to start from.
    assert [p["campaign_id"] for p in plan if p["action"] == "INCREASE"] == ["1"]
    decrease = next(p for p in plan if p["action"] == "DECREASE")
    assert decrease["campaign_id"] == "2"
    increase = next(p for p in plan if p["action"] == "INCREASE")
    assert increase["change_amount"] == -decrease["change_amount"]


@pytest.mark.unit
async def test_reallocation_inefficient_with_unknown_budget_is_not_cut() -> None:
    client = MockAnalysisClient()
    client.list_campaigns.return_value = [
        {"id": "1", "name": "Efficient", "status": "ENABLED"},
        {"id": "2", "name": "Inefficient", "status": "ENABLED"},
    ]
    client.get_performance_report.side_effect = [
        [{"metrics": {"cost": 3000, "conversions": 10}}],
        [{"metrics": {"cost": 7000, "conversions": 2}}],
    ]
    client.get_budget.side_effect = [
        {"daily_budget": 5000, "id": "b1"},
        _PlatformError(_SECRET),
    ]

    result = await client.suggest_budget_reallocation()

    assert result["reallocation_plan"] == []


@pytest.mark.unit
async def test_reallocation_inefficient_without_conversions_is_cut() -> None:
    client = MockAnalysisClient()
    client.list_campaigns.return_value = [
        {"id": "1", "name": "Efficient", "status": "ENABLED"},
        {"id": "2", "name": "No conversions", "status": "ENABLED"},
    ]
    client.get_performance_report.side_effect = [
        [{"metrics": {"cost": 3000, "conversions": 10}}],
        [{"metrics": {"cost": 7000, "conversions": 0}}],
    ]
    client.get_budget.side_effect = [
        {"daily_budget": 5000, "id": "b1"},
        {"daily_budget": 10000, "id": "b2"},
    ]

    result = await client.suggest_budget_reallocation()

    plan = result["reallocation_plan"]
    decrease = next(p for p in plan if p["action"] == "DECREASE")
    assert decrease["campaign_id"] == "2"
    assert "(CPA: ¥0)" in decrease["reason"]


# ---------------------------------------------------------------------------
# _monitoring
# ---------------------------------------------------------------------------

_MON_LOGGER = "mureo.google_ads._monitoring"


@pytest.mark.unit
async def test_delivery_goal_failed_parts_are_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _MockMonitoringClient()
    client.get_campaign = AsyncMock(return_value={"status": "ENABLED"})
    client.diagnose_campaign_delivery = AsyncMock(side_effect=_PlatformError(_SECRET))
    client.get_performance_report = AsyncMock(side_effect=_PlatformError(_SECRET))

    result = await client.evaluate_delivery_goal("123")

    assert result["diagnosis"] is None
    assert result["performance"] is None
    _assert_warned(caplog, _MON_LOGGER, "delivery diagnostics")
    _assert_warned(caplog, _MON_LOGGER, "previous day performance")
    assert result["campaign"] == {"status": "ENABLED"}
    assert result["status"] == "unknown"


@pytest.mark.unit
async def test_cpa_goal_failed_cost_analysis_is_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _MockMonitoringClient()
    client.get_performance_report = AsyncMock(
        return_value=[{"metrics": {"cost": 1000, "conversions": 1}}]
    )
    client.investigate_cost_increase = AsyncMock(side_effect=_PlatformError(_SECRET))

    result = await client.evaluate_cpa_goal("123", target_cpa=2000)

    assert result["cost_analysis"] is None
    assert result["wasteful_terms"] is None
    _assert_warned(caplog, _MON_LOGGER, "cost analysis")
    assert result["current_cpa"] == 1000.0
    assert result["status"] == "healthy"


@pytest.mark.unit
async def test_cv_goal_failed_performance_analysis_is_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _MockMonitoringClient()
    client.get_performance_report = AsyncMock(
        return_value=[
            {"metrics": {"impressions": 1000, "clicks": 50, "conversions": 7}}
        ]
    )
    client.analyze_performance = AsyncMock(side_effect=_PlatformError(_SECRET))

    result = await client.evaluate_cv_goal("123", target_cv_daily=1.0)

    assert result["performance_analysis"] is None
    _assert_warned(caplog, _MON_LOGGER, "performance analysis")
    assert result["status"] == "healthy"
    assert result["bottleneck"] == "cvr"


@pytest.mark.unit
async def test_zero_conversions_failed_parts_are_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _MockMonitoringClient()
    client.list_conversion_actions = AsyncMock(side_effect=_PlatformError(_SECRET))
    client.diagnose_campaign_delivery = AsyncMock(side_effect=_PlatformError(_SECRET))
    client.get_performance_report = AsyncMock(
        return_value=[{"metrics": {"impressions": 100, "clicks": 5}}]
    )

    result = await client.diagnose_zero_conversions("123")

    assert result["conversion_tracking"] is None
    assert result["delivery_diagnosis"] is None
    _assert_warned(caplog, _MON_LOGGER, "conversion action list")
    _assert_warned(caplog, _MON_LOGGER, "delivery diagnostics")
    assert result["funnel"]["impressions"] == 100
    assert result["status"] == "unknown"
