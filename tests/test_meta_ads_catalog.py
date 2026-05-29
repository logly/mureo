"""Unit tests for Meta Ads product catalogs and DPA.

Tests CatalogMixin with _get / _post / _delete mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mureo.meta_ads._catalog import CatalogMixin


# ---------------------------------------------------------------------------
# Helpers: mock class wrapping CatalogMixin for test isolation
# ---------------------------------------------------------------------------


def _make_catalog_client() -> CatalogMixin:
    """Build a CatalogMixin instance with mocked _get/_post/_delete/_ad_account_id."""

    class MockClient(CatalogMixin):
        def __init__(self) -> None:
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "new_id"})
            self._delete = AsyncMock(return_value={"success": True})

    return MockClient()


# ===========================================================================
# CatalogMixin tests
# ===========================================================================


@pytest.mark.unit
class TestCatalogMixin:
    @pytest.fixture()
    def client(self) -> CatalogMixin:
        return _make_catalog_client()

    # --- Catalog management ---

    @pytest.mark.asyncio
    async def test_list_catalogs(self, client: CatalogMixin) -> None:
        """Can list catalogs."""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {"id": "catalog_1", "name": "ECカタログ"},
                    {"id": "catalog_2", "name": "季節商品"},
                ]
            }
        )
        result = await client.list_catalogs("biz_001")
        assert len(result) == 2
        assert result[0]["id"] == "catalog_1"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/biz_001/owned_product_catalogs" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_catalog(self, client: CatalogMixin) -> None:
        """Can create a catalog."""
        client._post = AsyncMock(return_value={"id": "catalog_new"})
        result = await client.create_catalog("biz_001", "新カタログ")
        assert result["id"] == "catalog_new"
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/biz_001/owned_product_catalogs" in call_args[0][0]
        data = call_args[1].get("data") or call_args[0][1]
        assert data["name"] == "新カタログ"

    @pytest.mark.asyncio
    async def test_get_catalog(self, client: CatalogMixin) -> None:
        """Can fetch catalog details."""
        client._get = AsyncMock(
            return_value={"id": "catalog_1", "name": "ECカタログ", "product_count": 150}
        )
        result = await client.get_catalog("catalog_1")
        assert result["id"] == "catalog_1"
        assert result["name"] == "ECカタログ"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/catalog_1" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_delete_catalog(self, client: CatalogMixin) -> None:
        """Can delete a catalog."""
        client._delete = AsyncMock(return_value={"success": True})
        result = await client.delete_catalog("catalog_1")
        assert result["success"] is True
        client._delete.assert_called_once()
        call_args = client._delete.call_args
        assert "/catalog_1" in call_args[0][0]

    # --- Product management ---

    @pytest.mark.asyncio
    async def test_list_products(self, client: CatalogMixin) -> None:
        """Can list products."""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {"id": "prod_1", "name": "サンプル商品"},
                    {"id": "prod_2", "name": "テスト商品"},
                ]
            }
        )
        result = await client.list_products("catalog_1")
        assert len(result) == 2
        assert result[0]["id"] == "prod_1"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/catalog_1/products" in call_args[0][0]
        params = call_args[0][1]
        assert params["limit"] == 100

    @pytest.mark.asyncio
    async def test_list_products_custom_limit(self, client: CatalogMixin) -> None:
        """Can list products with a custom limit."""
        client._get = AsyncMock(return_value={"data": []})
        await client.list_products("catalog_1", limit=10)
        call_args = client._get.call_args
        params = call_args[0][1]
        assert params["limit"] == 10

    @pytest.mark.asyncio
    async def test_add_product(self, client: CatalogMixin) -> None:
        """Can add a product."""
        product_data = {
            "retailer_id": "SKU-001",
            "name": "サンプル商品",
            "description": "商品説明",
            "availability": "in stock",
            "condition": "new",
            "price": "1000 JPY",
            "url": "https://example.com/product/001",
            "image_url": "https://example.com/images/001.jpg",
            "brand": "ブランドA",
            "category": "衣類 > トップス",
        }
        client._post = AsyncMock(return_value={"id": "prod_new"})
        result = await client.add_product("catalog_1", product_data)
        assert result["id"] == "prod_new"
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/catalog_1/products" in call_args[0][0]
        data = call_args[1].get("data") or call_args[0][1]
        assert data["retailer_id"] == "SKU-001"
        assert data["name"] == "サンプル商品"

    @pytest.mark.asyncio
    async def test_get_product(self, client: CatalogMixin) -> None:
        """Can fetch product details."""
        client._get = AsyncMock(
            return_value={
                "id": "prod_1",
                "name": "サンプル商品",
                "price": "1000 JPY",
            }
        )
        result = await client.get_product("prod_1")
        assert result["id"] == "prod_1"
        assert result["name"] == "サンプル商品"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/prod_1" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_update_product(self, client: CatalogMixin) -> None:
        """Can update a product."""
        updates = {"name": "更新商品", "price": "2000 JPY"}
        client._post = AsyncMock(return_value={"success": True})
        result = await client.update_product("prod_1", updates)
        assert result["success"] is True
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/prod_1" in call_args[0][0]
        data = call_args[1].get("data") or call_args[0][1]
        assert data["name"] == "更新商品"
        assert data["price"] == "2000 JPY"

    @pytest.mark.asyncio
    async def test_delete_product(self, client: CatalogMixin) -> None:
        """Can delete a product."""
        client._delete = AsyncMock(return_value={"success": True})
        result = await client.delete_product("prod_1")
        assert result["success"] is True
        client._delete.assert_called_once()
        call_args = client._delete.call_args
        assert "/prod_1" in call_args[0][0]

    # --- Feed management ---

    @pytest.mark.asyncio
    async def test_list_product_feeds(self, client: CatalogMixin) -> None:
        """Can list product feeds."""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {"id": "feed_1", "name": "メインフィード"},
                ]
            }
        )
        result = await client.list_product_feeds("catalog_1")
        assert len(result) == 1
        assert result[0]["id"] == "feed_1"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/catalog_1/product_feeds" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_product_feed(self, client: CatalogMixin) -> None:
        """Can create a product feed."""
        client._post = AsyncMock(return_value={"id": "feed_new"})
        result = await client.create_product_feed(
            "catalog_1",
            "日次フィード",
            "https://example.com/feed.xml",
            schedule="DAILY",
        )
        assert result["id"] == "feed_new"
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/catalog_1/product_feeds" in call_args[0][0]
        data = call_args[1].get("data") or call_args[0][1]
        assert data["name"] == "日次フィード"
        assert data["schedule"]["url"] == "https://example.com/feed.xml"
        assert data["schedule"]["interval"] == "DAILY"

    # --- Error cases ---

    @pytest.mark.asyncio
    async def test_api_error(self, client: CatalogMixin) -> None:
        """RuntimeError is raised on API errors."""
        client._get = AsyncMock(
            side_effect=RuntimeError(
                "Meta API リクエストに失敗しました (status=400, path=/biz_001/owned_product_catalogs)"
            )
        )
        with pytest.raises(RuntimeError, match="Meta API"):
            await client.list_catalogs("biz_001")
