"""Tests for the Google Ads MCP analysis and monitoring tool handlers.

Verifies performance analysis, budget analysis, auction analysis, RSA
analysis, B2B optimization, creative, monitoring, screenshot capture,
and the additional campaign / budget / keyword / ad handlers.
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
    """Return mocks for Google Ads credentials and the API client."""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# Handler tests — campaigns / budget (additional)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _standalone_google_ads():
    """Pin these handler tests to STANDALONE (untenanted) Google Ads.

    Google Ads gained workspace scoping (#411, mirroring Search Console's
    #375): when a ``mureo.runtime_context_factory`` is installed AND its
    store is a shared-auth multi-account backend, an undeclared
    ``google_ads_customer_ids`` fail-closes every customer_id. A dev box carrying such a
    plugin would therefore break these standalone assertions. Neutralize
    the scoping seam so this module always exercises the unrestricted
    path; the scoped behavior lives in test_account_id_tenant_scope.py.
    """
    with patch(
        "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
        return_value=None,
    ), patch(
        "mureo.mcp._handlers_google_ads_analysis.runtime_google_ads_customer_ids",
        return_value=None,
    ):
        yield


@pytest.mark.unit
class TestGoogleAdsBudgetCreateAndAccountsHandlers:
    """Tests for budget creation, account listing, and network/ad performance reports."""

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
                "google_ads_budget_create",
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
                "google_ads_accounts_list",
                {"customer_id": "123"},
            )

        client.list_accounts.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert len(parsed) == 1

    async def test_accounts_list_without_customer_id_uses_id_free_discovery(
        self,
    ) -> None:
        """Recovery path: with NO customer_id, accounts-list must not require one
        — it uses the id-free ``list_accessible_accounts`` primitive (keyed on
        the OAuth user), not the customer-scoped client. This is what lets an
        agent recover from an unset customer_id instead of dead-ending."""
        mod = _import_google_ads_tools()
        creds = MagicMock()
        accounts = [
            {"id": "111", "name": "Acct A", "is_manager": False, "parent_id": None},
            {"id": "222", "name": "Acct B", "is_manager": False, "parent_id": None},
        ]
        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch("mureo.auth.load_google_ads_credentials", return_value=creds),
            patch(
                "mureo.google_ads.list_accessible_accounts", return_value=accounts
            ) as m_list,
        ):
            result = await mod.handle_tool("google_ads_accounts_list", {})

        # The id-free primitive was used with the creds, and no customer_id
        # was required (no "customer_id is required" error).
        m_list.assert_called_once_with(creds)
        parsed = json.loads(result[0].text)
        assert [a["id"] for a in parsed] == ["111", "222"]

    async def test_accounts_list_byod_keeps_scoped_client_path(self) -> None:
        """BYOD must keep using the customer-scoped client (CSV-backed
        `list_accounts`), NOT the id-free discovery primitive — even with no
        customer_id. Locks the branch against regression."""
        mod = _import_google_ads_tools()
        client = AsyncMock()
        client.list_accounts.return_value = [{"customer_id": "byod"}]
        with (
            patch("mureo.byod.runtime.byod_has", return_value=True),
            patch(
                "mureo.mcp._handlers_google_ads_analysis._get_client",
                return_value=client,
            ),
            patch("mureo.google_ads.list_accessible_accounts") as m_list,
        ):
            result = await mod.handle_tool("google_ads_accounts_list", {})

        client.list_accounts.assert_awaited_once()
        m_list.assert_not_called()  # id-free path NOT taken in BYOD
        assert json.loads(result[0].text) == [{"customer_id": "byod"}]

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
                "google_ads_network_performance_report",
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
                "google_ads_ad_performance_report",
                {"customer_id": "123"},
            )

        client.get_ad_performance_report.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["clicks"] == 50


# ---------------------------------------------------------------------------
# Handler tests — keywords (additional)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsKeywordExtendedHandlers:
    """Keyword-addition handler tests."""

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
                "google_ads_keywords_pause",
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
                "google_ads_negative_keywords_remove",
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
                "google_ads_negative_keywords_add_to_ad_group",
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
                "google_ads_search_terms_analyze",
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
                "google_ads_negative_keywords_suggest",
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
                "google_ads_keywords_audit",
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
                "google_ads_keywords_cross_adgroup_duplicates",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.find_cross_adgroup_duplicates.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["duplicates"] == []


# ---------------------------------------------------------------------------
# Handler tests — ads (additional)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsAdExtendedHandlers:
    """Ad-addition handler tests."""

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
                "google_ads_ads_policy_details",
                {"customer_id": "123", "ad_group_id": "10", "ad_id": "55"},
            )

        client.get_ad_policy_details.assert_awaited_once_with("10", "55")
        parsed = json.loads(result[0].text)
        assert parsed["policy_topics"] == []


# ---------------------------------------------------------------------------
# Handler tests — performance analysis
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsPerformanceAnalysisHandlers:
    """Performance-analysis handler tests."""

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
                "google_ads_performance_analyze",
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
                "google_ads_cost_increase_investigate",
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
                "google_ads_health_check_all",
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
                "google_ads_ad_performance_compare",
                {"customer_id": "123", "ad_group_id": "10"},
            )

        client.compare_ad_performance.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["comparison"] == []


# ---------------------------------------------------------------------------
# Handler tests — budget analysis
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsBudgetAnalysisHandlers:
    """Budget-analysis handler tests."""

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
                "google_ads_budget_efficiency",
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
                "google_ads_budget_reallocation",
                {"customer_id": "123"},
            )

        client.suggest_budget_reallocation.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["suggestions"] == []


# ---------------------------------------------------------------------------
# Handler tests — auction analysis
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsAuctionInsightsGetHandler:
    """Auction-analysis (get) handler tests."""

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
                "google_ads_auction_insights_get",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.get_auction_insights.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["competitors"] == []


# ---------------------------------------------------------------------------
# Handler tests — RSA analysis
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsRsaAssetsHandlers:
    """RSA-analysis handler tests."""

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
                "google_ads_rsa_assets_analyze",
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
                "google_ads_rsa_assets_audit",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.audit_rsa_assets.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["score"] == 90


# ---------------------------------------------------------------------------
# Handler tests — BtoB
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsBtoBHandlers:
    """BtoB optimization handler tests."""

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
                "google_ads_btob_optimizations",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.suggest_btob_optimizations.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["suggestions"] == []


# ---------------------------------------------------------------------------
# Handler tests — creatives
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsCreativeHandlers:
    """Creative-related handler tests."""

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
                "google_ads_landing_page_analyze",
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
                "google_ads_creative_research",
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
# Handler tests — monitoring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsMonitoringHandlers:
    """Monitoring handler tests."""

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
                "google_ads_monitoring_delivery_goal",
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
                "google_ads_monitoring_cpa_goal",
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
                "google_ads_monitoring_cv_goal",
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
                "google_ads_monitoring_zero_conversions",
                {"customer_id": "123", "campaign_id": "456"},
            )

        client.diagnose_zero_conversions.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["diagnosis"] == "low traffic"


# ---------------------------------------------------------------------------
# Handler tests — capture
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsCaptureHandlers:
    """Capture handler tests."""

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
                "google_ads_capture_screenshot",
                {"customer_id": "123", "url": "https://example.com"},
            )

        mock_screenshotter.capture.assert_awaited_once_with("https://example.com")
        parsed = json.loads(result[0].text)
        assert parsed["url"] == "https://example.com"
        assert parsed["format"] == "png"
        assert "screenshot_base64" in parsed
