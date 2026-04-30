"""Google Search Console API client.

Uses httpx.AsyncClient with OAuth2 Bearer token authentication.
Reuses the same google.oauth2.credentials.Credentials as Google Ads.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

    from mureo.throttle import Throttler

logger = logging.getLogger(__name__)

BASE_URL = "https://www.googleapis.com/webmasters/v3"
INSPECTION_URL = "https://searchconsole.googleapis.com/v1"


class SearchConsoleApiClient:
    """Google Search Console API client.

    Uses httpx.AsyncClient with OAuth2 Bearer token.
    """

    def __init__(
        self,
        credentials: Credentials,
        throttler: Throttler | None = None,
    ) -> None:
        """Initialize the Search Console API client.

        Args:
            credentials: google.oauth2.credentials.Credentials (same as Google Ads)
            throttler: Optional rate limiter
        """
        self._credentials = credentials
        self._throttler = throttler
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        await self._http.aclose()

    async def __aenter__(self) -> SearchConsoleApiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _ensure_token(self) -> None:
        """Refresh the OAuth2 token if not valid (expired or first use)."""
        if not self._credentials.valid:
            # google-auth's Credentials.refresh has type hints in some
            # versions but is unannotated in others; CI's resolver
            # picked an unannotated variant. Suppress here rather than
            # pin the whole package version.
            self._credentials.refresh(Request())  # type: ignore[no-untyped-call]

    def _auth_headers(self) -> dict[str, str]:
        """Return authorization headers."""
        self._ensure_token()
        return {"Authorization": f"Bearer {self._credentials.token}"}

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    async def _get(self, url: str) -> Any:
        """Perform an authenticated GET request."""
        if self._throttler is not None:
            await self._throttler.acquire()
        resp = await self._http.get(url, headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    async def _post(self, url: str, json_body: dict[str, Any]) -> Any:
        """Perform an authenticated POST request."""
        if self._throttler is not None:
            await self._throttler.acquire()
        resp = await self._http.post(url, json=json_body, headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    async def _put(self, url: str) -> None:
        """Perform an authenticated PUT request (expects 204 No Content)."""
        if self._throttler is not None:
            await self._throttler.acquire()
        self._ensure_token()
        resp = await self._http.put(url, headers=self._auth_headers())
        resp.raise_for_status()

    @staticmethod
    def _encode_site_url(site_url: str) -> str:
        """URL-encode a site URL for use in API paths."""
        return quote(site_url, safe="")

    # ------------------------------------------------------------------
    # Sites
    # ------------------------------------------------------------------

    async def list_sites(self) -> list[dict[str, Any]]:
        """List all verified Search Console sites."""
        data = await self._get(f"{BASE_URL}/sites")
        return data.get("siteEntry", [])  # type: ignore[no-any-return]

    async def get_site(self, site_url: str) -> dict[str, Any]:
        """Get details for a specific site."""
        encoded = self._encode_site_url(site_url)
        data = await self._get(f"{BASE_URL}/sites/{encoded}")
        return data  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Search Analytics
    # ------------------------------------------------------------------

    async def query_analytics(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
        row_limit: int = 100,
        dimension_filter_groups: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Query search analytics data.

        Args:
            site_url: The site URL (e.g., "https://example.com/")
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            dimensions: List of dimensions (query, page, country, device, date)
            row_limit: Maximum number of rows to return (default: 100)
            dimension_filter_groups: Optional filter groups

        Returns:
            List of row dicts with keys, clicks, impressions, ctr, position.
        """
        encoded = self._encode_site_url(site_url)
        body: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "rowLimit": row_limit,
        }
        if dimensions is not None:
            body["dimensions"] = dimensions
        if dimension_filter_groups is not None:
            body["dimensionFilterGroups"] = dimension_filter_groups

        data = await self._post(
            f"{BASE_URL}/sites/{encoded}/searchAnalytics/query", body
        )
        return data.get("rows", [])  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Sitemaps
    # ------------------------------------------------------------------

    async def list_sitemaps(self, site_url: str) -> list[dict[str, Any]]:
        """List sitemaps for a site."""
        encoded = self._encode_site_url(site_url)
        data = await self._get(f"{BASE_URL}/sites/{encoded}/sitemaps")
        return data.get("sitemap", [])  # type: ignore[no-any-return]

    async def submit_sitemap(self, site_url: str, feedpath: str) -> dict[str, Any]:
        """Submit a sitemap.

        Args:
            site_url: The site URL
            feedpath: The sitemap URL to submit

        Returns:
            Status dict indicating submission success.
        """
        encoded = self._encode_site_url(site_url)
        feedpath_encoded = quote(feedpath, safe="")
        await self._put(f"{BASE_URL}/sites/{encoded}/sitemaps/{feedpath_encoded}")
        return {"status": "submitted", "sitemap": feedpath}

    # ------------------------------------------------------------------
    # URL Inspection
    # ------------------------------------------------------------------

    async def inspect_url(self, site_url: str, inspection_url: str) -> dict[str, Any]:
        """Inspect URL indexing status.

        Args:
            site_url: The site URL
            inspection_url: The URL to inspect

        Returns:
            Inspection result dict.
        """
        body = {
            "inspectionUrl": inspection_url,
            "siteUrl": site_url,
        }
        data = await self._post(f"{INSPECTION_URL}/urlInspection/index:inspect", body)
        return data  # type: ignore[no-any-return]
