"""Google Ads MCP拡張ツール ハンドラーテスト

サイトリンク、コールアウト、コンバージョン、ターゲティング、変更履歴ハンドラーの検証。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_google_ads_tools():
    from mureo.mcp import tools_google_ads

    return tools_google_ads


def _import_handlers():
    from mureo.mcp import _handlers_google_ads

    return _handlers_google_ads


def _mock_google_ads_context():
    """Google Ads認証情報とクライアントのモックを返す"""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# ハンドラーテスト — サイトリンク
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsSitelinkHandlers:
    """サイトリンク系ハンドラーテスト"""

    async def test_sitelinks_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_sitelinks.return_value = [{"id": "1", "link_text": "Top"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_sitelinks_list",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.list_sitelinks.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed[0]["link_text"] == "Top"

    async def test_sitelinks_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_sitelink.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_sitelinks_create",
                {
                    "customer_id": "123",
                    "campaign_id": "456",
                    "link_text": "About",
                    "final_url": "https://example.com/about",
                },
            )

        client.create_sitelink.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_sitelinks_remove(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.remove_sitelink.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_sitelinks_remove",
                {"customer_id": "123", "campaign_id": "456", "asset_id": "789"},
            )

        client.remove_sitelink.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed


# ---------------------------------------------------------------------------
# ハンドラーテスト — コールアウト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsCalloutHandlers:
    """コールアウト系ハンドラーテスト"""

    async def test_callouts_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_callouts.return_value = [{"id": "1", "text": "Free shipping"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_callouts_list",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.list_callouts.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert len(parsed) == 1

    async def test_callouts_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_callout.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_callouts_create",
                {
                    "customer_id": "123",
                    "campaign_id": "456",
                    "callout_text": "Free shipping",
                },
            )

        client.create_callout.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_callouts_remove(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.remove_callout.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_callouts_remove",
                {"customer_id": "123", "campaign_id": "456", "asset_id": "789"},
            )

        client.remove_callout.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed


# ---------------------------------------------------------------------------
# ハンドラーテスト — コンバージョン
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsConversionHandlers:
    """コンバージョン系ハンドラーテスト"""

    async def test_conversions_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_conversion_actions.return_value = [{"id": "1", "name": "Purchase"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_conversions_list",
                {"customer_id": "123"},
            )

        client.list_conversion_actions.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert len(parsed) == 1

    async def test_conversions_get(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_conversion_action.return_value = {"id": "10", "name": "Purchase"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_conversions_get",
                {"customer_id": "123", "conversion_action_id": "10"},
            )

        client.get_conversion_action.assert_awaited_once_with("10")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "10"

    async def test_conversions_performance(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_conversion_performance.return_value = {"conversions": 50}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_conversions_performance",
                {"customer_id": "123"},
            )

        client.get_conversion_performance.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["conversions"] == 50

    async def test_conversions_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_conversion_action.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_conversions_create",
                {"customer_id": "123", "name": "New Conversion"},
            )

        client.create_conversion_action.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_conversions_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_conversion_action.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_conversions_update",
                {
                    "customer_id": "123",
                    "conversion_action_id": "10",
                    "name": "Updated",
                },
            )

        client.update_conversion_action.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_conversions_remove(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.remove_conversion_action.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_conversions_remove",
                {"customer_id": "123", "conversion_action_id": "10"},
            )

        client.remove_conversion_action.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_conversions_tag(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_conversion_action_tag.return_value = {"tag": "<script>...</script>"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_conversions_tag",
                {"customer_id": "123", "conversion_action_id": "10"},
            )

        client.get_conversion_action_tag.assert_awaited_once_with("10")
        parsed = json.loads(result[0].text)
        assert "tag" in parsed


# ---------------------------------------------------------------------------
# ハンドラーテスト — ターゲティング
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsTargetingHandlers:
    """ターゲティング系ハンドラーテスト"""

    async def test_recommendations_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_recommendations.return_value = [{"type": "KEYWORD"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_recommendations_list",
                {"customer_id": "123"},
            )

        client.list_recommendations.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["type"] == "KEYWORD"

    async def test_recommendations_apply(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.apply_recommendation.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_recommendations_apply",
                {
                    "customer_id": "123",
                    "resource_name": "customers/123/recommendations/456",
                },
            )

        client.apply_recommendation.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_device_targeting_get(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_device_targeting.return_value = {"devices": ["MOBILE", "DESKTOP"]}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_device_targeting_get",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.get_device_targeting.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert "MOBILE" in parsed["devices"]

    async def test_device_targeting_set(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.set_device_targeting.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_device_targeting_set",
                {
                    "customer_id": "123",
                    "campaign_id": "456",
                    "enabled_devices": ["MOBILE", "DESKTOP"],
                },
            )

        client.set_device_targeting.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_bid_adjustments_get(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_bid_adjustments.return_value = [{"criterion_id": "1"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_bid_adjustments_get",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.get_bid_adjustments.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed[0]["criterion_id"] == "1"

    async def test_bid_adjustments_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_bid_adjustment.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_bid_adjustments_update",
                {
                    "customer_id": "123",
                    "campaign_id": "456",
                    "criterion_id": "1",
                    "bid_modifier": 1.2,
                },
            )

        client.update_bid_adjustment.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_location_targeting_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_location_targeting.return_value = [{"location": "Tokyo"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_location_targeting_list",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.list_location_targeting.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed[0]["location"] == "Tokyo"

    async def test_location_targeting_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_location_targeting.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_location_targeting_update",
                {
                    "customer_id": "123",
                    "campaign_id": "456",
                    "add_locations": [{"geo_target_id": "1009312"}],
                },
            )

        client.update_location_targeting.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_schedule_targeting_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_schedule_targeting.return_value = [{"day": "MONDAY"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_schedule_targeting_list",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.list_schedule_targeting.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed[0]["day"] == "MONDAY"

    async def test_schedule_targeting_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_schedule_targeting.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_schedule_targeting_update",
                {
                    "customer_id": "123",
                    "campaign_id": "456",
                    "add_schedules": [
                        {"day": "MONDAY", "start_hour": 9, "end_hour": 17}
                    ],
                },
            )

        client.update_schedule_targeting.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_change_history_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_change_history.return_value = [{"change_type": "UPDATE"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_change_history_list",
                {"customer_id": "123"},
            )

        client.list_change_history.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["change_type"] == "UPDATE"
