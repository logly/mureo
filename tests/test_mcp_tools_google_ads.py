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
        """全83ツールが定義されていること"""
        mod = _import_google_ads_tools()
        assert len(mod.TOOLS) == 83

    def test_all_tool_names(self) -> None:
        """全ツール名が google_ads_ で始まること（MCP仕様準拠の underscore 区切り）"""
        mod = _import_google_ads_tools()
        for tool in mod.TOOLS:
            assert tool.name.startswith("google_ads_"), f"不正なツール名: {tool.name}"

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
            ("google_ads_campaigns_list", []),
            ("google_ads_campaigns_get", ["campaign_id"]),
            ("google_ads_campaigns_create", ["name"]),
            ("google_ads_campaigns_update", ["campaign_id"]),
            (
                "google_ads_campaigns_update_status",
                ["campaign_id", "status"],
            ),
            ("google_ads_ad_groups_list", []),
            (
                "google_ads_ad_groups_create",
                ["campaign_id", "name"],
            ),
            ("google_ads_ad_groups_update", ["ad_group_id"]),
            ("google_ads_ads_list", []),
            (
                "google_ads_ads_create",
                ["ad_group_id", "headlines", "descriptions"],
            ),
            (
                "google_ads_ads_create_display",
                [
                    "ad_group_id",
                    "headlines",
                    "long_headline",
                    "descriptions",
                    "business_name",
                    "marketing_image_paths",
                    "square_marketing_image_paths",
                    "final_url",
                ],
            ),
            ("google_ads_ads_update", ["ad_group_id", "ad_id"]),
            (
                "google_ads_ads_update_status",
                ["ad_group_id", "ad_id", "status"],
            ),
            ("google_ads_keywords_list", []),
            (
                "google_ads_keywords_add",
                ["ad_group_id", "keywords"],
            ),
            (
                "google_ads_keywords_remove",
                ["ad_group_id", "criterion_id"],
            ),
            ("google_ads_keywords_suggest", ["seed_keywords"]),
            ("google_ads_keywords_diagnose", ["campaign_id"]),
            ("google_ads_negative_keywords_list", ["campaign_id"]),
            (
                "google_ads_negative_keywords_add",
                ["campaign_id", "keywords"],
            ),
            ("google_ads_budget_get", ["campaign_id"]),
            (
                "google_ads_budget_update",
                ["budget_id", "amount"],
            ),
            ("google_ads_performance_report", []),
            ("google_ads_search_terms_report", []),
            (
                "google_ads_search_terms_review",
                ["campaign_id"],
            ),
            (
                "google_ads_auction_insights_analyze",
                ["campaign_id"],
            ),
            ("google_ads_cpc_detect_trend", ["campaign_id"]),
            ("google_ads_device_analyze", ["campaign_id"]),
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
            result = await mod.handle_tool(
                "google_ads_campaigns_list", {"customer_id": "123"}
            )

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
                "google_ads_campaigns_get",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.get_campaign.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "456"

    async def test_campaigns_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_campaign.return_value = {
            "resource_name": "customers/123/campaigns/789"
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_campaigns_create",
                {"customer_id": "123", "name": "New Campaign"},
            )

        client.create_campaign.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_campaigns_create_forwards_channel_type(self) -> None:
        """handle_campaigns_create が channel_type を client.create_campaign に転送すること。"""
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_campaign.return_value = {
            "resource_name": "customers/123/campaigns/999"
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            await mod.handle_tool(
                "google_ads_campaigns_create",
                {
                    "customer_id": "123",
                    "name": "Display Campaign",
                    "channel_type": "DISPLAY",
                    "budget_id": "555",
                    "bidding_strategy": "MAXIMIZE_CLICKS",
                },
            )

        client.create_campaign.assert_awaited_once()
        call_params = client.create_campaign.call_args[0][0]
        assert call_params["name"] == "Display Campaign"
        assert call_params["channel_type"] == "DISPLAY"
        assert call_params["budget_id"] == "555"
        assert call_params["bidding_strategy"] == "MAXIMIZE_CLICKS"

    async def test_campaigns_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_campaign.return_value = {
            "resource_name": "customers/123/campaigns/456"
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_campaigns_update",
                {"customer_id": "123", "campaign_id": "456", "name": "Updated"},
            )

        client.update_campaign.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_campaigns_update_status(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_campaign_status.return_value = {
            "resource_name": "customers/123/campaigns/456"
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_campaigns_update_status",
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
                "google_ads_ad_groups_list",
                {"customer_id": "123"},
            )

        client.list_ad_groups.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert len(parsed) == 1

    async def test_ad_groups_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_ad_group.return_value = {
            "resource_name": "customers/123/adGroups/99"
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_ad_groups_create",
                {"customer_id": "123", "campaign_id": "456", "name": "New AG"},
            )

        client.create_ad_group.assert_awaited_once()

    async def test_ad_groups_update(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.update_ad_group.return_value = {
            "resource_name": "customers/123/adGroups/99"
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_ad_groups_update",
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
                "google_ads_ads_list", {"customer_id": "123"}
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
                "google_ads_ads_create",
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
                "google_ads_ads_update_status",
                {
                    "customer_id": "123",
                    "ad_group_id": "10",
                    "ad_id": "55",
                    "status": "PAUSED",
                },
            )

        client.update_ad_status.assert_awaited_once()

    async def test_ads_create_display(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_display_ad.return_value = {
            "resource_name": "customers/123/adGroupAds/10~99",
            "uploaded_assets": {
                "marketing": ["customers/123/assets/1"],
                "square_marketing": ["customers/123/assets/2"],
                "logo": [],
            },
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads_ads_create_display",
                {
                    "customer_id": "123",
                    "ad_group_id": "10",
                    "headlines": ["H1", "H2"],
                    "long_headline": "Long Headline Sample",
                    "descriptions": ["D1"],
                    "business_name": "Acme",
                    "marketing_image_paths": ["/tmp/m.jpg"],
                    "square_marketing_image_paths": ["/tmp/s.jpg"],
                    "final_url": "https://example.com",
                },
            )

        client.create_display_ad.assert_awaited_once()
        call_args = client.create_display_ad.call_args[0][0]
        assert call_args["ad_group_id"] == "10"
        assert call_args["long_headline"] == "Long Headline Sample"
        assert call_args["business_name"] == "Acme"
        parsed = json.loads(result[0].text)
        assert "uploaded_assets" in parsed


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
                "google_ads_keywords_list", {"customer_id": "123"}
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
                "google_ads_keywords_add",
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
                "google_ads_keywords_remove",
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
                "google_ads_keywords_suggest",
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
                "google_ads_keywords_diagnose",
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
                "google_ads_negative_keywords_list",
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
                "google_ads_negative_keywords_add",
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
                "google_ads_budget_get",
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
                "google_ads_budget_update",
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
                "google_ads_performance_report",
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
                "google_ads_search_terms_report",
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
                "google_ads_search_terms_review",
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
                "google_ads_auction_insights_analyze",
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
                "google_ads_cpc_detect_trend",
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
                "google_ads_device_analyze",
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
        """customer_id未指定 + credentials.jsonにもない場合にエラーテキスト返却"""
        mod = _import_google_ads_tools()
        with patch(
            "mureo.mcp._handlers_google_ads.load_google_ads_credentials",
            return_value=None,
        ):
            result = await mod.handle_tool("google_ads_campaigns_list", {})
            assert any("Credentials not found" in r.text for r in result)

    async def test_unknown_tool_raises_error(self) -> None:
        """未知のツール名でValueErrorが発生"""
        mod = _import_google_ads_tools()
        with pytest.raises(ValueError, match="Unknown"):
            await mod.handle_tool("google_ads_unknown_tool", {"customer_id": "123"})

    async def test_no_credentials_returns_error_text(self) -> None:
        """認証情報なしでエラーテキストを返す"""
        mod = _import_google_ads_tools()
        h = _import_handlers()
        with patch.object(h, "load_google_ads_credentials", return_value=None):
            result = await mod.handle_tool(
                "google_ads_campaigns_list", {"customer_id": "123"}
            )
        assert len(result) == 1
        assert "Credentials not found" in result[0].text

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
                "google_ads_campaigns_diagnose",
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
                "google_ads_campaigns_list", {"customer_id": "123"}
            )

        assert len(result) == 1
        assert "API error" in result[0].text
        assert "API接続エラー" in result[0].text
