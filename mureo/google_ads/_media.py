"""Google Ads メディアアセット操作Mixin

画像アセットのアップロードを提供する。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mureo._image_validation import validate_image_file

logger = logging.getLogger(__name__)

# Google Ads 画像アセット制限
_GOOGLE_MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
_GOOGLE_ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif"})


class _MediaMixin:
    """Google Ads メディアアセット操作Mixin

    GoogleAdsApiClientに多重継承して使用する。
    """

    _client: Any
    _customer_id: str

    async def upload_image_asset(
        self,
        file_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """ローカルファイルから画像アセットをアップロードする。

        Args:
            file_path: ローカル画像ファイルのパス
            name: アセット名（省略時はファイル名を使用）

        Returns:
            {"resource_name": "customers/123/assets/456", "id": "456", "name": "..."}

        Raises:
            FileNotFoundError: ファイルが存在しない場合
            ValueError: バリデーションエラー
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
        # resource_nameからIDを抽出: "customers/123/assets/456" -> "456"
        asset_id = resource_name.rsplit("/", 1)[-1]

        return {
            "resource_name": resource_name,
            "id": asset_id,
            "name": asset_name,
        }
