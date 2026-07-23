"""Meta Ads pixel operations mixin.

Pixel listing, details, statistics, event checking, and creation.
Read paths are read-only; ``create_ad_pixel`` is the sole write.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Pixel retrieval fields
_PIXEL_FIELDS = (
    "id,name,creation_time,last_fired_time,"
    "is_created_by_business,owner_ad_account,"
    "code,data_use_setting"
)

# Period -> days mapping
_PERIOD_DAYS: dict[str, int] = {
    "last_7d": 7,
    "last_14d": 14,
    "last_30d": 30,
    "last_90d": 90,
}


class PixelsMixin:
    """Meta Ads pixel operations mixin

    Read paths (list / get / stats / events) are read-only;
    ``create_ad_pixel`` is the single write method.

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def list_ad_pixels(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List pixels linked to the ad account

        Returns:
            List of pixel information.
        """
        params: dict[str, Any] = {
            "fields": _PIXEL_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/adspixels", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_pixel(self, pixel_id: str) -> dict[str, Any]:
        """Get pixel details

        Args:
            pixel_id: Pixel ID

        Returns:
            Pixel detail information.
        """
        params: dict[str, Any] = {"fields": _PIXEL_FIELDS}
        return await self._get(f"/{pixel_id}", params)

    async def get_pixel_stats(
        self,
        pixel_id: str,
        period: str = "last_7d",
    ) -> list[dict[str, Any]]:
        """Get pixel event statistics

        Args:
            pixel_id: Pixel ID
            period: Aggregation period (last_7d, last_14d, last_30d, last_90d)

        Returns:
            List of event statistics.
        """
        days = _PERIOD_DAYS.get(period, 7)
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        params: dict[str, Any] = {
            "aggregation": "event",
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%S+0000"),
            "end_time": now.strftime("%Y-%m-%dT%H:%M:%S+0000"),
        }
        result = await self._get(f"/{pixel_id}/stats", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_pixel_events(
        self,
        pixel_id: str,
    ) -> list[dict[str, Any]]:
        """List event types received by the pixel

        Args:
            pixel_id: Pixel ID

        Returns:
            List of event types and counts.
        """
        params: dict[str, Any] = {
            "fields": "event_name,count",
        }
        result = await self._get(f"/{pixel_id}/stats", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def create_ad_pixel(self, name: str) -> dict[str, Any]:
        """Create a Meta Pixel on the ad account.

        Args:
            name: Pixel name shown in Events Manager. Must be
                non-empty (leading / trailing whitespace is stripped).

        Returns:
            Created pixel info dict — Meta returns ``{"id": "..."}``.

        Raises:
            ValueError: ``name`` is empty or whitespace-only.
        """
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("name must be a non-empty string")
        logger.info("Pixel creation: name=%s", clean_name)
        return await self._post(
            f"/{self._ad_account_id}/adspixels", {"name": clean_name}
        )
