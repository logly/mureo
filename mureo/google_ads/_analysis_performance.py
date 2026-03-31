"""Performance analysis and cost investigation mixin."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._analysis_constants import (
    _calc_change_rate,
    _get_comparison_date_ranges,
    _safe_metrics,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _PerformanceAnalysisMixin:
    """Mixin providing performance analysis and cost investigation methods."""

    # Type declarations for attributes/methods provided by parent class (GoogleAdsApiClient)
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...
    def _period_to_date_clause(self, period: str) -> str: ...  # type: ignore[empty-body]

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
    async def list_campaigns(  # type: ignore[empty-body]
        self, status_filter: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def get_performance_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]
    async def get_search_terms_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]
    async def list_recommendations(  # type: ignore[empty-body]
        self, campaign_id: str | None = None, recommendation_type: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def list_change_history(  # type: ignore[empty-body]
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def list_negative_keywords(  # type: ignore[empty-body]
        self, campaign_id: str
    ) -> list[dict[str, Any]]: ...
    async def get_ad_performance_report(  # type: ignore[empty-body]
        self,
        ad_group_id: str | None = None,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]: ...

    # =================================================================
    # Target CPA resolution helper
    # =================================================================

    async def _resolve_target_cpa(
        self,
        campaign_id: str,
        explicit: float | None = None,
    ) -> tuple[float | None, str]:
        """Resolve target CPA.

        Priority: argument -> bidding strategy (target_cpa) -> actual CPA (cost/conversions)

        Returns:
            (cpa_value, source_type: "explicit"|"bidding_strategy"|"actual"|"none")
        """
        if explicit is not None:
            return explicit, "explicit"

        # Retrieve from bidding strategy
        try:
            campaign = await self.get_campaign(campaign_id)
            if campaign:
                bidding = campaign.get("bidding_details") or {}
                target_cpa = bidding.get("target_cpa")
                if target_cpa is None:
                    target_cpa = None
                if target_cpa is not None and target_cpa > 0:
                    return float(target_cpa), "bidding_strategy"
        except Exception:
            logger.debug(
                "Failed to retrieve target CPA from bidding strategy: %s", campaign_id
            )

        # Calculate from actual CPA
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_30_DAYS"
            )
            m = _safe_metrics(perf)
            cost = float(m.get("cost", 0))
            convs = float(m.get("conversions", 0))
            if convs > 0:
                return round(cost / convs, 0), "actual"
        except Exception:
            logger.debug("Failed to calculate actual CPA: %s", campaign_id)

        return None, "none"

    # =================================================================
    # Common helpers
    # =================================================================

    async def _fetch_performance_comparison(
        self,
        campaign_id: str,
        period: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, float | None]]:
        """Retrieve current and previous period performance and calculate change rates.

        Returns:
            (current_metrics, previous_metrics, changes_pct)
        """
        current_period, previous_period = _get_comparison_date_ranges(period)
        current_perf = await self.get_performance_report(
            campaign_id=campaign_id, period=current_period
        )
        previous_perf = await self.get_performance_report(
            campaign_id=campaign_id, period=previous_period
        )
        current_m = _safe_metrics(current_perf)
        previous_m = _safe_metrics(previous_perf)

        changes: dict[str, float | None] = {}
        for key in ("impressions", "clicks", "cost", "conversions"):
            cur = float(current_m.get(key, 0))
            prev = float(previous_m.get(key, 0))
            changes[f"{key}_change_pct"] = _calc_change_rate(cur, prev)

        return current_m, previous_m, changes

    @staticmethod
    def _generate_performance_insights(
        changes: dict[str, float | None],
        current_m: dict[str, Any],
        previous_m: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        """Generate insights and CPA information from performance change rates."""
        insights: list[str] = []
        cpa_info: dict[str, Any] = {}

        imp_change = changes.get("impressions_change_pct")
        if imp_change is not None and imp_change < -20:
            insights.append(
                f"Impressions decreased {imp_change}% compared to previous period"
            )
        click_change = changes.get("clicks_change_pct")
        if click_change is not None and click_change < -20:
            insights.append(
                f"Clicks decreased {click_change}% compared to previous period"
            )
        cost_change = changes.get("cost_change_pct")
        if cost_change is not None and cost_change > 30:
            insights.append(
                f"Ad spend increased {cost_change}% compared to previous period"
            )
        conv_change = changes.get("conversions_change_pct")
        if conv_change is not None and conv_change < -20:
            insights.append(
                f"Conversions decreased {conv_change}% compared to previous period"
            )

        # CPA comparison
        cur_cost = float(current_m.get("cost", 0))
        cur_conv = float(current_m.get("conversions", 0))
        prev_cost = float(previous_m.get("cost", 0))
        prev_conv = float(previous_m.get("conversions", 0))
        cur_cpa = cur_cost / cur_conv if cur_conv > 0 else None
        prev_cpa = prev_cost / prev_conv if prev_conv > 0 else None
        if cur_cpa is not None:
            cpa_info["cpa_current"] = round(cur_cpa, 0)
        if prev_cpa is not None:
            cpa_info["cpa_previous"] = round(prev_cpa, 0)
        if cur_cpa is not None and prev_cpa is not None:
            cpa_change = _calc_change_rate(cur_cpa, prev_cpa)
            cpa_info["cpa_change_pct"] = cpa_change
            if cpa_change is not None and cpa_change > 20:
                insights.append(
                    f"CPA deteriorated {cpa_change}% compared to previous period"
                )

        return insights, cpa_info

    async def _analyze_search_term_changes(
        self,
        campaign_id: str,
    ) -> dict[str, Any]:
        """Analyze search term changes and identify new and wasteful terms."""
        current_period, previous_period = _get_comparison_date_ranges("LAST_7_DAYS")
        current_terms = await self.get_search_terms_report(
            campaign_id=campaign_id, period=current_period
        )
        previous_terms = await self.get_search_terms_report(
            campaign_id=campaign_id, period=previous_period
        )

        # Identify search terms not present in previous period
        prev_term_set = {t.get("search_term", "") for t in previous_terms}
        new_terms = [
            t for t in current_terms if t.get("search_term", "") not in prev_term_set
        ]
        new_terms_sorted = sorted(
            new_terms,
            key=lambda x: x.get("metrics", {}).get("cost", 0),
            reverse=True,
        )

        # Extract high-cost terms with no conversions as candidates
        wasteful_terms = [
            t
            for t in current_terms
            if t.get("metrics", {}).get("cost", 0) > 0
            and t.get("metrics", {}).get("conversions", 0) == 0
        ]
        wasteful_sorted = sorted(
            wasteful_terms,
            key=lambda x: x.get("metrics", {}).get("cost", 0),
            reverse=True,
        )

        finding = None
        if new_terms_sorted:
            total_new_cost = sum(
                t.get("metrics", {}).get("cost", 0) for t in new_terms_sorted
            )
            finding = (
                f"{len(new_terms)} new search terms found, "
                f"with a total cost of ¥{total_new_cost:,.0f}"
            )

        return {
            "new_search_terms": new_terms_sorted[:20],
            "wasteful_search_terms": wasteful_sorted[:20],
            "finding": finding,
        }

    # =================================================================
    # 1. Comprehensive performance analysis
    # =================================================================

    async def analyze_performance(
        self,
        campaign_id: str,
        period: str = "LAST_7_DAYS",
    ) -> dict[str, Any]:
        """Perform comprehensive campaign performance analysis."""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        insights: list[str] = []
        recs: list[str] = []

        result: dict[str, Any] = {"campaign_id": campaign_id, "period": period}

        # 1. Campaign basic info
        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"Campaign ID {campaign_id} not found"}
        result["campaign"] = campaign
        if campaign.get("status") != "ENABLED":
            issues.append(f"Campaign status is {campaign.get('status')}")

        # 2. Performance comparison (current vs previous, non-overlapping periods)
        try:
            current_m, previous_m, changes = await self._fetch_performance_comparison(
                campaign_id, period
            )
            result["performance_current"] = current_m
            result["performance_previous"] = previous_m
            result["changes"] = changes
            perf_insights, cpa_info = self._generate_performance_insights(
                changes, current_m, previous_m
            )
            insights.extend(perf_insights)
            result.update(cpa_info)
        except Exception:
            logger.warning("Failed to retrieve performance comparison", exc_info=True)
            result["performance_current"] = "Retrieval failed"

        # 3. Top 20 search terms
        try:
            search_terms = await self.get_search_terms_report(
                campaign_id=campaign_id, period=period
            )
            sorted_terms = sorted(
                search_terms,
                key=lambda x: x.get("metrics", {}).get("cost", 0),
                reverse=True,
            )
            result["top_search_terms"] = sorted_terms[:20]
        except Exception:
            logger.warning("Failed to retrieve search terms report", exc_info=True)
            result["top_search_terms"] = "Retrieval failed"

        # 4. Google recommendations
        try:
            recommendations = await self.list_recommendations(campaign_id=campaign_id)
            result["recommendations_from_google"] = recommendations[:10]
            if recommendations:
                recs.append(f"Google has {len(recommendations)} recommendations")
        except Exception:
            logger.warning("Failed to retrieve recommendations", exc_info=True)
            result["recommendations_from_google"] = "Retrieval failed"

        # 5. Recent change history
        try:
            changes_history = await self.list_change_history()
            result["recent_changes"] = changes_history[:10]
        except Exception:
            logger.warning("Failed to retrieve change history", exc_info=True)
            result["recent_changes"] = "Retrieval failed"

        # 6. Analysis summary
        result["issues"] = issues
        result["insights"] = insights
        result["recommendations"] = recs
        return result

    # =================================================================
    # 2. Ad spend increase / CPA deterioration investigation
    # =================================================================

    async def investigate_cost_increase(
        self,
        campaign_id: str,
    ) -> dict[str, Any]:
        """Investigate causes of ad spend increase and CPA deterioration."""
        self._validate_id(campaign_id, "campaign_id")
        findings: list[str] = []
        actions: list[str] = []

        result: dict[str, Any] = {"campaign_id": campaign_id}

        # 1. 7-day vs prior 7-day performance comparison (non-overlapping)
        current_m: dict[str, Any] = {}
        previous_m: dict[str, Any] = {}
        changes: dict[str, float | None] = {}
        try:
            current_m, previous_m, changes = await self._fetch_performance_comparison(
                campaign_id, "LAST_7_DAYS"
            )
            result["performance_current_7d"] = current_m
            result["performance_previous_7d"] = previous_m
            result["changes"] = changes
        except Exception:
            logger.warning("Failed to retrieve performance comparison", exc_info=True)
            result["performance_current_7d"] = "Retrieval failed"

        # 2. Cost increase breakdown (CPC increase vs click increase)
        cost_breakdown, breakdown_findings, cpc_change, clicks_change = (
            self._build_cost_breakdown(current_m, previous_m)
        )
        result["cost_breakdown"] = cost_breakdown
        findings.extend(breakdown_findings)

        # 3. Search term change analysis
        try:
            term_analysis = await self._analyze_search_term_changes(campaign_id)
            result["new_search_terms"] = term_analysis["new_search_terms"]
            result["wasteful_search_terms"] = term_analysis["wasteful_search_terms"]
            if term_analysis["finding"]:
                findings.append(term_analysis["finding"])
        except Exception:
            logger.warning("Search term analysis failed", exc_info=True)
            result["new_search_terms"] = "Retrieval failed"
            result["wasteful_search_terms"] = "Retrieval failed"

        # 4. Bid and budget change history
        try:
            change_history = await self.list_change_history()
            bid_budget_changes = [
                c
                for c in change_history
                if c.get("resource_type", "")
                in (
                    "CAMPAIGN_BUDGET",
                    "CAMPAIGN",
                    "AD_GROUP",
                    "CAMPAIGN_BID_MODIFIER",
                )
            ]
            result["bid_budget_changes"] = bid_budget_changes[:10]
            if bid_budget_changes:
                findings.append(
                    f"There are {len(bid_budget_changes)} recent bid/budget-related changes"
                )
        except Exception:
            logger.warning("Failed to retrieve change history", exc_info=True)
            result["bid_budget_changes"] = "Retrieval failed"

        # 5. Negative keyword candidates
        await self._find_negative_keyword_candidates(campaign_id, result, actions)

        # Summary
        if cpc_change is not None and cpc_change > 10:
            actions.append("Consider reviewing bidding strategy or adjusting max CPC")

        result["findings"] = findings
        result["recommended_actions"] = actions
        return result

    @staticmethod
    def _build_cost_breakdown(
        current_m: dict[str, Any],
        previous_m: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str], float | None, float | None]:
        """Build cost breakdown (CPC vs click volume changes).

        Returns:
            (cost_breakdown, findings, cpc_change, clicks_change)
        """
        cur_cpc = float(current_m.get("average_cpc", 0))
        prev_cpc = float(previous_m.get("average_cpc", 0))
        cur_clicks = float(current_m.get("clicks", 0))
        prev_clicks = float(previous_m.get("clicks", 0))

        cpc_change = _calc_change_rate(cur_cpc, prev_cpc)
        clicks_change = _calc_change_rate(cur_clicks, prev_clicks)

        cost_breakdown = {
            "cpc_current": cur_cpc,
            "cpc_previous": prev_cpc,
            "cpc_change_pct": cpc_change,
            "clicks_current": cur_clicks,
            "clicks_previous": prev_clicks,
            "clicks_change_pct": clicks_change,
        }

        findings: list[str] = []
        if cpc_change is not None and cpc_change > 10:
            findings.append(
                f"Average CPC increased {cpc_change}%. "
                "This may be due to increased competitor bidding or changes in auction environment"
            )
        if clicks_change is not None and clicks_change > 20:
            findings.append(
                f"Clicks increased {clicks_change}%. "
                "This may be due to broader search terms or new incoming queries"
            )
        return cost_breakdown, findings, cpc_change, clicks_change

    async def _find_negative_keyword_candidates(
        self,
        campaign_id: str,
        result: dict[str, Any],
        actions: list[str],
    ) -> None:
        """Identify negative keyword candidates."""
        try:
            existing_negatives = await self.list_negative_keywords(campaign_id)
            existing_neg_texts = {n.get("text", "").lower() for n in existing_negatives}
            result["existing_negative_keywords_count"] = len(existing_negatives)

            if isinstance(result.get("wasteful_search_terms"), list):
                neg_candidates = [
                    t
                    for t in result["wasteful_search_terms"]
                    if t.get("search_term", "").lower() not in existing_neg_texts
                ]
                result["negative_keyword_candidates"] = neg_candidates[:10]
                if neg_candidates:
                    actions.append(
                        f"There are {len(neg_candidates)} search terms with cost but no conversions. "
                        "Consider adding them as negative keywords"
                    )
        except Exception:
            logger.warning("Negative keyword analysis failed", exc_info=True)
            result["negative_keyword_candidates"] = "Retrieval failed"

    # =================================================================
    # 3. Cross-campaign health check
    # =================================================================

    async def health_check_all_campaigns(self) -> dict[str, Any]:
        """Perform cross-campaign health check."""
        # --- 1. All campaigns list ---
        campaigns = await self.list_campaigns()
        result: dict[str, Any] = {
            "total_campaigns": len(campaigns),
        }

        # Only ENABLED campaigns
        enabled = [c for c in campaigns if c.get("status") == "ENABLED"]
        paused = [c for c in campaigns if c.get("status") == "PAUSED"]
        removed = [c for c in campaigns if c.get("status") == "REMOVED"]

        result["enabled_count"] = len(enabled)
        result["paused_count"] = len(paused)
        result["removed_count"] = len(removed)

        # --- 2. Classification by primary_status ---
        healthy: list[dict[str, Any]] = []
        warning: list[dict[str, Any]] = []
        problem: list[dict[str, Any]] = []

        for camp in enabled:
            primary_status = camp.get("primary_status", "")
            camp_summary = {
                "campaign_id": camp.get("id", ""),
                "name": camp.get("name", ""),
                "primary_status": primary_status,
            }
            if primary_status == "ELIGIBLE":
                healthy.append(camp_summary)
            elif primary_status in ("NOT_ELIGIBLE", "ENDED", "REMOVED"):
                problem.append(camp_summary)
            else:
                warning.append(camp_summary)

        result["healthy_campaigns"] = healthy
        result["warning_campaigns"] = warning
        result["problem_campaigns"] = problem

        # --- 3. Detailed diagnostics for problem campaigns ---
        targets = (problem + warning)[:5]
        detailed_diagnostics: list[dict[str, Any]] = []
        for camp_summary in targets:
            cid = str(camp_summary["campaign_id"])
            try:
                diag = await self.diagnose_campaign_delivery(cid)  # type: ignore[attr-defined]
                detailed_diagnostics.append(
                    {
                        "campaign_id": cid,
                        "name": camp_summary["name"],
                        "issues": diag.get("issues", []),
                        "warnings": diag.get("warnings", []),
                        "recommendations": diag.get("recommendations", []),
                    }
                )
            except Exception:
                logger.warning(
                    "Failed to run detailed diagnostics for campaign %s",
                    cid,
                    exc_info=True,
                )
                detailed_diagnostics.append(
                    {
                        "campaign_id": cid,
                        "name": camp_summary["name"],
                        "error": "Detailed diagnostics retrieval failed",
                    }
                )
        result["detailed_diagnostics"] = detailed_diagnostics

        # --- 4. Cross-campaign summary ---
        result["summary"] = {
            "total_enabled": len(enabled),
            "healthy": len(healthy),
            "warning": len(warning),
            "problem": len(problem),
        }

        if problem:
            result["summary"]["message"] = (
                f"{len(problem)} campaigns have problems. "
                "Please review detailed diagnostics"
            )
        elif warning:
            result["summary"]["message"] = f"{len(warning)} campaigns have warnings"
        else:
            result["summary"]["message"] = "All campaigns are operating normally"

        return result

    # =================================================================
    # Ad A/B comparison
    # =================================================================

    async def compare_ad_performance(
        self,
        ad_group_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """Compare ad performance within an ad group."""
        self._validate_id(ad_group_id, "ad_group_id")

        ad_perf = await self.get_ad_performance_report(
            ad_group_id=ad_group_id, period=period
        )

        # Only ENABLED ads
        enabled_ads = [a for a in ad_perf if a.get("status") == "ENABLED"]

        ads_data: list[dict[str, Any]] = []
        for a in enabled_ads:
            m = a.get("metrics", {})
            impressions = int(m.get("impressions", 0))
            clicks = int(m.get("clicks", 0))
            conversions = float(m.get("conversions", 0))
            cost = float(m.get("cost", 0))

            ctr = clicks / impressions if impressions > 0 else 0.0
            cvr = conversions / clicks if clicks > 0 else 0.0
            cpa = cost / conversions if conversions > 0 else None

            # Score: ctr*cvr if CV exists, otherwise ctr only
            score = ctr * cvr if conversions > 0 else ctr

            entry: dict[str, Any] = {
                "ad_id": a.get("ad_id", ""),
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
                "cost": cost,
                "ctr": round(ctr, 4),
                "cvr": round(cvr, 4),
                "cpa": round(cpa, 0) if cpa is not None else None,
                "score": round(score, 6),
            }
            # Include RSA information if available
            if "headlines" in a:
                entry["headlines"] = a["headlines"]
            if "descriptions" in a:
                entry["descriptions"] = a["descriptions"]
            ads_data.append(entry)

        # Sort by score and assign rank/verdict
        sorted_ads = sorted(ads_data, key=lambda x: x["score"], reverse=True)
        best_score = sorted_ads[0]["score"] if sorted_ads else 0.0
        ranked_ads: list[dict[str, Any]] = []
        for rank, ad in enumerate(sorted_ads, start=1):
            if ad["impressions"] < 100:
                verdict = "INSUFFICIENT_DATA"
            elif ad["score"] == best_score:
                verdict = "WINNER"
            else:
                verdict = "LOSER"
            ranked_ads.append({**ad, "rank": rank, "verdict": verdict})

        winner = next((a for a in ranked_ads if a.get("verdict") == "WINNER"), None)

        # Recommended action
        if len(ads_data) < 2:
            recommendation = (
                "Not enough ads for comparison. " "Please add more ads for A/B testing"
            )
        elif winner:
            recommendation = (
                f"Ad {winner['ad_id']} has the best performance. "
                "We recommend pausing LOSER ads and testing new variations"
            )
        else:
            recommendation = (
                "Continue testing until sufficient data has been accumulated"
            )

        # Insights
        insights: list[str] = []
        insufficient = [
            a for a in ranked_ads if a.get("verdict") == "INSUFFICIENT_DATA"
        ]
        if insufficient:
            insights.append(
                f"{len(insufficient)} ads have insufficient data "
                "(less than 100 impressions)"
            )
        losers = [a for a in ranked_ads if a.get("verdict") == "LOSER"]
        if losers and winner:
            insights.append(
                f"WINNER (ad {winner['ad_id']}) has a CTR of {winner['ctr']:.2%}, "
                f"outperforming {len(losers)} other ads"
            )

        return {
            "ad_group_id": ad_group_id,
            "period": period,
            "ads": ranked_ads,
            "winner": winner,
            "recommendation": recommendation,
            "insights": insights,
        }
