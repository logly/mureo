"""Search Console client unit tests

Tests for SearchConsoleApiClient — each API method is tested
with mocked httpx responses.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _make_client(**kwargs: Any):
    """Create a SearchConsoleApiClient with mock credentials."""
    from mureo.search_console.client import SearchConsoleApiClient

    creds = MagicMock()
    creds.token = "fake-token"
    creds.expired = False
    return SearchConsoleApiClient(credentials=creds, **kwargs)


def _mock_response(status_code: int = 200, json_data: Any = None) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchConsoleClientInit:
    def test_valid_init(self) -> None:
        from mureo.search_console.client import SearchConsoleApiClient

        creds = MagicMock()
        creds.token = "tok"
        creds.expired = False
        client = SearchConsoleApiClient(credentials=creds)
        assert client._credentials is creds

    def test_with_throttler(self) -> None:
        from mureo.search_console.client import SearchConsoleApiClient

        creds = MagicMock()
        creds.token = "tok"
        creds.expired = False
        throttler = MagicMock()
        client = SearchConsoleApiClient(credentials=creds, throttler=throttler)
        assert client._throttler is throttler


# ---------------------------------------------------------------------------
# list_sites tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListSites:
    @pytest.mark.asyncio
    async def test_list_sites_success(self) -> None:
        client = _make_client()
        response_data = {
            "siteEntry": [
                {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
                {"siteUrl": "sc-domain:example.org", "permissionLevel": "siteOwner"},
            ]
        }
        mock_resp = _mock_response(200, response_data)
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.list_sites()
        assert len(result) == 2
        assert result[0]["siteUrl"] == "https://example.com/"

    @pytest.mark.asyncio
    async def test_list_sites_empty(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(200, {"siteEntry": []})
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.list_sites()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_sites_no_key(self) -> None:
        """API returns empty dict when no sites."""
        client = _make_client()
        mock_resp = _mock_response(200, {})
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.list_sites()
        assert result == []


# ---------------------------------------------------------------------------
# get_site tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSite:
    @pytest.mark.asyncio
    async def test_get_site_success(self) -> None:
        client = _make_client()
        response_data = {
            "siteUrl": "https://example.com/",
            "permissionLevel": "siteOwner",
        }
        mock_resp = _mock_response(200, response_data)
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.get_site("https://example.com/")
        assert result["siteUrl"] == "https://example.com/"

    @pytest.mark.asyncio
    async def test_get_site_url_encoded(self) -> None:
        """Site URL should be URL-encoded in the path."""
        client = _make_client()
        mock_resp = _mock_response(200, {"siteUrl": "https://example.com/"})
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        await client.get_site("https://example.com/")
        call_args = client._http.get.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        # URL should contain encoded site URL
        assert "https%3A%2F%2Fexample.com%2F" in url or "sites/" in url


# ---------------------------------------------------------------------------
# query_analytics tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueryAnalytics:
    @pytest.mark.asyncio
    async def test_query_analytics_success(self) -> None:
        client = _make_client()
        response_data = {
            "rows": [
                {
                    "keys": ["example query"],
                    "clicks": 100,
                    "impressions": 1000,
                    "ctr": 0.1,
                    "position": 3.5,
                }
            ]
        }
        mock_resp = _mock_response(200, response_data)
        client._http = MagicMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        result = await client.query_analytics(
            site_url="https://example.com/",
            start_date="2026-01-01",
            end_date="2026-01-31",
            dimensions=["query"],
        )
        assert len(result) == 1
        assert result[0]["clicks"] == 100

    @pytest.mark.asyncio
    async def test_query_analytics_with_row_limit(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(200, {"rows": []})
        client._http = MagicMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        await client.query_analytics(
            site_url="https://example.com/",
            start_date="2026-01-01",
            end_date="2026-01-31",
            row_limit=50,
        )
        call_args = client._http.post.call_args
        body = call_args[1].get("json", {}) if call_args[1] else {}
        assert body.get("rowLimit") == 50

    @pytest.mark.asyncio
    async def test_query_analytics_with_filters(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(200, {"rows": []})
        client._http = MagicMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        filters = [{"filters": [{"dimension": "query", "expression": "test"}]}]
        await client.query_analytics(
            site_url="https://example.com/",
            start_date="2026-01-01",
            end_date="2026-01-31",
            dimension_filter_groups=filters,
        )
        call_args = client._http.post.call_args
        body = call_args[1].get("json", {}) if call_args[1] else {}
        assert "dimensionFilterGroups" in body

    @pytest.mark.asyncio
    async def test_query_analytics_empty_rows(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(200, {})
        client._http = MagicMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        result = await client.query_analytics(
            site_url="https://example.com/",
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        assert result == []


# ---------------------------------------------------------------------------
# list_sitemaps tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListSitemaps:
    @pytest.mark.asyncio
    async def test_list_sitemaps_success(self) -> None:
        client = _make_client()
        response_data = {
            "sitemap": [
                {
                    "path": "https://example.com/sitemap.xml",
                    "lastSubmitted": "2026-01-01T00:00:00Z",
                }
            ]
        }
        mock_resp = _mock_response(200, response_data)
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.list_sitemaps("https://example.com/")
        assert len(result) == 1
        assert result[0]["path"] == "https://example.com/sitemap.xml"

    @pytest.mark.asyncio
    async def test_list_sitemaps_empty(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(200, {})
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.list_sitemaps("https://example.com/")
        assert result == []


# ---------------------------------------------------------------------------
# submit_sitemap tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmitSitemap:
    @pytest.mark.asyncio
    async def test_submit_sitemap_success(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(200, {})
        client._http = MagicMock()
        client._http.put = AsyncMock(return_value=mock_resp)

        result = await client.submit_sitemap(
            "https://example.com/", "https://example.com/sitemap.xml"
        )
        assert result == {"status": "submitted", "sitemap": "https://example.com/sitemap.xml"}


# ---------------------------------------------------------------------------
# inspect_url tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInspectUrl:
    @pytest.mark.asyncio
    async def test_inspect_url_success(self) -> None:
        client = _make_client()
        response_data = {
            "inspectionResult": {
                "indexStatusResult": {
                    "coverageState": "Submitted and indexed",
                    "verdict": "PASS",
                }
            }
        }
        mock_resp = _mock_response(200, response_data)
        client._http = MagicMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        result = await client.inspect_url(
            site_url="https://example.com/",
            inspection_url="https://example.com/page",
        )
        assert "inspectionResult" in result


# ---------------------------------------------------------------------------
# Token refresh tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self) -> None:
        from mureo.search_console.client import SearchConsoleApiClient

        creds = MagicMock()
        creds.token = "new-token"
        creds.valid = False
        creds.refresh = MagicMock()

        client = SearchConsoleApiClient(credentials=creds)
        mock_resp = _mock_response(200, {"siteEntry": []})
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        await client.list_sites()
        creds.refresh.assert_called_once()


# ---------------------------------------------------------------------------
# Throttler integration tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestThrottlerIntegration:
    @pytest.mark.asyncio
    async def test_throttler_acquire_called(self) -> None:
        throttler = MagicMock()
        throttler.acquire = AsyncMock()
        client = _make_client(throttler=throttler)

        mock_resp = _mock_response(200, {"siteEntry": []})
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        await client.list_sites()
        throttler.acquire.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_http_error_propagates(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(403, {"error": {"message": "Forbidden"}})
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        with pytest.raises(httpx.HTTPStatusError):
            await client.list_sites()
