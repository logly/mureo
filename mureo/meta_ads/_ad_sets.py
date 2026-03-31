from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class AdSetsMixin:
    """Meta Ads 広告セット操作Mixin

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
    _AD_SET_FIELDS = (
        "id,name,status,campaign_id,daily_budget,lifetime_budget,"
        "billing_event,optimization_goal,targeting,start_time,end_time,"
        "created_time,updated_time,bid_amount,bid_strategy"
    )

    async def list_ad_sets(
        self,
        campaign_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """広告セット一覧を取得する

        Args:
            campaign_id: キャンペーンID（指定時はそのキャンペーン配下のみ）
            limit: 取得件数上限

        Returns:
            広告セット情報のリスト
        """
        params: dict[str, Any] = {
            "fields": self._AD_SET_FIELDS,
            "limit": limit,
        }

        if campaign_id:
            path = f"/{campaign_id}/adsets"
        else:
            account_id = self._ad_account_id
            path = f"/{account_id}/adsets"

        result = await self._get(path, params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_ad_set(self, ad_set_id: str) -> dict[str, Any]:
        """広告セット詳細を取得する

        Args:
            ad_set_id: 広告セットID

        Returns:
            広告セット詳細情報
        """
        params: dict[str, Any] = {"fields": self._AD_SET_FIELDS}
        return await self._get(f"/{ad_set_id}", params)

    async def create_ad_set(
        self,
        campaign_id: str,
        name: str,
        daily_budget: int,
        billing_event: str = "IMPRESSIONS",
        optimization_goal: str = "REACH",
        targeting: dict[str, Any] | None = None,
        status: str = "PAUSED",
        use_dynamic_creative: bool = False,
    ) -> dict[str, Any]:
        """広告セットを作成する

        Args:
            campaign_id: 所属キャンペーンID
            name: 広告セット名
            daily_budget: 日次予算（セント単位）
            billing_event: 課金イベント（IMPRESSIONS, LINK_CLICKS等）
            optimization_goal: 最適化目標（REACH, LINK_CLICKS, CONVERSIONS等）
            targeting: ターゲティング設定
            status: 初期ステータス（デフォルト: PAUSED）
            use_dynamic_creative: ダイナミッククリエイティブを有効化

        Returns:
            作成された広告セット情報
        """
        account_id = self._ad_account_id
        data: dict[str, Any] = {
            "campaign_id": campaign_id,
            "name": name,
            "daily_budget": daily_budget,
            "billing_event": billing_event,
            "optimization_goal": optimization_goal,
            "status": status,
        }
        if targeting is not None:
            data["targeting"] = json.dumps(targeting)
        else:
            # デフォルトのターゲティング（日本全国）
            data["targeting"] = json.dumps({"geo_locations": {"countries": ["JP"]}})
        if use_dynamic_creative:
            data["use_dynamic_creative"] = True

        return await self._post(f"/{account_id}/adsets", data)

    async def update_ad_set(
        self,
        ad_set_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """広告セットを更新する

        Args:
            ad_set_id: 広告セットID
            **kwargs: 更新するフィールド（name, status, daily_budget,
                      targeting, optimization_goal等）

        Returns:
            更新結果
        """
        data: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value is not None:
                if key == "targeting" and isinstance(value, dict):
                    data[key] = json.dumps(value)
                else:
                    data[key] = value

        return await self._post(f"/{ad_set_id}", data)

    async def pause_ad_set(self, ad_set_id: str) -> dict[str, Any]:
        """広告セットを一時停止する

        Args:
            ad_set_id: 広告セットID

        Returns:
            更新結果
        """
        return await self.update_ad_set(ad_set_id, status="PAUSED")

    async def enable_ad_set(self, ad_set_id: str) -> dict[str, Any]:
        """広告セットを有効化する

        Args:
            ad_set_id: 広告セットID

        Returns:
            更新結果
        """
        return await self.update_ad_set(ad_set_id, status="ACTIVE")
