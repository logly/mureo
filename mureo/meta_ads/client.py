from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from mureo.meta_ads._ad_rules import AdRulesMixin
from mureo.meta_ads._ad_sets import AdSetsMixin
from mureo.meta_ads._ads import AdsMixin
from mureo.meta_ads._analysis import AnalysisMixin
from mureo.meta_ads._audiences import AudiencesMixin
from mureo.meta_ads._campaigns import CampaignsMixin
from mureo.meta_ads._catalog import CatalogMixin
from mureo.meta_ads._conversions import ConversionsMixin
from mureo.meta_ads._creatives import CreativesMixin
from mureo.meta_ads._insights import InsightsMixin
from mureo.meta_ads._instagram import InstagramMixin
from mureo.meta_ads._leads import LeadsMixin
from mureo.meta_ads._page_posts import PagePostsMixin
from mureo.meta_ads._pixels import PixelsMixin
from mureo.meta_ads._split_test import SplitTestMixin

if TYPE_CHECKING:
    from mureo.throttle import Throttler

logger = logging.getLogger(__name__)

# Rate limit warning threshold (usage %)
_RATE_LIMIT_WARNING_THRESHOLD = 80

# Retry configuration
_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 1.0


class MetaAdsApiClient(
    CampaignsMixin,
    AdSetsMixin,
    AdsMixin,
    CreativesMixin,
    AudiencesMixin,
    PixelsMixin,
    InsightsMixin,
    AnalysisMixin,
    CatalogMixin,
    ConversionsMixin,
    LeadsMixin,
    PagePostsMixin,
    InstagramMixin,
    SplitTestMixin,
    AdRulesMixin,
):
    """Meta Marketing API client.

    Operates Meta Ads (Facebook/Instagram) using Graph API v21.0.
    Includes built-in rate limit monitoring and exponential backoff retry.
    Provides campaigns, ad sets, ads, and insights operations via mixin multiple inheritance.
    """

    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(
        self,
        access_token: str,
        ad_account_id: str,
        throttler: Throttler | None = None,
    ) -> None:
        """
        Args:
            access_token: Meta Graph API access token (plaintext)
            ad_account_id: Ad account ID ("act_XXXX" format)
            throttler: Optional rate-limit throttler
        """
        if not access_token:
            raise ValueError("access_token is required")
        if not ad_account_id:
            raise ValueError("ad_account_id is required")
        if not ad_account_id.startswith("act_"):
            raise ValueError(f"ad_account_id must start with 'act_': {ad_account_id}")

        self._access_token = access_token
        self._ad_account_id = ad_account_id
        self._http = httpx.AsyncClient(timeout=30.0)
        self._throttler = throttler

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """GET request (with rate limit handling).

        Args:
            path: API path (e.g. "/{ad_account_id}/campaigns")
            params: Query parameters

        Returns:
            API response JSON

        Raises:
            RuntimeError: If the API request fails
        """
        return await self._request("GET", path, params=params)

    async def _post(
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """POST request (with rate limit handling).

        Args:
            path: API path
            data: Request body

        Returns:
            API response JSON

        Raises:
            RuntimeError: If the API request fails
        """
        return await self._request("POST", path, data=data)

    async def _delete(self, path: str) -> dict[str, Any]:
        """DELETE request (with rate limit handling)."""
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request (with rate limit handling and exponential backoff retry).

        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            data: Request body

        Returns:
            API response JSON

        Raises:
            RuntimeError: If the maximum retry count is exceeded
        """
        if self._throttler is not None:
            await self._throttler.acquire()

        url = f"{self.BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        if params is None:
            params = {}

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                if method == "GET":
                    resp = await self._http.get(url, params=params, headers=headers)
                elif method == "POST":
                    resp = await self._http.post(
                        url, params=params, data=data, headers=headers
                    )
                elif method == "DELETE":
                    resp = await self._http.delete(url, params=params, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Monitor rate limit headers
                self._check_rate_limit(resp)

                # 429 Too Many Requests -> backoff retry
                if resp.status_code == 429:
                    backoff = _INITIAL_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        "Meta API rate limit (429): retrying in %ss (attempt %d/%d)",
                        backoff,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(backoff)
                    continue

                if resp.status_code != 200:
                    error_body = resp.text[:500]
                    logger.error(
                        "Meta API error: method=%s, path=%s, status=%d, body=%s",
                        method,
                        path,
                        resp.status_code,
                        error_body,
                    )
                    # Extract detailed error from Meta API response
                    detail = ""
                    try:
                        err = resp.json().get("error", {})
                        parts = []
                        if err.get("message"):
                            parts.append(err["message"])
                        if err.get("error_user_title"):
                            parts.append(err["error_user_title"])
                        if err.get("error_user_msg"):
                            parts.append(err["error_user_msg"])
                        if parts:
                            detail = " | ".join(parts)
                    except Exception:
                        detail = error_body
                    raise RuntimeError(
                        f"Meta API request failed "
                        f"(status={resp.status_code}, path={path}): {detail}"
                    )

                return resp.json()  # type: ignore[no-any-return]

            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    backoff = _INITIAL_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        "Meta API communication error: %s. Retrying in %ss (attempt %d/%d)",
                        exc,
                        backoff,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise RuntimeError(
                    f"Meta API request failed (path={path}): {exc}"
                ) from exc

        raise RuntimeError(
            f"Meta API request exceeded maximum retry count ({_MAX_RETRIES}): "
            f"path={path}"
        ) from last_error

    def _check_rate_limit(self, resp: httpx.Response) -> None:
        """Check rate limit usage from response headers.

        Parses the x-business-use-case-usage header and logs a warning
        if usage exceeds the threshold.

        Args:
            resp: HTTP response
        """
        usage_header = resp.headers.get("x-business-use-case-usage")
        if not usage_header:
            return

        try:
            usage_data = json.loads(usage_header)
            for business_id, usage_list in usage_data.items():
                if not isinstance(usage_list, list):
                    continue
                for usage in usage_list:
                    call_count = usage.get("call_count", 0)
                    total_cputime = usage.get("total_cputime", 0)
                    total_time = usage.get("total_time", 0)

                    max_usage = max(call_count, total_cputime, total_time)
                    if max_usage >= _RATE_LIMIT_WARNING_THRESHOLD:
                        logger.warning(
                            "Meta API rate limit usage is high: "
                            "business_id=%s, call_count=%d%%, "
                            "cputime=%d%%, time=%d%%",
                            business_id,
                            call_count,
                            total_cputime,
                            total_time,
                        )
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.debug(
                "Failed to parse x-business-use-case-usage header: %s",
                usage_header[:200],
            )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> MetaAdsApiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
