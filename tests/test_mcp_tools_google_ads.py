"""Google Ads MCPツール定義・ハンドラーテスト

ツール定義（inputSchema、requiredフィールド）とハンドラー（クライアントモック）の検証。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_google_ads_tools():
    from mureo.mcp import tools_google_ads

    return tools_google_ads


def _import_handlers():
    from mureo.mcp import _handlers_google_ads

    return _handlers_google_ads


# ---------------------------------------------------------------------------
# ツール定義テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsToolDefinitions:
    """Google Adsツール一覧が正しく定義されていることを検証する"""

    def test_tool_count(self) -> None:
        """全82ツールが定義されていること"""
        mod = _import_google_ads_tools()
        assert len(mod.TOOLS) == 82

    def test_all_tool_names(self) -> None:
        """全ツール名がgoogle_ads.で始まること"""
        mod = _import_google_ads_tools()
        for tool in mod.TOOLS:
            assert tool.name.startswith("google_ads."), f"不正なツール名: {tool.name}"

    def test_all_tools_have_input_schema(self) -> None:
        """全ツールにinputSchemaが定義されていること"""
        mod = _import_google_ads_tools()
        for tool in mod.TOOLS:
            assert "type" in tool.inputSchema
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema

    @pytest.mark.parametrize(
        "tool_name,expected_required",
        [
            ("google_ads.campaigns.list", ["customer_id"]),
            ("google_ads.campaigns.get", ["customer_id", "campaign_id"]),
            ("google_ads.campaigns.create", ["customer_id", "name"]),
            ("google_ads.campaigns.update", ["customer_id", "campaign_id"]),
            (
                "google_ads.campaigns.update_status",
                ["customer_id", "campaign_id", "status"],
            ),
            ("google_ads.ad_groups.list", ["customer_id"]),
            (
                "google_ads.ad_groups.create",
                ["customer_id", "campaign_id", "name"],
            ),
            ("google_ads.ad_groups.update", ["customer_id", "ad_group_id"]),
            ("google_ads.ads.list", ["customer_id"]),
            (
                "google_ads.ads.create",
                ["customer_id", "ad_group_id", "headlines", "descriptions"],
            ),
            ("google_ads.ads.update", ["customer_id", "ad_group_id", "ad_id"]),
            (
                "google_ads.ads.update_status",
                ["customer_id", "ad_group_id", "ad_id", "status"],
            ),
            ("google_ads.keywords.list", ["customer_id"]),
            (
                "google_ads.keywords.add",
                ["customer_id", "ad_group_id", "keywords"],
            ),
            (
                "google_ads.keywords.remove",
                ["customer_id", "ad_group_id", "criterion_id"],
            ),
            ("google_ads.keywords.suggest", ["customer_id", "seed_keywords"]),
            ("google_ads.keywords.diagnose", ["customer_id", "campaign_id"]),
            ("google_ads.negative_keywords.list", ["customer_id", "campaign_id"]),
            (
                "google_ads.negative_keywords.add",
                ["customer_id", "campaign_id", "keywords"],
            ),
            ("google_ads.budget.get", ["customer_id", "campaign_id"]),
            (
                "google_ads.budget.update",
                ["customer_id", "budget_id", "amount"],
            ),
            ("google_ads.performance.report", ["customer_id"]),
            ("google_ads.search_terms.report", ["customer_id"]),
            (
                "google_ads.search_terms.review",
                ["customer_id", "campaign_id"],
            ),
            (
                "google_ads.auction_insights.analyze",
                ["customer_id", "campaign_id"],
            ),
            ("google_ads.cpc.detect_trend", ["customer_id", "campaign_id"]),
            ("google_ads.device.analyze", ["customer_id", "campaign_id"]),
        ],
    )
    def test_required_fields(
        self, tool_name: str, expected_required: list[str]
    ) -> None:
        """各ツールのrequiredフィールドが正しいこと"""
        mod = _import_google_ads_tools()
        tool = next((t for t in mod.TOOLS if t.name == tool_name), None)
        assert tool is not None, f"ツール {tool_name} が見つかりません"
        assert set(tool.inputSchema["required"]) == set(expected_required)


# ---------------------------------------------------------------------------
# ハンドラーテスト — ヘルパー
# ---------------------------------------------------------------------------


def _mock_google_ads_context():
    """Google Ads認証情報とクライアントのモックを返す"""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# ハンドラーテスト — キャンペーン
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsCampaignHandlers:
    """キャンペーン系ハンドラーテスト"""

    async def test_campaigns_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_campaigns.return_value = [{"id": "1", "name": "Test"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool("google_ads.campaigns.list", {"customer_id": "123"})

        client.list_campaigns.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "1"

    async def test_campaigns_get(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_campaign.return_value = {"id": "456", "name": "Detail"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.campaigns.get",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.get_campaign.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "456"

    async def test_campaigns_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_campaign.return_value = {"resource_name": "customers/123/campaigns/789"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.campaigns.create",
                {"customer_id": "123", "name": "New Campaign"},
            )

        client.create_campaign.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_campaigns_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_campaign.return_value = {"resource_name": "customers/123/campaigns/456"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.campaigns.update",
                {"customer_id": "123", "campaign_id": "456", "name": "Updated"},
            )

        client.update_campaign.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_campaigns_update_status(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_campaign_status.return_value = {"resource_name": "customers/123/campaigns/456"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.campaigns.update_status",
                {"customer_id": "123", "campaign_id": "456", "status": "PAUSED"},
            )

        client.update_campaign_status.assert_awaited_once_with("456", "PAUSED")


# ---------------------------------------------------------------------------
# ハンドラーテスト — 広告グループ
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsAdGroupHandlers:
    """広告グループ系ハンドラーテスト"""

    async def test_ad_groups_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_ad_groups.return_value = [{"id": "10", "name": "AG1"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ad_groups.list",
                {"customer_id": "123"},
            )

        client.list_ad_groups.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert len(parsed) == 1

    async def test_ad_groups_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_ad_group.return_value = {"resource_name": "customers/123/adGroups/99"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ad_groups.create",
                {"customer_id": "123", "campaign_id": "456", "name": "New AG"},
            )

        client.create_ad_group.assert_awaited_once()

    async def test_ad_groups_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_ad_group.return_value = {"resource_name": "customers/123/adGroups/99"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ad_groups.update",
                {"customer_id": "123", "ad_group_id": "99", "name": "Updated AG"},
            )

        client.update_ad_group.assert_awaited_once()


# ---------------------------------------------------------------------------
# ハンドラーテスト — 広告
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsAdHandlers:
    """広告系ハンドラーテスト"""

    async def test_ads_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_ads.return_value = [{"id": "77", "type": "RSA"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ads.list", {"customer_id": "123"}
            )

        client.list_ads.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert len(parsed) == 1

    async def test_ads_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_ad.return_value = {"resource_name": "customers/123/ads/55"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ads.create",
                {
                    "customer_id": "123",
                    "ad_group_id": "10",
                    "headlines": ["H1", "H2", "H3"],
                    "descriptions": ["D1", "D2"],
                },
            )

        client.create_ad.assert_awaited_once()

    async def test_ads_update_status(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_ad_status.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ads.update_status",
                {
                    "customer_id": "123",
                    "ad_group_id": "10",
                    "ad_id": "55",
                    "status": "PAUSED",
                },
            )

        client.update_ad_status.assert_awaited_once()


# ---------------------------------------------------------------------------
# ハンドラーテスト — キーワード
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsKeywordHandlers:
    """キーワード系ハンドラーテスト"""

    async def test_keywords_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_keywords.return_value = [{"text": "test", "match_type": "BROAD"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.keywords.list", {"customer_id": "123"}
            )

        client.list_keywords.assert_awaited_once()

    async def test_keywords_add(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.add_keywords.return_value = [{"resource_name": "res"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.keywords.add",
                {
                    "customer_id": "123",
                    "ad_group_id": "10",
                    "keywords": [{"text": "test", "match_type": "BROAD"}],
                },
            )

        client.add_keywords.assert_awaited_once()

    async def test_keywords_remove(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.remove_keyword.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.keywords.remove",
                {
                    "customer_id": "123",
                    "ad_group_id": "10",
                    "criterion_id": "99",
                },
            )

        client.remove_keyword.assert_awaited_once()

    async def test_keywords_suggest(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.suggest_keywords.return_value = [{"keyword": "suggested"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.keywords.suggest",
                {"customer_id": "123", "seed_keywords": ["test"]},
            )

        client.suggest_keywords.assert_awaited_once()

    async def test_keywords_diagnose(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.diagnose_keywords.return_value = {"total": 10, "issues": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.keywords.diagnose",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.diagnose_keywords.assert_awaited_once_with("456")

    async def test_negative_keywords_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_negative_keywords.return_value = [{"text": "neg"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.negative_keywords.list",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.list_negative_keywords.assert_awaited_once_with("456")

    async def test_negative_keywords_add(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.add_negative_keywords.return_value = [{"resource_name": "res"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.negative_keywords.add",
                {
                    "customer_id": "123",
                    "campaign_id": "456",
                    "keywords": [{"text": "neg", "match_type": "EXACT"}],
                },
            )

        client.add_negative_keywords.assert_awaited_once()


# ---------------------------------------------------------------------------
# ハンドラーテスト — 予算
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsBudgetHandlers:
    """予算系ハンドラーテスト"""

    async def test_budget_get(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_budget.return_value = {"id": "1", "daily_budget": 5000}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.budget.get",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.get_budget.assert_awaited_once_with("456")

    async def test_budget_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_budget.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.budget.update",
                {"customer_id": "123", "budget_id": "789", "amount": 10000},
            )

        client.update_budget.assert_awaited_once()


# ---------------------------------------------------------------------------
# ハンドラーテスト — 分析
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsAnalysisHandlers:
    """分析系ハンドラーテスト"""

    async def test_performance_report(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_performance_report.return_value = [{"clicks": 100}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.performance.report",
                {"customer_id": "123"},
            )

        client.get_performance_report.assert_awaited_once()

    async def test_search_terms_report(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_search_terms_report.return_value = [{"term": "query"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.search_terms.report",
                {"customer_id": "123"},
            )

        client.get_search_terms_report.assert_awaited_once()

    async def test_search_terms_review(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.review_search_terms.return_value = {"candidates": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.search_terms.review",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.review_search_terms.assert_awaited_once()

    async def test_auction_insights_analyze(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.analyze_auction_insights.return_value = {"competitors": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.auction_insights.analyze",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.analyze_auction_insights.assert_awaited_once()

    async def test_cpc_detect_trend(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.detect_cpc_trend.return_value = {"direction": "rising"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.cpc.detect_trend",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.detect_cpc_trend.assert_awaited_once()

    async def test_device_analyze(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.analyze_device_performance.return_value = {"devices": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.device.analyze",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.analyze_device_performance.assert_awaited_once()


# ---------------------------------------------------------------------------
# エラーハンドリングテスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsErrorHandling:
    """エラーハンドリングの検証"""

    async def test_missing_required_param(self) -> None:
        """必須パラメータ欠損でValueErrorが発生"""
        mod = _import_google_ads_tools()
        with pytest.raises(ValueError, match="customer_id"):
            await mod.handle_tool("google_ads.campaigns.list", {})

    async def test_unknown_tool_raises_error(self) -> None:
        """未知のツール名でValueErrorが発生"""
        mod = _import_google_ads_tools()
        with pytest.raises(ValueError, match="Unknown"):
            await mod.handle_tool("google_ads.unknown.tool", {"customer_id": "123"})

    async def test_no_credentials_returns_error_text(self) -> None:
        """認証情報なしでエラーテキストを返す"""
        mod = _import_google_ads_tools()
        h = _import_handlers()
        with patch.object(h, "load_google_ads_credentials", return_value=None):
            result = await mod.handle_tool(
                "google_ads.campaigns.list", {"customer_id": "123"}
            )
        assert len(result) == 1
        assert "認証情報" in result[0].text

    async def test_diagnose_campaign_handler(self) -> None:
        """campaigns.diagnose ハンドラーが動作すること"""
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.diagnose_campaign_delivery.return_value = {"issues": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.campaigns.diagnose",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.diagnose_campaign_delivery.assert_awaited_once_with("456")

    async def test_handler_api_error(self) -> None:
        """API例外がTextContentエラーメッセージに変換されること"""
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_campaigns.side_effect = RuntimeError("API接続エラー")

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.campaigns.list", {"customer_id": "123"}
            )

        assert len(result) == 1
        assert "APIエラー" in result[0].text
        assert "API接続エラー" in result[0].text
