from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CampaignsMixin:
    """Meta Ads キャンペーン操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    # 共通フィールド定義
    _CAMPAIGN_FIELDS = (
        "id,name,status,objective,daily_budget,lifetime_budget,"
        "created_time,updated_time,start_time,stop_time,"
        "special_ad_categories,bid_strategy,budget_remaining"
    )

    async def list_campaigns(
        self,
        *,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """キャンペーン一覧を取得する

        Args:
            status_filter: ステータスフィルター（ACTIVE, PAUSED, ARCHIVED, DELETED）
            limit: 取得件数上限

        Returns:
            キャンペーン情報のリスト
        """
        account_id = self._ad_account_id
        params: dict[str, Any] = {
            "fields": self._CAMPAIGN_FIELDS,
            "limit": limit,
        }
        if status_filter:
            params["filtering"] = json.dumps(
                [{"field": "status", "operator": "IN", "value": [status_filter]}]
            )

        result = await self._get(f"/{account_id}/campaigns", params)
        return result.get("data", [])

    async def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        """キャンペーン詳細を取得する

        Args:
            campaign_id: キャンペーンID

        Returns:
            キャンペーン詳細情報
        """
        params: dict[str, Any] = {"fields": self._CAMPAIGN_FIELDS}
        return await self._get(f"/{campaign_id}", params)

    async def create_campaign(
        self,
        name: str,
        objective: str,
        status: str = "PAUSED",
        *,
        daily_budget: int | None = None,
        lifetime_budget: int | None = None,
        special_ad_categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """キャンペーンを作成する

        Args:
            name: キャンペーン名
            objective: キャンペーン目的（CONVERSIONS, LINK_CLICKS, REACH等）
            status: 初期ステータス（デフォルト: PAUSED）
            daily_budget: 日次予算（セント単位）
            lifetime_budget: 通算予算（セント単位）
            special_ad_categories: 特別広告カテゴリ（HOUSING, CREDIT等）

        Returns:
            作成されたキャンペーン情報
        """
        account_id = self._ad_account_id
        data: dict[str, Any] = {
            "name": name,
            "objective": objective,
            "status": status,
        }
        if daily_budget is not None:
            data["daily_budget"] = daily_budget
        if lifetime_budget is not None:
            data["lifetime_budget"] = lifetime_budget
        if special_ad_categories is not None:
            data["special_ad_categories"] = json.dumps(special_ad_categories)
        else:
            # Meta APIはspecial_ad_categoriesが必須（空配列でも可）
            data["special_ad_categories"] = json.dumps([])

        return await self._post(f"/{account_id}/campaigns", data)

    async def update_campaign(
        self,
        campaign_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """キャンペーンを更新する

        Args:
            campaign_id: キャンペーンID
            **kwargs: 更新するフィールド（name, status, daily_budget, lifetime_budget等）

        Returns:
            更新結果
        """
        data: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value

        return await self._post(f"/{campaign_id}", data)

    async def pause_campaign(self, campaign_id: str) -> dict[str, Any]:
        """キャンペーンを一時停止する

        Args:
            campaign_id: キャンペーンID

        Returns:
            更新結果
        """
        return await self.update_campaign(campaign_id, status="PAUSED")

    async def enable_campaign(self, campaign_id: str) -> dict[str, Any]:
        """キャンペーンを有効化する

        Args:
            campaign_id: キャンペーンID

        Returns:
            更新結果
        """
        return await self.update_campaign(campaign_id, status="ACTIVE")
