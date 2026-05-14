from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Meta API date_preset mapping
_PERIOD_TO_DATE_PRESET: dict[str, str] = {
    "today": "today",
    "yesterday": "yesterday",
    "last_7d": "last_7d",
    "last_30d": "last_30d",
    "this_month": "this_month",
    "last_month": "last_month",
}

# Common Insights retrieval fields
_INSIGHTS_FIELDS = (
    "campaign_name,campaign_id,adset_name,adset_id,ad_name,ad_id,"
    "impressions,clicks,spend,cpc,cpm,ctr,"
    "actions,cost_per_action_type,"
    "reach,frequency"
)

# Day-grain insights fields used by ``insights_time_range`` (the Protocol
# adapter surface). Smaller than ``_INSIGHTS_FIELDS`` because the
# Protocol's ``DailyReportRow`` only needs date, volume, cost, and
# action counts.
_TIME_RANGE_INSIGHTS_FIELDS = "impressions,clicks,spend,actions,date_start,date_stop"


class InsightsMixin:
    """Meta Ads insights (performance report) operations mixin

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def get_performance_report(
        self,
        *,
        campaign_id: str | None = None,
        period: str = "last_7d",
        level: str = "campaign",
    ) -> list[dict[str, Any]]:
        """Get performance report

        Args:
            campaign_id: Campaign ID (limits to this campaign when specified)
            period: Period (today, yesterday, last_7d, last_30d, this_month, last_month)
            level: Aggregation level (campaign, adset, ad)

        Returns:
            List of insight data.
        """
        date_preset = _PERIOD_TO_DATE_PRESET.get(period, "last_7d")

        params: dict[str, Any] = {
            "fields": _INSIGHTS_FIELDS,
            "date_preset": date_preset,
            "level": level,
        }

        if campaign_id:
            path = f"/{campaign_id}/insights"
        else:
            account_id = self._ad_account_id
            path = f"/{account_id}/insights"

        result = await self._get(path, params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def insights_time_range(
        self,
        node_id: str,
        *,
        since: str,
        until: str,
        time_increment: int = 1,
        level: str = "campaign",
    ) -> list[dict[str, Any]]:
        """Get insights for an explicit date range with day-level granularity.

        The Protocol-layer ``CampaignProvider.daily_report`` requires
        arbitrary ``start_date`` / ``end_date`` plus one row per day —
        ``get_performance_report`` only supports named ``date_preset``
        values, so this companion method fills the gap.

        Args:
            node_id: Meta node id (campaign / ad-set / ad). Interpolated
                directly into the URL path; callers (notably the
                ``MetaAdsAdapter``) are responsible for digit-validating
                user-controlled values before passing them here.
            since: Start date, ``YYYY-MM-DD``.
            until: End date, ``YYYY-MM-DD``.
            time_increment: Bucket size in days (default: 1 = day-grain).
            level: Aggregation level (``campaign``, ``adset``, ``ad``).

        Returns:
            List of insight rows, one per day in the range.
        """
        params: dict[str, Any] = {
            "fields": _TIME_RANGE_INSIGHTS_FIELDS,
            "time_range": json.dumps({"since": since, "until": until}),
            "time_increment": time_increment,
            "level": level,
        }
        result = await self._get(f"/{node_id}/insights", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def analyze_performance(
        self,
        *,
        campaign_id: str | None = None,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """Comprehensively analyze campaign performance.

        Compares current and previous period insights to identify issues.
        """
        current = await self.get_performance_report(
            campaign_id=campaign_id, period=period
        )

        # Get previous period data
        prev_period_map = {
            "last_7d": "last_30d",
            "last_30d": "last_month",
            "today": "yesterday",
            "yesterday": "last_7d",
        }
        prev_period = prev_period_map.get(period, "last_30d")
        previous = await self.get_performance_report(
            campaign_id=campaign_id, period=prev_period
        )

        def _sum_metric(data: list[dict[str, Any]], key: str) -> float:
            return sum(float(row.get(key, 0) or 0) for row in data)

        cur_imp = _sum_metric(current, "impressions")
        cur_clicks = _sum_metric(current, "clicks")
        cur_spend = _sum_metric(current, "spend")
        prev_imp = _sum_metric(previous, "impressions")
        prev_clicks = _sum_metric(previous, "clicks")
        prev_spend = _sum_metric(previous, "spend")

        def _change_pct(cur: float, prev: float) -> float | None:
            if prev == 0:
                return None
            return round((cur - prev) / prev * 100, 1)

        insights: list[str] = []

        imp_change = _change_pct(cur_imp, prev_imp)
        if imp_change is not None and imp_change < -20:
            insights.append(f"Impressions decreased {imp_change}% vs. previous period")

        click_change = _change_pct(cur_clicks, prev_clicks)
        if click_change is not None and click_change < -20:
            insights.append(f"Clicks decreased {click_change}% vs. previous period")

        spend_change = _change_pct(cur_spend, prev_spend)
        if spend_change is not None and spend_change > 30:
            insights.append(f"Ad spend increased {spend_change}% vs. previous period")

        return {
            "campaign_id": campaign_id,
            "period": period,
            "current": {
                "impressions": int(cur_imp),
                "clicks": int(cur_clicks),
                "spend": round(cur_spend, 2),
                "ctr": round(cur_clicks / cur_imp * 100, 2) if cur_imp > 0 else 0,
            },
            "previous": {
                "impressions": int(prev_imp),
                "clicks": int(prev_clicks),
                "spend": round(prev_spend, 2),
            },
            "changes": {
                "impressions_change_pct": imp_change,
                "clicks_change_pct": click_change,
                "spend_change_pct": spend_change,
            },
            "insights": insights,
            "campaigns": current,
        }

    async def analyze_audience(
        self,
        campaign_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """Analyze audience efficiency from age x gender breakdown."""
        breakdown_data = await self.get_breakdown_report(
            campaign_id=campaign_id,
            breakdown="age,gender",
            period=period,
        )

        if not breakdown_data:
            return {
                "campaign_id": campaign_id,
                "period": period,
                "message": "No breakdown data available",
                "segments": [],
                "insights": [],
            }

        segments: list[dict[str, Any]] = []
        for row in breakdown_data:
            spend = float(row.get("spend", 0) or 0)
            clicks = int(row.get("clicks", 0) or 0)
            impressions = int(row.get("impressions", 0) or 0)
            ctr = float(row.get("ctr", 0) or 0)

            # Extract CV count from actions
            actions = row.get("actions", [])
            conversions = 0.0
            if actions:
                for a in actions:
                    if a.get("action_type") in (
                        "lead",
                        "purchase",
                        "complete_registration",
                    ):
                        conversions += float(a.get("value", 0))

            cpa = round(spend / conversions, 0) if conversions > 0 else None

            segments.append(
                {
                    "age": row.get("age", ""),
                    "gender": row.get("gender", ""),
                    "impressions": impressions,
                    "clicks": clicks,
                    "spend": round(spend, 2),
                    "ctr": round(ctr, 2),
                    "conversions": conversions,
                    "cpa": cpa,
                }
            )

        # Sort by cost descending
        segments.sort(key=lambda x: x["spend"], reverse=True)

        insights: list[str] = []

        # Compare best and worst segments where CPA can be calculated
        with_cpa = [s for s in segments if s["cpa"] is not None]
        if len(with_cpa) >= 2:
            best = min(with_cpa, key=lambda x: x["cpa"])
            worst = max(with_cpa, key=lambda x: x["cpa"])
            if worst["cpa"] > best["cpa"] * 2:
                insights.append(
                    f"{worst['age']}・{worst['gender']} CPA ({worst['cpa']}) is "
                    f"{best['age']}・{best['gender']}（{best['cpa']}) of "
                    f"{round(worst['cpa'] / best['cpa'], 1)}x."
                    "Consider reviewing your targeting."
                )

        # Segments with 0 CV and high cost
        for s in segments:
            if s["conversions"] == 0 and s["spend"] > 0:
                insights.append(
                    f"{s['age']}・{s['gender']} has 0 CV with {s['spend']} in cost."
                )

        return {
            "campaign_id": campaign_id,
            "period": period,
            "segments": segments[:20],
            "insights": insights,
        }

    async def get_breakdown_report(
        self,
        campaign_id: str,
        breakdown: str = "age,gender",
        period: str = "last_7d",
    ) -> list[dict[str, Any]]:
        """Get a report with breakdown

        Args:
            campaign_id: Campaign ID
            breakdown: Breakdown type (age, gender, age,gender,
                       country, region, publisher_platform, etc.)
            period: Period (today, yesterday, last_7d, last_30d, this_month, last_month)

        Returns:
            List of insight data with breakdowns.
        """
        date_preset = _PERIOD_TO_DATE_PRESET.get(period, "last_7d")

        params: dict[str, Any] = {
            "fields": _INSIGHTS_FIELDS,
            "date_preset": date_preset,
            "breakdowns": breakdown,
        }

        result = await self._get(f"/{campaign_id}/insights", params)
        return result.get("data", [])  # type: ignore[no-any-return]
