"""ページ投稿操作Mixin

Facebookページ投稿の一覧取得と広告化（Boost Post）を提供する。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PagePostsMixin:
    """Meta Ads ページ投稿操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    _PAGE_POST_FIELDS = "id,message,created_time,permalink_url,full_picture,type"

    async def list_page_posts(
        self, page_id: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        """ページ投稿一覧を取得する

        Args:
            page_id: FacebookページID
            limit: 取得件数上限（デフォルト: 25）

        Returns:
            投稿情報のリスト
        """
        params: dict[str, Any] = {
            "fields": self._PAGE_POST_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{page_id}/posts", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def boost_post(
        self,
        page_id: str,
        post_id: str,
        ad_set_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """ページ投稿を広告化する（Boost Post）

        既存のページ投稿をobject_story_idで参照して広告を作成する。

        Args:
            page_id: FacebookページID
            post_id: 投稿ID
            ad_set_id: 所属広告セットID
            name: 広告名（未指定時は自動生成）

        Returns:
            作成された広告情報
        """
        object_story_id = f"{page_id}_{post_id}"
        ad_name = name if name is not None else f"Boost: {object_story_id}"

        data: dict[str, Any] = {
            "name": ad_name,
            "adset_id": ad_set_id,
            "creative": json.dumps({"object_story_id": object_story_id}),
            "status": "PAUSED",
        }
        return await self._post(f"/{self._ad_account_id}/ads", data)
