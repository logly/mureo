"""サイトリンク操作 Mixin。

list_sitelinks / create_sitelink / remove_sitelink を提供する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import map_sitelink

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

# キャンペーンあたりのサイトリンク上限
_MAX_SITELINKS_PER_CAMPAIGN = 20


class _SitelinksMixin:
    """サイトリンク操作を提供する Mixin。"""

    # 親クラス (GoogleAdsApiClient) が提供する属性の型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    def _get_service(self, service_name: str) -> Any: ...

    # クラス変数として上限値を公開
    _MAX_SITELINKS_PER_CAMPAIGN = _MAX_SITELINKS_PER_CAMPAIGN

    async def list_sitelinks(self, campaign_id: str) -> list[dict[str, Any]]:
        """キャンペーンに適用されるサイトリンク一覧（キャンペーン＋アカウントレベル）

        Google Adsではサイトリンクは以下の3階層で設定可能:
        - アカウントレベル (customer_asset): 全キャンペーンに適用
        - キャンペーンレベル (campaign_asset): 指定キャンペーンのみ
        - 広告グループレベル (ad_group_asset): 指定広告グループのみ

        このメソッドはキャンペーンレベルとアカウントレベルの両方を返す。
        """
        self._validate_id(campaign_id, "campaign_id")

        # キャンペーンレベル
        campaign_query = f"""
            SELECT
                campaign.id,
                asset.id, asset.resource_name,
                asset.sitelink_asset.link_text,
                asset.sitelink_asset.description1,
                asset.sitelink_asset.description2,
                asset.final_urls
            FROM campaign_asset
            WHERE campaign_asset.field_type = 'SITELINK'
                AND campaign.id = {campaign_id}
        """

        # アカウントレベル（全キャンペーンに適用）
        account_query = """
            SELECT
                asset.id, asset.resource_name,
                asset.sitelink_asset.link_text,
                asset.sitelink_asset.description1,
                asset.sitelink_asset.description2,
                asset.final_urls
            FROM customer_asset
            WHERE customer_asset.field_type = 'SITELINK'
        """

        campaign_response = await self._search(campaign_query)
        results = [{**map_sitelink(row), "level": "campaign"} for row in campaign_response]

        # 重複を避けるため、既存のasset IDを記録
        seen_ids: set[str | None] = {r.get("id") for r in results}

        try:
            account_response = await self._search(account_query)
            for row in account_response:
                mapped = map_sitelink(row)
                if mapped.get("id") not in seen_ids:
                    mapped["level"] = "account"
                    results.append(mapped)
                    seen_ids.add(mapped.get("id"))
        except Exception:
            logger.debug("アカウントレベルのサイトリンク取得に失敗", exc_info=True)

        return results

    @_wrap_mutate_error("サイトリンク作成")
    async def create_sitelink(self, params: dict[str, Any]) -> dict[str, Any]:
        """サイトリンク作成＆キャンペーンにリンク"""
        # 上限チェック
        campaign_id = params["campaign_id"]
        existing = await self.list_sitelinks(campaign_id)
        campaign_count = sum(1 for s in existing if s.get("level") == "campaign")
        if campaign_count >= self._MAX_SITELINKS_PER_CAMPAIGN:
            return {
                "error": True,
                "error_type": "validation_error",
                "message": f"サイトリンクは1キャンペーンあたり最大{self._MAX_SITELINKS_PER_CAMPAIGN}件です。"
                f"現在{campaign_count}件登録済みのため、不要なサイトリンクを削除してから追加してください。",
            }

        # 1. アセット作成
        asset_service = self._get_service("AssetService")
        asset_op = self._client.get_type("AssetOperation")
        asset = asset_op.create
        asset.sitelink_asset.link_text = params["link_text"]
        asset.final_urls.append(params["final_url"])
        if "description1" in params:
            asset.sitelink_asset.description1 = params["description1"]
        if "description2" in params:
            asset.sitelink_asset.description2 = params["description2"]
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
        campaign_asset.field_type = self._client.enums.AssetFieldTypeEnum.SITELINK
        campaign_asset_service.mutate_campaign_assets(
            customer_id=self._customer_id,
            operations=[ca_op],
        )
        return {"resource_name": asset_resource_name}

    @_wrap_mutate_error("サイトリンク削除")
    async def remove_sitelink(self, params: dict[str, Any]) -> dict[str, Any]:
        """サイトリンク削除"""
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
            "SITELINK",
        )
        response = campaign_asset_service.mutate_campaign_assets(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}
