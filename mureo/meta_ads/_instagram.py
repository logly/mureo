"""Instagram integration mixin.

Provides Instagram account management, post listing, and post promotion.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class InstagramMixin:
    """Meta Ads Instagram integration mixin

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    _IG_ACCOUNT_FIELDS = "id,username,profile_pic"

    _IG_MEDIA_FIELDS = (
        "id,caption,media_type,media_url,permalink,timestamp,thumbnail_url"
    )

    async def list_instagram_accounts(self) -> list[dict[str, Any]]:
        """List linked Instagram accounts

        Returns:
            List of Instagram account information.
        """
        params: dict[str, Any] = {
            "fields": self._IG_ACCOUNT_FIELDS,
        }
        result = await self._get(f"/{self._ad_account_id}/instagram_accounts", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def list_instagram_media(
        self, ig_user_id: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        """List Instagram posts

        Args:
            ig_user_id: Instagram user ID
            limit: Maximum number of items to retrieve (default: 25)

        Returns:
            List of Instagram post information.
        """
        params: dict[str, Any] = {
            "fields": self._IG_MEDIA_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{ig_user_id}/media", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def boost_instagram_post(
        self,
        ig_user_id: str,
        media_id: str,
        ad_set_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Promote an Instagram post as an ad

        Args:
            ig_user_id: Instagram user ID
            media_id: Media ID
            ad_set_id: Parent ad set ID
            name: Ad name (auto-generated if not specified)

        Returns:
            Created ad information.
        """
        object_story_id = f"{ig_user_id}_{media_id}"
        ad_name = name if name is not None else f"IG Boost: {object_story_id}"

        data: dict[str, Any] = {
            "name": ad_name,
            "adset_id": ad_set_id,
            "creative": json.dumps(
                {
                    "object_story_id": object_story_id,
                    "instagram_actor_id": ig_user_id,
                }
            ),
            "status": "PAUSED",
        }
        return await self._post(f"/{self._ad_account_id}/ads", data)
