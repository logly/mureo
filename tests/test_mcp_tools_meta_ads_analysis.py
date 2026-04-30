"""Meta Ads 分析ハンドラーテスト

_handlers_meta_ads.py の分析系ハンドラーをカバーする。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_meta_ads_tools():
    from mureo.mcp import tools_meta_ads

    return tools_meta_ads


def _import_handlers():
    from mureo.mcp import _handlers_meta_ads

    return _handlers_meta_ads


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _mock_meta_ads_context():
    """Meta Ads認証情報とクライアントのモックを返す"""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# 分析系ハンドラー
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnalysisHandlers:
    """分析系ハンドラーテスト"""

    async def test_analysis_performance(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.analyze_performance.return_value = {"ctr": 0.05}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_analysis_performance",
                {"account_id": "act_123"},
            )

        client.analyze_performance.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["ctr"] == 0.05

    async def test_analysis_audience(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.analyze_audience.return_value = {"age_group": "25-34"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_analysis_audience",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.analyze_audience.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["age_group"] == "25-34"

    async def test_analysis_placements(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.analyze_placements.return_value = {"feed": 80}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_analysis_placements",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.analyze_placements.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["feed"] == 80

    async def test_analysis_cost(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.investigate_cost.return_value = {"cpm": 5.0}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_analysis_cost",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.investigate_cost.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["cpm"] == 5.0

    async def test_analysis_compare_ads(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.compare_ads.return_value = [{"ad_id": "a1", "ctr": 0.03}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_analysis_compare_ads",
                {"account_id": "act_123", "ad_set_id": "20"},
            )

        client.compare_ads.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["ad_id"] == "a1"

    async def test_analysis_suggest_creative(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.suggest_creative_improvements.return_value = {"suggestions": []}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_analysis_suggest_creative",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.suggest_creative_improvements.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["suggestions"] == []
