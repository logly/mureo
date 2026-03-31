"""Keyword operations mixin.

Provides list_keywords, add_keywords, remove_keyword,
suggest_keywords, list_negative_keywords, add_negative_keywords,
remove_negative_keyword, get_search_terms_report.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from google.ads.googleads.errors import GoogleAdsException
from google.protobuf.field_mask_pb2 import FieldMask as PbFieldMask

from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import (
    map_keyword,
    map_keyword_quality_info,
    map_negative_keyword,
    map_search_term,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _KeywordsMixin:
    """Keyword listing, adding, removing, suggestions, negative keywords, and search terms report."""

    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _validate_status(status: str) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _validate_match_type(match_type: str) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _extract_error_detail(exc: GoogleAdsException) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _has_error_code(exc: GoogleAdsException, attr_name: str, error_name: str) -> bool: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...
    def _period_to_date_clause(self, period: str) -> str: ...  # type: ignore[empty-body]

    # === Keywords ===

    async def list_keywords(
        self,
        ad_group_id: str | None = None,
        campaign_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """List keywords."""
        query = """
            SELECT
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.approval_status,
                campaign.id,
                campaign.name,
                ad_group.id,
                ad_group.name
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD'
        """
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            query += f"\n            AND campaign.id = {campaign_id}"
        if ad_group_id:
            self._validate_id(ad_group_id, "ad_group_id")
            query += f"\n            AND ad_group_criterion.ad_group = 'customers/{self._customer_id}/adGroups/{ad_group_id}'"
        if status_filter:
            validated = self._validate_status(status_filter)
            query += f"\n            AND ad_group_criterion.status = '{validated}'"
        response = await self._search(query)  # type: ignore[attr-defined]
        return [
            map_keyword(row.ad_group_criterion, row.campaign, row.ad_group)
            for row in response
        ]

    @_wrap_mutate_error("keyword addition")
    async def add_keywords(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Add keywords."""
        keywords = params.get("keywords", [])
        if not keywords:
            raise ValueError("At least one keyword must be specified")
        for kw in keywords:
            text = kw.get("text", "")
            if len(text) > 80:
                raise ValueError(
                    f"Keywords must be 80 characters or less: "
                    f"'{text[:20]}...'（{len(text)} chars)"
                )
        agc_service = self._get_service("AdGroupCriterionService")
        operations = []
        for kw in keywords:
            op = self._client.get_type("AdGroupCriterionOperation")
            criterion = op.create
            criterion.ad_group = self._client.get_service(
                "AdGroupService"
            ).ad_group_path(self._customer_id, params["ad_group_id"])
            criterion.keyword.text = kw["text"]
            validated_match = self._validate_match_type(kw.get("match_type", "BROAD"))
            match_type_enum = self._client.enums.KeywordMatchTypeEnum
            criterion.keyword.match_type = getattr(match_type_enum, validated_match)
            criterion.status = self._client.enums.AdGroupCriterionStatusEnum.ENABLED
            operations.append(op)
        response = agc_service.mutate_ad_group_criteria(
            customer_id=self._customer_id,
            operations=operations,
        )
        return [{"resource_name": r.resource_name} for r in response.results]

    @_wrap_mutate_error("keyword removal")
    async def remove_keyword(self, params: dict[str, Any]) -> dict[str, Any]:
        """Remove keyword."""
        self._validate_id(params["ad_group_id"], "ad_group_id")
        self._validate_id(params["criterion_id"], "criterion_id")
        agc_service = self._get_service("AdGroupCriterionService")
        op = self._client.get_type("AdGroupCriterionOperation")
        op.remove = self._client.get_service(
            "AdGroupCriterionService"
        ).ad_group_criterion_path(
            self._customer_id,
            params["ad_group_id"],
            params["criterion_id"],
        )
        response = agc_service.mutate_ad_group_criteria(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}

    @_wrap_mutate_error("keyword pause")
    async def pause_keyword(self, params: dict[str, Any]) -> dict[str, Any]:
        """Pause a keyword."""
        self._validate_id(params["ad_group_id"], "ad_group_id")
        self._validate_id(params["criterion_id"], "criterion_id")
        agc_service = self._get_service("AdGroupCriterionService")
        op = self._client.get_type("AdGroupCriterionOperation")
        criterion = op.update
        criterion.resource_name = self._client.get_service(
            "AdGroupCriterionService"
        ).ad_group_criterion_path(
            self._customer_id,
            params["ad_group_id"],
            params["criterion_id"],
        )
        criterion.status = self._client.enums.AdGroupCriterionStatusEnum.PAUSED
        self._client.copy_from(op.update_mask, PbFieldMask(paths=["status"]))
        response = agc_service.mutate_ad_group_criteria(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}

    # === Keyword Quality Diagnostics ===

    async def diagnose_keywords(self, campaign_id: str) -> dict[str, Any]:
        """Diagnose keyword quality scores and delivery status."""
        self._validate_id(campaign_id, "campaign_id")
        query = f"""
            SELECT
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.approval_status,
                ad_group_criterion.system_serving_status,
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.quality_info.creative_quality_score,
                ad_group_criterion.quality_info.post_click_quality_score,
                ad_group_criterion.quality_info.search_predicted_ctr,
                ad_group.id,
                ad_group.name,
                campaign.id,
                campaign.name
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD'
                AND ad_group_criterion.status != 'REMOVED'
                AND campaign.id = {campaign_id}
        """
        response = await self._search(query)  # type: ignore[attr-defined]
        keywords = [
            map_keyword_quality_info(row.ad_group_criterion, row.campaign, row.ad_group)
            for row in response
        ]

        # Get campaign name (from the first row)
        campaign_name = ""
        if keywords:
            campaign_name = keywords[0].get("campaign_name", "")

        # Quality score distribution
        high_count = 0
        medium_count = 0
        low_count = 0
        no_score_count = 0
        for kw in keywords:
            qs = kw.get("quality_score")
            if qs is None:
                no_score_count += 1
            elif qs >= 7:
                high_count += 1
            elif qs >= 5:
                medium_count += 1
            else:
                low_count += 1

        # Issue classification
        issues: dict[str, list[dict[str, Any]]] = {
            "low_quality_score": [],
            "rarely_served": [],
            "disapproved": [],
            "below_average_ctr": [],
            "below_average_ad_relevance": [],
            "below_average_landing_page": [],
        }
        issue_keyword_ids: set[str | None] = set()

        for kw in keywords:
            kw_id = kw.get("id")
            qs = kw.get("quality_score")
            if qs is not None and 1 <= qs <= 4:
                issues["low_quality_score"].append(kw)
                issue_keyword_ids.add(kw_id)
            if kw.get("system_serving_status") == "RARELY_SERVED":
                issues["rarely_served"].append(kw)
                issue_keyword_ids.add(kw_id)
            if kw.get("approval_status") == "DISAPPROVED":
                issues["disapproved"].append(kw)
                issue_keyword_ids.add(kw_id)
            if kw.get("search_predicted_ctr") == "BELOW_AVERAGE":
                issues["below_average_ctr"].append(kw)
                issue_keyword_ids.add(kw_id)
            if kw.get("creative_quality_score") == "BELOW_AVERAGE":
                issues["below_average_ad_relevance"].append(kw)
                issue_keyword_ids.add(kw_id)
            if kw.get("post_click_quality_score") == "BELOW_AVERAGE":
                issues["below_average_landing_page"].append(kw)
                issue_keyword_ids.add(kw_id)

        # Improvement actions per category
        category_labels: dict[str, str] = {
            "low_quality_score": "Low quality score (1-4)",
            "rarely_served": "Delivery restricted",
            "disapproved": "Disapproved",
            "below_average_ctr": "Predicted CTR below average",
            "below_average_ad_relevance": "Ad relevance below average",
            "below_average_landing_page": "Landing page experience below average",
        }
        category_actions: dict[str, list[str]] = {
            "low_quality_score": [
                "Include keywords in your ad text",
                "Align landing page content with keywords",
                "Consider reviewing match types",
            ],
            "rarely_served": [
                "Search volume may be low. Consider switching to broad match or adding related keywords",
            ],
            "disapproved": [
                "Check policy violation details in Google Ads dashboard and fix them",
            ],
            "below_average_ctr": [
                "Improve ad headlines to be more compelling",
                "Consider using dynamic keyword insertion",
            ],
            "below_average_ad_relevance": [
                "Narrow down the ad group theme",
                "Reflect keywords in ad text",
            ],
            "below_average_landing_page": [
                "Improve landing page loading speed",
                "Improve the relevance between landing page content and keywords",
            ],
        }

        recommendations = []
        for category, kw_list in issues.items():
            if kw_list:
                recommendations.append(
                    {
                        "category": category,
                        "category_label": category_labels[category],
                        "count": len(kw_list),
                        "actions": category_actions[category],
                    }
                )

        issue_keyword_ids.discard(None)

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "total_keywords": len(keywords),
            "quality_score_distribution": {
                "high_7_10": high_count,
                "medium_5_6": medium_count,
                "low_1_4": low_count,
                "no_score": no_score_count,
            },
            "issues": issues,
            "total_issues": len(issue_keyword_ids),
            "recommendations": recommendations,
            "keywords": keywords[:50],
        }

    # === Keyword Suggestions ===

    async def suggest_keywords(
        self, seed_keywords: list[str], language_id: str = "1005", geo_id: str = "2392"
    ) -> list[dict[str, Any]]:
        """Keyword suggestions (Keyword Planner)."""
        kp_service = self._get_service("KeywordPlanIdeaService")
        request = self._client.get_type("GenerateKeywordIdeasRequest")
        request.customer_id = self._customer_id
        request.language = f"languageConstants/{language_id}"
        request.geo_target_constants.append(f"geoTargetConstants/{geo_id}")
        request.keyword_seed.keywords.extend(seed_keywords)
        try:
            response = kp_service.generate_keyword_ideas(request=request)
        except GoogleAdsException as exc:
            if self._has_error_code(
                exc, "authorization_error", "DEVELOPER_TOKEN_NOT_APPROVED"
            ):
                raise ValueError(
                    "Keyword suggestion requires Basic or Standard access. "
                    "The current Developer Token has Explorer access and cannot use this feature. "
                    "Please apply for access level upgrade from the Google Ads API Center."
                ) from exc
            detail = self._extract_error_detail(exc)
            logger.error("Keyword suggestion failed: %s", detail)
            raise RuntimeError(
                "An error occurred while processing keyword suggestions."
            ) from exc
        return [
            {
                "keyword": idea.text,
                "avg_monthly_searches": idea.keyword_idea_metrics.avg_monthly_searches,
                "competition": str(idea.keyword_idea_metrics.competition),
            }
            for idea in response.results[:20]
        ]

    # === Negative Keywords ===

    async def list_negative_keywords(self, campaign_id: str) -> list[dict[str, Any]]:
        """List campaign-level negative keywords."""
        self._validate_id(campaign_id, "campaign_id")
        query = f"""
            SELECT
                campaign_criterion.criterion_id,
                campaign_criterion.keyword.text,
                campaign_criterion.keyword.match_type
            FROM campaign_criterion
            WHERE campaign_criterion.type = 'KEYWORD'
                AND campaign_criterion.negative = true
                AND campaign.id = {campaign_id}
        """
        response = await self._search(query)  # type: ignore[attr-defined]
        return [map_negative_keyword(row.campaign_criterion) for row in response]

    @_wrap_mutate_error("negative keyword addition")
    async def add_negative_keywords(
        self, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Add negative keywords."""
        cc_service = self._get_service("CampaignCriterionService")
        operations = []
        for kw in params.get("keywords", []):
            op = self._client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = self._client.get_service(
                "CampaignService"
            ).campaign_path(self._customer_id, params["campaign_id"])
            criterion.negative = True
            criterion.keyword.text = kw["text"]
            validated_match = self._validate_match_type(kw.get("match_type", "BROAD"))
            match_type_enum = self._client.enums.KeywordMatchTypeEnum
            criterion.keyword.match_type = getattr(match_type_enum, validated_match)
            operations.append(op)
        response = cc_service.mutate_campaign_criteria(
            customer_id=self._customer_id,
            operations=operations,
        )
        return [{"resource_name": r.resource_name} for r in response.results]

    @_wrap_mutate_error("ad group-level negative keyword addition")
    async def add_negative_keywords_to_ad_group(
        self, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Add ad group-level negative keywords."""
        self._validate_id(params["ad_group_id"], "ad_group_id")
        ag_service = self._get_service("AdGroupCriterionService")
        operations = []
        for kw in params.get("keywords", []):
            op = self._client.get_type("AdGroupCriterionOperation")
            criterion = op.create
            criterion.ad_group = self._client.get_service(
                "AdGroupService"
            ).ad_group_path(self._customer_id, params["ad_group_id"])
            criterion.negative = True
            criterion.keyword.text = kw["text"]
            validated_match = self._validate_match_type(kw.get("match_type", "BROAD"))
            match_type_enum = self._client.enums.KeywordMatchTypeEnum
            criterion.keyword.match_type = getattr(match_type_enum, validated_match)
            operations.append(op)
        response = ag_service.mutate_ad_group_criteria(
            customer_id=self._customer_id,
            operations=operations,
        )
        return [{"resource_name": r.resource_name} for r in response.results]

    @_wrap_mutate_error("negative keyword removal")
    async def remove_negative_keyword(self, params: dict[str, Any]) -> dict[str, Any]:
        """Remove negative keyword."""
        self._validate_id(params["campaign_id"], "campaign_id")
        self._validate_id(params["criterion_id"], "criterion_id")
        cc_service = self._get_service("CampaignCriterionService")
        op = self._client.get_type("CampaignCriterionOperation")
        op.remove = self._client.get_service(
            "CampaignCriterionService"
        ).campaign_criterion_path(
            self._customer_id,
            params["campaign_id"],
            params["criterion_id"],
        )
        response = cc_service.mutate_campaign_criteria(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}

    # === Search Terms Report ===

    async def get_search_terms_report(
        self,
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """Search terms report."""
        date_clause = self._period_to_date_clause(period)
        query = f"""
            SELECT
                search_term_view.search_term,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.ctr
            FROM search_term_view
            WHERE segments.date {date_clause}
        """
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            query += f"\n            AND campaign.id = {campaign_id}"
        if ad_group_id:
            self._validate_id(ad_group_id, "ad_group_id")
            query += f"\n            AND ad_group.id = {ad_group_id}"
        response = await self._search(query)  # type: ignore[attr-defined]
        return [map_search_term(row) for row in response]
