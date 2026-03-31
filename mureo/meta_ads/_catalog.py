"""Meta Ads product catalog and Dynamic Product Ads (DPA) mixin.

Provides product catalog management, product CRUD, and feed management.
Foundation for Dynamic Product Ads targeting e-commerce businesses.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Product retrieval fields
_PRODUCT_FIELDS = (
    "id,retailer_id,name,description,availability,condition,"
    "price,url,image_url,brand,category"
)

# Catalog retrieval fields
_CATALOG_FIELDS = "id,name,product_count,vertical"

# Feed retrieval fields
_FEED_FIELDS = "id,name,schedule,product_count,latest_upload"


class CatalogMixin:
    """Meta Ads product catalog & DPA operations mixin.

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _delete(self, path: str) -> dict[str, Any]: ...  # type: ignore[empty-body]

    # === Catalog management ===

    async def list_catalogs(self, business_id: str) -> list[dict[str, Any]]:
        """List catalogs.

        Args:
            business_id: Business ID

        Returns:
            List of catalog information
        """
        params: dict[str, Any] = {"fields": _CATALOG_FIELDS}
        result = await self._get(f"/{business_id}/owned_product_catalogs", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def create_catalog(self, business_id: str, name: str) -> dict[str, Any]:
        """Create a catalog.

        Args:
            business_id: Business ID
            name: Catalog name

        Returns:
            Created catalog information (includes id)
        """
        data: dict[str, Any] = {"name": name}
        return await self._post(f"/{business_id}/owned_product_catalogs", data=data)

    async def get_catalog(self, catalog_id: str) -> dict[str, Any]:
        """Get catalog details.

        Args:
            catalog_id: Catalog ID

        Returns:
            Catalog detail information
        """
        params: dict[str, Any] = {"fields": _CATALOG_FIELDS}
        return await self._get(f"/{catalog_id}", params)

    async def delete_catalog(self, catalog_id: str) -> dict[str, Any]:
        """Delete a catalog.

        Args:
            catalog_id: Catalog ID

        Returns:
            Deletion result
        """
        return await self._delete(f"/{catalog_id}")

    # === Product management ===

    async def list_products(
        self, catalog_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List products.

        Args:
            catalog_id: Catalog ID
            limit: Maximum number of results (default: 100)

        Returns:
            List of product information
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
        """Add a product.

        Args:
            catalog_id: Catalog ID
            product_data: Product data (retailer_id, name, price, etc.)

        Returns:
            Created product information (includes id)
        """
        return await self._post(f"/{catalog_id}/products", data=product_data)

    async def get_product(self, product_id: str) -> dict[str, Any]:
        """Get product details.

        Args:
            product_id: Product ID

        Returns:
            Product detail information
        """
        params: dict[str, Any] = {"fields": _PRODUCT_FIELDS}
        return await self._get(f"/{product_id}", params)

    async def update_product(
        self, product_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a product.

        Args:
            product_id: Product ID
            updates: Update data

        Returns:
            Update result
        """
        return await self._post(f"/{product_id}", data=updates)

    async def delete_product(self, product_id: str) -> dict[str, Any]:
        """Delete a product.

        Args:
            product_id: Product ID

        Returns:
            Deletion result
        """
        return await self._delete(f"/{product_id}")

    # === Feed management ===

    async def list_product_feeds(self, catalog_id: str) -> list[dict[str, Any]]:
        """List product feeds.

        Args:
            catalog_id: Catalog ID

        Returns:
            List of feed information
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
        """Create a product feed (URL-based, with scheduled auto-import).

        Args:
            catalog_id: Catalog ID
            name: Feed name
            feed_url: Feed URL
            schedule: Import schedule (DAILY, HOURLY, WEEKLY)

        Returns:
            Created feed information (includes id)
        """
        data: dict[str, Any] = {
            "name": name,
            "schedule": {
                "url": feed_url,
                "interval": schedule,
            },
        }
        return await self._post(f"/{catalog_id}/product_feeds", data=data)
