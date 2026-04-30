"""Search Console MCP tool definitions and handler tests

Tests for tool definitions (inputSchema, required fields) and
handlers (mock client).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_tools():
    from mureo.mcp import tools_search_console

    return tools_search_console


def _import_handlers():
    from mureo.mcp import _handlers_search_console

    return _handlers_search_console


# ---------------------------------------------------------------------------
# Tool definition tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchConsoleToolDefinitions:
    """Verify Search Console tool definitions are correct."""

    def test_tool_count(self) -> None:
        """All 10 tools are defined."""
        mod = _import_tools()
        assert len(mod.TOOLS) == 10

    def test_all_tool_names_prefixed(self) -> None:
        """All tool names start with the search_console namespace prefix."""
        mod = _import_tools()
        for tool in mod.TOOLS:
            assert tool.name.startswith(
                "search_console_"
            ), f"Invalid tool name: {tool.name}"

    def test_all_tools_have_input_schema(self) -> None:
        """All tools have a valid inputSchema."""
        mod = _import_tools()
        for tool in mod.TOOLS:
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema

    @pytest.mark.parametrize(
        "tool_name,expected_required",
        [
            ("search_console_sites_list", []),
            ("search_console_sites_get", ["site_url"]),
            (
                "search_console_analytics_query",
                ["site_url", "start_date", "end_date"],
            ),
            (
                "search_console_analytics_top_queries",
                ["site_url", "start_date", "end_date"],
            ),
            (
                "search_console_analytics_top_pages",
                ["site_url", "start_date", "end_date"],
            ),
            (
                "search_console_analytics_device_breakdown",
                ["site_url", "start_date", "end_date"],
            ),
            (
                "search_console_analytics_compare_periods",
                [
                    "site_url",
                    "start_date_1",
                    "end_date_1",
                    "start_date_2",
                    "end_date_2",
                ],
            ),
            ("search_console_sitemaps_list", ["site_url"]),
            ("search_console_sitemaps_submit", ["site_url", "feedpath"]),
            (
                "search_console_url_inspection_inspect",
                ["site_url", "inspection_url"],
            ),
        ],
    )
    def test_required_fields(
        self, tool_name: str, expected_required: list[str]
    ) -> None:
        """Each tool has the correct required fields."""
        mod = _import_tools()
        tool = next((t for t in mod.TOOLS if t.name == tool_name), None)
        assert tool is not None, f"Tool {tool_name} not found"
        actual = set(tool.inputSchema.get("required", []))
        assert actual == set(expected_required)

    def test_tool_names_unique(self) -> None:
        """All tool names are unique."""
        mod = _import_tools()
        names = [t.name for t in mod.TOOLS]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Handler dispatch tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerDispatch:
    async def test_unknown_tool_raises(self) -> None:
        mod = _import_tools()
        with pytest.raises(ValueError, match="Unknown tool"):
            await mod.handle_tool("search_console.nonexistent", {})

    async def test_dispatch_sites_list(self) -> None:
        mod = _import_tools()
        handler_mod = _import_handlers()
        mock_creds = MagicMock()
        mock_client = AsyncMock()
        mock_client.list_sites.return_value = [{"siteUrl": "https://example.com/"}]
        with (
            patch.object(
                handler_mod, "load_google_ads_credentials", return_value=mock_creds
            ),
            patch.object(
                handler_mod,
                "create_search_console_client",
                return_value=mock_client,
            ),
        ):
            result = await mod.handle_tool("search_console_sites_list", {})

        assert len(result) == 1
        parsed = json.loads(result[0].text)
        assert parsed[0]["siteUrl"] == "https://example.com/"


# ---------------------------------------------------------------------------
# Individual handler tests
# ---------------------------------------------------------------------------


def _setup_handler_mocks(handler_mod: Any) -> tuple[MagicMock, AsyncMock]:
    """Return (mock_creds, mock_client) for handler tests."""
    mock_creds = MagicMock()
    mock_client = AsyncMock()
    return mock_creds, mock_client


@pytest.mark.unit
class TestSitesHandlers:
    async def test_sites_list(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.list_sites.return_value = [{"siteUrl": "https://example.com/"}]
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_sites_list({})

        parsed = json.loads(result[0].text)
        assert len(parsed) == 1
        mock_client.list_sites.assert_awaited_once()

    async def test_sites_get(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.get_site.return_value = {
            "siteUrl": "https://example.com/",
            "permissionLevel": "siteOwner",
        }
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_sites_get({"site_url": "https://example.com/"})

        parsed = json.loads(result[0].text)
        assert parsed["permissionLevel"] == "siteOwner"

    async def test_no_credentials(self) -> None:
        h = _import_handlers()
        with patch.object(h, "load_google_ads_credentials", return_value=None):
            result = await h.handle_sites_list({})

        assert "Credentials not found" in result[0].text


# ---------------------------------------------------------------------------
# Analytics handler tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnalyticsHandlers:
    async def test_query_analytics(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.query_analytics.return_value = [
            {"keys": ["test"], "clicks": 50, "impressions": 500}
        ]
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_analytics_query(
                {
                    "site_url": "https://example.com/",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                    "dimensions": ["query"],
                    "row_limit": 100,
                }
            )

        parsed = json.loads(result[0].text)
        assert parsed[0]["clicks"] == 50

    async def test_top_queries(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.query_analytics.return_value = [{"keys": ["query1"], "clicks": 100}]
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_analytics_top_queries(
                {
                    "site_url": "https://example.com/",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                }
            )

        parsed = json.loads(result[0].text)
        assert len(parsed) >= 1
        # Should have called with dimensions=["query"]
        call_kwargs = mock_client.query_analytics.call_args[1]
        assert call_kwargs["dimensions"] == ["query"]

    async def test_top_pages(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.query_analytics.return_value = [{"keys": ["/page1"], "clicks": 200}]
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_analytics_top_pages(
                {
                    "site_url": "https://example.com/",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                }
            )

        call_kwargs = mock_client.query_analytics.call_args[1]
        assert call_kwargs["dimensions"] == ["page"]

    async def test_device_breakdown(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.query_analytics.return_value = [{"keys": ["MOBILE"], "clicks": 300}]
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_analytics_device_breakdown(
                {
                    "site_url": "https://example.com/",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                }
            )

        call_kwargs = mock_client.query_analytics.call_args[1]
        assert call_kwargs["dimensions"] == ["device"]

    async def test_compare_periods(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.query_analytics.side_effect = [
            [{"keys": ["q1"], "clicks": 100}],
            [{"keys": ["q1"], "clicks": 150}],
        ]
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_analytics_compare_periods(
                {
                    "site_url": "https://example.com/",
                    "start_date_1": "2026-01-01",
                    "end_date_1": "2026-01-31",
                    "start_date_2": "2026-02-01",
                    "end_date_2": "2026-02-28",
                }
            )

        parsed = json.loads(result[0].text)
        assert "period_1" in parsed
        assert "period_2" in parsed
        assert mock_client.query_analytics.await_count == 2


# ---------------------------------------------------------------------------
# Sitemap handler tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSitemapHandlers:
    async def test_list_sitemaps(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.list_sitemaps.return_value = [
            {"path": "https://example.com/sitemap.xml"}
        ]
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_sitemaps_list({"site_url": "https://example.com/"})

        parsed = json.loads(result[0].text)
        assert len(parsed) == 1

    async def test_submit_sitemap(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.submit_sitemap.return_value = {
            "status": "submitted",
            "sitemap": "https://example.com/sitemap.xml",
        }
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_sitemaps_submit(
                {
                    "site_url": "https://example.com/",
                    "feedpath": "https://example.com/sitemap.xml",
                }
            )

        parsed = json.loads(result[0].text)
        assert parsed["status"] == "submitted"


# ---------------------------------------------------------------------------
# URL inspection handler tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUrlInspectionHandler:
    async def test_inspect_url(self) -> None:
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.inspect_url.return_value = {
            "inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}
        }
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_url_inspection_inspect(
                {
                    "site_url": "https://example.com/",
                    "inspection_url": "https://example.com/page",
                }
            )

        parsed = json.loads(result[0].text)
        assert parsed["inspectionResult"]["indexStatusResult"]["verdict"] == "PASS"

    async def test_inspect_url_missing_params(self) -> None:
        h = _import_handlers()
        mock_creds = MagicMock()
        with patch.object(h, "load_google_ads_credentials", return_value=mock_creds):
            with pytest.raises(ValueError, match="inspection_url"):
                await h.handle_url_inspection_inspect(
                    {"site_url": "https://example.com/"}
                )


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerErrors:
    async def test_api_error_returns_text(self) -> None:
        """API errors are caught and returned as text."""
        h = _import_handlers()
        mock_creds, mock_client = _setup_handler_mocks(h)
        mock_client.list_sites.side_effect = RuntimeError("API boom")
        with (
            patch.object(h, "load_google_ads_credentials", return_value=mock_creds),
            patch.object(h, "create_search_console_client", return_value=mock_client),
        ):
            result = await h.handle_sites_list({})

        assert "API error" in result[0].text

    async def test_missing_required_raises_value_error(self) -> None:
        """Missing required param raises ValueError (not caught by decorator)."""
        h = _import_handlers()
        mock_creds = MagicMock()
        with patch.object(h, "load_google_ads_credentials", return_value=mock_creds):
            with pytest.raises(ValueError, match="site_url"):
                await h.handle_sites_get({})
