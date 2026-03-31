"""Meta Ads オーディエンス操作Mixin

カスタムオーディエンス管理・類似オーディエンス作成。
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# カスタムオーディエンス取得用フィールド
_AUDIENCE_FIELDS = (
    "id,name,subtype,description,approximate_count,"
    "delivery_status,operation_status,retention_days,"
    "rule,lookalike_spec,time_created,time_updated"
)


class AudiencesMixin:
    """Meta Ads オーディエンス操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _delete(self, path: str) -> dict[str, Any]: ...

    async def list_custom_audiences(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """カスタムオーディエンス一覧を取得する

        Returns:
            カスタムオーディエンス情報のリスト
        """
        params: dict[str, Any] = {
            "fields": _AUDIENCE_FIELDS,
            "limit": limit,
        }
        result = await self._get(
            f"/{self._ad_account_id}/customaudiences", params
        )
        return result.get("data", [])

    async def get_custom_audience(
        self, audience_id: str
    ) -> dict[str, Any]:
        """カスタムオーディエンス詳細を取得する

        Args:
            audience_id: オーディエンスID

        Returns:
            オーディエンス詳細情報
        """
        params: dict[str, Any] = {"fields": _AUDIENCE_FIELDS}
        return await self._get(f"/{audience_id}", params)

    async def create_custom_audience(
        self,
        name: str,
        subtype: str,
        *,
        description: str | None = None,
        retention_days: int | None = None,
        rule: dict[str, Any] | None = None,
        pixel_id: str | None = None,
        customer_file_source: str | None = None,
    ) -> dict[str, Any]:
        """カスタムオーディエンスを作成する

        Args:
            name: オーディエンス名
            subtype: サブタイプ（WEBSITE, CUSTOM, APP, ENGAGEMENT等）
            description: 説明
            retention_days: リテンション期間（日数、WEBSITE用）
            rule: ルール定義（WEBSITE用、JSON形式）
            pixel_id: Meta PixelID（WEBSITE用）
            customer_file_source: 顧客ファイルソース（CUSTOM用）

        Returns:
            作成されたオーディエンス情報
        """
        data: dict[str, Any] = {
            "name": name,
            "subtype": subtype,
        }

        if description:
            data["description"] = description
        if retention_days is not None:
            data["retention_days"] = retention_days
        if rule is not None:
            data["rule"] = json.dumps(rule)
        if pixel_id:
            data["pixel_id"] = pixel_id
        if customer_file_source:
            data["customer_file_source"] = customer_file_source

        return await self._post(
            f"/{self._ad_account_id}/customaudiences", data
        )

    async def delete_custom_audience(
        self, audience_id: str
    ) -> dict[str, Any]:
        """カスタムオーディエンスを削除する

        Args:
            audience_id: オーディエンスID

        Returns:
            削除結果
        """
        return await self._delete(f"/{audience_id}")

    async def create_lookalike_audience(
        self,
        name: str,
        source_audience_id: str,
        country: str | list[str],
        ratio: float,
        *,
        starting_ratio: float = 0.0,
    ) -> dict[str, Any]:
        """類似オーディエンスを作成する

        Args:
            name: オーディエンス名
            source_audience_id: ソースとなるカスタムオーディエンスID
            country: 対象国コード（単一 or リスト）
            ratio: 類似度（0.01=上位1%, 0.05=上位5%, 最大0.20）
            starting_ratio: 類似度の開始位置（デフォルト0.0、範囲指定時に使用）

        Returns:
            作成された類似オーディエンス情報
        """
        lookalike_spec = {
            "origin_audience_id": source_audience_id,
            "starting_ratio": starting_ratio,
            "ratio": ratio,
            "country": country if isinstance(country, list) else country,
        }

        data: dict[str, Any] = {
            "name": name,
            "subtype": "LOOKALIKE",
            "lookalike_spec": json.dumps(lookalike_spec),
        }

        return await self._post(
            f"/{self._ad_account_id}/customaudiences", data
        )
