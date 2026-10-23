from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._enum_names import SMART_BIDDING_STRATEGIES

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)

#: Funnel bottlenecks that are critical, and the issue each one reports.
_FUNNEL_ISSUES = {
    "no_delivery": "Impressions in the last 7 days are 0",
    "no_clicks": "Clicks in the last 7 days are 0",
}


class _MonitoringMixin:
    """Mixin providing monitoring target evaluation macro tools."""

    # Type declarations for attributes/methods provided by parent class (GoogleAdsApiClient)
    # Not present at runtime (placed inside TYPE_CHECKING to avoid overriding implementations via MRO)
    if TYPE_CHECKING:
        _customer_id: str
        _client: GoogleAdsClient

        @staticmethod
        def _validate_id(value: str, field_name: str) -> str: ...
        async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
        async def get_performance_report(
            self, **kwargs: Any
        ) -> list[dict[str, Any]]: ...
        async def diagnose_campaign_delivery(
            self, campaign_id: str
        ) -> dict[str, Any]: ...
        async def analyze_performance(
            self, campaign_id: str, period: str = "LAST_7_DAYS"
        ) -> dict[str, Any]: ...
        async def investigate_cost_increase(
            self, campaign_id: str
        ) -> dict[str, Any]: ...
        async def get_search_terms_report(
            self, **kwargs: Any
        ) -> list[dict[str, Any]]: ...
        async def list_conversion_actions(self) -> list[dict[str, Any]]: ...

    # =================================================================
    # 1. Delivery goal evaluation
    # =================================================================

    async def evaluate_delivery_goal(self, campaign_id: str) -> dict[str, Any]:
        """Evaluate delivery goal by integrating delivery status and performance."""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        result: dict[str, Any] = {"campaign_id": campaign_id}

        # 1. Campaign basic information
        campaign: dict[str, Any] | None = None
        campaign_read = True
        try:
            campaign = await self.get_campaign(campaign_id)
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            # Class name only. A traceback would print the GoogleAdsException
            # repr, which carries the request metadata (developer token,
            # authorization header) — see mureo/google_ads/accounts.py for the
            # full reasoning (#603).
            logger.warning(
                "Failed to retrieve campaign information (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve campaign information")
            campaign_read = False
        result["campaign"] = campaign

        # 2. Delivery diagnostics
        diagnosis: dict[str, Any] | None = None
        try:
            diagnosis = await self.diagnose_campaign_delivery(campaign_id)
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve delivery diagnostics (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve delivery diagnostics")
        result["diagnosis"] = diagnosis

        # 3. Previous day performance
        performance: list[dict[str, Any]] | None = None
        try:
            performance = await self.get_performance_report(
                campaign_id=campaign_id, period="YESTERDAY"
            )
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve previous day performance (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve previous day performance")
        result["performance"] = performance

        # Extract metrics; unknown (None) when the read failed, not 0
        metrics = performance[0].get("metrics", {}) if performance else {}
        impressions = (
            int(metrics.get("impressions", 0)) if performance is not None else None
        )

        # Status determination
        has_issues = bool((diagnosis or {}).get("issues"))
        has_warnings = bool((diagnosis or {}).get("warnings"))
        campaign_status = (campaign or {}).get("status", "")

        if has_issues:
            issues.append("Issues detected in delivery diagnostics")
        if campaign_status and campaign_status != "ENABLED":
            issues.append(f"Campaign status is {campaign_status}")
        if impressions == 0:
            issues.append("Yesterday's impressions are 0")

        is_critical = (
            has_issues
            or (campaign_status and campaign_status != "ENABLED")
            or impressions == 0
        )
        is_warning = has_warnings or (
            not is_critical and impressions is not None and 0 < impressions < 10
        )
        all_read = campaign_read and diagnosis is not None and performance is not None

        if is_critical:
            status = "critical"
        elif not all_read:
            # Nothing read proves a problem, and a failed read hides any.
            status = "unknown"
        elif is_warning:
            status = "warning"
            if has_warnings:
                issues.append("Warnings detected in delivery diagnostics")
        else:
            status = "healthy"

        result["status"] = status
        result["issues"] = issues

        if status in ("critical", "warning"):
            result["suggested_workflow"] = "delivery_fix"

        # Summary generation
        if status == "critical":
            result["summary"] = (
                f"Campaign {campaign_id} has critical delivery issues. "
                f"Issues detected: {', '.join(issues)}"
            )
        elif status == "warning":
            result["summary"] = (
                f"Campaign {campaign_id} delivery needs attention. "
                f"Warnings detected: {', '.join(issues)}"
            )
        elif status == "unknown":
            result["summary"] = (
                f"Campaign {campaign_id} delivery could not be evaluated. "
                f"Issues: {', '.join(issues)}"
            )
        else:
            result["summary"] = (
                f"Campaign {campaign_id} delivery is operating normally. "
                f"Previous day impressions: {impressions:,}"
            )

        return result

    # =================================================================
    # 2. CPA goal evaluation
    # =================================================================

    async def evaluate_cpa_goal(
        self, campaign_id: str, target_cpa: float
    ) -> dict[str, Any]:
        """Evaluate current performance against CPA target."""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        result: dict[str, Any] = {
            "campaign_id": campaign_id,
            "target_cpa": target_cpa,
        }

        # 1. Last 7 days performance
        perf: list[dict[str, Any]] | None = None
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_7_DAYS"
            )
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve performance report (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve performance report")

        metrics = perf[0].get("metrics", {}) if perf else {}
        cost = float(metrics.get("cost", 0))
        conversions = float(metrics.get("conversions", 0))

        # 2. Calculate CPA (unknown, not "0 conversions", when the read failed)
        current_cpa: float | None = None
        if conversions > 0:
            current_cpa = round(cost / conversions, 1)
        elif perf is not None:
            issues.append(
                "Cannot calculate CPA because there are 0 conversions in the last 7 days"
            )
        result["current_cpa"] = current_cpa

        # 3. Cost analysis
        cost_analysis: dict[str, Any] | None = None
        try:
            cost_analysis = await self.investigate_cost_increase(campaign_id)
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning("Failed to retrieve cost analysis (%s)", type(exc).__name__)
            issues.append("Failed to retrieve cost analysis")
        result["cost_analysis"] = cost_analysis

        # Wasteful search terms (top 5), null when the cost analysis failed
        if cost_analysis is None:
            result["wasteful_terms"] = None
        else:
            wasteful_terms = cost_analysis.get("wasteful_search_terms", [])
            is_list = isinstance(wasteful_terms, list)
            result["wasteful_terms"] = wasteful_terms[:5] if is_list else []

        # 4. Calculate deviation rate and determine status
        if current_cpa is not None:
            deviation_pct = round((current_cpa - target_cpa) / target_cpa * 100, 1)
            result["deviation_pct"] = deviation_pct

            if current_cpa <= target_cpa:
                status = "healthy"
            elif current_cpa <= target_cpa * 1.2:
                status = "warning"
                issues.append(
                    f"CPA exceeds target by {deviation_pct}%"
                    f" (current: {current_cpa:,.0f} / target: {target_cpa:,.0f})"
                )
            else:
                status = "critical"
                issues.append(
                    f"CPA significantly exceeds target ({deviation_pct}% over). "
                    f"Current: {current_cpa:,.0f} / target: {target_cpa:,.0f}"
                )
        else:
            # No conversions, or no performance read at all
            status = "warning" if perf is not None else "unknown"
            result["deviation_pct"] = None

        result["status"] = status
        result["issues"] = issues

        if status in ("critical", "warning"):
            result["suggested_workflow"] = "cpa_optimization"

        # Summary generation
        if current_cpa is not None:
            if status == "healthy":
                result["summary"] = (
                    f"Campaign {campaign_id} CPA is within target. "
                    f"Current CPA: {current_cpa:,.0f} yen / Target: {target_cpa:,.0f} yen"
                    f" (deviation: {result['deviation_pct']}%)"
                )
            elif status == "warning":
                result["summary"] = (
                    f"Campaign {campaign_id} CPA slightly exceeds target. "
                    f"Current CPA: {current_cpa:,.0f} yen / Target: {target_cpa:,.0f} yen"
                    f" (deviation: {result['deviation_pct']}%). Early action recommended"
                )
            else:
                result["summary"] = (
                    f"Campaign {campaign_id} CPA significantly exceeds target. "
                    f"Current CPA: {current_cpa:,.0f} yen / Target: {target_cpa:,.0f} yen"
                    f" (deviation: {result['deviation_pct']}%). Urgent action required"
                )
        elif status == "unknown":
            result["summary"] = (
                f"Campaign {campaign_id} CPA could not be evaluated: the "
                "performance report could not be retrieved"
            )
        else:
            result["summary"] = (
                f"Campaign {campaign_id} has 0 conversions in the last 7 days, so "
                f"CPA cannot be evaluated. Checking delivery status and conversion tracking is recommended"
            )

        return result

    # =================================================================
    # 3. CV goal evaluation
    # =================================================================

    async def evaluate_cv_goal(
        self, campaign_id: str, target_cv_daily: float
    ) -> dict[str, Any]:
        """Evaluate current performance against daily CV target."""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        result: dict[str, Any] = {
            "campaign_id": campaign_id,
            "target_cv_daily": target_cv_daily,
        }

        # 1. Last 7 days performance
        perf: list[dict[str, Any]] | None = None
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_7_DAYS"
            )
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve performance report (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve performance report")

        metrics = perf[0].get("metrics", {}) if perf else {}
        impressions = int(metrics.get("impressions", 0))
        clicks = int(metrics.get("clicks", 0))
        conversions = float(metrics.get("conversions", 0))

        # 2. Calculate daily average CV (unknown when the read failed)
        daily_cv = round(conversions / 7, 2)
        result["current_cv_daily"] = daily_cv if perf is not None else None

        # 3. Comprehensive performance analysis
        performance_analysis: dict[str, Any] = {}
        try:
            performance_analysis = await self.analyze_performance(campaign_id)
            result["performance_analysis"] = performance_analysis
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve performance analysis (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve performance analysis")
            result["performance_analysis"] = None

        if perf is None:
            # Nothing to measure against the target: derive nothing.
            result["deviation_pct"] = None
            result["status"] = "unknown"
            result["bottleneck"] = None
            result["issues"] = issues
            result["summary"] = (
                f"Campaign {campaign_id} CV count could not be evaluated: the "
                "performance report could not be retrieved"
            )
            return result

        # 4. Calculate deviation rate
        if target_cv_daily > 0:
            deviation_pct = round(
                (daily_cv - target_cv_daily) / target_cv_daily * 100, 1
            )
        else:
            deviation_pct = 0.0
        result["deviation_pct"] = deviation_pct

        # 5. Status determination
        if daily_cv >= target_cv_daily:
            status = "healthy"
        elif daily_cv >= target_cv_daily * 0.8:
            status = "warning"
            issues.append(
                f"Daily CV is below target"
                f" (current: {daily_cv:.1f}/day / target: {target_cv_daily:.1f}/day)"
            )
        else:
            status = "critical"
            issues.append(
                f"Daily CV is significantly below target"
                f" (current: {daily_cv:.1f}/day / target: {target_cv_daily:.1f}/day,"
                f" deviation: {deviation_pct}%)"
            )

        result["status"] = status

        # 6. Bottleneck identification
        analysis_insights = performance_analysis.get("insights", [])
        impression_issue_in_insights = any(
            "impression" in insight.lower() for insight in analysis_insights
        )

        if impression_issue_in_insights or (clicks > 0 and impressions < clicks * 10):
            bottleneck = "impression"
            if status != "healthy":
                issues.append("Impression shortage may be the bottleneck")
        elif impressions > 0 and (clicks / impressions) < 0.02:
            bottleneck = "ctr"
            if status != "healthy":
                ctr_value = round(clicks / impressions * 100, 2)
                issues.append(
                    f"CTR is low ({ctr_value}%, below industry average of 2%)"
                )
        elif clicks > 0 and (conversions / clicks) < 0.01:
            bottleneck = "cvr"
            if status != "healthy":
                cvr_value = round(conversions / clicks * 100, 2)
                issues.append(f"CVR is low ({cvr_value}%, below 1%)")
        else:
            bottleneck = "cvr"

        result["bottleneck"] = bottleneck
        result["issues"] = issues

        if status in ("critical", "warning"):
            result["suggested_workflow"] = "cv_increase"

        # Summary generation
        bottleneck_label = {
            "impression": "Insufficient impressions",
            "ctr": "CTR (click-through rate) decline",
            "cvr": "CVR (conversion rate) decline",
        }
        if status == "healthy":
            result["summary"] = (
                f"Campaign {campaign_id} CV count meets the target. "
                f"Daily CV: {daily_cv:.1f} / target: {target_cv_daily:.1f}"
            )
        elif status == "warning":
            result["summary"] = (
                f"Campaign {campaign_id} CV count is slightly below target. "
                f"Daily CV: {daily_cv:.1f} / target: {target_cv_daily:.1f}"
                f" (deviation: {deviation_pct}%)."
                f" Main bottleneck: {bottleneck_label[bottleneck]}"
            )
        else:
            result["summary"] = (
                f"Campaign {campaign_id} CV count is significantly below target. "
                f"Daily CV: {daily_cv:.1f} / target: {target_cv_daily:.1f}"
                f" (deviation: {deviation_pct}%)."
                f" Main bottleneck: {bottleneck_label[bottleneck]}. Urgent action required"
            )

        return result

    # =================================================================
    # 4. Conversion acquisition improvement diagnosis
    # =================================================================

    async def diagnose_zero_conversions(self, campaign_id: str) -> dict[str, Any]:
        """Diagnose zero-conversion issues. Collect all data needed for LLM improvement strategy planning."""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        result: dict[str, Any] = {"campaign_id": campaign_id}

        # 1. Campaign basic information
        campaign: dict[str, Any] | None = None
        campaign_read = True
        try:
            campaign = await self.get_campaign(campaign_id)
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve campaign information (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve campaign information")
            campaign_read = False

        # 2. Conversion tracking configuration; has_cv_issue is unknown (None)
        # when the action list could not be read
        cv_actions: list[dict[str, Any]] | None = None
        try:
            cv_actions = await self.list_conversion_actions()
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve conversion action list (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve conversion action list")

        has_cv_issue: bool | None = None
        result["conversion_tracking"] = None
        if cv_actions is not None:
            total_actions = len(cv_actions)
            enabled_actions = sum(
                1 for a in cv_actions if a.get("status", "").upper() == "ENABLED"
            )
            has_cv_issue = total_actions == 0 or enabled_actions == 0
            result["conversion_tracking"] = {
                "total_actions": total_actions,
                "enabled_actions": enabled_actions,
                "has_issue": has_cv_issue,
                "actions": cv_actions,
            }
            if has_cv_issue:
                issues.append("No active conversion actions are configured")

        # 3. Bidding x CV alignment check
        bidding_strategy = (
            (campaign or {}).get("bidding_strategy", "") if campaign_read else None
        )
        is_smart = (
            bidding_strategy.upper() in SMART_BIDDING_STRATEGIES
            if bidding_strategy is not None
            else None
        )
        bidding_issue: str | None = None
        if is_smart and has_cv_issue:
            bidding_issue = (
                f"Smart bidding ({bidding_strategy}) is configured, but "
                "no active conversion tracking is configured"
            )
            issues.append(bidding_issue)
        result["bidding_cv_alignment"] = {
            "strategy": bidding_strategy,
            "is_smart_bidding": is_smart,
            "cv_tracking_configured": (
                None if has_cv_issue is None else not has_cv_issue
            ),
            "issue": bidding_issue,
        }

        # 4. Funnel data (last 7 days); null when the report could not be read
        perf: list[dict[str, Any]] | None = None
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_7_DAYS"
            )
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve performance report (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve performance report")

        metrics = perf[0].get("metrics", {}) if perf else {}
        clicks = int(metrics.get("clicks", 0))
        conversions = float(metrics.get("conversions", 0))
        cost = float(metrics.get("cost", 0))
        funnel = self._build_funnel(metrics) if perf is not None else None
        bottleneck = funnel["bottleneck"] if funnel is not None else None
        if bottleneck in _FUNNEL_ISSUES:
            issues.append(_FUNNEL_ISSUES[bottleneck])
        result["funnel"] = funnel

        # 5. Delivery diagnostics
        try:
            diagnosis = await self.diagnose_campaign_delivery(campaign_id)
            result["delivery_diagnosis"] = {
                "issues": diagnosis.get("issues", []),
                "warnings": diagnosis.get("warnings", []),
                "recommendations": diagnosis.get("recommendations", []),
            }
        except Exception as exc:  # noqa: BLE001 — partial read; failures warned
            logger.warning(
                "Failed to retrieve delivery diagnostics (%s)", type(exc).__name__
            )
            issues.append("Failed to retrieve delivery diagnostics")
            result["delivery_diagnosis"] = None

        # 6. Search term quality (only when clicks > 0)
        search_term_quality: dict[str, Any] | None = None
        if clicks > 0:
            try:
                terms = await self.get_search_terms_report(
                    campaign_id=campaign_id, period="LAST_7_DAYS"
                )
                zero_cv_terms = [
                    t
                    for t in terms
                    if float(t.get("metrics", {}).get("conversions", 0)) == 0
                ]
                zero_cv_cost = sum(
                    float(t.get("metrics", {}).get("cost", 0)) for t in zero_cv_terms
                )
                # Top 10 zero-CV high-cost items
                sorted_wasteful = sorted(
                    zero_cv_terms,
                    key=lambda t: float(t.get("metrics", {}).get("cost", 0)),
                    reverse=True,
                )
                search_term_quality = {
                    "total_terms": len(terms),
                    "zero_cv_terms": len(zero_cv_terms),
                    "zero_cv_cost": zero_cv_cost,
                    "top_wasteful_terms": sorted_wasteful[:10],
                }
                # If zero-CV high-cost terms exceed 50%
                if cost > 0 and zero_cv_cost / cost > 0.5:
                    issues.append(
                        f"Zero-CV search terms account for "
                        f"{round(zero_cv_cost / cost * 100, 1)}% of total cost"
                    )
            except Exception as exc:  # noqa: BLE001 — partial read; failures warned
                logger.warning(
                    "Failed to retrieve search terms report (%s)", type(exc).__name__
                )
                issues.append("Failed to retrieve search terms report")
        result["search_term_quality"] = search_term_quality

        # Status determination: critical only on what was read; "unknown" when
        # a read the verdict rests on failed and nothing read proves critical
        if has_cv_issue or bidding_issue or bottleneck in _FUNNEL_ISSUES:
            status = "critical"
        elif not campaign_read or cv_actions is None or perf is None:
            status = "unknown"
        elif conversions == 0:
            status = "warning"
        else:
            status = "healthy"

        result["status"] = status
        result["issues"] = issues

        if status in ("critical", "warning"):
            result["suggested_workflow"] = "cv_acquisition"

        # Recommended actions
        result["recommended_actions"] = self._build_cv_recommendations(
            has_cv_issue=bool(has_cv_issue),
            bidding_issue=bidding_issue,
            bottleneck=bottleneck,
            search_term_quality=search_term_quality,
            cost=cost,
        )

        # Summary generation
        if status == "critical":
            result["summary"] = (
                f"Campaign {campaign_id} has not acquired any conversions."
                f"Critical issues detected: {', '.join(issues[:3])}"
            )
        elif status == "unknown":
            result["summary"] = (
                f"Campaign {campaign_id} could not be fully diagnosed. "
                f"Issues: {', '.join(issues)}"
            )
        elif status == "warning":
            result["summary"] = (
                f"Campaign {campaign_id} has 0 conversions."
                f"Imp={int(metrics.get('impressions', 0)):,}, Click={clicks:,}, CV=0."
                f"Planning an improvement strategy is recommended"
            )
        else:
            result["summary"] = (
                f"Campaign {campaign_id} is generating conversions."
                f"Conversions in the last 7 days: {conversions:.1f}"
            )

        return result

    @staticmethod
    def _build_funnel(metrics: dict[str, Any]) -> dict[str, Any]:
        """The LAST_7_DAYS funnel and its bottleneck, from a metrics row that was read."""
        impressions = int(metrics.get("impressions", 0))
        clicks = int(metrics.get("clicks", 0))
        conversions = float(metrics.get("conversions", 0))
        if impressions == 0:
            bottleneck: str | None = "no_delivery"
        elif clicks == 0:
            bottleneck = "no_clicks"
        elif conversions == 0:
            bottleneck = "no_conversions"
        else:
            bottleneck = None
        return {
            "period": "LAST_7_DAYS",
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "cost": float(metrics.get("cost", 0)),
            "ctr": round(clicks / impressions * 100, 2) if impressions > 0 else None,
            "cvr": round(conversions / clicks * 100, 2) if clicks > 0 else None,
            "bottleneck": bottleneck,
        }

    @staticmethod
    def _build_cv_recommendations(
        *,
        has_cv_issue: bool,
        bidding_issue: str | None,
        bottleneck: str | None,
        search_term_quality: dict[str, Any] | None,
        cost: float,
    ) -> list[dict[str, Any]]:
        """Generate prioritized recommended actions for CV improvement."""
        actions: list[dict[str, Any]] = []
        priority = 1

        if has_cv_issue:
            actions.append(
                {
                    "priority": priority,
                    "action": "fix_cv_tracking",
                    "description": "Configure/fix conversion tracking",
                }
            )
            priority += 1

        if bidding_issue:
            actions.append(
                {
                    "priority": priority,
                    "action": "fix_bidding_strategy",
                    "description": "Fix alignment between bidding strategy and CV tracking",
                }
            )
            priority += 1

        if search_term_quality and search_term_quality["zero_cv_terms"] > 0:
            actions.append(
                {
                    "priority": priority,
                    "action": "add_negative_keywords",
                    "description": "Add negative keywords for zero-CV search terms",
                }
            )
            priority += 1

        if bottleneck in _FUNNEL_ISSUES:
            actions.append(
                {
                    "priority": priority,
                    "action": "fix_delivery",
                    "description": "Improve delivery and click acquisition",
                }
            )
            priority += 1

        # Always suggest candidates
        actions.append(
            {
                "priority": priority,
                "action": "improve_ads_and_keywords",
                "description": "Improve ad copy and expand keywords",
            }
        )
        priority += 1

        actions.append(
            {
                "priority": priority,
                "action": "review_landing_page",
                "description": "Landing page improvement (text-based advice)",
            }
        )

        return actions
