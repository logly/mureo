"""Tests for miscellaneous Meta Ads handlers.

Covers the page posts, Instagram, split test, and automated rule handlers.
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
# Helpers
# ---------------------------------------------------------------------------


def _mock_meta_ads_context():
    """Return mocks for Meta Ads credentials and client."""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# Page post handlers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _standalone_meta_ads():
    """Pin these handler tests to STANDALONE (untenanted) Meta Ads.

    Meta Ads gained workspace scoping (#411, mirroring Search Console's
    #375): when a ``mureo.runtime_context_factory`` is installed AND its
    store is a shared-auth multi-account backend, an undeclared
    ``meta_account_ids`` fail-closes every account_id. A dev box carrying such a
    plugin would therefore break these standalone assertions. Neutralize
    the scoping seam so this module always exercises the unrestricted
    path; the scoped behavior lives in test_account_id_tenant_scope.py.
    """
    with patch(
        "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
        return_value=None,
    ):
        yield


@pytest.mark.unit
class TestPagePostsHandlers:
    """Page post handler tests."""

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
                "meta_ads_page_posts_list",
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
                "meta_ads_page_posts_boost",
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
# Instagram handlers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstagramHandlers:
    """Instagram handler tests."""

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
                "meta_ads_instagram_accounts",
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
                "meta_ads_instagram_media",
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
                "meta_ads_instagram_boost",
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
# Split Test (A/B test) handlers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSplitTestHandlers:
    """Split test handler tests."""

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
                "meta_ads_split_tests_list",
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
                "meta_ads_split_tests_get",
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
                "meta_ads_split_tests_create",
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
                "meta_ads_split_tests_end",
                {"account_id": "act_123", "study_id": "st_1"},
            )

        client.end_split_test.assert_awaited_once_with("st_1")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# Ad Rules (automated rule) handlers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdRulesHandlers:
    """Automated rule handler tests."""

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
                "meta_ads_ad_rules_list",
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
                "meta_ads_ad_rules_get",
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
                "meta_ads_ad_rules_create",
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
                "meta_ads_ad_rules_update",
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
                "meta_ads_ad_rules_delete",
                {"account_id": "act_123", "rule_id": "rule_1"},
            )

        client.delete_ad_rule.assert_awaited_once_with("rule_1")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True
