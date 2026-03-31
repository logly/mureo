"""Meta Ads Conversions API (CAPI) Mixin

サーバーサイドからコンバージョンイベントを Meta Ads に送信する。
iOS ATT 等でブラウザピクセルの精度が低下しているため、
CAPI による計測精度向上は必須。

エンドポイント: POST https://graph.facebook.com/v21.0/{pixel_id}/events
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mureo.meta_ads._hash_utils import normalize_user_data

logger = logging.getLogger(__name__)


class ConversionsMixin:
    """Meta Ads Conversions API (CAPI)

    MetaAdsApiClient に多重継承して使用する。
    """

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def send_event(
        self,
        pixel_id: str,
        events: list[dict[str, Any]],
        test_event_code: str | None = None,
    ) -> dict[str, Any]:
        """コンバージョンイベントを送信する

        Args:
            pixel_id: Meta Pixel ID
            events: イベントデータのリスト。各イベントは event_name,
                     event_time, action_source, user_data を含む。
            test_event_code: テストモード用コード（本番では None）

        Returns:
            API レスポンス（events_received, fbtrace_id 等）

        Raises:
            RuntimeError: API リクエストに失敗した場合
        """
        # user_data 内の PII を自動ハッシュ化
        normalized_events = []
        for event in events:
            normalized = {**event}
            if "user_data" in normalized:
                normalized["user_data"] = normalize_user_data(normalized["user_data"])
            normalized_events.append(normalized)

        post_data: dict[str, Any] = {
            "data": json.dumps(normalized_events),
        }
        if test_event_code is not None:
            post_data["test_event_code"] = test_event_code

        logger.info(
            "CAPI イベント送信: pixel_id=%s, events=%d件, test=%s",
            pixel_id,
            len(events),
            test_event_code or "なし",
        )

        return await self._post(f"/{pixel_id}/events", data=post_data)

    async def send_purchase_event(
        self,
        pixel_id: str,
        event_time: int,
        user_data: dict[str, Any],
        currency: str,
        value: float,
        content_ids: list[str] | None = None,
        event_source_url: str | None = None,
        test_event_code: str | None = None,
    ) -> dict[str, Any]:
        """購入イベントを送信するヘルパー

        Args:
            pixel_id: Meta Pixel ID
            event_time: イベント発生時刻（UNIX タイムスタンプ）
            user_data: ユーザー情報（em, ph, client_ip_address 等）
            currency: 通貨コード（USD, JPY 等）
            value: 購入金額
            content_ids: 商品 ID のリスト
            event_source_url: イベント発生 URL
            test_event_code: テストモード用コード

        Returns:
            API レスポンス
        """
        custom_data: dict[str, Any] = {
            "currency": currency,
            "value": value,
        }
        if content_ids is not None:
            custom_data["content_ids"] = content_ids

        event: dict[str, Any] = {
            "event_name": "Purchase",
            "event_time": event_time,
            "action_source": "website",
            "user_data": user_data,
            "custom_data": custom_data,
        }
        if event_source_url is not None:
            event["event_source_url"] = event_source_url

        return await self.send_event(pixel_id, [event], test_event_code=test_event_code)

    async def send_lead_event(
        self,
        pixel_id: str,
        event_time: int,
        user_data: dict[str, Any],
        event_source_url: str | None = None,
        test_event_code: str | None = None,
    ) -> dict[str, Any]:
        """リードイベントを送信するヘルパー

        Args:
            pixel_id: Meta Pixel ID
            event_time: イベント発生時刻（UNIX タイムスタンプ）
            user_data: ユーザー情報
            event_source_url: イベント発生 URL
            test_event_code: テストモード用コード

        Returns:
            API レスポンス
        """
        event: dict[str, Any] = {
            "event_name": "Lead",
            "event_time": event_time,
            "action_source": "website",
            "user_data": user_data,
        }
        if event_source_url is not None:
            event["event_source_url"] = event_source_url

        return await self.send_event(pixel_id, [event], test_event_code=test_event_code)
