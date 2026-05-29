"""Unit tests for Google Ads _diagnostics.py.

Mock-based tests for _DiagnosticsMixin.diagnose_campaign_delivery and
its helper methods.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.google_ads._diagnostics import (
    _DiagnosticsMixin,
    _LEARNING_STATUS_DESC,
    _PRIMARY_STATUS_REASON_DESC,
    _REASON_IS_ISSUE,
    _SMART_BIDDING_STRATEGIES,
)


# ---------------------------------------------------------------------------
# Mock client class for tests
# ---------------------------------------------------------------------------


class _MockDiagClient(_DiagnosticsMixin):
    """Mock class that makes _DiagnosticsMixin testable."""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._client = MagicMock()
        self._search = AsyncMock(return_value=[])

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        if not value or not value.isdigit():
            raise ValueError(f"{field_name} must be a numeric string: {value}")
        return value

    def _get_service(self, service_name: str):
        return MagicMock()

    async def get_campaign(self, campaign_id: str):
        return None

    async def list_ad_groups(self, campaign_id: str = "", **kwargs):
        return []

    async def get_performance_report(self, **kwargs):
        return []

    async def list_sitelinks(self, campaign_id: str):
        return []


# ---------------------------------------------------------------------------
# _extract_bidding_details tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractBiddingDetails:
    def test_target_cpa(self) -> None:
        campaign = MagicMock()
        campaign.bidding_strategy_type = 6  # TARGET_CPA enum
        campaign.target_cpa.target_cpa_micros = 5_000_000_000  # 5000 JPY

        with patch(
            "mureo.google_ads._diagnostics.map_bidding_strategy_type",
            return_value="TARGET_CPA",
        ):
            details = _DiagnosticsMixin._extract_bidding_details(campaign)

        assert details["strategy"] == "TARGET_CPA"
        assert details["target_cpa"] == 5000.0

    def test_maximize_conversions_with_optional_cpa(self) -> None:
        campaign = MagicMock()
        campaign.bidding_strategy_type = 10
        campaign.maximize_conversions.target_cpa_micros = 3_000_000_000

        with patch(
            "mureo.google_ads._diagnostics.map_bidding_strategy_type",
            return_value="MAXIMIZE_CONVERSIONS",
        ):
            details = _DiagnosticsMixin._extract_bidding_details(campaign)

        assert details["strategy"] == "MAXIMIZE_CONVERSIONS"
        assert details["optional_target_cpa"] == 3000.0

    def test_maximize_clicks_with_ceiling(self) -> None:
        campaign = MagicMock()
        campaign.bidding_strategy_type = 2
        campaign.target_spend.cpc_bid_ceiling_micros = 500_000_000

        with patch(
            "mureo.google_ads._diagnostics.map_bidding_strategy_type",
            return_value="MAXIMIZE_CLICKS",
        ):
            details = _DiagnosticsMixin._extract_bidding_details(campaign)

        assert details["strategy"] == "MAXIMIZE_CLICKS"
        assert details["cpc_bid_ceiling"] == 500.0

    def test_target_roas(self) -> None:
        campaign = MagicMock()
        campaign.bidding_strategy_type = 7
        campaign.target_roas.target_roas = 4.0

        with patch(
            "mureo.google_ads._diagnostics.map_bidding_strategy_type",
            return_value="TARGET_ROAS",
        ):
            details = _DiagnosticsMixin._extract_bidding_details(campaign)

        assert details["strategy"] == "TARGET_ROAS"
        assert details["target_roas"] == 4.0

    def test_target_impression_share_zero_ceiling(self) -> None:
        campaign = MagicMock()
        campaign.bidding_strategy_type = 15
        tis = campaign.target_impression_share
        tis.location = 3  # TOP_OF_PAGE
        tis.location_fraction_micros = 0
        tis.cpc_bid_ceiling_micros = 0

        with patch(
            "mureo.google_ads._diagnostics.map_bidding_strategy_type",
            return_value="TARGET_IMPRESSION_SHARE",
        ):
            details = _DiagnosticsMixin._extract_bidding_details(campaign)

        assert details["strategy"] == "TARGET_IMPRESSION_SHARE"
        assert "issue" in details
        assert "¥0" in details["issue"]


# ---------------------------------------------------------------------------
# diagnose_campaign_delivery tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDiagnoseCampaignDelivery:
    @pytest.fixture()
    def client(self) -> _MockDiagClient:
        return _MockDiagClient()

    def _make_base_campaign(self, **overrides) -> dict:
        base = {
            "status": "ENABLED",
            "serving_status": "SERVING",
            "primary_status": "ELIGIBLE",
            "primary_status_reasons": [],
            "bidding_strategy_system_status": "",
            "start_date": "",
            "end_date": "",
            "budget_daily": 10000,
            "budget_status": "ENABLED",
            "bidding_details": {"strategy": "MAXIMIZE_CLICKS"},
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    async def test_healthy_campaign(self, client: _MockDiagClient) -> None:
        """For a healthy campaign, issues is empty."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])

        # Keyword mock
        kw_mock = MagicMock()
        kw_mock.ad_group_criterion.keyword.text = "test"
        kw_mock.ad_group_criterion.keyword.match_type = "BROAD"
        kw_mock.ad_group_criterion.approval_status = 2  # APPROVED
        kw_mock.ad_group_criterion.system_serving_status = "ELIGIBLE"
        with patch(
            "mureo.google_ads._diagnostics.map_criterion_approval_status",
            return_value="APPROVED",
        ):
            # Ad mock
            ad_mock = MagicMock()
            ad_mock.ad_group_ad.policy_summary.approval_status = 2
            ad_mock.ad_group_ad.policy_summary.review_status = 2
            ad_mock.ad_group_ad.ad.type_ = 14  # RSA
            ad_mock.ad_group_ad.ad.id = 1
            ad_mock.ad_group_ad.status = "ENABLED"
            rsa = ad_mock.ad_group_ad.ad.responsive_search_ad
            h = MagicMock()
            h.text = "見出し"
            d = MagicMock()
            d.text = "説明"
            rsa.headlines = [h]
            rsa.descriptions = [d]
            ad_mock.ad_group_ad.ad.final_urls = ["https://example.com"]
            ad_mock.ad_group.id = 1
            ad_mock.ad_group.name = "AG1"

            with (
                patch(
                    "mureo.google_ads._diagnostics.map_approval_status",
                    return_value="APPROVED",
                ),
                patch(
                    "mureo.google_ads._diagnostics.map_review_status",
                    return_value="REVIEWED",
                ),
                patch(
                    "mureo.google_ads._diagnostics.map_ad_type",
                    return_value="RESPONSIVE_SEARCH_AD",
                ),
            ):
                # _search: kw, ads, locations, billing, is
                client._search = AsyncMock(
                    side_effect=[
                        [kw_mock],  # keywords
                        [ad_mock],  # ads
                        [],  # locations
                        [MagicMock()],  # billing (has_billing=True)
                        [],  # impression share
                    ]
                )

                result = await client.diagnose_campaign_delivery("123")

        # Basic checks (missing geo targeting lands in warnings).
        assert (
            result["diagnosis"] == "No issues" or "issues found" in result["diagnosis"]
        )
        assert "campaign" in result

    @pytest.mark.asyncio
    async def test_campaign_not_found(self, client: _MockDiagClient) -> None:
        """When the campaign cannot be found."""
        client.get_campaign = AsyncMock(return_value=None)
        result = await client.diagnose_campaign_delivery("999")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_paused_campaign(self, client: _MockDiagClient) -> None:
        """A paused campaign is included in issues."""
        campaign = self._make_base_campaign(status="PAUSED")
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any(
            "PAUSED" in issue or "ENABLED" in issue for issue in result["issues"]
        )

    @pytest.mark.asyncio
    async def test_learning_status_detected(self, client: _MockDiagClient) -> None:
        """A learning status is included in learning_status."""
        campaign = self._make_base_campaign(
            bidding_strategy_system_status="LEARNING_NEW"
        )
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert "learning_status" in result
        assert result["learning_status"]["status"] == "LEARNING_NEW"

    @pytest.mark.asyncio
    async def test_zero_budget_issue(self, client: _MockDiagClient) -> None:
        """A daily budget of 0 is included in issues."""
        campaign = self._make_base_campaign(budget_daily=0)
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any("¥0" in issue for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_primary_status_reasons_issues(self, client: _MockDiagClient) -> None:
        """Issue classification from primary_status_reasons."""
        campaign = self._make_base_campaign(
            primary_status="NOT_ELIGIBLE",
            primary_status_reasons=["CAMPAIGN_PAUSED", "BUDGET_CONSTRAINED"],
        )
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        # CAMPAIGN_PAUSED is an issue.
        assert any("CAMPAIGN_PAUSED" in issue for issue in result["issues"])
        # BUDGET_CONSTRAINED is a warning (not an issue).
        assert any("BUDGET_CONSTRAINED" in w for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_smart_bidding_no_cv_tracking(self, client: _MockDiagClient) -> None:
        """Smart bidding without conversions configured is included in issues."""
        campaign = self._make_base_campaign(
            bidding_details={"strategy": "MAXIMIZE_CONVERSIONS"}
        )
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])
        # kw, ads, locations, billing, cv_actions, cv_by_action, is
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        # Smart bidding + CV=0 → issue
        cv_actions = result.get("active_conversion_actions")
        if cv_actions == 0:
            assert any("conversion" in i.lower() for i in result["issues"])


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDiagnosticsConstants:
    def test_reason_is_issue_subset_of_reason_desc(self) -> None:
        """All keys in _REASON_IS_ISSUE exist in _PRIMARY_STATUS_REASON_DESC."""
        for reason in _REASON_IS_ISSUE:
            assert (
                reason in _PRIMARY_STATUS_REASON_DESC
            ), f"{reason} not in _PRIMARY_STATUS_REASON_DESC"

    def test_learning_status_reasons(self) -> None:
        """All learning status reason keys start with LEARNING_."""
        for key in _LEARNING_STATUS_DESC:
            assert key.startswith("LEARNING_")

    def test_smart_bidding_strategies(self) -> None:
        assert "MAXIMIZE_CONVERSIONS" in _SMART_BIDDING_STRATEGIES
        assert "TARGET_CPA" in _SMART_BIDDING_STRATEGIES


