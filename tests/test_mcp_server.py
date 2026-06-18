"""MCP server tests.

Exercises list_tools / call_tool on the MCP server.
GoogleAdsApiClient and MetaAdsApiClient are mocked, and the server
functions are invoked directly without the stdio layer.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_server_module():
    """Import mureo/mcp/server.py."""
    from mureo.mcp import server as mcp_server_module

    return mcp_server_module


def _import_google_ads_handlers():
    from mureo.mcp import _handlers_google_ads

    return _handlers_google_ads


# ---------------------------------------------------------------------------
# list_tools tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListTools:
    """Verify list_tools returns the correct tool definitions."""

    async def test_list_tools_returns_all_tools(self) -> None:
        """list_tools returns all tools (Google Ads 83 + Meta Ads 82 + Search Console 10
        + Rollback 2 + Analysis 1 + Mureo Context 6 + Analytics Registry 1
        + Learning 2 = 187)."""
        mod = _import_server_module()
        tools = await mod.handle_list_tools()
        assert len(tools) == 187

    async def test_list_tools_contains_google_and_meta(self) -> None:
        """Google Ads and Meta Ads tools are included."""
        mod = _import_server_module()
        tools = await mod.handle_list_tools()
        names = {t.name for t in tools}
        assert "google_ads_campaigns_list" in names
        assert "google_ads_campaigns_get" in names
        assert "meta_ads_campaigns_list" in names
        assert "meta_ads_campaigns_get" in names

    async def test_list_tools_campaigns_list_schema(self) -> None:
        """campaigns.list's inputSchema has customer_id as optional."""
        mod = _import_server_module()
        tools = await mod.handle_list_tools()
        tool = next(t for t in tools if t.name == "google_ads_campaigns_list")
        schema = tool.inputSchema
        assert schema["type"] == "object"
        assert "customer_id" in schema["properties"]
        # customer_id is optional (falls back to credentials.json)
        assert "customer_id" not in schema.get("required", [])

    async def test_list_tools_campaigns_get_schema(self) -> None:
        """campaigns.get's inputSchema has campaign_id as required."""
        mod = _import_server_module()
        tools = await mod.handle_list_tools()
        tool = next(t for t in tools if t.name == "google_ads_campaigns_get")
        schema = tool.inputSchema
        assert schema["type"] == "object"
        assert "customer_id" in schema["properties"]
        assert "campaign_id" in schema["properties"]
        # customer_id is optional, campaign_id is required
        assert "campaign_id" in schema["required"]


# ---------------------------------------------------------------------------
# call_tool tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCallToolCampaignsList:
    """Tests that call_tool invokes google_ads_campaigns_list."""

    async def test_campaigns_list_calls_client(self) -> None:
        """campaigns.list calls GoogleAdsApiClient.list_campaigns."""
        mod = _import_server_module()
        ga_mod = _import_google_ads_handlers()

        mock_client = AsyncMock()
        mock_client.list_campaigns.return_value = [
            {"id": "123", "name": "Campaign 1", "status": "ENABLED"}
        ]

        mock_creds = MagicMock()
        with (
            patch.object(
                ga_mod, "load_google_ads_credentials", return_value=mock_creds
            ),
            patch.object(ga_mod, "create_google_ads_client", return_value=mock_client),
        ):
            result = await mod.handle_call_tool(
                "google_ads_campaigns_list",
                {"customer_id": "1234567890"},
            )

        mock_client.list_campaigns.assert_awaited_once()
        assert len(result) == 1
        assert result[0].type == "text"
        parsed = json.loads(result[0].text)
        assert len(parsed) == 1
        assert parsed[0]["id"] == "123"


@pytest.mark.unit
class TestCallToolCampaignsGet:
    """Tests that call_tool invokes google_ads_campaigns_get."""

    async def test_campaigns_get_calls_client(self) -> None:
        """campaigns.get calls GoogleAdsApiClient.get_campaign."""
        mod = _import_server_module()
        ga_mod = _import_google_ads_handlers()

        mock_client = AsyncMock()
        mock_client.get_campaign.return_value = {
            "id": "456",
            "name": "Campaign Detail",
            "status": "PAUSED",
            "budget_daily": 5000.0,
        }

        mock_creds = MagicMock()
        with (
            patch.object(
                ga_mod, "load_google_ads_credentials", return_value=mock_creds
            ),
            patch.object(ga_mod, "create_google_ads_client", return_value=mock_client),
        ):
            result = await mod.handle_call_tool(
                "google_ads_campaigns_get",
                {"customer_id": "1234567890", "campaign_id": "456"},
            )

        mock_client.get_campaign.assert_awaited_once_with("456")
        assert len(result) == 1
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "456"
        assert parsed["budget_daily"] == 5000.0


@pytest.mark.unit
class TestCallToolErrors:
    """Verify call_tool error cases."""

    async def test_unknown_tool_raises_error(self) -> None:
        """An unknown tool name raises ValueError."""
        mod = _import_server_module()

        with pytest.raises(ValueError, match="Unknown tool"):
            await mod.handle_call_tool("nonexistent.tool", {})

    async def test_missing_required_param_customer_id(self) -> None:
        """campaigns.list with missing customer_id and no credentials.json fallback."""
        mod = _import_server_module()

        with patch(
            "mureo.mcp._handlers_google_ads.load_google_ads_credentials",
            return_value=None,
        ):
            result = await mod.handle_call_tool("google_ads_campaigns_list", {})
            assert any("Credentials not found" in r.text for r in result)

    async def test_missing_required_param_campaign_id(self) -> None:
        """campaigns.get errors when campaign_id is missing."""
        mod = _import_server_module()
        ga_mod = _import_google_ads_handlers()

        mock_creds = MagicMock()
        with patch.object(
            ga_mod, "load_google_ads_credentials", return_value=mock_creds
        ):
            with pytest.raises(ValueError, match="campaign_id"):
                await mod.handle_call_tool(
                    "google_ads_campaigns_get",
                    {"customer_id": "1234567890"},
                )

    async def test_no_credentials_returns_error_text(self) -> None:
        """When credentials are missing, the error is returned as TextContent."""
        ga_mod = _import_google_ads_handlers()
        mod = _import_server_module()

        with patch.object(
            ga_mod,
            "load_google_ads_credentials",
            return_value=None,
        ):
            result = await mod.handle_call_tool(
                "google_ads_campaigns_list",
                {"customer_id": "1234567890"},
            )

        assert len(result) == 1
        assert result[0].type == "text"
        assert "Credentials not found" in result[0].text

    async def test_report_set_invalid_report_rejected_by_schema(self) -> None:
        """mureo_state_report_set with a ``report`` outside the enum is rejected
        by the dispatcher's schema pass (#277) before any handler runs."""
        mod = _import_server_module()
        with pytest.raises(ValueError, match="report"):
            await mod.handle_call_tool(
                "mureo_state_report_set",
                {"report": "monthly", "summary": {"narrative": "x"}},
            )
