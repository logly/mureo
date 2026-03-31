"""Meta Ads 商品カタログ & Dynamic Product Ads (DPA) Mixin

Product Catalogの管理、商品CRUD、フィード管理を提供する。
EC事業者向けDynamic Product Adsの基盤機能。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 商品取得用フィールド
_PRODUCT_FIELDS = (
    "id,retailer_id,name,description,availability,condition,"
    "price,url,image_url,brand,category"
)

# カタログ取得用フィールド
_CATALOG_FIELDS = "id,name,product_count,vertical"

# フィード取得用フィールド
_FEED_FIELDS = "id,name,schedule,product_count,latest_upload"


class CatalogMixin:
    """Meta Ads 商品カタログ & DPA操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _delete(self, path: str) -> dict[str, Any]: ...  # type: ignore[empty-body]

    # === カタログ管理 ===

    async def list_catalogs(self, business_id: str) -> list[dict[str, Any]]:
        """カタログ一覧を取得する

        Args:
            business_id: ビジネスID

        Returns:
            カタログ情報のリスト
        """
        params: dict[str, Any] = {"fields": _CATALOG_FIELDS}
        result = await self._get(f"/{business_id}/owned_product_catalogs", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def create_catalog(self, business_id: str, name: str) -> dict[str, Any]:
        """カタログを作成する

        Args:
            business_id: ビジネスID
            name: カタログ名

        Returns:
            作成されたカタログ情報（idを含む）
        """
        data: dict[str, Any] = {"name": name}
        return await self._post(f"/{business_id}/owned_product_catalogs", data=data)

    async def get_catalog(self, catalog_id: str) -> dict[str, Any]:
        """カタログ詳細を取得する

        Args:
            catalog_id: カタログID

        Returns:
            カタログ詳細情報
        """
        params: dict[str, Any] = {"fields": _CATALOG_FIELDS}
        return await self._get(f"/{catalog_id}", params)

    async def delete_catalog(self, catalog_id: str) -> dict[str, Any]:
        """カタログを削除する

        Args:
            catalog_id: カタログID

        Returns:
            削除結果
        """
        return await self._delete(f"/{catalog_id}")

    # === 商品管理 ===

    async def list_products(
        self, catalog_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """商品一覧を取得する

        Args:
            catalog_id: カタログID
            limit: 取得件数上限（デフォルト: 100）

        Returns:
            商品情報のリスト
        """
        params: dict[str, Any] = {
            "fields": _PRODUCT_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{catalog_id}/products", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def add_product(
        self, catalog_id: str, product_data: dict[str, Any]
    ) -> dict[str, Any]:
        """商品を追加する

        Args:
            catalog_id: カタログID
            product_data: 商品データ（retailer_id, name, price等）

        Returns:
            作成された商品情報（idを含む）
        """
        return await self._post(f"/{catalog_id}/products", data=product_data)

    async def get_product(self, product_id: str) -> dict[str, Any]:
        """商品詳細を取得する

        Args:
            product_id: 商品ID

        Returns:
            商品詳細情報
        """
        params: dict[str, Any] = {"fields": _PRODUCT_FIELDS}
        return await self._get(f"/{product_id}", params)

    async def update_product(
        self, product_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """商品を更新する

        Args:
            product_id: 商品ID
            updates: 更新データ

        Returns:
            更新結果
        """
        return await self._post(f"/{product_id}", data=updates)

    async def delete_product(self, product_id: str) -> dict[str, Any]:
        """商品を削除する

        Args:
            product_id: 商品ID

        Returns:
            削除結果
        """
        return await self._delete(f"/{product_id}")

    # === フィード管理 ===

    async def list_product_feeds(self, catalog_id: str) -> list[dict[str, Any]]:
        """フィード一覧を取得する

        Args:
            catalog_id: カタログID

        Returns:
            フィード情報のリスト
        """
        params: dict[str, Any] = {"fields": _FEED_FIELDS}
        result = await self._get(f"/{catalog_id}/product_feeds", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def create_product_feed(
        self,
        catalog_id: str,
        name: str,
        feed_url: str,
        schedule: str = "DAILY",
    ) -> dict[str, Any]:
        """フィードを作成する（URL指定、スケジュール自動取込）

        Args:
            catalog_id: カタログID
            name: フィード名
            feed_url: フィードURL
            schedule: 取込スケジュール（DAILY, HOURLY, WEEKLY）

        Returns:
            作成されたフィード情報（idを含む）
        """
        data: dict[str, Any] = {
            "name": name,
            "schedule": {
                "url": feed_url,
                "interval": schedule,
            },
        }
        return await self._post(f"/{catalog_id}/product_feeds", data=data)
