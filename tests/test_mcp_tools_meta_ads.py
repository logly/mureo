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
class TestMetaAdsToolDefinitions:
    """Verify the Meta Ads tool list is defined correctly."""

    def test_tool_count(self) -> None:
        """All 82 tools are defined (81 + meta_ads_pages_upload_photo, #151)."""
        mod = _import_meta_ads_tools()
        assert len(mod.TOOLS) == 82

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

    def test_ad_sets_update_exposes_schedule_and_lifetime_budget(self) -> None:
        """meta_ads_ad_sets_update exposes end_time and lifetime_budget (#367)."""
        mod = _import_meta_ads_tools()
        tool = next(t for t in mod.TOOLS if t.name == "meta_ads_ad_sets_update")
        props = tool.inputSchema["properties"]
        assert "end_time" in props
        assert "lifetime_budget" in props
        assert props["lifetime_budget"]["type"] == "integer"


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

    async def test_campaigns_create_rejects_zero_daily_budget(self) -> None:
        """A 0 daily budget halts delivery — refuse before any API call (#277)."""
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="greater than 0"):
            await mod.handle_tool(
                "meta_ads_campaigns_create",
                {
                    "account_id": "act_123",
                    "name": "C",
                    "objective": "CONVERSIONS",
                    "daily_budget": 0,
                },
            )

    async def test_campaigns_update_rejects_negative_daily_budget(self) -> None:
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="greater than 0"):
            await mod.handle_tool(
                "meta_ads_campaigns_update",
                {"account_id": "act_123", "campaign_id": "456", "daily_budget": -10},
            )


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

    async def test_ad_sets_update_forwards_lifetime_budget(self) -> None:
        """lifetime_budget reaches update_ad_set unchanged (#367)."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.update_ad_set.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            await mod.handle_tool(
                "meta_ads_ad_sets_update",
                {"account_id": "act_123", "ad_set_id": "20", "lifetime_budget": 90000},
            )

        kwargs = client.update_ad_set.await_args.kwargs
        assert kwargs["lifetime_budget"] == 90000

    async def test_ad_sets_update_forwards_end_time_string(self) -> None:
        """An ISO 8601 end_time string reaches update_ad_set unchanged (#367)."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.update_ad_set.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            await mod.handle_tool(
                "meta_ads_ad_sets_update",
                {
                    "account_id": "act_123",
                    "ad_set_id": "20",
                    "end_time": "2026-08-01T00:00:00+09:00",
                },
            )

        kwargs = client.update_ad_set.await_args.kwargs
        assert kwargs["end_time"] == "2026-08-01T00:00:00+09:00"

    async def test_ad_sets_update_end_time_zero_clears_end_date(self) -> None:
        """end_time=0 (Meta convention: no end date) is forwarded, not dropped (#367)."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.update_ad_set.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            await mod.handle_tool(
                "meta_ads_ad_sets_update",
                {"account_id": "act_123", "ad_set_id": "20", "end_time": 0},
            )

        kwargs = client.update_ad_set.await_args.kwargs
        assert kwargs["end_time"] == 0

    async def test_ad_sets_update_rejects_both_budgets(self) -> None:
        """daily_budget and lifetime_budget are mutually exclusive on Meta (#367)."""
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="mutually exclusive"):
            await mod.handle_tool(
                "meta_ads_ad_sets_update",
                {
                    "account_id": "act_123",
                    "ad_set_id": "20",
                    "daily_budget": 5000,
                    "lifetime_budget": 90000,
                },
            )

    @pytest.mark.parametrize("no_end", [0, "0", " 0 "])
    async def test_ad_sets_update_rejects_lifetime_budget_with_no_end(
        self, no_end: Any
    ) -> None:
        """A lifetime budget requires an end date — end_time=0 contradicts it,
        including the string form "0" which is wire-identical to 0 (#367)."""
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="end_time"):
            await mod.handle_tool(
                "meta_ads_ad_sets_update",
                {
                    "account_id": "act_123",
                    "ad_set_id": "20",
                    "lifetime_budget": 90000,
                    "end_time": no_end,
                },
            )

    async def test_ad_sets_update_normalizes_string_zero_end_time(self) -> None:
        """end_time="0" is normalized to the integer 0 before forwarding (#367)."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.update_ad_set.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            await mod.handle_tool(
                "meta_ads_ad_sets_update",
                {"account_id": "act_123", "ad_set_id": "20", "end_time": "0"},
            )

        kwargs = client.update_ad_set.await_args.kwargs
        assert kwargs["end_time"] == 0

    async def test_ad_sets_update_rejects_zero_lifetime_budget(self) -> None:
        """A 0 lifetime budget halts delivery — refuse before any API call (#367)."""
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="greater than 0"):
            await mod.handle_tool(
                "meta_ads_ad_sets_update",
                {"account_id": "act_123", "ad_set_id": "20", "lifetime_budget": 0},
            )

    @pytest.mark.parametrize("bad_end_time", [-1, True, "", "  "])
    async def test_ad_sets_update_rejects_invalid_end_time(
        self, bad_end_time: Any
    ) -> None:
        """Negative / boolean / blank end_time values are rejected (#367)."""
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="end_time"):
            await mod.handle_tool(
                "meta_ads_ad_sets_update",
                {"account_id": "act_123", "ad_set_id": "20", "end_time": bad_end_time},
            )

    async def test_pages_upload_photo(self) -> None:
        """meta_ads_pages_upload_photo returns the PAGE photo_id (cover_photo_id)."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.upload_page_photo.return_value = {"photo_id": "123_456"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_pages_upload_photo",
                {
                    "account_id": "act_123",
                    "page_id": "111",
                    "image_url": "https://example.com/banner.png",
                },
            )

        client.upload_page_photo.assert_awaited_once()
        assert "123_456" in result[0].text

    async def test_ad_sets_create_rejects_zero_bid_amount(self) -> None:
        mod = _import_meta_ads_tools()
        with pytest.raises(ValueError, match="greater than 0"):
            await mod.handle_tool(
                "meta_ads_ad_sets_create",
                {
                    "account_id": "act_123",
                    "campaign_id": "456",
                    "name": "AS",
                    "bid_amount": 0,
                },
            )


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
