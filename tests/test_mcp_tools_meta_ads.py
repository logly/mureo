"""Meta Ads MCPツール定義・ハンドラーテスト

ツール定義（inputSchema、requiredフィールド）とハンドラー（クライアントモック）の検証。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_meta_ads_tools():
    from mureo.mcp import tools_meta_ads

    return tools_meta_ads


def _import_handlers():
    from mureo.mcp import _handlers_meta_ads

    return _handlers_meta_ads


# ---------------------------------------------------------------------------
# ツール定義テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsToolDefinitions:
    """Meta Adsツール一覧が正しく定義されていることを検証する"""

    def test_tool_count(self) -> None:
        """全52ツールが定義されていること"""
        mod = _import_meta_ads_tools()
        assert len(mod.TOOLS) == 52

    def test_all_tool_names(self) -> None:
        """全ツール名がmeta_ads.で始まること"""
        mod = _import_meta_ads_tools()
        for tool in mod.TOOLS:
            assert tool.name.startswith("meta_ads."), f"不正なツール名: {tool.name}"

    def test_all_tools_have_input_schema(self) -> None:
        """全ツールにinputSchemaが定義されていること"""
        mod = _import_meta_ads_tools()
        for tool in mod.TOOLS:
            assert "type" in tool.inputSchema
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema

    @pytest.mark.parametrize(
        "tool_name,expected_required",
        [
            ("meta_ads.campaigns.list", ["account_id"]),
            ("meta_ads.campaigns.get", ["account_id", "campaign_id"]),
            (
                "meta_ads.campaigns.create",
                ["account_id", "name", "objective"],
            ),
            ("meta_ads.campaigns.update", ["account_id", "campaign_id"]),
            ("meta_ads.ad_sets.list", ["account_id"]),
            (
                "meta_ads.ad_sets.create",
                ["account_id", "campaign_id", "name", "daily_budget"],
            ),
            ("meta_ads.ad_sets.update", ["account_id", "ad_set_id"]),
            ("meta_ads.ads.list", ["account_id"]),
            (
                "meta_ads.ads.create",
                ["account_id", "ad_set_id", "name", "creative_id"],
            ),
            ("meta_ads.ads.update", ["account_id", "ad_id"]),
            ("meta_ads.insights.report", ["account_id"]),
            (
                "meta_ads.insights.breakdown",
                ["account_id", "campaign_id"],
            ),
            ("meta_ads.audiences.list", ["account_id"]),
            ("meta_ads.audiences.create", ["account_id", "name", "subtype"]),
        ],
    )
    def test_required_fields(
        self, tool_name: str, expected_required: list[str]
    ) -> None:
        """各ツールのrequiredフィールドが正しいこと"""
        mod = _import_meta_ads_tools()
        tool = next((t for t in mod.TOOLS if t.name == tool_name), None)
        assert tool is not None, f"ツール {tool_name} が見つかりません"
        assert set(tool.inputSchema["required"]) == set(expected_required)


# ---------------------------------------------------------------------------
# ハンドラーテスト — ヘルパー
# ---------------------------------------------------------------------------


def _mock_meta_ads_context():
    """Meta Ads認証情報とクライアントのモックを返す"""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# ハンドラーテスト — キャンペーン
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsCampaignHandlers:
    """キャンペーン系ハンドラーテスト"""

    async def test_campaigns_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_campaigns.return_value = [{"id": "1", "name": "Meta Camp"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.campaigns.list", {"account_id": "act_123"}
            )

        client.list_campaigns.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "1"

    async def test_campaigns_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_campaign.return_value = {"id": "456", "name": "Detail"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.campaigns.get",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.get_campaign.assert_awaited_once_with("456")

    async def test_campaigns_create(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_campaign.return_value = {"id": "789"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.campaigns.create",
                {
                    "account_id": "act_123",
                    "name": "New Camp",
                    "objective": "CONVERSIONS",
                },
            )

        client.create_campaign.assert_awaited_once()

    async def test_campaigns_update(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.update_campaign.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.campaigns.update",
                {"account_id": "act_123", "campaign_id": "456", "name": "Updated"},
            )

        client.update_campaign.assert_awaited_once()


# ---------------------------------------------------------------------------
# ハンドラーテスト — 広告セット
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsAdSetHandlers:
    """広告セット系ハンドラーテスト"""

    async def test_ad_sets_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_ad_sets.return_value = [{"id": "10", "name": "AS1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_sets.list", {"account_id": "act_123"}
            )

        client.list_ad_sets.assert_awaited_once()

    async def test_ad_sets_create(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_ad_set.return_value = {"id": "20"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_sets.create",
                {
                    "account_id": "act_123",
                    "campaign_id": "456",
                    "name": "New AdSet",
                    "daily_budget": 5000,
                },
            )

        client.create_ad_set.assert_awaited_once()

    async def test_ad_sets_update(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.update_ad_set.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_sets.update",
                {"account_id": "act_123", "ad_set_id": "20", "name": "Updated"},
            )

        client.update_ad_set.assert_awaited_once()


# ---------------------------------------------------------------------------
# ハンドラーテスト — 広告
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsAdHandlers:
    """広告系ハンドラーテスト"""

    async def test_ads_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_ads.return_value = [{"id": "30", "name": "Ad1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ads.list", {"account_id": "act_123"}
            )

        client.list_ads.assert_awaited_once()

    async def test_ads_create(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_ad.return_value = {"id": "40"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ads.create",
                {
                    "account_id": "act_123",
                    "ad_set_id": "20",
                    "name": "New Ad",
                    "creative_id": "cr_999",
                },
            )

        client.create_ad.assert_awaited_once()

    async def test_ads_update(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.update_ad.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ads.update",
                {"account_id": "act_123", "ad_id": "40", "name": "Updated Ad"},
            )

        client.update_ad.assert_awaited_once()


# ---------------------------------------------------------------------------
# ハンドラーテスト — インサイト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsInsightsHandlers:
    """インサイト系ハンドラーテスト"""

    async def test_insights_report(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_performance_report.return_value = [{"impressions": 1000}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.insights.report", {"account_id": "act_123"}
            )

        client.get_performance_report.assert_awaited_once()

    async def test_insights_breakdown(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_breakdown_report.return_value = [{"age": "18-24"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.insights.breakdown",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.get_breakdown_report.assert_awaited_once()


# ---------------------------------------------------------------------------
# ハンドラーテスト — オーディエンス
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsAudienceHandlers:
    """オーディエンス系ハンドラーテスト"""

    async def test_audiences_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_custom_audiences.return_value = [{"id": "50", "name": "Aud1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.audiences.list", {"account_id": "act_123"}
            )

        client.list_custom_audiences.assert_awaited_once()

    async def test_audiences_create(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_custom_audience.return_value = {"id": "60"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.audiences.create",
                {
                    "account_id": "act_123",
                    "name": "New Audience",
                    "subtype": "WEBSITE",
                },
            )

        client.create_custom_audience.assert_awaited_once()


# ---------------------------------------------------------------------------
# エラーハンドリングテスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsErrorHandling:
    """エラーハンドリングの検証"""

    async def test_missing_required_param(self) -> None:
        """必須パラメータ欠損でValueErrorが発生"""
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="account_id"):
            await mod.handle_tool("meta_ads.campaigns.list", {})

    async def test_unknown_tool_raises_error(self) -> None:
        """未知のツール名でValueErrorが発生"""
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="Unknown"):
            await mod.handle_tool("meta_ads.unknown.tool", {"account_id": "act_123"})

    async def test_no_credentials_returns_error_text(self) -> None:
        """認証情報なしでエラーテキストを返す"""
        handlers = _import_handlers()
        mod = _import_meta_ads_tools()
        with patch.object(handlers, "load_meta_ads_credentials", return_value=None):
            result = await mod.handle_tool(
                "meta_ads.campaigns.list", {"account_id": "act_123"}
            )
        assert len(result) == 1
        assert "認証情報" in result[0].text

    async def test_handler_api_error(self) -> None:
        """API例外がTextContentエラーメッセージに変換されること"""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_campaigns.side_effect = RuntimeError("Meta API接続エラー")

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.campaigns.list", {"account_id": "act_123"}
            )

        assert len(result) == 1
        assert "APIエラー" in result[0].text
        assert "Meta API接続エラー" in result[0].text
