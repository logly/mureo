from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AdsMixin:
    """Meta Ads 広告操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    # 共通フィールド定義
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
        """広告一覧を取得する

        Args:
            ad_set_id: 広告セットID（指定時はその広告セット配下のみ）
            limit: 取得件数上限

        Returns:
            広告情報のリスト
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
        """広告詳細を取得する

        Args:
            ad_id: 広告ID

        Returns:
            広告詳細情報
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
        """広告を作成する

        Args:
            ad_set_id: 所属広告セットID
            name: 広告名
            creative_id: クリエイティブID
            status: 初期ステータス（デフォルト: PAUSED）

        Returns:
            作成された広告情報
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
        """広告を更新する

        Args:
            ad_id: 広告ID
            **kwargs: 更新するフィールド（name, status, creative等）

        Returns:
            更新結果
        """
        data: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        return await self._post(f"/{ad_id}", data)

    async def pause_ad(self, ad_id: str) -> dict[str, Any]:
        """広告を一時停止する

        Args:
            ad_id: 広告ID

        Returns:
            更新結果
        """
        return await self._post(f"/{ad_id}", {"status": "PAUSED"})

    async def enable_ad(self, ad_id: str) -> dict[str, Any]:
        """広告を有効化する

        Args:
            ad_id: 広告ID

        Returns:
            更新結果
        """
        return await self._post(f"/{ad_id}", {"status": "ACTIVE"})
