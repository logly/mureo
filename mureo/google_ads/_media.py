"""Google Ads media asset operations mixin.

Provides image asset uploading and listing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mureo._image_validation import validate_image_file
from mureo.google_ads.mappers import ASSET_TYPE_MAP, MIME_TYPE_MAP, map_enum_name

logger = logging.getLogger(__name__)

# Google Ads image asset limits
_GOOGLE_MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
_GOOGLE_ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif"})


class _MediaMixin:
    """Google Ads media asset operations mixin.

    Used via multiple inheritance with GoogleAdsApiClient.
    """

    _client: Any
    _customer_id: str

    async def _search(self, query: str) -> Any: ...

    async def list_image_assets(self, limit: int = 100) -> list[dict[str, Any]]:
        """List image assets in the account with names and dimensions (#366).

        Read-only. Returns id, name, type, file_size (bytes), mime_type,
        full-size width/height in pixels, and the serving URL per asset.

        Args:
            limit: Maximum number of assets to return (1–1000).
        """
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not (1 <= limit <= 1000)
        ):
            raise ValueError(f"limit must be an integer in 1..1000 (got {limit!r})")
        query = f"""
            SELECT
                asset.id,
                asset.name,
                asset.type,
                asset.image_asset.file_size,
                asset.image_asset.mime_type,
                asset.image_asset.full_size.width_pixels,
                asset.image_asset.full_size.height_pixels,
                asset.image_asset.full_size.url
            FROM asset
            WHERE asset.type = 'IMAGE'
            LIMIT {limit}
        """
        response = await self._search(query)
        results: list[dict[str, Any]] = []
        for row in response:
            asset = row.asset
            image = asset.image_asset
            results.append(
                {
                    "id": str(asset.id),
                    "name": str(asset.name),
                    "type": map_enum_name(asset.type_, ASSET_TYPE_MAP),
                    "file_size": int(image.file_size),
                    "mime_type": map_enum_name(image.mime_type, MIME_TYPE_MAP),
                    "width_pixels": int(image.full_size.width_pixels),
                    "height_pixels": int(image.full_size.height_pixels),
                    "url": str(image.full_size.url),
                }
            )
        return results

    async def upload_image_asset(
        self,
        file_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Upload image assets from a local file.

        Args:
            file_path: Local image file path
            name: Asset name (defaults to filename if omitted)

        Returns:
            {"resource_name": "customers/123/assets/456", "id": "456", "name": "..."}

        Raises:
            FileNotFoundError: File does not exist
            ValueError: Validation error
        """
        path = validate_image_file(
            file_path,
            max_size_bytes=_GOOGLE_MAX_IMAGE_SIZE_BYTES,
            max_size_label="5MB",
            allowed_extensions=_GOOGLE_ALLOWED_IMAGE_EXTENSIONS,
        )

        asset_name = name or path.name
        image_data = path.read_bytes()

        asset_service = self._client.get_service("AssetService")
        asset_operation = self._client.get_type("AssetOperation")
        asset = asset_operation.create

        asset.type_ = self._client.enums.AssetTypeEnum.AssetType.IMAGE
        asset.name = asset_name
        asset.image_asset.data = image_data
        asset.image_asset.file_size = len(image_data)

        def _do_mutate() -> Any:
            return asset_service.mutate_assets(
                customer_id=self._customer_id,
                operations=[asset_operation],
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _do_mutate)

        resource_name = response.results[0].resource_name
        # Extract ID from resource_name: "customers/123/assets/456" -> "456"
        asset_id = resource_name.rsplit("/", 1)[-1]

        return {
            "resource_name": resource_name,
            "id": asset_id,
            "name": asset_name,
        }
