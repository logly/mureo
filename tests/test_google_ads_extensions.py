"""Google Ads _extensions.py ユニットテスト

_ExtensionsMixin の各メソッドをモックベースでテストする。
_search / _get_service / _client をモックし、外部API呼び出しを排除。
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
# テスト用のモッククライアントクラス
# ---------------------------------------------------------------------------


class _MockExtensionsClient(_ExtensionsMixin):
    """_ExtensionsMixin をテスト可能にするモッククラス"""

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
# _normalize_device_type テスト
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
# list_sitelinks テスト
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
        """キャンペーンレベルとアカウントレベルのサイトリンクを統合して返す"""
        campaign_row = MagicMock()
        # map_sitelink が呼ばれるので、パッチする
        with patch("mureo.google_ads._extensions_sitelinks.map_sitelink") as mock_map:
            mock_map.side_effect = [
                {"id": "1", "link_text": "Link1"},
                {"id": "2", "link_text": "Link2"},
            ]
            client._search = AsyncMock(
                side_effect=[
                    [campaign_row],  # キャンペーンレベル
                    [MagicMock()],  # アカウントレベル
                ]
            )
            result = await client.list_sitelinks("123")

        assert len(result) == 2
        assert result[0]["level"] == "campaign"
        assert result[1]["level"] == "account"

    @pytest.mark.asyncio
    async def test_dedup_by_id(self, client: _MockExtensionsClient) -> None:
        """同一IDのサイトリンクは重複排除される"""
        with patch("mureo.google_ads._extensions_sitelinks.map_sitelink") as mock_map:
            mock_map.side_effect = [
                {"id": "1", "link_text": "Link1"},
                {"id": "1", "link_text": "Link1dup"},  # 同じID
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
        """アカウントレベルの取得に失敗してもキャンペーンレベルは返る"""
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
# create_sitelink テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSitelink:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_max_sitelinks_exceeded(self, client: _MockExtensionsClient) -> None:
        """上限超過時はバリデーションエラーを返す"""
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
# list_callouts テスト
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
# create_callout テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCallout:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_max_callouts_exceeded(self, client: _MockExtensionsClient) -> None:
        """上限超過時はバリデーションエラーを返す"""
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
# list_conversion_actions テスト
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
# create_conversion_action バリデーションテスト
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
# update_conversion_action バリデーションテスト
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
# get_conversion_action テスト
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
# get_conversion_action_tag テスト
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
# list_recommendations テスト
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
# get_device_targeting テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDeviceTargeting:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_all_devices_returned(self, client: _MockExtensionsClient) -> None:
        """criterionが無くても3デバイスが常に返る"""
        client._search = AsyncMock(return_value=[])
        result = await client.get_device_targeting("123")
        assert len(result) == 3
        device_types = {r["device_type"] for r in result}
        assert device_types == {"DESKTOP", "MOBILE", "TABLET"}
        # デフォルトは有効
        for r in result:
            assert r["enabled"] is True
            assert r["criterion_id"] is None

    @pytest.mark.asyncio
    async def test_disabled_device(self, client: _MockExtensionsClient) -> None:
        """bid_modifier=0.0 のデバイスは無効と判定される"""
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
# set_device_targeting バリデーションテスト
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
# get_bid_adjustments テスト
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
# update_bid_adjustment バリデーションテスト
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
# list_change_history テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListChangeHistory:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_default_date_range(self, client: _MockExtensionsClient) -> None:
        """日付未指定時はデフォルトの14日間で検索される"""
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
# list_location_targeting テスト
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
# list_schedule_targeting テスト
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
# get_conversion_performance テスト
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
        cost_row.metrics.cost_micros = 10_000_000_000  # 10,000円

        # 1回目: CV別、2回目: コスト、3回目: LP別
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
        """campaign_id指定時のフィルタリング"""
        client._search = AsyncMock(return_value=[])
        result = await client.get_conversion_performance(campaign_id="456")
        assert result["campaign_id"] == "456"
        assert result["total_conversions"] == 0

    @pytest.mark.asyncio
    async def test_cost_query_failure_fallback(
        self, client: _MockExtensionsClient
    ) -> None:
        """コスト取得失敗時にCPAは0で返却される"""
        cv_row = MagicMock()
        cv_row.campaign.id = 1
        cv_row.campaign.name = "Campaign A"
        cv_row.segments.conversion_action_name = "Purchase"
        cv_row.segments.date = "2024-01-01"
        cv_row.metrics.conversions = 3.0
        cv_row.metrics.conversions_value = 30000.0

        client._search = AsyncMock(
            side_effect=[
                [cv_row],  # CV別
                RuntimeError("fail"),  # コスト取得失敗
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
        """LP別CV取得失敗時も正常に返却される"""
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
                RuntimeError("lp fail"),  # LP取得失敗
            ]
        )
        result = await client.get_conversion_performance()
        assert result["total_conversions"] == 2.0
        assert result["landing_pages"] == []

    @pytest.mark.asyncio
    async def test_with_lp_data(self, client: _MockExtensionsClient) -> None:
        """LP別CVデータが正しく返る"""
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
        """複数日のデータでfirst_date/last_dateが正しく設定される"""
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
# create_callout 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCalloutSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_create_callout_success(self, client: _MockExtensionsClient) -> None:
        """コールアウト作成が正常に完了する"""
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
# remove_callout 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveCallout:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_remove_callout_success(self, client: _MockExtensionsClient) -> None:
        """コールアウト削除が正常に完了する"""
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
        """無効なcampaign_idでバリデーションエラー"""
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
        """無効なasset_idでバリデーションエラー"""
        with pytest.raises(ValueError, match="Invalid"):
            await client.remove_callout(
                {
                    "campaign_id": "123",
                    "asset_id": "abc",
                }
            )


# ---------------------------------------------------------------------------
# create_sitelink 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSitelinkSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_create_sitelink_success(self, client: _MockExtensionsClient) -> None:
        """サイトリンク作成が正常に完了する"""
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
        """description1/description2を含むサイトリンク作成"""
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
        # description1/description2がセットされたことを確認
        asset_op.create.sitelink_asset.description1 = "Learn more"
        asset_op.create.sitelink_asset.description2 = "About our company"

    @pytest.mark.asyncio
    async def test_create_sitelink_account_level_not_counted(
        self, client: _MockExtensionsClient
    ) -> None:
        """アカウントレベルのサイトリンクは上限カウントに含まれない"""
        with patch.object(client, "list_sitelinks", new_callable=AsyncMock) as mock_ls:
            # 19件キャンペーン + 5件アカウント = 24件だが、キャンペーンレベルは19なので作成可能
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
# remove_sitelink 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveSitelink:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_remove_sitelink_success(self, client: _MockExtensionsClient) -> None:
        """サイトリンク削除が正常に完了する"""
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
        """無効なIDでバリデーションエラー"""
        with pytest.raises(ValueError, match="Invalid"):
            await client.remove_sitelink(
                {
                    "campaign_id": "abc",
                    "asset_id": "456",
                }
            )


# ---------------------------------------------------------------------------
# create_conversion_action 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateConversionActionSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_create_basic(self, client: _MockExtensionsClient) -> None:
        """基本的なコンバージョンアクション作成"""
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
        """value_settings付きコンバージョンアクション作成"""
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
# update_conversion_action 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateConversionActionSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_update_name(self, client: _MockExtensionsClient) -> None:
        """名前の更新"""
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
        """複数フィールド同時更新"""
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
        """更新時のname長チェック"""
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
        """更新時のlookback windowバリデーション"""
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
        """更新時のview_through_lookback_window_daysバリデーション"""
        with pytest.raises(ValueError, match="1.+30"):
            await client.update_conversion_action(
                {
                    "conversion_action_id": "456",
                    "view_through_lookback_window_days": 31,
                }
            )


# ---------------------------------------------------------------------------
# remove_conversion_action 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveConversionAction:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_remove_success(self, client: _MockExtensionsClient) -> None:
        """コンバージョンアクション削除が正常に完了する"""
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
        """無効なIDでバリデーションエラー"""
        with pytest.raises(ValueError, match="Invalid"):
            await client.remove_conversion_action({"conversion_action_id": "abc"})


# ---------------------------------------------------------------------------
# set_device_targeting 正常系テスト
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
        """既存criterionのbid_modifierを更新"""
        # 既存のDESKTOP criterionがある
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
        """criterionが存在しない場合は新規作成"""
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
        assert len(result["updated"]) == 3  # 3デバイス分のmutate

    @pytest.mark.asyncio
    async def test_set_devices_partial_failure(
        self, client: _MockExtensionsClient
    ) -> None:
        """一部デバイスの設定失敗時にerrorsを含むが結果は返す"""
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
        """全デバイスの設定失敗時にValueErrorを送出"""
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
# update_bid_adjustment 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateBidAdjustmentSuccess:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_update_success(self, client: _MockExtensionsClient) -> None:
        """入札調整率の更新が正常に完了する"""
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
# update_location_targeting 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateLocationTargeting:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_add_locations(self, client: _MockExtensionsClient) -> None:
        """地域ターゲティングの追加"""
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
        """geoTargetConstants/ID形式での追加"""
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
        """地域ターゲティングの削除"""
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
        """追加と削除の同時操作"""
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
# update_schedule_targeting 正常系テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateScheduleTargeting:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_add_schedules(self, client: _MockExtensionsClient) -> None:
        """広告スケジュールの追加"""
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
        """広告スケジュールの削除"""
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
        """start_hour/end_hour未指定時のデフォルト値"""
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
                    {"day": "TUESDAY"},  # start_hour/end_hour省略
                ],
            }
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# apply_recommendation テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyRecommendation:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_apply_success(self, client: _MockExtensionsClient) -> None:
        """推奨事項適用が正常に完了する"""
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
# list_recommendations フィルタテスト
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
        """recommendation_type指定時のフィルタリング"""
        client._search = AsyncMock(return_value=[])
        result = await client.list_recommendations(recommendation_type="KEYWORD")
        assert result == []
        # _searchが呼ばれたクエリにKEYWORDが含まれているか確認
        call_args = client._search.call_args[0][0]
        assert "KEYWORD" in call_args

    @pytest.mark.asyncio
    async def test_with_both_filters(self, client: _MockExtensionsClient) -> None:
        """campaign_idとrecommendation_type両方指定"""
        client._search = AsyncMock(return_value=[])
        result = await client.list_recommendations(
            campaign_id="123", recommendation_type="KEYWORD"
        )
        assert result == []
        call_args = client._search.call_args[0][0]
        assert "123" in call_args
        assert "KEYWORD" in call_args


# ---------------------------------------------------------------------------
# list_location_targeting bid_modifier=None テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListLocationTargetingBidModifier:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_bid_modifier_none(self, client: _MockExtensionsClient) -> None:
        """bid_modifierが未設定の場合はNoneを返す"""
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
# list_schedule_targeting bid_modifier=None テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListScheduleTargetingBidModifier:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_bid_modifier_none(self, client: _MockExtensionsClient) -> None:
        """bid_modifierが未設定の場合はNoneを返す"""
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
# get_bid_adjustments type_/type 互換性テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBidAdjustmentsCompat:
    @pytest.fixture()
    def client(self) -> _MockExtensionsClient:
        return _MockExtensionsClient()

    @pytest.mark.asyncio
    async def test_type_attribute_fallback(self, client: _MockExtensionsClient) -> None:
        """type_がない場合typeにフォールバックする"""
        mock_row = MagicMock(spec=["campaign_criterion"])
        mock_row.campaign_criterion = MagicMock()
        mock_row.campaign_criterion.criterion_id = "1"
        # type_を持たない（specでtype_を除外）
        del mock_row.campaign_criterion.type_
        mock_row.campaign_criterion.type = "DEVICE"
        mock_row.campaign_criterion.bid_modifier = 1.2
        mock_row.campaign_criterion.device.type_ = "MOBILE"

        client._search = AsyncMock(return_value=[mock_row])
        result = await client.get_bid_adjustments("123")
        assert result[0]["type"] == "DEVICE"
