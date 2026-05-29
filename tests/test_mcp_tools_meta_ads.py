"""Tests for the Meta Ads MCP tool definitions and handlers.

Verifies tool definitions (inputSchema, required fields) and handlers
(with the client mocked).
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
# Tool-definition tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsToolDefinitions:
    """Verify the Meta Ads tool list is defined correctly."""

    def test_tool_count(self) -> None:
        """All 81 tools are defined."""
        mod = _import_meta_ads_tools()
        assert len(mod.TOOLS) == 81

    def test_all_tool_names(self) -> None:
        """Every tool name starts with meta_ads_ (underscore-separated, per MCP spec)."""
        mod = _import_meta_ads_tools()
        for tool in mod.TOOLS:
            assert tool.name.startswith("meta_ads_"), f"Invalid tool name: {tool.name}"

    def test_all_tools_have_input_schema(self) -> None:
        """Every tool defines an inputSchema."""
        mod = _import_meta_ads_tools()
        for tool in mod.TOOLS:
            assert "type" in tool.inputSchema
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema

    @pytest.mark.parametrize(
        "tool_name,expected_required",
        [
            ("meta_ads_campaigns_list", []),
            ("meta_ads_campaigns_get", ["campaign_id"]),
            (
                "meta_ads_campaigns_create",
                ["name", "objective"],
            ),
            ("meta_ads_campaigns_update", ["campaign_id"]),
            ("meta_ads_ad_sets_list", []),
            (
                "meta_ads_ad_sets_create",
                ["campaign_id", "name"],
            ),
            ("meta_ads_ad_sets_update", ["ad_set_id"]),
            ("meta_ads_ads_list", []),
            (
                "meta_ads_ads_create",
                ["ad_set_id", "name", "creative_id"],
            ),
            ("meta_ads_ads_update", ["ad_id"]),
            ("meta_ads_insights_report", []),
            (
                "meta_ads_insights_breakdown",
                ["campaign_id"],
            ),
            ("meta_ads_audiences_list", []),
            ("meta_ads_audiences_create", ["name"]),
        ],
    )
    def test_required_fields(
        self, tool_name: str, expected_required: list[str]
    ) -> None:
        """Each tool's required field list is correct."""
        mod = _import_meta_ads_tools()
        tool = next((t for t in mod.TOOLS if t.name == tool_name), None)
        assert tool is not None, f"Tool {tool_name} not found"
        assert set(tool.inputSchema["required"]) == set(expected_required)


# ---------------------------------------------------------------------------
# Handler tests — helpers
# ---------------------------------------------------------------------------


def _mock_meta_ads_context():
    """Return mocks for Meta Ads credentials and the API client."""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# Handler tests — campaigns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsCampaignHandlers:
    """Campaign-related handler tests."""

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
                "meta_ads_campaigns_list", {"account_id": "act_123"}
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
                "meta_ads_campaigns_get",
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
                "meta_ads_campaigns_create",
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
                "meta_ads_campaigns_update",
                {"account_id": "act_123", "campaign_id": "456", "name": "Updated"},
            )

        client.update_campaign.assert_awaited_once()


# ---------------------------------------------------------------------------
# Handler tests — ad sets
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsAdSetHandlers:
    """Ad-set-related handler tests."""

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
                "meta_ads_ad_sets_list", {"account_id": "act_123"}
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
                "meta_ads_ad_sets_create",
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
                "meta_ads_ad_sets_update",
                {"account_id": "act_123", "ad_set_id": "20", "name": "Updated"},
            )

        client.update_ad_set.assert_awaited_once()


# ---------------------------------------------------------------------------
# Handler tests — ads
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsAdHandlers:
    """Ad-related handler tests."""

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
                "meta_ads_ads_list", {"account_id": "act_123"}
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
                "meta_ads_ads_create",
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
                "meta_ads_ads_update",
                {"account_id": "act_123", "ad_id": "40", "name": "Updated Ad"},
            )

        client.update_ad.assert_awaited_once()


# ---------------------------------------------------------------------------
# Handler tests — insights
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsInsightsHandlers:
    """Insight-related handler tests."""

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
                "meta_ads_insights_report", {"account_id": "act_123"}
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
                "meta_ads_insights_breakdown",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.get_breakdown_report.assert_awaited_once()


# ---------------------------------------------------------------------------
# Handler tests — audiences
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsAudienceHandlers:
    """Audience-related handler tests."""

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
                "meta_ads_audiences_list", {"account_id": "act_123"}
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
                "meta_ads_audiences_create",
                {
                    "account_id": "act_123",
                    "name": "New Audience",
                    "subtype": "WEBSITE",
                },
            )

        client.create_custom_audience.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error-handling tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsErrorHandling:
    """Verify error handling."""

    async def test_missing_required_param(self) -> None:
        """Returns error text when account_id is missing and credentials.json has none."""
        mod = _import_meta_ads_tools()
        with patch(
            "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
            return_value=None,
        ):
            result = await mod.handle_tool("meta_ads_campaigns_list", {})
            assert any("Credentials not found" in r.text for r in result)

    async def test_unknown_tool_raises_error(self) -> None:
        """An unknown tool name raises ValueError."""
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="Unknown"):
            await mod.handle_tool("meta_ads_unknown_tool", {"account_id": "act_123"})

    async def test_no_credentials_returns_error_text(self) -> None:
        """Returns error text when no credentials are present."""
        handlers = _import_handlers()
        mod = _import_meta_ads_tools()
        with patch.object(handlers, "load_meta_ads_credentials", return_value=None):
            result = await mod.handle_tool(
                "meta_ads_campaigns_list", {"account_id": "act_123"}
            )
        assert len(result) == 1
        assert "Credentials not found" in result[0].text

    async def test_handler_api_error(self) -> None:
        """API exceptions are converted into TextContent error messages."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_campaigns.side_effect = RuntimeError("Meta API接続エラー")

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_campaigns_list", {"account_id": "act_123"}
            )

        assert len(result) == 1
        assert "API error" in result[0].text
        assert "Meta API接続エラー" in result[0].text
