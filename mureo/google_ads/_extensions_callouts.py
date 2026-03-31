"""コールアウト操作 Mixin。

list_callouts / create_callout / remove_callout を提供する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import map_callout

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

# キャンペーンあたりのコールアウト上限
_MAX_CALLOUTS_PER_CAMPAIGN = 20


class _CalloutsMixin:
    """コールアウト操作を提供する Mixin。"""

    # 親クラス (GoogleAdsApiClient) が提供する属性の型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    def _get_service(self, service_name: str) -> Any: ...

    # クラス変数として上限値を公開
    _MAX_CALLOUTS_PER_CAMPAIGN = _MAX_CALLOUTS_PER_CAMPAIGN

    async def list_callouts(self, campaign_id: str) -> list[dict[str, Any]]:
        """キャンペーンのコールアウト拡張一覧"""
        self._validate_id(campaign_id, "campaign_id")

        query = f"""
            SELECT
                campaign.id,
                asset.id, asset.resource_name,
                asset.callout_asset.callout_text
            FROM campaign_asset
            WHERE campaign_asset.field_type = 'CALLOUT'
                AND campaign.id = {campaign_id}
        """
        response = await self._search(query)  # type: ignore[attr-defined]
        return [map_callout(row) for row in response]

    @_wrap_mutate_error("コールアウト作成")
    async def create_callout(self, params: dict[str, Any]) -> dict[str, Any]:
        """コールアウト作成＆キャンペーンにリンク"""
        # 上限チェック
        campaign_id = params["campaign_id"]
        existing = await self.list_callouts(campaign_id)
        if len(existing) >= self._MAX_CALLOUTS_PER_CAMPAIGN:
            return {
                "error": True,
                "error_type": "validation_error",
                "message": f"コールアウトは1キャンペーンあたり最大{self._MAX_CALLOUTS_PER_CAMPAIGN}件です。"
                f"現在{len(existing)}件登録済みのため、不要なコールアウトを削除してから追加してください。",
            }

        # 1. アセット作成
        asset_service = self._get_service("AssetService")
        asset_op = self._client.get_type("AssetOperation")
        asset = asset_op.create
        asset.callout_asset.callout_text = params["callout_text"]
        asset_response = asset_service.mutate_assets(
            customer_id=self._customer_id,
            operations=[asset_op],
        )
        asset_resource_name = asset_response.results[0].resource_name

        # 2. キャンペーンにリンク
        campaign_asset_service = self._get_service("CampaignAssetService")
        ca_op = self._client.get_type("CampaignAssetOperation")
        campaign_asset = ca_op.create
        campaign_asset.campaign = self._client.get_service(
            "CampaignService"
        ).campaign_path(self._customer_id, params["campaign_id"])
        campaign_asset.asset = asset_resource_name
        campaign_asset.field_type = self._client.enums.AssetFieldTypeEnum.CALLOUT
        campaign_asset_service.mutate_campaign_assets(
            customer_id=self._customer_id,
            operations=[ca_op],
        )
        return {"resource_name": asset_resource_name}

    @_wrap_mutate_error("コールアウト削除")
    async def remove_callout(self, params: dict[str, Any]) -> dict[str, Any]:
        """コールアウト削除"""
        self._validate_id(params["campaign_id"], "campaign_id")
        self._validate_id(params["asset_id"], "asset_id")
        campaign_asset_service = self._get_service("CampaignAssetService")
        op = self._client.get_type("CampaignAssetOperation")
        op.remove = self._client.get_service(
            "CampaignAssetService"
        ).campaign_asset_path(
            self._customer_id,
            params["campaign_id"],
            params["asset_id"],
            "CALLOUT",
        )
        response = campaign_asset_service.mutate_campaign_assets(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}
