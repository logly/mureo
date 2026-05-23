"""Tests for the diagnose_performance live wiring and result-indicator
mismatch detection.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.analytics.builtin.google_ads import (
    GoogleAdsAnalyticsModule,
    _summarise_performance,
)
from mureo.analytics.builtin.meta_ads import (
    MetaAdsAnalyticsModule,
    _classify_result_indicator,
    _detect_cv_definition_mismatch,
    _summarise_meta_performance,
)
from mureo.analytics.models import PerformanceScope

# ---------------------------------------------------------------------------
# Google Ads — pure summariser
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_google_summarise_empty_returns_no_data_headline() -> None:
    diag = _summarise_performance(
        platform="google_ads",
        account_id="acct-1",
        scope=PerformanceScope.ACCOUNT,
        rows=[],
    )
    assert diag.headline == "no performance data available"
    assert diag.findings == ()


@pytest.mark.unit
def test_google_summarise_aggregates_two_campaigns() -> None:
    rows: list[dict[str, Any]] = [
        {
            "metrics": {
                "cost": 1000.0,
                "impressions": 5000,
                "clicks": 100,
                "conversions": 5,
            }
        },
        {
            "metrics": {
                "cost": 2000.0,
                "impressions": 10000,
                "clicks": 200,
                "conversions": 10,
            }
        },
    ]
    diag = _summarise_performance(
        platform="google_ads",
        account_id="acct-1",
        scope=PerformanceScope.ACCOUNT,
        rows=rows,
    )
    metrics = dict(diag.metrics)
    assert metrics["cost"] == 3000.0
    assert metrics["impressions"] == 15000.0
    assert metrics["conversions"] == 15.0
    assert metrics["cpa"] == pytest.approx(200.0)
    assert "2 campaign(s)" in diag.findings[0]


@pytest.mark.unit
def test_google_summarise_deep_scope_flags_no_drilldown() -> None:
    rows: list[dict[str, Any]] = [
        {
            "metrics": {
                "cost": 100.0,
                "impressions": 1000,
                "clicks": 30,
                "conversions": 2,
            }
        },
    ]
    diag = _summarise_performance(
        platform="google_ads",
        account_id="a",
        scope=PerformanceScope.DEEP,
        rows=rows,
    )
    assert any("drilldown not yet implemented" in f for f in diag.findings)


@pytest.mark.unit
def test_google_summarise_skips_cpa_when_no_conversions() -> None:
    rows: list[dict[str, Any]] = [
        {
            "metrics": {
                "cost": 100.0,
                "impressions": 1000,
                "clicks": 30,
                "conversions": 0,
            }
        },
    ]
    diag = _summarise_performance(
        platform="google_ads",
        account_id="a",
        scope=PerformanceScope.ACCOUNT,
        rows=rows,
    )
    metrics = dict(diag.metrics)
    assert "cpa" not in metrics


# ---------------------------------------------------------------------------
# Google Ads — adapter wiring (uses injected performance_fetcher)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_adapter_diagnose_uses_injected_fetcher() -> None:
    captured: dict[str, Any] = {}

    async def fetcher(account_id: str, period: str) -> list[dict[str, object]]:
        captured["account_id"] = account_id
        captured["period"] = period
        return [
            {
                "metrics": {
                    "cost": 500.0,
                    "impressions": 2000,
                    "clicks": 50,
                    "conversions": 4,
                }
            },
        ]

    adapter = GoogleAdsAnalyticsModule(performance_fetcher=fetcher)
    diag = await adapter.diagnose_performance("acct-9", scope=PerformanceScope.ACCOUNT)
    assert captured == {"account_id": "acct-9", "period": "LAST_7_DAYS"}
    assert "spend=500" in diag.headline


@pytest.mark.asyncio
async def test_google_adapter_diagnose_deep_scope_uses_longer_period() -> None:
    captured: dict[str, str] = {}

    async def fetcher(account_id: str, period: str) -> list[dict[str, object]]:
        captured["period"] = period
        return []

    adapter = GoogleAdsAnalyticsModule(performance_fetcher=fetcher)
    await adapter.diagnose_performance("acct", scope=PerformanceScope.DEEP)
    assert captured["period"] == "LAST_30_DAYS"


# ---------------------------------------------------------------------------
# Meta Ads — result-indicator classifier
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_result_indicator_click() -> None:
    assert _classify_result_indicator(["link_click", "video_play"]) == "click"


@pytest.mark.unit
def test_classify_result_indicator_conversion_wins_over_click() -> None:
    # A conversion campaign that also records clicks remains a
    # conversion campaign — clicks are the cheaper signal.
    assert (
        _classify_result_indicator(["link_click", "offsite_conversion.fb_pixel_lead"])
        == "conversion"
    )


@pytest.mark.unit
def test_classify_result_indicator_unknown_for_empty() -> None:
    assert _classify_result_indicator([]) == "unknown"


@pytest.mark.unit
def test_detect_cv_mismatch_when_both_styles_present() -> None:
    rows: list[dict[str, Any]] = [
        {"actions": [{"action_type": "link_click"}]},
        {
            "actions": [
                {"action_type": "offsite_conversion.fb_pixel_lead"},
            ]
        },
    ]
    finding = _detect_cv_definition_mismatch(rows)
    assert finding is not None
    assert "mismatch" in finding


@pytest.mark.unit
def test_detect_cv_mismatch_returns_none_when_uniform() -> None:
    rows: list[dict[str, Any]] = [
        {"actions": [{"action_type": "offsite_conversion.fb_pixel_lead"}]},
        {"actions": [{"action_type": "lead"}]},
    ]
    assert _detect_cv_definition_mismatch(rows) is None


@pytest.mark.unit
def test_detect_cv_mismatch_handles_missing_actions() -> None:
    rows: list[dict[str, Any]] = [{}, {"actions": "not_a_list"}]
    assert _detect_cv_definition_mismatch(rows) is None


# ---------------------------------------------------------------------------
# Meta Ads — summariser
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_meta_summarise_includes_cv_mismatch_finding() -> None:
    rows: list[dict[str, Any]] = [
        {
            "spend": 100,
            "impressions": 1000,
            "clicks": 50,
            "actions": [{"action_type": "link_click", "value": 50}],
        },
        {
            "spend": 200,
            "impressions": 2000,
            "clicks": 80,
            "actions": [
                {"action_type": "offsite_conversion.fb_pixel_lead", "value": 5},
            ],
        },
    ]
    diag = _summarise_meta_performance(
        platform="meta_ads",
        account_id="act_1",
        scope=PerformanceScope.ACCOUNT,
        rows=rows,
    )
    assert any("mismatch" in f for f in diag.findings)


@pytest.mark.unit
def test_meta_summarise_no_data() -> None:
    diag = _summarise_meta_performance(
        platform="meta_ads",
        account_id="act_1",
        scope=PerformanceScope.ACCOUNT,
        rows=[],
    )
    assert diag.headline == "no performance data available"


# ---------------------------------------------------------------------------
# Meta Ads — adapter wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_adapter_diagnose_renders_sentinel_on_missing_creds() -> None:
    """When the live fetcher raises ``NoCredentialsError``, the adapter
    must render a sentinel :class:`PerformanceDiagnosis` rather than an
    empty-data one — so callers can tell ``no data`` apart from
    ``creds missing``.
    """
    from unittest.mock import patch

    adapter = GoogleAdsAnalyticsModule()  # no fetcher → live path
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_google_ads_credentials", return_value=None),
    ):
        diag = await adapter.diagnose_performance(
            "acct-x", scope=PerformanceScope.ACCOUNT
        )
    assert diag.headline == "google_ads credentials not configured"
    assert diag.findings == ()


@pytest.mark.asyncio
async def test_meta_adapter_diagnose_renders_sentinel_on_missing_creds() -> None:
    from unittest.mock import patch

    adapter = MetaAdsAnalyticsModule()
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_meta_ads_credentials", return_value=None),
    ):
        diag = await adapter.diagnose_performance(
            "act_x", scope=PerformanceScope.ACCOUNT
        )
    assert diag.headline == "meta_ads credentials not configured"


@pytest.mark.asyncio
async def test_meta_adapter_diagnose_uses_injected_fetcher() -> None:
    captured: dict[str, str] = {}

    async def fetcher(account_id: str, period: str) -> list[dict[str, object]]:
        captured["period"] = period
        return [
            {
                "spend": 50,
                "impressions": 500,
                "clicks": 20,
                "actions": [{"action_type": "link_click", "value": 20}],
            }
        ]

    adapter = MetaAdsAnalyticsModule(performance_fetcher=fetcher)
    diag = await adapter.diagnose_performance("act_42", scope=PerformanceScope.ACCOUNT)
    assert captured["period"] == "last_7d"
    assert "1 campaign" in diag.findings[0]
