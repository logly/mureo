"""Unit tests for Google Ads _extensions.py.

Mock-based tests for each method on _ExtensionsMixin.
Mocks _search / _get_service / _client to eliminate any external API calls.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.google_ads._extensions import (
    _ExtensionsMixin,
    _DEVICE_ENUM_MAP,
    _normalize_device_type,
    _VALID_CONVERSION_ACTION_TYPES,
    _VALID_CONVERSION_ACTION_CATEGORIES,
    _VALID_CONVERSION_ACTION_STATUSES,
)


# ---------------------------------------------------------------------------
# Mock client class for tests
# ---------------------------------------------------------------------------


class _MockExtensionsClient(_ExtensionsMixin):
    """Mock class that makes _ExtensionsMixin testable."""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._client = MagicMock()
        self._search = AsyncMock(return_value=[])

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        if not value or not value.isdigit():
            raise ValueError(f"Invalid {field_name}: {value}")
        return value

    @staticmethod
    def _validate_date(value: str, field_name: str) -> str:
        return value

    @staticmethod
    def _validate_recommendation_type(rec_type: str) -> str:
        return rec_type

    @staticmethod
    def _validate_resource_name(value: str, pattern, field_name: str) -> str:
        return value

    def _get_service(self, service_name: str):
        return MagicMock()


# ---------------------------------------------------------------------------
# _normalize_device_type tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeDeviceType:
    def test_int_values(self) -> None:
        assert _normalize_device_type(2) == "MOBILE"
        assert _normalize_device_type(3) == "TABLET"
        assert _normalize_device_type(4) == "DESKTOP"

    def test_unknown_int(self) -> None:
        result = _normalize_device_type(99)
        assert "UNKNOWN" in result

    def test_dotted_string(self) -> None:
        assert _normalize_device_type("DeviceType.DESKTOP") == "DESKTOP"

    def test_plain_string(self) -> None:
        assert _normalize_device_type("MOBILE") == "MOBILE"

    def test_int_string(self) -> None:
        assert _normalize_device_type("2") == "MOBILE"
        assert _normalize_device_type("4") == "DESKTOP"

    def test_non_numeric_string(self) -> None:
        assert _normalize_device_type("TABLET") == "TABLET"


# ---------------------------------------------------------------------------
# list_sitelinks tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListSitelinks:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_returns_campaign_and_account_sitelinks(
        self, client: _MockExtensionsClient
    ) -> None:
        """Returns campaign-level and account-level sitelinks merged together."""
        campaign_row = MagicMock()
        # map_sitelink is called, so patch it.
        with patch("mureo.google_ads._extensions_sitelinks.map_sitelink") as mock_map:
            mock_map.side_effect = [
                {"id": "1", "link_text": "Link1"},
                {"id": "2", "link_text": "Link2"},
            ]
            client._search = AsyncMock(
                side_effect=[
                    [campaign_row],  # campaign-level
                    [MagicMock()],  # account-level
                ]
            )
            result = await client.list_sitelinks("123")

        assert len(result) == 2
        assert result[0]["level"] == "campaign"
        assert result[1]["level"] == "account"

    @pytest.mark.asyncio
    async def test_dedup_by_id(self, client: _MockExtensionsClient) -> None:
        """Sitelinks with the same ID are deduplicated."""
        with patch("mureo.google_ads._extensions_sitelinks.map_sitelink") as mock_map:
            mock_map.side_effect = [
                {"id": "1", "link_text": "Link1"},
                {"id": "1", "link_text": "Link1dup"},  # same ID
            ]
            client._search = AsyncMock(
                side_effect=[
                    [MagicMock()],
                    [MagicMock()],
                ]
            )
            result = await client.list_sitelinks("123")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_account_level_failure_graceful(
        self, client: _MockExtensionsClient
    ) -> None:
        """Campaign-level sitelinks are returned even when account-level fetch fails."""
        with patch("mureo.google_ads._extensions_sitelinks.map_sitelink") as mock_map:
            mock_map.return_value = {"id": "1", "link_text": "Link1"}
            client._search = AsyncMock(
                side_effect=[
                    [MagicMock()],
                    RuntimeError("account query failed"),
                ]
            )
            result = await client.list_sitelinks("123")

        assert len(result) == 1
        assert result[0]["level"] == "campaign"


# ---------------------------------------------------------------------------
# create_sitelink tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSitelink:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_max_sitelinks_exceeded(self, client: _MockExtensionsClient) -> None:
        """Returns a validation error when over the limit."""
        with patch.object(client, "list_sitelinks", new_callable=AsyncMock) as mock_ls:
            mock_ls.return_value = [
                {"id": str(i), "level": "campaign"} for i in range(20)
            ]
            result = await client.create_sitelink(
                {
                    "campaign_id": "123",
                    "link_text": "Test",
                    "final_url": "https://example.com",
                }
            )
        assert result["error"] is True
        assert "Maximum 20" in result["message"]


# ---------------------------------------------------------------------------
# list_callouts tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListCallouts:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_returns_callouts(self, client: _MockExtensionsClient) -> None:
        with patch("mureo.google_ads._extensions_callouts.map_callout") as mock_map:
            mock_map.return_value = {"id": "1", "callout_text": "Free"}
            client._search = AsyncMock(return_value=[MagicMock()])
            result = await client.list_callouts("123")

        assert len(result) == 1
        assert result[0]["callout_text"] == "Free"


# ---------------------------------------------------------------------------
# create_callout tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCallout:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_max_callouts_exceeded(self, client: _MockExtensionsClient) -> None:
        """Returns a validation error when over the limit."""
        with patch.object(client, "list_callouts", new_callable=AsyncMock) as mock_lc:
            mock_lc.return_value = [{"id": str(i)} for i in range(20)]
            result = await client.create_callout(
                {
                    "campaign_id": "123",
                    "callout_text": "Test",
                }
            )
        assert result["error"] is True
        assert "Maximum 20" in result["message"]


# ---------------------------------------------------------------------------
# list_conversion_actions tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListConversionActions:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_returns_mapped_actions(self, client: _MockExtensionsClient) -> None:
        mock_row = MagicMock()
        client._search = AsyncMock(return_value=[mock_row])
        with patch(
            "mureo.google_ads._extensions_conversions.map_conversion_action"
        ) as mock_map:
            mock_map.return_value = {"id": "1", "name": "Purchase"}
            result = await client.list_conversion_actions()

        assert len(result) == 1
        assert result[0]["name"] == "Purchase"


# ---------------------------------------------------------------------------
# create_conversion_action validation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateConversionActionValidation:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_empty_name_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="name is required"):
            await client.create_conversion_action({"name": ""})

    @pytest.mark.asyncio
    async def test_long_name_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="256 characters"):
            await client.create_conversion_action({"name": "x" * 257})

    @pytest.mark.asyncio
    async def test_invalid_type_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="Invalid type"):
            await client.create_conversion_action({"name": "Test", "type": "INVALID"})

    @pytest.mark.asyncio
    async def test_invalid_category_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="Invalid category"):
            await client.create_conversion_action(
                {"name": "Test", "category": "INVALID"}
            )

    @pytest.mark.asyncio
    async def test_lookback_window_out_of_range(
        self, client: _MockExtensionsClient
    ) -> None:
        with pytest.raises(ValueError, match="1.+90"):
            await client.create_conversion_action(
                {
                    "name": "Test",
                    "click_through_lookback_window_days": 100,
                }
            )

    @pytest.mark.asyncio
    async def test_view_through_lookback_out_of_range(
        self, client: _MockExtensionsClient
    ) -> None:
        with pytest.raises(ValueError, match="1.+30"):
            await client.create_conversion_action(
                {
                    "name": "Test",
                    "view_through_lookback_window_days": 31,
                }
            )


# ---------------------------------------------------------------------------
# update_conversion_action validation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateConversionActionValidation:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_no_fields_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="At least one field must be specified"):
            await client.update_conversion_action({"conversion_action_id": "123"})

    @pytest.mark.asyncio
    async def test_invalid_status_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            await client.update_conversion_action(
                {
                    "conversion_action_id": "123",
                    "status": "INVALID",
                }
            )

    @pytest.mark.asyncio
    async def test_invalid_category_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="Invalid category"):
            await client.update_conversion_action(
                {
                    "conversion_action_id": "123",
                    "category": "BADCAT",
                }
            )


# ---------------------------------------------------------------------------
# get_conversion_action tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetConversionAction:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_found(self, client: _MockExtensionsClient) -> None:
        mock_row = MagicMock()
        client._search = AsyncMock(return_value=[mock_row])
        with patch(
            "mureo.google_ads._extensions_conversions.map_conversion_action"
        ) as mock_map:
            mock_map.return_value = {"id": "1", "name": "Purchase"}
            result = await client.get_conversion_action("1")
        assert result is not None
        assert result["name"] == "Purchase"

    @pytest.mark.asyncio
    async def test_not_found(self, client: _MockExtensionsClient) -> None:
        client._search = AsyncMock(return_value=[])
        result = await client.get_conversion_action("999")
        assert result is None


# ---------------------------------------------------------------------------
# get_conversion_action_tag tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetConversionActionTag:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_returns_snippets(self, client: _MockExtensionsClient) -> None:
        snippet = MagicMock()
        mock_row = MagicMock()
        mock_row.conversion_action.tag_snippets = [snippet]
        client._search = AsyncMock(return_value=[mock_row])
        with patch(
            "mureo.google_ads._extensions_conversions.map_tag_snippet"
        ) as mock_map:
            mock_map.return_value = {"type": "EVENT_SNIPPET"}
            result = await client.get_conversion_action_tag("1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_not_found_returns_empty(self, client: _MockExtensionsClient) -> None:
        client._search = AsyncMock(return_value=[])
        result = await client.get_conversion_action_tag("999")
        assert result == []


# ---------------------------------------------------------------------------
# list_recommendations tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListRecommendations:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_no_filter(self, client: _MockExtensionsClient) -> None:
        mock_row = MagicMock()
        client._search = AsyncMock(return_value=[mock_row])
        with patch(
            "mureo.google_ads._extensions_targeting.map_recommendation"
        ) as mock_map:
            mock_map.return_value = {"type": "KEYWORD"}
            result = await client.list_recommendations()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_with_campaign_filter(self, client: _MockExtensionsClient) -> None:
        client._search = AsyncMock(return_value=[])
        result = await client.list_recommendations(campaign_id="123")
        assert result == []


# ---------------------------------------------------------------------------
# get_device_targeting tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDeviceTargeting:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_all_devices_returned(self, client: _MockExtensionsClient) -> None:
        """All three device types are always returned even when no criterion exists."""
        client._search = AsyncMock(return_value=[])
        result = await client.get_device_targeting("123")
        assert len(result) == 3
        device_types = {r["device_type"] for r in result}
        assert device_types == {"DESKTOP", "MOBILE", "TABLET"}
        # Default is enabled.
        for r in result:
            assert r["enabled"] is True
            assert r["criterion_id"] is None

    @pytest.mark.asyncio
    async def test_disabled_device(self, client: _MockExtensionsClient) -> None:
        """A device with bid_modifier=0.0 is classified as disabled."""
        mock_row = MagicMock()
        mock_row.campaign_criterion.device.type_ = 4  # DESKTOP
        mock_row.campaign_criterion.bid_modifier = 0.0
        mock_row.campaign_criterion.criterion_id = "99"
        client._search = AsyncMock(return_value=[mock_row])

        result = await client.get_device_targeting("123")
        desktop = [r for r in result if r["device_type"] == "DESKTOP"][0]
        assert desktop["enabled"] is False
        assert desktop["criterion_id"] == "99"


# ---------------------------------------------------------------------------
# set_device_targeting validation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetDeviceTargetingValidation:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_invalid_device_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="Invalid device type"):
            await client.set_device_targeting(
                {
                    "campaign_id": "123",
                    "enabled_devices": ["PHONE"],
                }
            )

    @pytest.mark.asyncio
    async def test_empty_devices_raises(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="At least one"):
            await client.set_device_targeting(
                {
                    "campaign_id": "123",
                    "enabled_devices": [],
                }
            )


# ---------------------------------------------------------------------------
# get_bid_adjustments tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBidAdjustments:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_returns_adjustments(self, client: _MockExtensionsClient) -> None:
        mock_row = MagicMock()
        mock_row.campaign_criterion.criterion_id = "1"
        mock_row.campaign_criterion.type_ = "DEVICE"
        mock_row.campaign_criterion.bid_modifier = 1.5
        mock_row.campaign_criterion.device.type_ = 4  # DESKTOP
        client._search = AsyncMock(return_value=[mock_row])

        result = await client.get_bid_adjustments("123")
        assert len(result) == 1
        assert result[0]["bid_modifier"] == 1.5
        assert result[0]["device_type"] == "DESKTOP"

    @pytest.mark.asyncio
    async def test_empty_adjustments(self, client: _MockExtensionsClient) -> None:
        client._search = AsyncMock(return_value=[])
        result = await client.get_bid_adjustments("123")
        assert result == []


# ---------------------------------------------------------------------------
# update_bid_adjustment validation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateBidAdjustmentValidation:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_bid_modifier_too_low(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="0\\.1.+10\\.0"):
            await client.update_bid_adjustment(
                {
                    "campaign_id": "123",
                    "criterion_id": "1",
                    "bid_modifier": 0.05,
                }
            )

    @pytest.mark.asyncio
    async def test_bid_modifier_too_high(self, client: _MockExtensionsClient) -> None:
        with pytest.raises(ValueError, match="0\\.1.+10\\.0"):
            await client.update_bid_adjustment(
                {
                    "campaign_id": "123",
                    "criterion_id": "1",
                    "bid_modifier": 10.5,
                }
            )


# ---------------------------------------------------------------------------
# list_change_history tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListChangeHistory:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_default_date_range(self, client: _MockExtensionsClient) -> None:
        """Without a date, the default 14-day window is used."""
        mock_row = MagicMock()
        client._search = AsyncMock(return_value=[mock_row])
        with patch(
            "mureo.google_ads._extensions_targeting.map_change_event"
        ) as mock_map:
            mock_map.return_value = {"change_date_time": "2024-01-01"}
            result = await client.list_change_history()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_custom_date_range(self, client: _MockExtensionsClient) -> None:
        client._search = AsyncMock(return_value=[])
        result = await client.list_change_history(
            start_date="2024-01-01", end_date="2024-01-31"
        )
        assert result == []


# ---------------------------------------------------------------------------
# list_location_targeting tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListLocationTargeting:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_returns_locations(self, client: _MockExtensionsClient) -> None:
        mock_row = MagicMock()
        mock_row.campaign_criterion.criterion_id = "1"
        mock_row.campaign_criterion.location.geo_target_constant = (
            "geoTargetConstants/2392"
        )
        mock_row.campaign_criterion.bid_modifier = 1.0
        client._search = AsyncMock(return_value=[mock_row])

        result = await client.list_location_targeting("123")
        assert len(result) == 1
        assert "2392" in result[0]["geo_target_constant"]

    @pytest.mark.asyncio
    async def test_empty_locations(self, client: _MockExtensionsClient) -> None:
        client._search = AsyncMock(return_value=[])
        result = await client.list_location_targeting("123")
        assert result == []


# ---------------------------------------------------------------------------
# list_schedule_targeting tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListScheduleTargeting:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_returns_schedules(self, client: _MockExtensionsClient) -> None:
        mock_row = MagicMock()
        mock_row.campaign_criterion.criterion_id = "1"
        mock_row.campaign_criterion.ad_schedule.day_of_week = "MONDAY"
        mock_row.campaign_criterion.ad_schedule.start_hour = 9
        mock_row.campaign_criterion.ad_schedule.end_hour = 18
        mock_row.campaign_criterion.ad_schedule.start_minute = "ZERO"
        mock_row.campaign_criterion.ad_schedule.end_minute = "ZERO"
        mock_row.campaign_criterion.bid_modifier = 1.0
        client._search = AsyncMock(return_value=[mock_row])

        result = await client.list_schedule_targeting("123")
        assert len(result) == 1
        assert result[0]["day_of_week"] == "MONDAY"
        assert result[0]["start_hour"] == 9
        assert result[0]["end_hour"] == 18


# ---------------------------------------------------------------------------
# get_conversion_performance tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetConversionPerformance:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        c = _MockExtensionsClient()
        c._period_to_date_clause = MagicMock(return_value="DURING LAST_30_DAYS")
        return c

    @pytest.mark.asyncio
    async def test_empty_response(self, client: _MockExtensionsClient) -> None:
        client._search = AsyncMock(return_value=[])
        result = await client.get_conversion_performance()
        assert result["total_conversions"] == 0
        assert result["actions"] == []
        assert result["daily_details"] == []

    @pytest.mark.asyncio
    async def test_with_data(self, client: _MockExtensionsClient) -> None:
        cv_row = MagicMock()
        cv_row.campaign.id = 1
        cv_row.campaign.name = "Campaign A"
        cv_row.segments.conversion_action_name = "Purchase"
        cv_row.segments.date = "2024-01-01"
        cv_row.metrics.conversions = 5.0
        cv_row.metrics.conversions_value = 50000.0

        cost_row = MagicMock()
        cost_row.campaign.id = 1
        cost_row.metrics.cost_micros = 10_000_000_000  # 10,000 JPY

        # 1st call: per-CV; 2nd: cost; 3rd: per-LP.
        client._search = AsyncMock(
            side_effect=[
                [cv_row],
                [cost_row],
                [],  # LP
            ]
        )
        result = await client.get_conversion_performance()
        assert result["total_conversions"] == 5.0
        assert len(result["actions"]) == 1
        assert result["actions"][0]["conversion_action_name"] == "Purchase"

    @pytest.mark.asyncio
    async def test_with_campaign_id_filter(self, client: _MockExtensionsClient) -> None:
        """Filtering when campaign_id is provided."""
        client._search = AsyncMock(return_value=[])
        result = await client.get_conversion_performance(campaign_id="456")
        assert result["campaign_id"] == "456"
        assert result["total_conversions"] == 0

    @pytest.mark.asyncio
    async def test_cost_query_failure_fallback(
        self, client: _MockExtensionsClient
    ) -> None:
        """When cost fetch fails, CPA is returned as 0."""
        cv_row = MagicMock()
        cv_row.campaign.id = 1
        cv_row.campaign.name = "Campaign A"
        cv_row.segments.conversion_action_name = "Purchase"
        cv_row.segments.date = "2024-01-01"
        cv_row.metrics.conversions = 3.0
        cv_row.metrics.conversions_value = 30000.0

        client._search = AsyncMock(
            side_effect=[
                [cv_row],  # per-CV
                RuntimeError("fail"),  # cost fetch failure
                [],  # LP
            ]
        )
        result = await client.get_conversion_performance()
        assert result["total_conversions"] == 3.0
        assert result["actions"][0]["cost_per_conversion"] == 0

    @pytest.mark.asyncio
    async def test_lp_query_failure_graceful(
        self, client: _MockExtensionsClient
    ) -> None:
        """Returns normally even when per-LP CV fetch fails."""
        cv_row = MagicMock()
        cv_row.campaign.id = 1
        cv_row.campaign.name = "Campaign A"
        cv_row.segments.conversion_action_name = "Purchase"
        cv_row.segments.date = "2024-01-01"
        cv_row.metrics.conversions = 2.0
        cv_row.metrics.conversions_value = 20000.0

        cost_row = MagicMock()
        cost_row.campaign.id = 1
        cost_row.metrics.cost_micros = 5_000_000_000

        client._search = AsyncMock(
            side_effect=[
                [cv_row],
                [cost_row],
                RuntimeError("lp fail"),  # LP fetch failure
            ]
        )
        result = await client.get_conversion_performance()
        assert result["total_conversions"] == 2.0
        assert result["landing_pages"] == []

    @pytest.mark.asyncio
    async def test_with_lp_data(self, client: _MockExtensionsClient) -> None:
        """Per-LP CV data is returned correctly."""
        cv_row = MagicMock()
        cv_row.campaign.id = 1
        cv_row.campaign.name = "Campaign A"
        cv_row.segments.conversion_action_name = "Purchase"
        cv_row.segments.date = "2024-01-01"
        cv_row.metrics.conversions = 5.0
        cv_row.metrics.conversions_value = 50000.0

        cost_row = MagicMock()
        cost_row.campaign.id = 1
        cost_row.metrics.cost_micros = 10_000_000_000

        lp_row = MagicMock()
        lp_row.segments.date = "2024-01-01"
        lp_row.landing_page_view.unexpanded_final_url = "https://example.com"
        lp_row.campaign.id = 1
        lp_row.campaign.name = "Campaign A"
        lp_row.metrics.conversions = 5.0
        lp_row.metrics.conversions_value = 50000.0
        lp_row.metrics.clicks = 100

        client._search = AsyncMock(
            side_effect=[
                [cv_row],
                [cost_row],
                [lp_row],
            ]
        )
        result = await client.get_conversion_performance()
        assert len(result["landing_pages"]) == 1
        assert result["landing_pages"][0]["landing_page_url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_date_range_tracking_in_summary(
        self, client: _MockExtensionsClient
    ) -> None:
        """For multi-day data, first_date / last_date are set correctly."""
        rows = []
        for d in ["2024-01-02", "2024-01-01", "2024-01-03"]:
            row = MagicMock()
            row.campaign.id = 1
            row.campaign.name = "C"
            row.segments.conversion_action_name = "Purchase"
            row.segments.date = d
            row.metrics.conversions = 1.0
            row.metrics.conversions_value = 1000.0
            rows.append(row)

        client._search = AsyncMock(
            side_effect=[
                rows,
                [],  # cost
                [],  # lp
            ]
        )
        result = await client.get_conversion_performance()
        action = result["actions"][0]
        assert action["first_date"] == "2024-01-01"
        assert action["last_date"] == "2024-01-03"
        assert action["conversions"] == 3.0


# ---------------------------------------------------------------------------
# create_callout happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCalloutSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_create_callout_success(self, client: _MockExtensionsClient) -> None:
        """Callout creation completes successfully."""
        with patch.object(client, "list_callouts", new_callable=AsyncMock) as mock_lc:
            mock_lc.return_value = [{"id": str(i)} for i in range(5)]

            # AssetService mock
            asset_service = MagicMock()
            asset_response = MagicMock()
            asset_response.results = [
                MagicMock(resource_name="customers/123/assets/456")
            ]
            asset_service.mutate_assets.return_value = asset_response

            # CampaignAssetService mock
            ca_service = MagicMock()
            ca_service.mutate_campaign_assets.return_value = MagicMock()

            def get_service(name: str) -> MagicMock:
                if name == "AssetService":
                    return asset_service
                return ca_service

            client._get_service = get_service

            # client mock setup
            asset_op = MagicMock()
            client._client.get_type.return_value = asset_op
            client._client.get_service.return_value = MagicMock(
                campaign_path=MagicMock(return_value="customers/123/campaigns/789")
            )
            client._client.enums.AssetFieldTypeEnum.CALLOUT = "CALLOUT"

            result = await client.create_callout(
                {
                    "campaign_id": "789",
                    "callout_text": "Free Shipping",
                }
            )

        assert result["resource_name"] == "customers/123/assets/456"


# ---------------------------------------------------------------------------
# remove_callout happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveCallout:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_remove_callout_success(self, client: _MockExtensionsClient) -> None:
        """Callout removal completes successfully."""
        ca_service = MagicMock()
        response = MagicMock()
        response.results = [MagicMock(resource_name="customers/123/campaignAssets/del")]
        ca_service.mutate_campaign_assets.return_value = response

        client._get_service = lambda name: ca_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_asset_path=MagicMock(
                return_value="customers/123/campaignAssets/456~789~CALLOUT"
            )
        )

        result = await client.remove_callout(
            {
                "campaign_id": "123",
                "asset_id": "456",
            }
        )
        assert result["resource_name"] == "customers/123/campaignAssets/del"

    @pytest.mark.asyncio
    async def test_remove_callout_invalid_campaign_id(
        self, client: _MockExtensionsClient
    ) -> None:
        """Invalid campaign_id triggers a validation error."""
        with pytest.raises(ValueError, match="Invalid"):
            await client.remove_callout(
                {
                    "campaign_id": "abc",
                    "asset_id": "456",
                }
            )

    @pytest.mark.asyncio
    async def test_remove_callout_invalid_asset_id(
        self, client: _MockExtensionsClient
    ) -> None:
        """Invalid asset_id triggers a validation error."""
        with pytest.raises(ValueError, match="Invalid"):
            await client.remove_callout(
                {
                    "campaign_id": "123",
                    "asset_id": "abc",
                }
            )


# ---------------------------------------------------------------------------
# create_sitelink happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSitelinkSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_create_sitelink_success(self, client: _MockExtensionsClient) -> None:
        """Sitelink creation completes successfully."""
        with patch.object(client, "list_sitelinks", new_callable=AsyncMock) as mock_ls:
            mock_ls.return_value = [
                {"id": str(i), "level": "campaign"} for i in range(5)
            ]

            asset_service = MagicMock()
            asset_response = MagicMock()
            asset_response.results = [
                MagicMock(resource_name="customers/123/assets/789")
            ]
            asset_service.mutate_assets.return_value = asset_response

            ca_service = MagicMock()
            ca_service.mutate_campaign_assets.return_value = MagicMock()

            def get_service(name: str) -> MagicMock:
                if name == "AssetService":
                    return asset_service
                return ca_service

            client._get_service = get_service

            asset_op = MagicMock()
            asset_op.create.final_urls = []
            client._client.get_type.return_value = asset_op
            client._client.get_service.return_value = MagicMock(
                campaign_path=MagicMock(return_value="customers/123/campaigns/456")
            )
            client._client.enums.AssetFieldTypeEnum.SITELINK = "SITELINK"

            result = await client.create_sitelink(
                {
                    "campaign_id": "456",
                    "link_text": "About Us",
                    "final_url": "https://example.com/about",
                }
            )

        assert result["resource_name"] == "customers/123/assets/789"

    @pytest.mark.asyncio
    async def test_create_sitelink_with_descriptions(
        self, client: _MockExtensionsClient
    ) -> None:
        """Create a sitelink including description1/description2."""
        with patch.object(client, "list_sitelinks", new_callable=AsyncMock) as mock_ls:
            mock_ls.return_value = []

            asset_service = MagicMock()
            asset_response = MagicMock()
            asset_response.results = [
                MagicMock(resource_name="customers/123/assets/789")
            ]
            asset_service.mutate_assets.return_value = asset_response

            ca_service = MagicMock()
            ca_service.mutate_campaign_assets.return_value = MagicMock()

            def get_service(name: str) -> MagicMock:
                if name == "AssetService":
                    return asset_service
                return ca_service

            client._get_service = get_service

            asset_op = MagicMock()
            asset_op.create.final_urls = []
            client._client.get_type.return_value = asset_op
            client._client.get_service.return_value = MagicMock(
                campaign_path=MagicMock(return_value="customers/123/campaigns/456")
            )
            client._client.enums.AssetFieldTypeEnum.SITELINK = "SITELINK"

            result = await client.create_sitelink(
                {
                    "campaign_id": "456",
                    "link_text": "About Us",
                    "final_url": "https://example.com/about",
                    "description1": "Learn more",
                    "description2": "About our company",
                }
            )

        assert result["resource_name"] == "customers/123/assets/789"
        # Verify description1/description2 were set.
        asset_op.create.sitelink_asset.description1 = "Learn more"
        asset_op.create.sitelink_asset.description2 = "About our company"

    @pytest.mark.asyncio
    async def test_create_sitelink_account_level_not_counted(
        self, client: _MockExtensionsClient
    ) -> None:
        """Account-level sitelinks do not count toward the limit."""
        with patch.object(client, "list_sitelinks", new_callable=AsyncMock) as mock_ls:
            # 19 campaign-level + 5 account-level = 24 total, but campaign-level is 19, so creation is allowed.
            mock_ls.return_value = [
                {"id": str(i), "level": "campaign"} for i in range(19)
            ] + [{"id": str(i + 100), "level": "account"} for i in range(5)]

            asset_service = MagicMock()
            asset_response = MagicMock()
            asset_response.results = [
                MagicMock(resource_name="customers/123/assets/new")
            ]
            asset_service.mutate_assets.return_value = asset_response

            ca_service = MagicMock()
            ca_service.mutate_campaign_assets.return_value = MagicMock()

            def get_service(name: str) -> MagicMock:
                if name == "AssetService":
                    return asset_service
                return ca_service

            client._get_service = get_service

            asset_op = MagicMock()
            asset_op.create.final_urls = []
            client._client.get_type.return_value = asset_op
            client._client.get_service.return_value = MagicMock(
                campaign_path=MagicMock(return_value="customers/123/campaigns/456")
            )
            client._client.enums.AssetFieldTypeEnum.SITELINK = "SITELINK"

            result = await client.create_sitelink(
                {
                    "campaign_id": "456",
                    "link_text": "New Link",
                    "final_url": "https://example.com/new",
                }
            )

        assert "resource_name" in result


# ---------------------------------------------------------------------------
# remove_sitelink happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveSitelink:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_remove_sitelink_success(self, client: _MockExtensionsClient) -> None:
        """Sitelink removal completes successfully."""
        ca_service = MagicMock()
        response = MagicMock()
        response.results = [MagicMock(resource_name="customers/123/campaignAssets/del")]
        ca_service.mutate_campaign_assets.return_value = response

        client._get_service = lambda name: ca_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_asset_path=MagicMock(
                return_value="customers/123/campaignAssets/456~789~SITELINK"
            )
        )

        result = await client.remove_sitelink(
            {
                "campaign_id": "123",
                "asset_id": "456",
            }
        )
        assert result["resource_name"] == "customers/123/campaignAssets/del"

    @pytest.mark.asyncio
    async def test_remove_sitelink_invalid_ids(
        self, client: _MockExtensionsClient
    ) -> None:
        """Invalid ID triggers a validation error."""
        with pytest.raises(ValueError, match="Invalid"):
            await client.remove_sitelink(
                {
                    "campaign_id": "abc",
                    "asset_id": "456",
                }
            )


# ---------------------------------------------------------------------------
# create_conversion_action happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateConversionActionSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_create_basic(self, client: _MockExtensionsClient) -> None:
        """Basic conversion-action creation."""
        ca_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/conversionActions/456")
        ]
        ca_service.mutate_conversion_actions.return_value = response

        client._get_service = lambda name: ca_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.enums.ConversionActionTypeEnum.WEBPAGE = "WEBPAGE"
        client._client.enums.ConversionActionCategoryEnum.DEFAULT = "DEFAULT"

        result = await client.create_conversion_action({"name": "Purchase"})
        assert result["resource_name"] == "customers/123/conversionActions/456"

    @pytest.mark.asyncio
    async def test_create_with_value_settings(
        self, client: _MockExtensionsClient
    ) -> None:
        """Conversion-action creation with value_settings."""
        ca_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/conversionActions/789")
        ]
        ca_service.mutate_conversion_actions.return_value = response

        client._get_service = lambda name: ca_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.enums.ConversionActionTypeEnum.WEBPAGE = "WEBPAGE"
        client._client.enums.ConversionActionCategoryEnum.PURCHASE = "PURCHASE"

        result = await client.create_conversion_action(
            {
                "name": "Purchase",
                "type": "WEBPAGE",
                "category": "PURCHASE",
                "default_value": 5000.0,
                "always_use_default_value": True,
                "click_through_lookback_window_days": 30,
                "view_through_lookback_window_days": 7,
            }
        )
        assert result["resource_name"] == "customers/123/conversionActions/789"


# ---------------------------------------------------------------------------
# update_conversion_action happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateConversionActionSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_update_name(self, client: _MockExtensionsClient) -> None:
        """Update the name."""
        ca_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/conversionActions/456")
        ]
        ca_service.mutate_conversion_actions.return_value = response

        client._get_service = lambda name: ca_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            conversion_action_path=MagicMock(
                return_value="customers/123/conversionActions/456"
            )
        )

        result = await client.update_conversion_action(
            {
                "conversion_action_id": "456",
                "name": "New Name",
            }
        )
        assert result["resource_name"] == "customers/123/conversionActions/456"

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, client: _MockExtensionsClient) -> None:
        """Update multiple fields at once."""
        ca_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/conversionActions/456")
        ]
        ca_service.mutate_conversion_actions.return_value = response

        client._get_service = lambda name: ca_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            conversion_action_path=MagicMock(
                return_value="customers/123/conversionActions/456"
            )
        )
        client._client.enums.ConversionActionCategoryEnum.PURCHASE = "PURCHASE"
        client._client.enums.ConversionActionStatusEnum.ENABLED = "ENABLED"

        result = await client.update_conversion_action(
            {
                "conversion_action_id": "456",
                "name": "Updated",
                "category": "PURCHASE",
                "status": "ENABLED",
                "default_value": 1000.0,
                "always_use_default_value": False,
                "click_through_lookback_window_days": 60,
                "view_through_lookback_window_days": 14,
            }
        )
        assert result["resource_name"] == "customers/123/conversionActions/456"

    @pytest.mark.asyncio
    async def test_update_long_name_raises(self, client: _MockExtensionsClient) -> None:
        """Name length check during update."""
        with pytest.raises(ValueError, match="256 characters"):
            await client.update_conversion_action(
                {
                    "conversion_action_id": "456",
                    "name": "x" * 257,
                }
            )

    @pytest.mark.asyncio
    async def test_update_lookback_window_out_of_range(
        self, client: _MockExtensionsClient
    ) -> None:
        """Lookback window validation during update."""
        with pytest.raises(ValueError, match="1.+90"):
            await client.update_conversion_action(
                {
                    "conversion_action_id": "456",
                    "click_through_lookback_window_days": 91,
                }
            )

    @pytest.mark.asyncio
    async def test_update_view_through_out_of_range(
        self, client: _MockExtensionsClient
    ) -> None:
        """view_through_lookback_window_days validation during update."""
        with pytest.raises(ValueError, match="1.+30"):
            await client.update_conversion_action(
                {
                    "conversion_action_id": "456",
                    "view_through_lookback_window_days": 31,
                }
            )


# ---------------------------------------------------------------------------
# remove_conversion_action happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveConversionAction:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_remove_success(self, client: _MockExtensionsClient) -> None:
        """Conversion-action removal completes successfully."""
        ca_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/conversionActions/456")
        ]
        ca_service.mutate_conversion_actions.return_value = response

        client._get_service = lambda name: ca_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            conversion_action_path=MagicMock(
                return_value="customers/123/conversionActions/456"
            )
        )

        result = await client.remove_conversion_action({"conversion_action_id": "456"})
        assert result["resource_name"] == "customers/123/conversionActions/456"

    @pytest.mark.asyncio
    async def test_remove_invalid_id(self, client: _MockExtensionsClient) -> None:
        """Invalid ID triggers a validation error."""
        with pytest.raises(ValueError, match="Invalid"):
            await client.remove_conversion_action({"conversion_action_id": "abc"})


# ---------------------------------------------------------------------------
# set_device_targeting happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetDeviceTargetingSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        c = _MockExtensionsClient()
        c._extract_error_detail = MagicMock(return_value="error detail")
        return c

    @pytest.mark.asyncio
    async def test_set_devices_update_existing(
        self, client: _MockExtensionsClient
    ) -> None:
        """Update bid_modifier on an existing criterion."""
        # An existing DESKTOP criterion is present.
        mock_row = MagicMock()
        mock_row.campaign_criterion.device.type_ = 4  # DESKTOP
        mock_row.campaign_criterion.bid_modifier = 1.0
        mock_row.campaign_criterion.criterion_id = "100"
        client._search = AsyncMock(return_value=[mock_row])

        cc_service = MagicMock()
        resp = MagicMock()
        resp.results = [MagicMock(resource_name="customers/123/campaignCriteria/100")]
        cc_service.mutate_campaign_criteria.return_value = resp
        cc_service.campaign_criterion_path = MagicMock(
            return_value="customers/123/campaignCriteria/100"
        )

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456")
        )
        client._client.enums.DeviceEnum.DESKTOP = "DESKTOP"
        client._client.enums.DeviceEnum.MOBILE = "MOBILE"
        client._client.enums.DeviceEnum.TABLET = "TABLET"

        result = await client.set_device_targeting(
            {
                "campaign_id": "456",
                "enabled_devices": ["DESKTOP", "MOBILE"],
            }
        )
        assert "DESKTOP" in result["enabled_devices"]
        assert "MOBILE" in result["enabled_devices"]
        assert "TABLET" in result["disabled_devices"]

    @pytest.mark.asyncio
    async def test_set_devices_create_new(self, client: _MockExtensionsClient) -> None:
        """Create a new criterion when one does not exist."""
        client._search = AsyncMock(return_value=[])

        cc_service = MagicMock()
        resp = MagicMock()
        resp.results = [MagicMock(resource_name="customers/123/campaignCriteria/new")]
        cc_service.mutate_campaign_criteria.return_value = resp

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456")
        )
        client._client.enums.DeviceEnum.DESKTOP = "DESKTOP"
        client._client.enums.DeviceEnum.MOBILE = "MOBILE"
        client._client.enums.DeviceEnum.TABLET = "TABLET"

        result = await client.set_device_targeting(
            {
                "campaign_id": "456",
                "enabled_devices": ["MOBILE"],
            }
        )
        assert "MOBILE" in result["enabled_devices"]
        assert len(result["updated"]) == 3  # mutate for all 3 device types

    @pytest.mark.asyncio
    async def test_set_devices_partial_failure(
        self, client: _MockExtensionsClient
    ) -> None:
        """When some devices fail, errors are included but a result is still returned."""
        client._search = AsyncMock(return_value=[])

        cc_service = MagicMock()
        call_count = 0

        def mutate_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("API error")
            resp = MagicMock()
            resp.results = [MagicMock(resource_name=f"res/{call_count}")]
            return resp

        cc_service.mutate_campaign_criteria.side_effect = mutate_side_effect

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456")
        )
        client._client.enums.DeviceEnum.DESKTOP = "DESKTOP"
        client._client.enums.DeviceEnum.MOBILE = "MOBILE"
        client._client.enums.DeviceEnum.TABLET = "TABLET"

        result = await client.set_device_targeting(
            {
                "campaign_id": "456",
                "enabled_devices": ["DESKTOP"],
            }
        )
        assert len(result["updated"]) == 2
        assert result["errors"] is not None
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_set_devices_all_fail_raises(
        self, client: _MockExtensionsClient
    ) -> None:
        """Raise ValueError when configuration fails for every device."""
        client._search = AsyncMock(return_value=[])

        cc_service = MagicMock()
        cc_service.mutate_campaign_criteria.side_effect = RuntimeError("all fail")

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456")
        )
        client._client.enums.DeviceEnum.DESKTOP = "DESKTOP"
        client._client.enums.DeviceEnum.MOBILE = "MOBILE"
        client._client.enums.DeviceEnum.TABLET = "TABLET"

        with pytest.raises(ValueError, match="Failed to set all devices"):
            await client.set_device_targeting(
                {
                    "campaign_id": "456",
                    "enabled_devices": ["DESKTOP"],
                }
            )


# ---------------------------------------------------------------------------
# update_bid_adjustment happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateBidAdjustmentSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_update_success(self, client: _MockExtensionsClient) -> None:
        """Bid-adjustment update completes successfully."""
        cc_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/456")
        ]
        cc_service.mutate_campaign_criteria.return_value = response

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_criterion_path=MagicMock(
                return_value="customers/123/campaignCriteria/456"
            )
        )

        result = await client.update_bid_adjustment(
            {
                "campaign_id": "123",
                "criterion_id": "456",
                "bid_modifier": 1.5,
            }
        )
        assert result["resource_name"] == "customers/123/campaignCriteria/456"


# ---------------------------------------------------------------------------
# update_location_targeting happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateLocationTargeting:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_add_locations(self, client: _MockExtensionsClient) -> None:
        """Add geo targeting."""
        cc_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/new")
        ]
        cc_service.mutate_campaign_criteria.return_value = response

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456"),
            campaign_criterion_path=MagicMock(
                return_value="customers/123/campaignCriteria/old"
            ),
        )

        result = await client.update_location_targeting(
            {
                "campaign_id": "456",
                "add_locations": ["2392"],
            }
        )
        assert len(result) == 1
        assert result[0]["resource_name"] == "customers/123/campaignCriteria/new"

    @pytest.mark.asyncio
    async def test_add_locations_with_full_path(
        self, client: _MockExtensionsClient
    ) -> None:
        """Add via the geoTargetConstants/ID format."""
        cc_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/new")
        ]
        cc_service.mutate_campaign_criteria.return_value = response

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456"),
        )

        result = await client.update_location_targeting(
            {
                "campaign_id": "456",
                "add_locations": ["geoTargetConstants/2392"],
            }
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_remove_locations(self, client: _MockExtensionsClient) -> None:
        """Remove geo targeting."""
        cc_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/del")
        ]
        cc_service.mutate_campaign_criteria.return_value = response

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_criterion_path=MagicMock(
                return_value="customers/123/campaignCriteria/del"
            ),
        )

        result = await client.update_location_targeting(
            {
                "campaign_id": "456",
                "remove_criterion_ids": ["789"],
            }
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_add_and_remove_locations(
        self, client: _MockExtensionsClient
    ) -> None:
        """Add and remove in a single operation."""
        cc_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/1"),
            MagicMock(resource_name="customers/123/campaignCriteria/2"),
        ]
        cc_service.mutate_campaign_criteria.return_value = response

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456"),
            campaign_criterion_path=MagicMock(
                return_value="customers/123/campaignCriteria/del"
            ),
        )

        result = await client.update_location_targeting(
            {
                "campaign_id": "456",
                "add_locations": ["2392"],
                "remove_criterion_ids": ["100"],
            }
        )
        assert len(result) == 2


# ---------------------------------------------------------------------------
# update_schedule_targeting happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateScheduleTargeting:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_add_schedules(self, client: _MockExtensionsClient) -> None:
        """Add an ad schedule."""
        cc_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/new")
        ]
        cc_service.mutate_campaign_criteria.return_value = response

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456"),
        )
        client._client.enums.DayOfWeekEnum.MONDAY = "MONDAY"
        client._client.enums.MinuteOfHourEnum.ZERO = "ZERO"

        result = await client.update_schedule_targeting(
            {
                "campaign_id": "456",
                "add_schedules": [
                    {"day": "MONDAY", "start_hour": 9, "end_hour": 18},
                ],
            }
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_remove_schedules(self, client: _MockExtensionsClient) -> None:
        """Remove an ad schedule."""
        cc_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/del")
        ]
        cc_service.mutate_campaign_criteria.return_value = response

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_criterion_path=MagicMock(
                return_value="customers/123/campaignCriteria/del"
            ),
        )

        result = await client.update_schedule_targeting(
            {
                "campaign_id": "456",
                "remove_criterion_ids": ["789"],
            }
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_add_schedule_default_hours(
        self, client: _MockExtensionsClient
    ) -> None:
        """Default values when start_hour/end_hour are unspecified."""
        cc_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/new")
        ]
        cc_service.mutate_campaign_criteria.return_value = response

        client._get_service = lambda name: cc_service

        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.get_service.return_value = MagicMock(
            campaign_path=MagicMock(return_value="customers/123/campaigns/456"),
        )
        client._client.enums.DayOfWeekEnum.TUESDAY = "TUESDAY"
        client._client.enums.MinuteOfHourEnum.ZERO = "ZERO"

        result = await client.update_schedule_targeting(
            {
                "campaign_id": "456",
                "add_schedules": [
                    {"day": "TUESDAY"},  # start_hour/end_hour omitted
                ],
            }
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# apply_recommendation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyRecommendation:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_apply_success(self, client: _MockExtensionsClient) -> None:
        """Applying a recommendation completes successfully."""
        rec_service = MagicMock()
        response = MagicMock()
        response.results = [
            MagicMock(resource_name="customers/123/recommendations/456")
        ]
        rec_service.apply_recommendation.return_value = response

        client._get_service = lambda name: rec_service

        op = MagicMock()
        client._client.get_type.return_value = op

        result = await client.apply_recommendation(
            {
                "resource_name": "customers/123/recommendations/456",
            }
        )
        assert result["resource_name"] == "customers/123/recommendations/456"


# ---------------------------------------------------------------------------
# list_recommendations filter tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListRecommendationsFilters:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_with_recommendation_type_filter(
        self, client: _MockExtensionsClient
    ) -> None:
        """Filtering when recommendation_type is provided."""
        client._search = AsyncMock(return_value=[])
        result = await client.list_recommendations(recommendation_type="KEYWORD")
        assert result == []
        # Check that the query passed to _search contains KEYWORD.
        call_args = client._search.call_args[0][0]
        assert "KEYWORD" in call_args

    @pytest.mark.asyncio
    async def test_with_both_filters(self, client: _MockExtensionsClient) -> None:
        """Both campaign_id and recommendation_type provided."""
        client._search = AsyncMock(return_value=[])
        result = await client.list_recommendations(
            campaign_id="123", recommendation_type="KEYWORD"
        )
        assert result == []
        call_args = client._search.call_args[0][0]
        assert "123" in call_args
        assert "KEYWORD" in call_args


# ---------------------------------------------------------------------------
# list_location_targeting bid_modifier=None tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListLocationTargetingBidModifier:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_bid_modifier_none(self, client: _MockExtensionsClient) -> None:
        """Returns None when bid_modifier is unset."""
        mock_row = MagicMock()
        mock_row.campaign_criterion.criterion_id = "1"
        mock_row.campaign_criterion.location.geo_target_constant = (
            "geoTargetConstants/2392"
        )
        mock_row.campaign_criterion.bid_modifier = 0  # Falsy
        client._search = AsyncMock(return_value=[mock_row])

        result = await client.list_location_targeting("123")
        assert result[0]["bid_modifier"] is None


# ---------------------------------------------------------------------------
# list_schedule_targeting bid_modifier=None tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListScheduleTargetingBidModifier:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_bid_modifier_none(self, client: _MockExtensionsClient) -> None:
        """Returns None when bid_modifier is unset."""
        mock_row = MagicMock()
        mock_row.campaign_criterion.criterion_id = "1"
        mock_row.campaign_criterion.ad_schedule.day_of_week = "MONDAY"
        mock_row.campaign_criterion.ad_schedule.start_hour = 0
        mock_row.campaign_criterion.ad_schedule.end_hour = 24
        mock_row.campaign_criterion.ad_schedule.start_minute = "ZERO"
        mock_row.campaign_criterion.ad_schedule.end_minute = "ZERO"
        mock_row.campaign_criterion.bid_modifier = 0  # Falsy
        client._search = AsyncMock(return_value=[mock_row])

        result = await client.list_schedule_targeting("123")
        assert result[0]["bid_modifier"] is None


# ---------------------------------------------------------------------------
# get_bid_adjustments type_/type compatibility tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBidAdjustmentsCompat:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_type_attribute_fallback(self, client: _MockExtensionsClient) -> None:
        """Falls back to `type` when `type_` is missing."""
        mock_row = MagicMock(spec=["campaign_criterion"])
        mock_row.campaign_criterion = MagicMock()
        mock_row.campaign_criterion.criterion_id = "1"
        # No type_ attribute (excluded via spec).
        del mock_row.campaign_criterion.type_
        mock_row.campaign_criterion.type = "DEVICE"
        mock_row.campaign_criterion.bid_modifier = 1.2
        mock_row.campaign_criterion.device.type_ = "MOBILE"

        client._search = AsyncMock(return_value=[mock_row])
        result = await client.get_bid_adjustments("123")
        assert result[0]["type"] == "DEVICE"
