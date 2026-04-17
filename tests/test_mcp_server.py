"""MCP サーバーテスト

MCPサーバーの list_tools / call_tool の動作を検証する。
GoogleAdsApiClient / MetaAdsApiClient はモックし、stdio 層は介さずサーバー関数を直接呼ぶ。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _import_server_module():
    """mureo/mcp/server.py をインポートする"""
    from mureo.mcp import server as mcp_server_module

    return mcp_server_module


def _import_google_ads_handlers():
    from mureo.mcp import _handlers_google_ads

    return _handlers_google_ads


# ---------------------------------------------------------------------------
# list_tools テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListTools:
    """list_tools が正しいツール定義を返すことを検証する"""

    async def test_list_tools_returns_all_tools(self) -> None:
        """list_tools は全ツール（Google Ads 83 + Meta Ads 77 + Search Console 10
        + Rollback 2 + Analysis 1 = 173）を返す"""
        mod = _import_server_module()
        tools = await mod.handle_list_tools()
        assert len(tools) == 173

    async def test_list_tools_contains_google_and_meta(self) -> None:
        """Google Ads と Meta Ads のツールが含まれること"""
        mod = _import_server_module()
        tools = await mod.handle_list_tools()
        names = {t.name for t in tools}
        assert "google_ads.campaigns.list" in names
        assert "google_ads.campaigns.get" in names
        assert "meta_ads.campaigns.list" in names
        assert "meta_ads.campaigns.get" in names

    async def test_list_tools_campaigns_list_schema(self) -> None:
        """campaigns.list の inputSchema が customer_id を optional で持つこと"""
        mod = _import_server_module()
        tools = await mod.handle_list_tools()
        tool = next(t for t in tools if t.name == "google_ads.campaigns.list")
        schema = tool.inputSchema
        assert schema["type"] == "object"
        assert "customer_id" in schema["properties"]
        # customer_id is optional (falls back to credentials.json)
        assert "customer_id" not in schema.get("required", [])

    async def test_list_tools_campaigns_get_schema(self) -> None:
        """campaigns.get の inputSchema が campaign_id を required で持つこと"""
        mod = _import_server_module()
        tools = await mod.handle_list_tools()
        tool = next(t for t in tools if t.name == "google_ads.campaigns.get")
        schema = tool.inputSchema
        assert schema["type"] == "object"
        assert "customer_id" in schema["properties"]
        assert "campaign_id" in schema["properties"]
        # customer_id is optional, campaign_id is required
        assert "campaign_id" in schema["required"]


# ---------------------------------------------------------------------------
# call_tool テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCallToolCampaignsList:
    """call_tool で google_ads.campaigns.list を呼ぶテスト"""

    async def test_campaigns_list_calls_client(self) -> None:
        """campaigns.list が GoogleAdsApiClient.list_campaigns を呼ぶこと"""
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
                "google_ads.campaigns.list",
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
    """call_tool で google_ads.campaigns.get を呼ぶテスト"""

    async def test_campaigns_get_calls_client(self) -> None:
        """campaigns.get が GoogleAdsApiClient.get_campaign を呼ぶこと"""
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
                "google_ads.campaigns.get",
                {"customer_id": "1234567890", "campaign_id": "456"},
            )

        mock_client.get_campaign.assert_awaited_once_with("456")
        assert len(result) == 1
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "456"
        assert parsed["budget_daily"] == 5000.0


@pytest.mark.unit
class TestCallToolErrors:
    """call_tool のエラーケースを検証する"""

    async def test_unknown_tool_raises_error(self) -> None:
        """未知のツール名で ValueError が発生すること"""
        mod = _import_server_module()

        with pytest.raises(ValueError, match="Unknown tool"):
            await mod.handle_call_tool("nonexistent.tool", {})

    async def test_missing_required_param_customer_id(self) -> None:
        """campaigns.list で customer_id が欠損 + credentials.jsonにもない場合"""
        mod = _import_server_module()

        with patch(
            "mureo.mcp._handlers_google_ads.load_google_ads_credentials",
            return_value=None,
        ):
            result = await mod.handle_call_tool("google_ads.campaigns.list", {})
            assert any("Credentials not found" in r.text for r in result)

    async def test_missing_required_param_campaign_id(self) -> None:
        """campaigns.get で campaign_id が欠損した場合にエラーになること"""
        mod = _import_server_module()
        ga_mod = _import_google_ads_handlers()

        mock_creds = MagicMock()
        with patch.object(
            ga_mod, "load_google_ads_credentials", return_value=mock_creds
        ):
            with pytest.raises(ValueError, match="campaign_id"):
                await mod.handle_call_tool(
                    "google_ads.campaigns.get",
                    {"customer_id": "1234567890"},
                )

    async def test_no_credentials_returns_error_text(self) -> None:
        """認証情報がない場合、エラーメッセージを TextContent で返すこと"""
        ga_mod = _import_google_ads_handlers()
        mod = _import_server_module()

        with patch.object(
            ga_mod,
            "load_google_ads_credentials",
            return_value=None,
        ):
            result = await mod.handle_call_tool(
                "google_ads.campaigns.list",
                {"customer_id": "1234567890"},
            )

        assert len(result) == 1
        assert result[0].type == "text"
        assert "Credentials not found" in result[0].text
