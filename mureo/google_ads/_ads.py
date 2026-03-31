"""広告（Ad）操作のMixin。

list_ads, get_ad_policy_details, create_ad, update_ad, update_ad_status を提供する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from google.protobuf.field_mask_pb2 import FieldMask as PbFieldMask

from mureo.google_ads._rsa_validator import (
    RSAValidationResult,
    predict_ad_strength,
    validate_rsa_texts,
)
from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import (
    map_ad_strength,
    map_ad_type,
    map_approval_status,
    map_entity_status,
    map_policy_topic_type,
    map_review_status,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _AdsMixin:
    """広告の一覧・詳細・作成・ステータス変更"""

    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _validate_status(status: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...
    @staticmethod
    def _extract_evidences(entry: Any) -> list[str]: ...  # type: ignore[empty-body]

    # === 広告 ===

    @staticmethod
    def _validate_and_prepare_rsa(
        headlines: list[str],
        descriptions: list[str],
        final_url: str,
    ) -> tuple[list[str], list[str], RSAValidationResult]:
        """RSAバリデーション + 上限切り詰め + 最小個数チェックの共通処理。"""
        rsa_result = validate_rsa_texts(headlines, descriptions, final_url)
        headlines = list(rsa_result.headlines)
        descriptions = list(rsa_result.descriptions)
        if rsa_result.warnings:
            logger.warning("RSAバリデーション警告: %s", rsa_result.warnings)

        if len(headlines) > 15:
            logger.info("見出しが上限超過のため切り詰め: %d → 15", len(headlines))
            headlines = headlines[:15]
        if len(descriptions) > 4:
            logger.info("説明文が上限超過のため切り詰め: %d → 4", len(descriptions))
            descriptions = descriptions[:4]

        if len(headlines) < 3:
            raise ValueError(f"見出しは3個以上必要です（現在{len(headlines)}個）")
        if len(descriptions) < 2:
            raise ValueError(f"説明文は2個以上必要です（現在{len(descriptions)}個）")
        return headlines, descriptions, rsa_result

    @staticmethod
    def _build_ad_strength_result(
        result: dict[str, Any],
        rsa_result: RSAValidationResult,
        headlines: list[str],
        descriptions: list[str],
        keywords: list[str] | None,
    ) -> dict[str, Any]:
        """Ad Strength予測結果を result に追加する共通処理。"""
        if rsa_result.warnings:
            result["warnings"] = list(rsa_result.warnings)

        ad_strength = predict_ad_strength(
            headlines=headlines,
            descriptions=descriptions,
            keywords=keywords,
        )
        result["ad_strength"] = {
            "level": ad_strength.level,
            "score": round(ad_strength.score, 2),
            "suggestions": list(ad_strength.suggestions),
        }
        if ad_strength.level == "POOR":
            result["warnings"] = result.get("warnings", []) + [
                f"Ad Strength予測: {ad_strength.level}（{ad_strength.score:.0%}）— 改善を推奨"
            ]
        return result

    async def list_ads(
        self,
        ad_group_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """広告一覧"""
        query = """
            SELECT
                ad_group_ad.ad.id, ad_group_ad.ad.name,
                ad_group_ad.ad.type, ad_group_ad.status,
                ad_group_ad.ad_strength,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad.responsive_search_ad.descriptions,
                ad_group_ad.policy_summary.review_status,
                ad_group_ad.policy_summary.approval_status,
                ad_group.id, ad_group.name,
                campaign.id, campaign.name, campaign.status
            FROM ad_group_ad
        """
        conditions: list[str] = []
        if ad_group_id:
            self._validate_id(ad_group_id, "ad_group_id")
            conditions.append(
                f"ad_group_ad.ad_group = 'customers/{self._customer_id}/adGroups/{ad_group_id}'"
            )
        if status_filter:
            validated = self._validate_status(status_filter)
            conditions.append(f"ad_group_ad.status = '{validated}'")
        if conditions:
            query += "\n            WHERE " + " AND ".join(conditions)
        response = await self._search(query)
        results = []
        for row in response:
            ps = row.ad_group_ad.policy_summary
            ad_type = map_ad_type(row.ad_group_ad.ad.type_)
            headlines: list[str] = []
            descriptions: list[str] = []
            if ad_type == "RESPONSIVE_SEARCH_AD":
                rsa = row.ad_group_ad.ad.responsive_search_ad
                headlines = (
                    [asset.text for asset in rsa.headlines] if rsa.headlines else []
                )
                descriptions = (
                    [asset.text for asset in rsa.descriptions]
                    if rsa.descriptions
                    else []
                )
            results.append(
                {
                    "id": str(row.ad_group_ad.ad.id),
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "campaign_status": map_entity_status(row.campaign.status),
                    "status": map_entity_status(row.ad_group_ad.status),
                    "type": ad_type,
                    "ad_strength": map_ad_strength(row.ad_group_ad.ad_strength),
                    "headlines": headlines,
                    "descriptions": descriptions,
                    "review_status": map_review_status(ps.review_status) if ps else "",
                    "approval_status": (
                        map_approval_status(ps.approval_status) if ps else ""
                    ),
                }
            )
        return results

    async def get_ad_policy_details(
        self, ad_group_id: str, ad_id: str
    ) -> dict[str, Any] | None:
        """広告のポリシー詳細（不承認理由等）を取得"""
        self._validate_id(ad_group_id, "ad_group_id")
        self._validate_id(ad_id, "ad_id")
        query = f"""
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.status,
                ad_group_ad.policy_summary.approval_status,
                ad_group_ad.policy_summary.review_status,
                ad_group_ad.policy_summary.policy_topic_entries
            FROM ad_group_ad
            WHERE ad_group.id = {ad_group_id}
                AND ad_group_ad.ad.id = {ad_id}
        """
        response = await self._search(query)
        for row in response:
            ps = row.ad_group_ad.policy_summary
            policy_issues: list[dict[str, Any]] = []
            if ps and ps.policy_topic_entries:
                for entry in ps.policy_topic_entries:
                    policy_issues.append(
                        {
                            "topic": str(entry.topic),
                            "type": map_policy_topic_type(entry.type_),
                            "evidences": self._extract_evidences(entry),
                        }
                    )
            return {
                "ad_id": str(row.ad_group_ad.ad.id),
                "status": map_entity_status(row.ad_group_ad.status),
                "approval_status": (
                    map_approval_status(ps.approval_status) if ps else ""
                ),
                "review_status": map_review_status(ps.review_status) if ps else "",
                "policy_issues": policy_issues,
            }
        return None

    @_wrap_mutate_error("広告作成")
    async def create_ad(self, params: dict[str, Any]) -> dict[str, Any]:
        """レスポンシブ検索広告を作成"""
        final_url = params.get("final_url", "")
        headlines, descriptions, rsa_result = self._validate_and_prepare_rsa(
            params.get("headlines", []),
            params.get("descriptions", []),
            final_url,
        )

        ad_group_ad_service = self._get_service("AdGroupAdService")
        op = self._client.get_type("AdGroupAdOperation")
        ad_group_ad = op.create
        ad_group_ad.ad_group = self._client.get_service("AdGroupService").ad_group_path(
            self._customer_id, params["ad_group_id"]
        )
        ad_group_ad.status = self._client.enums.AdGroupAdStatusEnum.PAUSED
        ad = ad_group_ad.ad
        for h in headlines:
            text_asset = self._client.get_type("AdTextAsset")
            text_asset.text = h
            ad.responsive_search_ad.headlines.append(text_asset)
        for d in descriptions:
            text_asset = self._client.get_type("AdTextAsset")
            text_asset.text = d
            ad.responsive_search_ad.descriptions.append(text_asset)
        ad.final_urls.append(final_url)
        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=self._customer_id,
            operations=[op],
        )
        result: dict[str, Any] = {
            "resource_name": response.results[0].resource_name,
        }
        return self._build_ad_strength_result(
            result,
            rsa_result,
            headlines,
            descriptions,
            params.get("keywords"),
        )

    @_wrap_mutate_error("広告テキスト更新")
    async def update_ad(self, params: dict[str, Any]) -> dict[str, Any]:
        """既存のレスポンシブ検索広告の見出し・説明文を更新する。

        AdService.mutate_ads を使用（AdGroupAdService ではない）。
        見出し・説明文は差分ではなく全置換。
        """
        ad_id = params.get("ad_id", "")
        self._validate_id(ad_id, "ad_id")
        final_url = params.get("final_url")

        # final_url 未指定時はダミーURLでバリデーションを通す（URL自体は更新しない）
        validation_url = final_url if final_url else "https://placeholder.example.com"
        headlines, descriptions, rsa_result = self._validate_and_prepare_rsa(
            params.get("headlines", []),
            params.get("descriptions", []),
            validation_url,
        )

        # AdService で更新（AdGroupAdService ではない）
        ad_service = self._get_service("AdService")
        op = self._client.get_type("AdOperation")
        ad = op.update
        ad.resource_name = ad_service.ad_path(self._customer_id, ad_id)

        for h in headlines:
            text_asset = self._client.get_type("AdTextAsset")
            text_asset.text = h
            ad.responsive_search_ad.headlines.append(text_asset)
        for d in descriptions:
            text_asset = self._client.get_type("AdTextAsset")
            text_asset.text = d
            ad.responsive_search_ad.descriptions.append(text_asset)

        # FieldMask 構築
        paths = [
            "responsive_search_ad.headlines",
            "responsive_search_ad.descriptions",
        ]
        if final_url:
            ad.final_urls.append(final_url)
            paths.append("final_urls")
        self._client.copy_from(op.update_mask, PbFieldMask(paths=paths))

        response = ad_service.mutate_ads(
            customer_id=self._customer_id,
            operations=[op],
        )
        result: dict[str, Any] = {
            "resource_name": response.results[0].resource_name,
        }
        return self._build_ad_strength_result(
            result,
            rsa_result,
            headlines,
            descriptions,
            params.get("keywords"),
        )

    _MAX_ENABLED_RSA_PER_AD_GROUP = 3

    @_wrap_mutate_error("広告ステータス変更")
    async def update_ad_status(
        self, ad_group_id: str, ad_id: str, status: str
    ) -> dict[str, Any]:
        """広告のステータスを変更"""
        self._validate_id(ad_group_id, "ad_group_id")
        self._validate_id(ad_id, "ad_id")
        validated_status = self._validate_status(status)

        # ENABLED に変更する場合、RSA上限チェック
        if validated_status == "ENABLED":
            try:
                ads_data = await self.list_ads(ad_group_id=ad_group_id)
                ads = ads_data.get("ads", []) if isinstance(ads_data, dict) else []
                enabled_rsa = sum(
                    1
                    for a in ads
                    if a.get("status") == "ENABLED"
                    and a.get("type") == "RESPONSIVE_SEARCH_AD"
                    and str(a.get("id", "")) != ad_id
                )
                if enabled_rsa >= self._MAX_ENABLED_RSA_PER_AD_GROUP:
                    return {
                        "error": True,
                        "error_type": "validation_error",
                        "message": (
                            f"この広告グループには既に有効なRSAが{enabled_rsa}件あります"
                            f"（上限{self._MAX_ENABLED_RSA_PER_AD_GROUP}件）。"
                            "既存の広告を一時停止してから有効化してください。"
                        ),
                    }
            except Exception:
                logger.debug("RSA上限チェックに失敗（続行）", exc_info=True)

        ad_group_ad_service = self._get_service("AdGroupAdService")
        op = self._client.get_type("AdGroupAdOperation")
        ad_group_ad = op.update
        ad_group_ad.resource_name = self._client.get_service(
            "AdGroupAdService"
        ).ad_group_ad_path(self._customer_id, ad_group_id, ad_id)
        status_enum = self._client.enums.AdGroupAdStatusEnum
        ad_group_ad.status = getattr(status_enum, validated_status)
        self._client.copy_from(
            op.update_mask,
            PbFieldMask(paths=["status"]),
        )
        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}
