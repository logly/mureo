"""Meta Ads Pixel操作Mixin

ピクセル一覧・詳細・統計・イベント確認（読み取り専用）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ピクセル取得用フィールド
_PIXEL_FIELDS = (
    "id,name,creation_time,last_fired_time,"
    "is_created_by_business,owner_ad_account,"
    "code,data_use_setting"
)

# 期間→日数マッピング
_PERIOD_DAYS: dict[str, int] = {
    "last_7d": 7,
    "last_14d": 14,
    "last_30d": 30,
    "last_90d": 90,
}


class PixelsMixin:
    """Meta Ads Pixel操作Mixin（読み取り専用）

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def list_ad_pixels(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """広告アカウントに紐づくピクセル一覧を取得する

        Returns:
            ピクセル情報のリスト
        """
        params: dict[str, Any] = {
            "fields": _PIXEL_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/adspixels", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_pixel(self, pixel_id: str) -> dict[str, Any]:
        """ピクセル詳細を取得する

        Args:
            pixel_id: ピクセルID

        Returns:
            ピクセル詳細情報
        """
        params: dict[str, Any] = {"fields": _PIXEL_FIELDS}
        return await self._get(f"/{pixel_id}", params)

    async def get_pixel_stats(
        self,
        pixel_id: str,
        period: str = "last_7d",
    ) -> list[dict[str, Any]]:
        """ピクセルのイベント統計を取得する

        Args:
            pixel_id: ピクセルID
            period: 集計期間（last_7d, last_14d, last_30d, last_90d）

        Returns:
            イベント統計のリスト
        """
        days = _PERIOD_DAYS.get(period, 7)
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        params: dict[str, Any] = {
            "aggregation": "event",
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%S+0000"),
            "end_time": now.strftime("%Y-%m-%dT%H:%M:%S+0000"),
        }
        result = await self._get(f"/{pixel_id}/stats", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_pixel_events(
        self,
        pixel_id: str,
    ) -> list[dict[str, Any]]:
        """ピクセルで受信しているイベント種別一覧を取得する

        Args:
            pixel_id: ピクセルID

        Returns:
            イベント種別と件数のリスト
        """
        params: dict[str, Any] = {
            "fields": "event_name,count",
        }
        result = await self._get(f"/{pixel_id}/stats", params)
        return result.get("data", [])  # type: ignore[no-any-return]
