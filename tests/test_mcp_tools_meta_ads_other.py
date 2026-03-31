"""Meta Ads その他ハンドラーテスト

ページ投稿、Instagram、スプリットテスト、自動ルールハンドラーをカバーする。
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
# ページ投稿ハンドラー
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPagePostsHandlers:
    """ページ投稿系ハンドラーテスト"""

    async def test_page_posts_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_page_posts.return_value = [{"id": "post_1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.page_posts.list",
                {"account_id": "act_123", "page_id": "pg_1"},
            )

        client.list_page_posts.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "post_1"

    async def test_page_posts_boost(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.boost_post.return_value = {"id": "boosted_1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.page_posts.boost",
                {
                    "account_id": "act_123",
                    "page_id": "pg_1",
                    "post_id": "post_1",
                    "ad_set_id": "20",
                },
            )

        client.boost_post.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "boosted_1"


# ---------------------------------------------------------------------------
# Instagramハンドラー
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstagramHandlers:
    """Instagram系ハンドラーテスト"""

    async def test_instagram_accounts(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_instagram_accounts.return_value = [{"id": "ig_1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.instagram.accounts",
                {"account_id": "act_123"},
            )

        client.list_instagram_accounts.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "ig_1"

    async def test_instagram_media(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_instagram_media.return_value = [{"id": "media_1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.instagram.media",
                {"account_id": "act_123", "ig_user_id": "ig_1"},
            )

        client.list_instagram_media.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "media_1"

    async def test_instagram_boost(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.boost_instagram_post.return_value = {"id": "boosted_ig_1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.instagram.boost",
                {
                    "account_id": "act_123",
                    "ig_user_id": "ig_1",
                    "media_id": "media_1",
                    "ad_set_id": "20",
                },
            )

        client.boost_instagram_post.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "boosted_ig_1"


# ---------------------------------------------------------------------------
# Split Test (A/Bテスト) ハンドラー
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSplitTestHandlers:
    """スプリットテスト系ハンドラーテスト"""

    async def test_split_tests_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_split_tests.return_value = [{"id": "st_1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.split_tests.list",
                {"account_id": "act_123"},
            )

        client.list_split_tests.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "st_1"

    async def test_split_tests_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_split_test.return_value = {"id": "st_1", "name": "Test1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.split_tests.get",
                {"account_id": "act_123", "study_id": "st_1"},
            )

        client.get_split_test.assert_awaited_once_with("st_1")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "st_1"

    async def test_split_tests_create(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_split_test.return_value = {"id": "st_2"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.split_tests.create",
                {
                    "account_id": "act_123",
                    "name": "ABTest",
                    "cells": [{"cell_id": "c1"}],
                    "objectives": ["REACH"],
                    "start_time": "2026-04-01T00:00:00",
                    "end_time": "2026-04-30T00:00:00",
                },
            )

        client.create_split_test.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "st_2"

    async def test_split_tests_end(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.end_split_test.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.split_tests.end",
                {"account_id": "act_123", "study_id": "st_1"},
            )

        client.end_split_test.assert_awaited_once_with("st_1")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# Ad Rules (自動ルール) ハンドラー
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdRulesHandlers:
    """自動ルール系ハンドラーテスト"""

    async def test_ad_rules_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_ad_rules.return_value = [{"id": "rule_1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_rules.list",
                {"account_id": "act_123"},
            )

        client.list_ad_rules.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "rule_1"

    async def test_ad_rules_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_ad_rule.return_value = {"id": "rule_1", "name": "Rule1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_rules.get",
                {"account_id": "act_123", "rule_id": "rule_1"},
            )

        client.get_ad_rule.assert_awaited_once_with("rule_1")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "rule_1"

    async def test_ad_rules_create(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_ad_rule.return_value = {"id": "rule_2"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_rules.create",
                {
                    "account_id": "act_123",
                    "name": "AutoRule",
                    "evaluation_spec": {"field": "impressions"},
                    "execution_spec": {"type": "PAUSE"},
                },
            )

        client.create_ad_rule.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "rule_2"

    async def test_ad_rules_update(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.update_ad_rule.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_rules.update",
                {
                    "account_id": "act_123",
                    "rule_id": "rule_1",
                    "name": "Updated Rule",
                },
            )

        client.update_ad_rule.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True

    async def test_ad_rules_delete(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.delete_ad_rule.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_rules.delete",
                {"account_id": "act_123", "rule_id": "rule_1"},
            )

        client.delete_ad_rule.assert_awaited_once_with("rule_1")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True
