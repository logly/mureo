"""Ad operations mixin.

Provides list_ads, get_ad_policy_details, create_ad, update_ad, update_ad_status.
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
    """Ad listing, details, creation, and status changes."""

    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _validate_status(status: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...
    @staticmethod
    def _extract_evidences(entry: Any) -> list[str]: ...  # type: ignore[empty-body]

    # === Ads ===

    @staticmethod
    def _validate_and_prepare_rsa(
        headlines: list[str],
        descriptions: list[str],
        final_url: str,
    ) -> tuple[list[str], list[str], RSAValidationResult]:
        """Common processing for RSA validation + limit truncation + minimum count check."""
        rsa_result = validate_rsa_texts(headlines, descriptions, final_url)
        headlines = list(rsa_result.headlines)
        descriptions = list(rsa_result.descriptions)
        if rsa_result.warnings:
            logger.warning("RSA validation warnings: %s", rsa_result.warnings)

        if len(headlines) > 15:
            logger.info(
                "Truncating headlines exceeding limit: %d -> 15", len(headlines)
            )
            headlines = headlines[:15]
        if len(descriptions) > 4:
            logger.info(
                "Truncating descriptions exceeding limit: %d -> 4", len(descriptions)
            )
            descriptions = descriptions[:4]

        if len(headlines) < 3:
            raise ValueError(
                f"At least 3 headlines are required (currently {len(headlines)})"
            )
        if len(descriptions) < 2:
            raise ValueError(
                f"At least 2 descriptions are required (currently {len(descriptions)})"
            )
        return headlines, descriptions, rsa_result

    @staticmethod
    def _build_ad_strength_result(
        result: dict[str, Any],
        rsa_result: RSAValidationResult,
        headlines: list[str],
        descriptions: list[str],
        keywords: list[str] | None,
    ) -> dict[str, Any]:
        """Common processing to add Ad Strength prediction results to result."""
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
                f"Ad Strength prediction: {ad_strength.level} ({ad_strength.score:.0%}) - improvement recommended"
            ]
        return result

    async def list_ads(
        self,
        ad_group_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """List ads."""
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
        response = await self._search(query)  # type: ignore[attr-defined]
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
        """Get ad policy details (disapproval reasons, etc.)."""
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
        response = await self._search(query)  # type: ignore[attr-defined]
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

    @_wrap_mutate_error("ad creation")
    async def create_ad(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a responsive search ad."""
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

    @_wrap_mutate_error("ad text update")
    async def update_ad(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update headlines and descriptions of an existing responsive search ad.

        Uses AdService.mutate_ads (not AdGroupAdService).
        Headlines and descriptions are fully replaced, not patched.
        """
        ad_id = params.get("ad_id", "")
        self._validate_id(ad_id, "ad_id")
        final_url = params.get("final_url")

        # Use dummy URL for validation when final_url is not specified (URL itself is not updated)
        validation_url = final_url if final_url else "https://placeholder.example.com"
        headlines, descriptions, rsa_result = self._validate_and_prepare_rsa(
            params.get("headlines", []),
            params.get("descriptions", []),
            validation_url,
        )

        # Update via AdService (not AdGroupAdService)
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

        # Build FieldMask
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

    @_wrap_mutate_error("ad status change")
    async def update_ad_status(
        self, ad_group_id: str, ad_id: str, status: str
    ) -> dict[str, Any]:
        """Change ad status."""
        self._validate_id(ad_group_id, "ad_group_id")
        self._validate_id(ad_id, "ad_id")
        validated_status = self._validate_status(status)

        # Check RSA limit when changing to ENABLED
        if validated_status == "ENABLED":
            try:
                ads_data = await self.list_ads(ad_group_id=ad_group_id)
                ads = ads_data.get("ads", []) if isinstance(ads_data, dict) else []  # type: ignore[var-annotated]
                enabled_rsa = sum(
                    1  # type: ignore[misc]
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
                            f"This ad group already has {enabled_rsa} active RSAs"
                            f" (limit: {self._MAX_ENABLED_RSA_PER_AD_GROUP})."
                            " Please pause existing ads before enabling."
                        ),
                    }
            except Exception:
                logger.debug("RSA limit check failed (continuing)", exc_info=True)

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
