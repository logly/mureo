from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from mureo.google_ads.mappers import (
    map_ad_type,
    map_approval_status,
    map_bidding_strategy_type,
    map_criterion_approval_status,
    map_review_status,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# primary_status_reasons -> description mapping
# ---------------------------------------------------------------------------

_PRIMARY_STATUS_REASON_DESC: dict[str, str] = {
    "CAMPAIGN_DRAFT": "Campaign is in draft status",
    "CAMPAIGN_PAUSED": "Campaign is paused",
    "CAMPAIGN_REMOVED": "Campaign has been removed",
    "CAMPAIGN_ENDED": "Campaign end date has passed",
    "CAMPAIGN_PENDING": "Campaign start date has not yet arrived",
    "BIDDING_STRATEGY_MISCONFIGURED": "Bidding strategy is misconfigured",
    "BIDDING_STRATEGY_LIMITED": "Bidding strategy is limited due to insufficient data",
    "BIDDING_STRATEGY_LEARNING": "Bidding strategy is in learning period (1-2 weeks)",
    "BIDDING_STRATEGY_CONSTRAINED": "Bidding strategy is constrained",
    "BUDGET_CONSTRAINED": "Missing display opportunities due to insufficient budget",
    "BUDGET_MISCONFIGURED": "Budget is misconfigured",
    "SEARCH_VOLUME_LIMITED": "Search volume is insufficient",
    "AD_GROUPS_PAUSED": "All ad groups are paused",
    "NO_AD_GROUPS": "No ad groups exist",
    "KEYWORDS_PAUSED": "All keywords are paused",
    "NO_KEYWORDS": "No keywords exist",
    "AD_GROUP_ADS_PAUSED": "All ads are paused",
    "NO_AD_GROUP_ADS": "No ads exist",
    "HAS_ADS_LIMITED_BY_POLICY": "Some ads are limited by policy",
    "HAS_ADS_DISAPPROVED": "There are disapproved ads",
    "MOST_ADS_UNDER_REVIEW": "Most ads are under review",
    "MISSING_LEAD_FORM_EXTENSION": "Lead form extension is not configured",
    "MISSING_CALL_EXTENSION": "Call extension is not configured",
    "LEAD_FORM_EXTENSION_UNDER_REVIEW": "Lead form extension is under review",
    "LEAD_FORM_EXTENSION_DISAPPROVED": "Lead form extension is disapproved",
    "CALL_EXTENSION_UNDER_REVIEW": "Call extension is under review",
    "CALL_EXTENSION_DISAPPROVED": "Call extension is disapproved",
    "NO_ACTIVE_MOBILE_APP_STORE_LINKS": "No active mobile app store links",
    "CAMPAIGN_GROUP_PAUSED": "Campaign group is paused",
    "CAMPAIGN_GROUP_ALL_GROUP_BUDGETS_ENDED": "All campaign group budgets have ended",
    "APP_NOT_RELEASED": "App is not released",
    "APP_PARTIALLY_RELEASED": "App is partially released",
    "HAS_ASSET_GROUPS_DISAPPROVED": "Asset groups are disapproved",
    "HAS_ASSET_GROUPS_LIMITED_BY_POLICY": "Asset groups are limited by policy",
    "MOST_ASSET_GROUPS_UNDER_REVIEW": "Most asset groups are under review",
    "NO_ASSET_GROUPS": "No asset groups exist",
    "ASSET_GROUPS_PAUSED": "All asset groups are paused",
}

# primary_status_reasons treated as issues (directly impact delivery)
_REASON_IS_ISSUE: frozenset[str] = frozenset(
    {
        "CAMPAIGN_PAUSED",
        "CAMPAIGN_REMOVED",
        "CAMPAIGN_ENDED",
        "BIDDING_STRATEGY_MISCONFIGURED",
        "BUDGET_MISCONFIGURED",
        "NO_AD_GROUPS",
        "NO_KEYWORDS",
        "NO_AD_GROUP_ADS",
        "AD_GROUPS_PAUSED",
        "KEYWORDS_PAUSED",
        "AD_GROUP_ADS_PAUSED",
        "HAS_ADS_DISAPPROVED",
        "MISSING_LEAD_FORM_EXTENSION",
        "MISSING_CALL_EXTENSION",
        "LEAD_FORM_EXTENSION_DISAPPROVED",
        "CALL_EXTENSION_DISAPPROVED",
        "NO_ACTIVE_MOBILE_APP_STORE_LINKS",
        "APP_NOT_RELEASED",
        "HAS_ASSET_GROUPS_DISAPPROVED",
        "NO_ASSET_GROUPS",
    }
)

# bidding_strategy_system_status learning status -> description
_LEARNING_STATUS_DESC: dict[str, str] = {
    "LEARNING_NEW": "A new bidding strategy was created; adjusting for optimization",
    "LEARNING_SETTING_CHANGE": "Bidding strategy settings were changed; readjusting",
    "LEARNING_BUDGET_CHANGE": "Budget was changed; readjusting",
    "LEARNING_COMPOSITION_CHANGE": "Campaign structure (keywords, ad groups, etc.) was changed; readjusting",
    "LEARNING_CONVERSION_TYPE_CHANGE": "Conversion settings were changed; readjusting",
    "LEARNING_CONVERSION_SETTING_CHANGE": "Conversion settings were changed; readjusting",
}

# Smart bidding strategies (require conversion tracking)
_SMART_BIDDING_STRATEGIES: frozenset[str] = frozenset(
    {
        "MAXIMIZE_CONVERSIONS",
        "TARGET_CPA",
        "TARGET_ROAS",
        "MAXIMIZE_CONVERSION_VALUE",
    }
)


class _DiagnosticsMixin:
    """Mixin providing campaign diagnostics."""

    # Type declarations for attributes provided by parent class (GoogleAdsApiClient)
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...

    # Parent class methods (called by mixin)
    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
    async def list_ad_groups(  # type: ignore[empty-body]
        self, campaign_id: str = "", **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def get_performance_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]
    async def list_sitelinks(self, campaign_id: str) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]

    @staticmethod
    def _extract_bidding_details(campaign: Any) -> dict[str, Any]:
        """Extract specific bidding strategy parameters."""
        details: dict[str, Any] = {}
        strategy = map_bidding_strategy_type(campaign.bidding_strategy_type)
        details["strategy"] = strategy

        if strategy == "TARGET_IMPRESSION_SHARE":
            tis = campaign.target_impression_share
            loc_map = {
                0: "UNSPECIFIED",
                1: "UNKNOWN",
                2: "ANYWHERE_ON_PAGE",
                3: "TOP_OF_PAGE",
                4: "ABSOLUTE_TOP_OF_PAGE",
            }
            loc_val = (
                int(tis.location) if hasattr(tis.location, "__int__") else tis.location
            )
            details["location"] = loc_map.get(loc_val, str(loc_val))
            details["target_fraction_percent"] = tis.location_fraction_micros / 10_000
            details["cpc_bid_ceiling"] = tis.cpc_bid_ceiling_micros / 1_000_000
            # Detect configuration issues
            bid_issues: list[str] = []
            if tis.cpc_bid_ceiling_micros == 0:
                bid_issues.append("Max CPC=¥0: Cannot participate in auctions")
            if tis.location_fraction_micros == 0:
                bid_issues.append(
                    "Target impression share=0%: No display target is set"
                )
            if bid_issues:
                details["issue"] = "; ".join(bid_issues)
        elif strategy == "TARGET_CPA":
            details["target_cpa"] = campaign.target_cpa.target_cpa_micros / 1_000_000
        elif strategy == "MAXIMIZE_CONVERSIONS":
            optional_cpa = campaign.maximize_conversions.target_cpa_micros
            if optional_cpa:
                details["optional_target_cpa"] = optional_cpa / 1_000_000
        elif strategy == "MAXIMIZE_CLICKS":
            ts = campaign.target_spend
            ceiling = getattr(ts, "cpc_bid_ceiling_micros", 0)
            if ceiling:
                details["cpc_bid_ceiling"] = ceiling / 1_000_000
        elif strategy == "TARGET_ROAS":
            details["target_roas"] = campaign.target_roas.target_roas
        return details

    async def diagnose_campaign_delivery(self, campaign_id: str) -> dict[str, Any]:
        """Perform comprehensive campaign delivery diagnostics.

        Systematically check causes of non-delivery and return issues and recommended actions.
        """
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []

        # 1. Campaign basic information + bidding strategy details
        campaign_data = await self.get_campaign(campaign_id)
        if not campaign_data:
            return {"error": f"Campaign ID {campaign_id} not found"}

        result: dict[str, Any] = {
            "campaign": campaign_data,
        }

        # Status check
        if campaign_data["status"] != "ENABLED":
            issues.append(
                f"Campaign status is {campaign_data['status']}. "
                "Must be ENABLED for delivery"
            )
        serving_st = campaign_data.get("serving_status", "")
        if serving_st and serving_st != "SERVING":
            issues.append(f"Serving status is {serving_st} (not SERVING)")

        # --- NEW: primary_status / primary_status_reasons analysis ---
        primary_st = campaign_data.get("primary_status", "")
        if primary_st and primary_st != "ELIGIBLE":
            issues.append(
                f"Campaign primary_status is {primary_st} "
                "(non-ELIGIBLE may indicate delivery issues)"
            )

        primary_reasons: list[str] = campaign_data.get("primary_status_reasons", [])
        if primary_reasons:
            result["primary_status_reasons_detail"] = []
            for reason in primary_reasons:
                ja = _PRIMARY_STATUS_REASON_DESC.get(reason, reason)
                result["primary_status_reasons_detail"].append(
                    {"reason": reason, "description": ja}
                )
                if reason in _REASON_IS_ISSUE:
                    issues.append(f"[{reason}] {ja}")
                elif reason not in ("UNSPECIFIED", "UNKNOWN"):
                    warnings.append(f"[{reason}] {ja}")

        # --- NEW: Bidding strategy system status ---
        bidding_sys_st = campaign_data.get("bidding_strategy_system_status", "")
        if bidding_sys_st:
            if bidding_sys_st.startswith("MISCONFIGURED"):
                issues.append(
                    f"Bidding strategy system status is {bidding_sys_st}. "
                    "Please review bidding strategy settings"
                )
            elif bidding_sys_st.startswith("LEARNING"):
                # Display learning status prominently in a dedicated field
                learning_reason = _LEARNING_STATUS_DESC.get(
                    bidding_sys_st, "Bidding strategy is in learning phase"
                )
                result["learning_status"] = {
                    "status": bidding_sys_st,
                    "description": learning_reason,
                    "message": (
                        "⚠️ This campaign is currently in the [Learning Period].\n"
                        f"Reason: {learning_reason}\n"
                        "During the learning period (typically 1-2 weeks), avoid the following:\n"
                        "• Changing bidding strategy settings (target CPA/ROAS, etc.)\n"
                        "• Major budget changes (20% or more)\n"
                        "• Adding or removing large numbers of keywords\n"
                        "• Changing conversion settings\n"
                        "These changes may reset the learning phase and "
                        "potentially cause unstable performance."
                    ),
                }
                warnings.append(
                    f"Bidding strategy is in learning phase ({bidding_sys_st}). "
                    "We recommend waiting 1-2 weeks for stabilization"
                )
            elif bidding_sys_st.startswith("LIMITED"):
                warnings.append(f"Bidding strategy is limited ({bidding_sys_st})")

        # --- NEW: Campaign date range check ---
        today = date.today()
        start_date_str = campaign_data.get("start_date", "")
        end_date_str = campaign_data.get("end_date", "")
        if start_date_str:
            try:
                start_d = date.fromisoformat(start_date_str)
                if start_d > today:
                    issues.append(
                        f"Campaign start date is in the future ({start_date_str}). "
                        "Delivery will not begin until the start date"
                    )
            except ValueError:
                pass
        if end_date_str:
            try:
                end_d = date.fromisoformat(end_date_str)
                if end_d < today:
                    issues.append(
                        f"Campaign end date has passed ({end_date_str}). "
                        "Delivery has stopped"
                    )
            except ValueError:
                pass

        # Budget check
        budget_daily = campaign_data.get("budget_daily", 0)
        budget_status = campaign_data.get("budget_status", "")
        if budget_status != "ENABLED":
            issues.append(f"Budget status is {budget_status}")
        if budget_daily <= 0:
            issues.append("Daily budget is ¥0")

        # Bidding strategy check
        bidding = campaign_data.get("bidding_details", {})
        if bidding.get("issue"):
            issues.append(f"Bidding strategy issue: {bidding['issue']}")

        # 2. Ad group check
        ad_groups = await self.list_ad_groups(
            campaign_id=campaign_id, status_filter="ENABLED"
        )
        result["ad_groups_enabled_count"] = len(ad_groups)
        if not ad_groups:
            issues.append("No active ad groups")

        # 3. Keyword check (with system_serving_status)
        kw_query = f"""
            SELECT
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.approval_status,
                ad_group_criterion.system_serving_status
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD'
                AND campaign.id = {campaign_id}
                AND ad_group_criterion.status = 'ENABLED'
        """
        kw_response = await self._search(kw_query)  # type: ignore[attr-defined]
        enabled_kws = []
        rarely_served_kws: list[str] = []
        for row in kw_response:
            kw = row.ad_group_criterion
            approval = map_criterion_approval_status(kw.approval_status)
            sys_status = (
                str(kw.system_serving_status)
                if hasattr(kw, "system_serving_status")
                else ""
            )
            enabled_kws.append(
                {
                    "text": kw.keyword.text,
                    "match_type": str(kw.keyword.match_type),
                    "approval_status": approval,
                    "system_serving_status": sys_status,
                }
            )
            if "RARELY_SERVED" in sys_status:
                rarely_served_kws.append(kw.keyword.text)
        result["keywords_enabled_count"] = len(enabled_kws)
        disapproved_kws = [
            k for k in enabled_kws if k["approval_status"] == "DISAPPROVED"
        ]
        if not enabled_kws:
            issues.append("No active keywords")
        if disapproved_kws:
            warnings.append(
                f"{len(disapproved_kws)} keywords are disapproved: "
                + ", ".join(k["text"] for k in disapproved_kws[:5])
            )
        # --- NEW: RARELY_SERVED keyword detection ---
        if rarely_served_kws:
            warnings.append(
                f"{len(rarely_served_kws)} keywords are rarely being displayed"
                f"（RARELY_SERVED）: {', '.join(rarely_served_kws[:5])}"
            )

        # Keyword duplicate count + duplicate texts
        kw_texts = [k["text"].lower() for k in enabled_kws]
        seen: set[str] = set()
        duplicated: list[str] = []
        for t in kw_texts:
            if t in seen and t not in duplicated:
                duplicated.append(t)
            seen.add(t)
        result["keyword_duplicates_count"] = len(duplicated)
        result["keyword_duplicates"] = duplicated

        # 4. Ad check (including RSA and ad group-level aggregation)
        ad_query = f"""
            SELECT
                ad_group.id, ad_group.name,
                ad_group_ad.ad.id, ad_group_ad.ad.type,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad.responsive_search_ad.descriptions,
                ad_group_ad.ad.final_urls,
                ad_group_ad.status,
                ad_group_ad.policy_summary.approval_status,
                ad_group_ad.policy_summary.review_status
            FROM ad_group_ad
            WHERE campaign.id = {campaign_id}
                AND ad_group_ad.status = 'ENABLED'
        """
        ad_response = await self._search(ad_query)  # type: ignore[attr-defined]
        enabled_ads = []
        rsa_headline_counts: list[int] = []
        rsa_description_counts: list[int] = []
        rsa_headline_texts: list[str] = []
        rsa_description_texts: list[str] = []
        ad_group_ad_map: dict[str, dict[str, Any]] = {}
        final_urls_set: set[str] = set()
        for row in ad_response:
            ad = row.ad_group_ad
            approval = map_approval_status(ad.policy_summary.approval_status)
            review = map_review_status(ad.policy_summary.review_status)
            ad_type = map_ad_type(ad.ad.type_)
            enabled_ads.append(
                {
                    "ad_id": str(ad.ad.id),
                    "ad_type": ad_type,
                    "approval_status": approval,
                    "review_status": review,
                }
            )
            # Collect final_urls
            for url in list(getattr(ad.ad, "final_urls", [])):
                final_urls_set.add(str(url))
            # RSA headline/description count + text
            if ad_type == "RESPONSIVE_SEARCH_AD":
                headlines = list(getattr(ad.ad.responsive_search_ad, "headlines", []))
                descriptions = list(
                    getattr(ad.ad.responsive_search_ad, "descriptions", [])
                )
                rsa_headline_counts.append(len(headlines))
                rsa_description_counts.append(len(descriptions))
                for h in headlines:
                    text = getattr(h, "text", "")
                    if text and text not in rsa_headline_texts:
                        rsa_headline_texts.append(text)
                for d in descriptions:
                    text = getattr(d, "text", "")
                    if text and text not in rsa_description_texts:
                        rsa_description_texts.append(text)
            # Ad group-level aggregation
            ag_id = str(row.ad_group.id)
            ag_name = str(row.ad_group.name)
            if ag_id not in ad_group_ad_map:
                ad_group_ad_map[ag_id] = {
                    "ad_group_id": ag_id,
                    "name": ag_name,
                    "ad_count": 0,
                }
            ad_group_ad_map[ag_id]["ad_count"] += 1

        result["ads_enabled_count"] = len(enabled_ads)
        result["has_rsa"] = len(rsa_headline_counts) > 0
        result["rsa_min_headlines"] = (
            min(rsa_headline_counts) if rsa_headline_counts else 0
        )
        result["rsa_min_descriptions"] = (
            min(rsa_description_counts) if rsa_description_counts else 0
        )
        result["rsa_headline_texts"] = rsa_headline_texts
        result["rsa_description_texts"] = rsa_description_texts
        result["ad_final_urls"] = sorted(final_urls_set)
        result["ad_group_ad_counts"] = list(ad_group_ad_map.values())

        disapproved_ads = [
            a for a in enabled_ads if a["approval_status"] == "DISAPPROVED"
        ]
        limited_ads = [
            a for a in enabled_ads if a["approval_status"] == "APPROVED_LIMITED"
        ]
        if not enabled_ads:
            issues.append("No active ads")
        if disapproved_ads:
            issues.append(f"{len(disapproved_ads)} ads are disapproved")
        if limited_ads:
            warnings.append(
                f"{len(limited_ads)} ads have limited approval (APPROVED_LIMITED). "
                "They may not be shown to some audiences"
            )

        # 5. Location targeting check
        loc_query = f"""
            SELECT
                campaign_criterion.location.geo_target_constant,
                campaign_criterion.negative
            FROM campaign_criterion
            WHERE campaign.id = {campaign_id}
                AND campaign_criterion.type = 'LOCATION'
        """
        loc_response = await self._search(loc_query)  # type: ignore[attr-defined]
        locations = []
        for row in loc_response:
            cc = row.campaign_criterion
            locations.append(
                {
                    "geo_target": str(cc.location.geo_target_constant),
                    "negative": bool(cc.negative),
                }
            )
        result["location_targeting_count"] = len(locations)
        if not locations:
            warnings.append(
                "No location targeting set (worldwide). "
                "If targeting Japan only, set geoTargetConstants/2392 (Japan)"
            )

        # 6. Performance (last 30 days)
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_30_DAYS"
            )
            if perf:
                result["performance_last_30_days"] = perf[0].get("metrics", {})
            else:
                result["performance_last_30_days"] = {
                    "impressions": 0,
                    "clicks": 0,
                    "cost": 0,
                }
        except Exception:
            result["performance_last_30_days"] = "Retrieval failed"

        # 7. Sitelink count
        try:
            sitelinks = await self.list_sitelinks(campaign_id)
            result["sitelinks_count"] = len(sitelinks)
        except Exception:
            logger.debug("Failed to retrieve sitelink count", exc_info=True)
            result["sitelinks_count"] = 0

        # 8. Billing setup check
        try:
            billing_query = """
                SELECT billing_setup.id, billing_setup.status
                FROM billing_setup
                WHERE billing_setup.status = 'APPROVED'
            """
            billing_response = await self._search(billing_query)  # type: ignore[attr-defined]
            has_billing = any(True for _ in billing_response)
            result["billing_setup"] = "APPROVED" if has_billing else "Not configured"
            if not has_billing:
                issues.append(
                    "No active billing setup. "
                    "Please configure a payment method in Google Ads dashboard"
                )
        except Exception:
            result["billing_setup"] = "Verification failed"

        # --- NEW: 8. Conversion tracking check (smart bidding only) ---
        strategy = bidding.get("strategy", "")
        if strategy in _SMART_BIDDING_STRATEGIES:
            try:
                cv_query = """
                    SELECT
                        conversion_action.id,
                        conversion_action.status
                    FROM conversion_action
                    WHERE conversion_action.status = 'ENABLED'
                """
                cv_response = await self._search(cv_query)  # type: ignore[attr-defined]
                active_cv_count = sum(1 for _ in cv_response)
                result["active_conversion_actions"] = active_cv_count
                if active_cv_count == 0:
                    issues.append(
                        f"Using smart bidding ({strategy}), but "
                        "there are 0 active conversion actions. "
                        "Please configure conversion tracking"
                    )
            except Exception:
                result["active_conversion_actions"] = "Verification failed"

        # --- Conversion action performance (last 30 days) ---
        # cost_per_conversion cannot be fetched simultaneously with segments.conversion_action_name,
        # so fetch campaign total cost separately and calculate CPA by CV proportion
        try:
            cv_by_action_query = f"""
                SELECT
                    segments.conversion_action_name,
                    metrics.conversions,
                    metrics.conversions_value
                FROM campaign
                WHERE campaign.id = {campaign_id}
                    AND segments.date DURING LAST_30_DAYS
                    AND metrics.conversions > 0
            """
            cv_by_action_response = await self._search(cv_by_action_query)  # type: ignore[attr-defined]

            # Get campaign total cost and CV count for CPA calculation
            total_cost = float(
                result.get("performance_last_30_days", {}).get("cost", 0)
            )
            total_cv = float(
                result.get("performance_last_30_days", {}).get("conversions", 0)
            )
            campaign_cpa = total_cost / total_cv if total_cv > 0 else 0

            conversion_actions_detail: list[dict[str, Any]] = []
            for row in cv_by_action_response:
                action_name = str(getattr(row.segments, "conversion_action_name", ""))
                conversions = float(row.metrics.conversions)
                # Estimate CPA by CV proportion
                action_cpa = campaign_cpa if total_cv > 0 else 0
                conversion_actions_detail.append(
                    {
                        "name": action_name,
                        "conversions": conversions,
                        "conversions_value": float(
                            getattr(row.metrics, "conversions_value", 0)
                        ),
                        "cost_per_conversion": round(action_cpa, 0),
                    }
                )
            # Sort by CV count descending
            conversion_actions_detail.sort(key=lambda x: x["conversions"], reverse=True)
            result["conversion_actions_detail"] = conversion_actions_detail
        except Exception:
            logger.debug(
                "Failed to retrieve conversion action performance", exc_info=True
            )
            result["conversion_actions_detail"] = []

        # --- NEW: 9. Impression share check ---
        try:
            is_query = f"""
                SELECT
                    metrics.search_impression_share,
                    metrics.search_rank_lost_impression_share,
                    metrics.search_budget_lost_impression_share
                FROM campaign
                WHERE campaign.id = {campaign_id}
                    AND segments.date DURING LAST_30_DAYS
            """
            is_response = await self._search(is_query)  # type: ignore[attr-defined]
            for row in is_response:
                m = row.metrics
                is_data: dict[str, Any] = {}
                search_is = getattr(m, "search_impression_share", None)
                if search_is is not None:
                    is_data["search_impression_share"] = round(
                        float(search_is) * 100, 1
                    )
                rank_lost = getattr(m, "search_rank_lost_impression_share", None)
                if rank_lost is not None:
                    is_data["rank_lost_pct"] = round(float(rank_lost) * 100, 1)
                budget_lost = getattr(m, "search_budget_lost_impression_share", None)
                if budget_lost is not None:
                    is_data["budget_lost_pct"] = round(float(budget_lost) * 100, 1)
                if is_data:
                    result["impression_share"] = is_data
                    if is_data.get("budget_lost_pct", 0) > 20:
                        warnings.append(
                            f"Missing {is_data['budget_lost_pct']}% "
                            f"of impressions due to budget constraints"
                        )
                    if is_data.get("rank_lost_pct", 0) > 30:
                        warnings.append(
                            f"Missing {is_data['rank_lost_pct']}% "
                            f"of impressions due to insufficient ad rank"
                        )
                break  # First row only
        except Exception:
            logger.debug("Failed to retrieve impression share", exc_info=True)

        # Generate recommended actions
        if bidding.get("strategy") == "TARGET_IMPRESSION_SHARE":
            if bidding.get("cpc_bid_ceiling", 0) == 0:
                recommendations.append(
                    "Set a max CPC for the bidding strategy (e.g., ¥500-¥2,000). "
                    "¥0 prevents auction participation"
                )
            if bidding.get("target_fraction_percent", 0) == 0:
                recommendations.append("Set a target impression share (e.g., 50%-80%)")
            if bidding.get("location", "UNSPECIFIED") == "UNSPECIFIED":
                recommendations.append(
                    "Specify ad placement (ANYWHERE_ON_PAGE / TOP_OF_PAGE / "
                    "ABSOLUTE_TOP_OF_PAGE)"
                )
        if not locations:
            recommendations.append(
                "Add Japan (geoTargetConstants/2392) to location targeting"
            )

        # --- NEW: Recommended actions based on primary_status_reasons ---
        for reason in primary_reasons:
            if reason == "BIDDING_STRATEGY_MISCONFIGURED":
                recommendations.append(
                    "Please review bidding strategy settings. "
                    "Use campaigns.get to check detailed parameters and "
                    "verify that required parameters such as max CPC and target CPA are configured"
                )
            elif reason == "BUDGET_CONSTRAINED":
                recommendations.append(
                    "Consider increasing the daily budget. "
                    "The current budget is missing impression opportunities. "
                    "Use budget.update to adjust the budget"
                )
            elif reason == "SEARCH_VOLUME_LIMITED":
                recommendations.append(
                    "Consider adding keywords or changing match types. "
                    "Switching to broad match or adding related keywords can expand search volume"
                )
            elif reason == "HAS_ADS_DISAPPROVED":
                recommendations.append(
                    "Check and fix disapproved ads. "
                    "Use ads.policy to check disapproval reasons and revise to comply with policies"
                )

        # Smart bidding + no CV configured recommended action
        if (
            strategy in _SMART_BIDDING_STRATEGIES
            and result.get("active_conversion_actions") == 0
        ):
            recommendations.append(
                "Please configure conversion actions. "
                "You can set them up from Tools > Conversions in the Google Ads dashboard. "
                "After configuration, install tags via Google Tag Manager or similar"
            )

        result["issues"] = issues
        result["warnings"] = warnings
        result["recommendations"] = recommendations
        result["diagnosis"] = (
            "No issues" if not issues else f"{len(issues)} issues found"
        )
        return result
