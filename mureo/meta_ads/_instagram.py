"""Instagram連携Mixin

Instagramアカウント管理、投稿一覧取得、投稿の広告化を提供する。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class InstagramMixin:
    """Meta Ads Instagram連携Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    _IG_ACCOUNT_FIELDS = "id,username,profile_pic"

    _IG_MEDIA_FIELDS = (
        "id,caption,media_type,media_url,permalink,timestamp,thumbnail_url"
    )

    async def list_instagram_accounts(self) -> list[dict[str, Any]]:
        """連携Instagramアカウント一覧を取得する

        Returns:
            Instagramアカウント情報のリスト
        """
        params: dict[str, Any] = {
            "fields": self._IG_ACCOUNT_FIELDS,
        }
        result = await self._get(f"/{self._ad_account_id}/instagram_accounts", params)
        return result.get("data", [])

    async def list_instagram_media(
        self, ig_user_id: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        """Instagram投稿一覧を取得する

        Args:
            ig_user_id: InstagramユーザーID
            limit: 取得件数上限（デフォルト: 25）

        Returns:
            Instagram投稿情報のリスト
        """
        params: dict[str, Any] = {
            "fields": self._IG_MEDIA_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{ig_user_id}/media", params)
        return result.get("data", [])

    async def boost_instagram_post(
        self,
        ig_user_id: str,
        media_id: str,
        ad_set_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Instagram投稿を広告化する

        Args:
            ig_user_id: InstagramユーザーID
            media_id: メディアID
            ad_set_id: 所属広告セットID
            name: 広告名（未指定時は自動生成）

        Returns:
            作成された広告情報
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
