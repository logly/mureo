from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AdsMixin:
    """Meta Ads ad operations mixin

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    # Common field definitions
    _AD_FIELDS = (
        "id,name,status,adset_id,campaign_id,"
        "creative{id,name,title,body,image_url,thumbnail_url,object_story_spec},"
        "created_time,updated_time"
    )

    async def list_ads(
        self,
        ad_set_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List ads.

        Args:
            ad_set_id: Ad set ID (when specified, only ads under this ad set)
            limit: Maximum number of results

        Returns:
            List of ad information
        """
        params: dict[str, Any] = {
            "fields": self._AD_FIELDS,
            "limit": limit,
        }

        if ad_set_id:
            path = f"/{ad_set_id}/ads"
        else:
            account_id = self._ad_account_id
            path = f"/{account_id}/ads"

        result = await self._get(path, params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_ad(self, ad_id: str) -> dict[str, Any]:
        """Get ad details.

        Args:
            ad_id: Ad ID

        Returns:
            Ad detail information
        """
        params: dict[str, Any] = {"fields": self._AD_FIELDS}
        return await self._get(f"/{ad_id}", params)

    async def create_ad(
        self,
        ad_set_id: str,
        name: str,
        creative_id: str,
        status: str = "PAUSED",
    ) -> dict[str, Any]:
        """Create an ad.

        Args:
            ad_set_id: Parent ad set ID
            name: Ad name
            creative_id: Creative ID
            status: Initial status (default: PAUSED)

        Returns:
            Created ad information
        """
        import json as _json

        account_id = self._ad_account_id
        data: dict[str, Any] = {
            "name": name,
            "adset_id": ad_set_id,
            "creative": _json.dumps({"creative_id": creative_id}),
            "status": status,
        }
        return await self._post(f"/{account_id}/ads", data)

    async def update_ad(
        self,
        ad_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update an ad.

        Args:
            ad_id: Ad ID
            **kwargs: Fields to update (name, status, creative, etc.)

        Returns:
            Update result
        """
        data: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        return await self._post(f"/{ad_id}", data)

    async def pause_ad(self, ad_id: str) -> dict[str, Any]:
        """Pause an ad.

        Args:
            ad_id: Ad ID

        Returns:
            Update result
        """
        return await self._post(f"/{ad_id}", {"status": "PAUSED"})

    async def enable_ad(self, ad_id: str) -> dict[str, Any]:
        """Enable an ad.

        Args:
            ad_id: Ad ID

        Returns:
            Update result
        """
        return await self._post(f"/{ad_id}", {"status": "ACTIVE"})
