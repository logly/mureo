"""Google Ads MCP分析・監視ツール ハンドラーテスト

パフォーマンス分析、予算分析、オークション分析、RSA分析、
BtoB最適化、クリエイティブ、監視、キャプチャ、および追加の
キャンペーン/予算/キーワード/広告ハンドラーの検証。
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
# ハンドラーテスト — キャンペーン・予算（追加分）
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsBudgetCreateAndAccountsHandlers:
    """予算作成・アカウント一覧・ネットワーク/広告パフォーマンスレポートのテスト"""

    async def test_budget_create(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.create_budget.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.budget.create",
                {"customer_id": "123", "name": "Daily Budget", "amount": 5000},
            )

        client.create_budget.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_accounts_list(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_accounts.return_value = [{"id": "111", "name": "Account1"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.accounts.list",
                {"customer_id": "123"},
            )

        client.list_accounts.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert len(parsed) == 1

    async def test_network_performance_report(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_network_performance_report.return_value = [{"network": "SEARCH"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.network_performance.report",
                {"customer_id": "123"},
            )

        client.get_network_performance_report.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["network"] == "SEARCH"

    async def test_ad_performance_report(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_ad_performance_report.return_value = [{"ad_id": "1", "clicks": 50}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ad_performance.report",
                {"customer_id": "123"},
            )

        client.get_ad_performance_report.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["clicks"] == 50


# ---------------------------------------------------------------------------
# ハンドラーテスト — キーワード（追加分）
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsKeywordExtendedHandlers:
    """キーワード追加ハンドラーテスト"""

    async def test_keywords_pause(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.pause_keyword.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.keywords.pause",
                {"customer_id": "123", "ad_group_id": "10", "criterion_id": "99"},
            )

        client.pause_keyword.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_negative_keywords_remove(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.remove_negative_keyword.return_value = {"resource_name": "res"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.negative_keywords.remove",
                {"customer_id": "123", "campaign_id": "456", "criterion_id": "99"},
            )

        client.remove_negative_keyword.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert "resource_name" in parsed

    async def test_negative_keywords_add_to_ad_group(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.add_negative_keywords_to_ad_group.return_value = [
            {"resource_name": "res"}
        ]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.negative_keywords.add_to_ad_group",
                {
                    "customer_id": "123",
                    "ad_group_id": "10",
                    "keywords": [{"text": "neg", "match_type": "EXACT"}],
                },
            )

        client.add_negative_keywords_to_ad_group.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["resource_name"] == "res"

    async def test_search_terms_analyze(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.analyze_search_terms.return_value = {"categories": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.search_terms.analyze",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.analyze_search_terms.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["categories"] == []

    async def test_negative_keywords_suggest(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.suggest_negative_keywords.return_value = [{"keyword": "free"}]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.negative_keywords.suggest",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.suggest_negative_keywords.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["keyword"] == "free"

    async def test_keywords_audit(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.audit_keywords.return_value = {"issues": [], "score": 85}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.keywords.audit",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.audit_keywords.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["score"] == 85

    async def test_keywords_cross_adgroup_duplicates(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.find_cross_adgroup_duplicates.return_value = {"duplicates": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.keywords.cross_adgroup_duplicates",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.find_cross_adgroup_duplicates.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["duplicates"] == []


# ---------------------------------------------------------------------------
# ハンドラーテスト — 広告（追加分）
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsAdExtendedHandlers:
    """広告追加ハンドラーテスト"""

    async def test_ads_policy_details(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_ad_policy_details.return_value = {"policy_topics": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ads.policy_details",
                {"customer_id": "123", "ad_group_id": "10", "ad_id": "55"},
            )

        client.get_ad_policy_details.assert_awaited_once_with("10", "55")
        parsed = json.loads(result[0].text)
        assert parsed["policy_topics"] == []


# ---------------------------------------------------------------------------
# ハンドラーテスト — パフォーマンス分析
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsPerformanceAnalysisHandlers:
    """パフォーマンス分析系ハンドラーテスト"""

    async def test_performance_analyze(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.analyze_performance.return_value = {"trend": "improving"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.performance.analyze",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.analyze_performance.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["trend"] == "improving"

    async def test_cost_increase_investigate(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.investigate_cost_increase.return_value = {"cause": "CPC rise"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.cost_increase.investigate",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.investigate_cost_increase.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["cause"] == "CPC rise"

    async def test_health_check_all(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.health_check_all_campaigns.return_value = {"status": "healthy"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.health_check.all",
                {"customer_id": "123"},
            )

        client.health_check_all_campaigns.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "healthy"

    async def test_ad_performance_compare(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.compare_ad_performance.return_value = {"comparison": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.ad_performance.compare",
                {"customer_id": "123", "ad_group_id": "10"},
            )

        client.compare_ad_performance.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["comparison"] == []


# ---------------------------------------------------------------------------
# ハンドラーテスト — 予算分析
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsBudgetAnalysisHandlers:
    """予算分析系ハンドラーテスト"""

    async def test_budget_efficiency(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.analyze_budget_efficiency.return_value = {"efficiency": 0.85}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.budget.efficiency",
                {"customer_id": "123"},
            )

        client.analyze_budget_efficiency.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["efficiency"] == 0.85

    async def test_budget_reallocation(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.suggest_budget_reallocation.return_value = {"suggestions": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.budget.reallocation",
                {"customer_id": "123"},
            )

        client.suggest_budget_reallocation.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["suggestions"] == []


# ---------------------------------------------------------------------------
# ハンドラーテスト — オークション分析
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsAuctionInsightsGetHandler:
    """オークション分析（get）ハンドラーテスト"""

    async def test_auction_insights_get(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.get_auction_insights.return_value = {"competitors": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.auction_insights.get",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.get_auction_insights.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["competitors"] == []


# ---------------------------------------------------------------------------
# ハンドラーテスト — RSA分析
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsRsaAssetsHandlers:
    """RSA分析系ハンドラーテスト"""

    async def test_rsa_assets_analyze(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.analyze_rsa_assets.return_value = {"assets": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.rsa_assets.analyze",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.analyze_rsa_assets.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["assets"] == []

    async def test_rsa_assets_audit(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.audit_rsa_assets.return_value = {"score": 90, "issues": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.rsa_assets.audit",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.audit_rsa_assets.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["score"] == 90


# ---------------------------------------------------------------------------
# ハンドラーテスト — BtoB
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsBtoBHandlers:
    """BtoB最適化ハンドラーテスト"""

    async def test_btob_optimizations(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.suggest_btob_optimizations.return_value = {"suggestions": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.btob.optimizations",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.suggest_btob_optimizations.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["suggestions"] == []


# ---------------------------------------------------------------------------
# ハンドラーテスト — クリエイティブ
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsCreativeHandlers:
    """クリエイティブ系ハンドラーテスト"""

    async def test_landing_page_analyze(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.analyze_landing_page.return_value = {"score": 75, "issues": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.landing_page.analyze",
                {"customer_id": "123", "url": "https://example.com"},
            )

        client.analyze_landing_page.assert_awaited_once_with("https://example.com")
        parsed = json.loads(result[0].text)
        assert parsed["score"] == 75

    async def test_creative_research(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.research_creative.return_value = {"suggestions": []}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.creative.research",
                {
                    "customer_id": "123",
                    "campaign_id": "456",
                    "url": "https://example.com",
                },
            )

        client.research_creative.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["suggestions"] == []


# ---------------------------------------------------------------------------
# ハンドラーテスト — 監視
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsMonitoringHandlers:
    """監視系ハンドラーテスト"""

    async def test_delivery_goal_evaluate(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.evaluate_delivery_goal.return_value = {"on_track": True}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.monitoring.delivery_goal",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.evaluate_delivery_goal.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["on_track"] is True

    async def test_cpa_goal_evaluate(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.evaluate_cpa_goal.return_value = {"within_target": True}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.monitoring.cpa_goal",
                {"customer_id": "123", "campaign_id": "456", "target_cpa": 1000},
            )

        client.evaluate_cpa_goal.assert_awaited_once_with("456", 1000)
        parsed = json.loads(result[0].text)
        assert parsed["within_target"] is True

    async def test_cv_goal_evaluate(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.evaluate_cv_goal.return_value = {"on_track": False}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.monitoring.cv_goal",
                {"customer_id": "123", "campaign_id": "456", "target_cv_daily": 10},
            )

        client.evaluate_cv_goal.assert_awaited_once_with("456", 10)
        parsed = json.loads(result[0].text)
        assert parsed["on_track"] is False

    async def test_zero_conversions_diagnose(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.diagnose_zero_conversions.return_value = {"diagnosis": "low traffic"}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "google_ads.monitoring.zero_conversions",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.diagnose_zero_conversions.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["diagnosis"] == "low traffic"


# ---------------------------------------------------------------------------
# ハンドラーテスト — キャプチャ
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsCaptureHandlers:
    """キャプチャ系ハンドラーテスト"""

    async def test_capture_screenshot(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        mock_screenshotter = AsyncMock()
        mock_screenshotter.capture.return_value = b"\x89PNG\r\n\x1a\n"

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
            patch(
                "mureo.google_ads._message_match.LPScreenshotter",
                return_value=mock_screenshotter,
            ),
        ):
            result = await mod.handle_tool(
                "google_ads.capture.screenshot",
                {"customer_id": "123", "url": "https://example.com"},
            )

        mock_screenshotter.capture.assert_awaited_once_with("https://example.com")
        parsed = json.loads(result[0].text)
        assert parsed["url"] == "https://example.com"
        assert parsed["format"] == "png"
        assert "screenshot_base64" in parsed