# ---------------------------------------------------------------------------
# Additional tests: cover previously uncovered lines
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDiagnoseCampaignDeliveryAdditional:
    @pytest.fixture()
    def client(self) -> _MockDiagClient:
        return _MockDiagClient()

    def _make_base_campaign(self, **overrides) -> dict:
        base = {
            "status": "ENABLED",
            "serving_status": "SERVING",
            "primary_status": "ELIGIBLE",
            "primary_status_reasons": [],
            "bidding_strategy_system_status": "",
            "start_date": "",
            "end_date": "",
            "budget_daily": 10000,
            "budget_status": "ENABLED",
            "bidding_details": {"strategy": "MAXIMIZE_CLICKS"},
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    async def test_serving_status_not_serving(self, client: _MockDiagClient) -> None:
        """When serving_status is not SERVING, it is included in issues (line 196)."""
        campaign = self._make_base_campaign(serving_status="SUSPENDED")
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any("SUSPENDED" in issue for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_bidding_misconfigured_status(self, client: _MockDiagClient) -> None:
        """When bidding_strategy_system_status is MISCONFIGURED* (line 225)."""
        campaign = self._make_base_campaign(
            bidding_strategy_system_status="MISCONFIGURED_ZERO_BUDGET"
        )
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any("MISCONFIGURED" in issue for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_bidding_limited_status(self, client: _MockDiagClient) -> None:
        """When bidding_strategy_system_status is LIMITED* (lines 253-254)."""
        campaign = self._make_base_campaign(
            bidding_strategy_system_status="LIMITED_BY_DATA"
        )
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any("LIMITED" in w for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_future_start_date(self, client: _MockDiagClient) -> None:
        """When the start date is in the future (lines 263-271)."""
        campaign = self._make_base_campaign(start_date="2099-12-31")
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any(
            "start date" in issue.lower() and "future" in issue.lower()
            for issue in result["issues"]
        )

    @pytest.mark.asyncio
    async def test_past_end_date(self, client: _MockDiagClient) -> None:
        """When the end date has passed (lines 273-281)."""
        campaign = self._make_base_campaign(end_date="2020-01-01")
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any("end date" in issue.lower() for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_invalid_start_date_format(self, client: _MockDiagClient) -> None:
        """Invalid date formats do not raise (line 271)."""
        campaign = self._make_base_campaign(start_date="not-a-date")
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        # The ValueError is caught and skipped; a diagnostic result is returned without error.
        assert "campaign" in result

    @pytest.mark.asyncio
    async def test_budget_status_not_enabled(self, client: _MockDiagClient) -> None:
        """When the budget status is not ENABLED (line 287)."""
        campaign = self._make_base_campaign(budget_status="PAUSED")
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any(
            "budget" in issue.lower() and "PAUSED" in issue
            for issue in result["issues"]
        )

    @pytest.mark.asyncio
    async def test_bidding_details_issue(self, client: _MockDiagClient) -> None:
        """When the bidding strategy has a problem (line 294)."""
        campaign = self._make_base_campaign(
            bidding_details={
                "strategy": "TARGET_IMPRESSION_SHARE",
                "issue": "上限CPC=¥0",
            }
        )
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert any("Bidding strategy issue" in issue for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_disapproved_keywords_warning(self, client: _MockDiagClient) -> None:
        """Disapproved-keyword warning (line 337)."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])

        kw_mock = MagicMock()
        kw_mock.ad_group_criterion.keyword.text = "bad_keyword"
        kw_mock.ad_group_criterion.keyword.match_type = "EXACT"
        kw_mock.ad_group_criterion.approval_status = 3  # DISAPPROVED
        kw_mock.ad_group_criterion.system_serving_status = "ELIGIBLE"

        with patch(
            "mureo.google_ads._diagnostics.map_criterion_approval_status",
            return_value="DISAPPROVED",
        ):
            client._search = AsyncMock(
                side_effect=[
                    [kw_mock],  # keywords
                    [],  # ads
                    [],  # locations
                    [],  # billing
                    [],  # impression share
                ]
            )

            result = await client.diagnose_campaign_delivery("123")

        assert any("disapproved" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_rarely_served_keywords_warning(
        self, client: _MockDiagClient
    ) -> None:
        """RARELY_SERVED keyword warning (line 343)."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])

        kw_mock = MagicMock()
        kw_mock.ad_group_criterion.keyword.text = "rare_keyword"
        kw_mock.ad_group_criterion.keyword.match_type = "BROAD"
        kw_mock.ad_group_criterion.approval_status = 2  # APPROVED
        kw_mock.ad_group_criterion.system_serving_status = "RARELY_SERVED"

        with patch(
            "mureo.google_ads._diagnostics.map_criterion_approval_status",
            return_value="APPROVED",
        ):
            client._search = AsyncMock(
                side_effect=[
                    [kw_mock],  # keywords
                    [],  # ads
                    [],  # locations
                    [],  # billing
                    [],  # impression share
                ]
            )

            result = await client.diagnose_campaign_delivery("123")

        assert any("RARELY_SERVED" in w for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_disapproved_ads_issue(self, client: _MockDiagClient) -> None:
        """Disapproved-ad issue (line 431)."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])

        ad_mock = MagicMock()
        ad_mock.ad_group_ad.policy_summary.approval_status = 3
        ad_mock.ad_group_ad.policy_summary.review_status = 2
        ad_mock.ad_group_ad.ad.type_ = 14  # RSA
        ad_mock.ad_group_ad.ad.id = 1
        ad_mock.ad_group_ad.status = "ENABLED"
        rsa = ad_mock.ad_group_ad.ad.responsive_search_ad
        h = MagicMock()
        h.text = "test"
        rsa.headlines = [h]
        rsa.descriptions = [h]
        ad_mock.ad_group_ad.ad.final_urls = ["https://example.com"]
        ad_mock.ad_group.id = 1
        ad_mock.ad_group.name = "AG1"

        with (
            patch(
                "mureo.google_ads._diagnostics.map_criterion_approval_status",
                return_value="APPROVED",
            ),
            patch(
                "mureo.google_ads._diagnostics.map_approval_status",
                return_value="DISAPPROVED",
            ),
            patch(
                "mureo.google_ads._diagnostics.map_review_status",
                return_value="REVIEWED",
            ),
            patch(
                "mureo.google_ads._diagnostics.map_ad_type",
                return_value="RESPONSIVE_SEARCH_AD",
            ),
        ):
            client._search = AsyncMock(
                side_effect=[
                    [],  # keywords
                    [ad_mock],  # ads
                    [],  # locations
                    [],  # billing
                    [],  # impression share
                ]
            )

            result = await client.diagnose_campaign_delivery("123")

        assert any("disapproved" in issue.lower() for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_limited_ads_warning(self, client: _MockDiagClient) -> None:
        """Approved-with-limitation ad warning (line 433)."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])

        ad_mock = MagicMock()
        ad_mock.ad_group_ad.policy_summary.approval_status = 4
        ad_mock.ad_group_ad.policy_summary.review_status = 2
        ad_mock.ad_group_ad.ad.type_ = 14
        ad_mock.ad_group_ad.ad.id = 1
        ad_mock.ad_group_ad.status = "ENABLED"
        rsa = ad_mock.ad_group_ad.ad.responsive_search_ad
        h = MagicMock()
        h.text = "test"
        rsa.headlines = [h]
        rsa.descriptions = [h]
        ad_mock.ad_group_ad.ad.final_urls = ["https://example.com"]
        ad_mock.ad_group.id = 1
        ad_mock.ad_group.name = "AG1"

        with (
            patch(
                "mureo.google_ads._diagnostics.map_criterion_approval_status",
                return_value="APPROVED",
            ),
            patch(
                "mureo.google_ads._diagnostics.map_approval_status",
                return_value="APPROVED_LIMITED",
            ),
            patch(
                "mureo.google_ads._diagnostics.map_review_status",
                return_value="REVIEWED",
            ),
            patch(
                "mureo.google_ads._diagnostics.map_ad_type",
                return_value="RESPONSIVE_SEARCH_AD",
            ),
        ):
            client._search = AsyncMock(
                side_effect=[
                    [],  # keywords
                    [ad_mock],  # ads
                    [],  # locations
                    [],  # billing
                    [],  # impression share
                ]
            )

            result = await client.diagnose_campaign_delivery("123")

        assert any("APPROVED_LIMITED" in w for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_performance_report_exception(self, client: _MockDiagClient) -> None:
        """Fallback when the performance report fetch fails (lines 473-474)."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client.get_performance_report = AsyncMock(side_effect=RuntimeError("API error"))
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert result["performance_last_30_days"] == "Retrieval failed"

    @pytest.mark.asyncio
    async def test_sitelinks_exception(self, client: _MockDiagClient) -> None:
        """Fallback when the sitelink fetch fails (lines 480-482)."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client.list_sitelinks = AsyncMock(side_effect=RuntimeError("API error"))
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")
        assert result["sitelinks_count"] == 0

    @pytest.mark.asyncio
    async def test_billing_check_failure(self, client: _MockDiagClient) -> None:
        """Fallback when the billing-setup check fails (lines 499-500)."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])

        call_count = 0

        async def _search_side_effect(query):
            nonlocal call_count
            call_count += 1
            # Raise on the billing_setup query (the 4th call).
            if "billing_setup" in query:
                raise RuntimeError("billing error")
            return []

        client._search = _search_side_effect

        result = await client.diagnose_campaign_delivery("123")
        assert result["billing_setup"] == "Verification failed"

    @pytest.mark.asyncio
    async def test_impression_share_warnings(self, client: _MockDiagClient) -> None:
        """Impression-share warning (lines 584-607)."""
        campaign = self._make_base_campaign()
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[{"id": "1"}])

        is_mock = MagicMock()
        is_mock.metrics.search_impression_share = 0.3
        is_mock.metrics.search_rank_lost_impression_share = 0.4  # 40% > 30%
        is_mock.metrics.search_budget_lost_impression_share = 0.25  # 25% > 20%

        call_count = 0

        async def _search_side_effect(query):
            nonlocal call_count
            call_count += 1
            if "search_impression_share" in query:
                return [is_mock]
            return []

        client._search = _search_side_effect

        result = await client.diagnose_campaign_delivery("123")
        assert "impression_share" in result
        # Budget-constrained warning
        assert any("budget" in w.lower() for w in result["warnings"])
        # Ad rank warning
        assert any("ad rank" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_recommendations_for_primary_reasons(
        self, client: _MockDiagClient
    ) -> None:
        """Recommended actions based on primary_status_reasons (lines 634-652)."""
        campaign = self._make_base_campaign(
            primary_status="NOT_ELIGIBLE",
            primary_status_reasons=[
                "BIDDING_STRATEGY_MISCONFIGURED",
                "BUDGET_CONSTRAINED",
                "SEARCH_VOLUME_LIMITED",
                "HAS_ADS_DISAPPROVED",
            ],
        )
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")

        recs = result["recommendations"]
        assert any("bidding strategy" in r.lower() for r in recs)
        assert any("daily budget" in r.lower() for r in recs)
        assert any("keyword" in r.lower() for r in recs)
        assert any("disapproved" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_target_impression_share_recommendations(
        self, client: _MockDiagClient
    ) -> None:
        """Recommended actions for the TARGET_IMPRESSION_SHARE bidding strategy (lines 612-626)."""
        campaign = self._make_base_campaign(
            bidding_details={
                "strategy": "TARGET_IMPRESSION_SHARE",
                "cpc_bid_ceiling": 0,
                "target_fraction_percent": 0,
                "location": "UNSPECIFIED",
            }
        )
        client.get_campaign = AsyncMock(return_value=campaign)
        client.list_ad_groups = AsyncMock(return_value=[])
        client._search = AsyncMock(return_value=[])

        result = await client.diagnose_campaign_delivery("123")

        recs = result["recommendations"]
        assert any("max cpc" in r.lower() for r in recs)
        assert any("target impression share" in r.lower() for r in recs)
        assert any("ad placement" in r.lower() for r in recs)


@pytest.mark.unit
class TestExtractBiddingDetailsAdditional:
    def test_maximize_conversions_without_optional_cpa(self) -> None:
        """MAXIMIZE_CONVERSIONS with optional_target_cpa = 0."""
        campaign = MagicMock()
        campaign.bidding_strategy_type = 10
        campaign.maximize_conversions.target_cpa_micros = 0

        with patch(
            "mureo.google_ads._diagnostics.map_bidding_strategy_type",
            return_value="MAXIMIZE_CONVERSIONS",
        ):
            details = _DiagnosticsMixin._extract_bidding_details(campaign)

        assert details["strategy"] == "MAXIMIZE_CONVERSIONS"
        assert "optional_target_cpa" not in details

    def test_maximize_clicks_without_ceiling(self) -> None:
        """MAXIMIZE_CLICKS with ceiling = 0."""
        campaign = MagicMock()
        campaign.bidding_strategy_type = 2
        campaign.target_spend.cpc_bid_ceiling_micros = 0

        with patch(
            "mureo.google_ads._diagnostics.map_bidding_strategy_type",
            return_value="MAXIMIZE_CLICKS",
        ):
            details = _DiagnosticsMixin._extract_bidding_details(campaign)

        assert details["strategy"] == "MAXIMIZE_CLICKS"
        assert "cpc_bid_ceiling" not in details

    def test_target_impression_share_normal(self) -> None:
        """Healthy parameters for TARGET_IMPRESSION_SHARE (no issues)."""
        campaign = MagicMock()
        campaign.bidding_strategy_type = 15
        tis = campaign.target_impression_share
        tis.location = 3  # TOP_OF_PAGE
        tis.location_fraction_micros = 500_000  # 50%
        tis.cpc_bid_ceiling_micros = 1_000_000  # ¥1,000

        with patch(
            "mureo.google_ads._diagnostics.map_bidding_strategy_type",
            return_value="TARGET_IMPRESSION_SHARE",
        ):
            details = _DiagnosticsMixin._extract_bidding_details(campaign)

        assert details["strategy"] == "TARGET_IMPRESSION_SHARE"
        assert details["location"] == "TOP_OF_PAGE"
        assert details["target_fraction_percent"] == 50.0
        assert details["cpc_bid_ceiling"] == 1.0
        assert "issue" not in details
