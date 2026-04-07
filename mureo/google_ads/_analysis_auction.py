"""Auction analysis, CPC anomaly detection, and device analysis mixin."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _AuctionAnalysisMixin:
    """Mixin providing auction analysis, CPC anomaly detection, and device analysis methods."""

    # Type declarations for attributes/methods provided by parent class
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _period_to_date_clause(self, period: str) -> str: ...  # type: ignore[empty-body]
    async def _search(self, query: str) -> list[Any]: ...  # type: ignore[empty-body]
    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...

    # =================================================================
    # Device-level CPA analysis
    # =================================================================

    async def analyze_device_performance(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """Compare and analyze CPA, CVR, etc. by device (Desktop/Mobile/Tablet)."""
        self._validate_id(campaign_id, "campaign_id")

        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"Campaign ID {campaign_id} not found"}

        date_clause = self._period_to_date_clause(period)
        query = f"""
            SELECT
                segments.device,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.ctr,
                metrics.average_cpc
            FROM campaign
            WHERE campaign.id = {campaign_id}
                AND segments.date {date_clause}
        """

        try:
            rows = await self._search(query)
        except Exception as exc:
            return {"error": f"Failed to retrieve device performance data: {exc}"}

        if not rows:
            return {
                "campaign_id": campaign_id,
                "campaign_name": campaign.get("name", ""),
                "period": period,
                "message": "No device-level data available",
                "devices": [],
                "insights": [],
            }

        devices: list[dict[str, Any]] = []
        for row in rows:
            device_type = str(row.segments.device).split(".")[-1]
            cost = float(row.metrics.cost_micros) / 1_000_000
            conversions = float(row.metrics.conversions)
            cpa = round(cost / conversions, 0) if conversions > 0 else None
            clicks = int(row.metrics.clicks)
            cvr = round(conversions / clicks * 100, 2) if clicks > 0 else 0

            devices.append(
                {
                    "device_type": device_type,
                    "impressions": int(row.metrics.impressions),
                    "clicks": clicks,
                    "cost": round(cost, 0),
                    "conversions": conversions,
                    "ctr": round(float(row.metrics.ctr) * 100, 2),
                    "average_cpc": round(float(row.metrics.average_cpc) / 1_000_000, 0),
                    "cpa": cpa,
                    "cvr": cvr,
                }
            )

        # Sort by cost descending
        devices.sort(key=lambda x: x["cost"], reverse=True)

        insights = self._generate_device_insights(devices)

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name", ""),
            "period": period,
            "devices": devices,
            "insights": insights,
        }

    @staticmethod
    def _generate_device_insights(
        devices: list[dict[str, Any]],
    ) -> list[str]:
        """Generate insights from device-level data."""
        insights: list[str] = []

        # Device with 0 conversions but cost incurred
        for d in devices:
            if d["conversions"] == 0 and d["cost"] > 0:
                insights.append(
                    f"{d['device_type']} has 0 conversions with {d['cost']} yen in cost. "
                    "Consider lowering bid adjustments or excluding this device."
                )

        # Compare only devices with calculable CPA
        devices_with_cpa = [d for d in devices if d["cpa"] is not None]
        if len(devices_with_cpa) >= 2:
            best = min(devices_with_cpa, key=lambda x: x["cpa"])
            worst = max(devices_with_cpa, key=lambda x: x["cpa"])

            if best["device_type"] != worst["device_type"] and worst["cpa"] > 0:
                ratio = worst["cpa"] / best["cpa"]
                if ratio > 1.5:
                    insights.append(
                        f"{worst['device_type']} CPA ({worst['cpa']} yen) is "
                        f"{round(ratio, 1)}x that of {best['device_type']} ({best['cpa']} yen). "
                        f"Consider lowering bid adjustments for {worst['device_type']}."
                    )

        # Mobile vs Desktop CTR comparison
        mobile = next((d for d in devices if d["device_type"] in ("MOBILE", "2")), None)
        desktop = next(
            (d for d in devices if d["device_type"] in ("DESKTOP", "1")), None
        )
        if mobile and desktop and desktop["ctr"] > 0:
            ctr_ratio = mobile["ctr"] / desktop["ctr"]
            if ctr_ratio < 0.5:
                insights.append(
                    f"Mobile CTR ({mobile['ctr']}%) is less than half of Desktop ({desktop['ctr']}%). "
                    "Consider optimizing ad copy and landing pages for mobile."
                )

        return insights

    # =================================================================
    # CPC trend detection
    # =================================================================

    async def detect_cpc_trend(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """Retrieve daily CPC data and detect rising trends."""
        self._validate_id(campaign_id, "campaign_id")

        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"Campaign ID {campaign_id} not found"}

        date_clause = self._period_to_date_clause(period)
        query = f"""
            SELECT
                segments.date,
                metrics.average_cpc,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros
            FROM campaign
            WHERE campaign.id = {campaign_id}
                AND segments.date {date_clause}
                AND metrics.clicks > 0
            ORDER BY segments.date ASC
        """

        try:
            rows = await self._search(query)
        except Exception as exc:
            return {"error": f"Failed to retrieve daily CPC data: {exc}"}

        if not rows:
            return {
                "campaign_id": campaign_id,
                "campaign_name": campaign.get("name", ""),
                "period": period,
                "message": "No CPC data available (only days with 0 clicks)",
                "daily_data": [],
                "trend": None,
                "insights": [],
            }

        daily_data: list[dict[str, Any]] = []
        cpc_values: list[float] = []
        for row in rows:
            cpc = round(float(row.metrics.average_cpc) / 1_000_000, 1)
            daily_data.append(
                {
                    "date": str(row.segments.date),
                    "average_cpc": cpc,
                    "clicks": int(row.metrics.clicks),
                    "impressions": int(row.metrics.impressions),
                    "cost": round(float(row.metrics.cost_micros) / 1_000_000, 0),
                }
            )
            cpc_values.append(cpc)

        trend_info = self._calculate_cpc_trend(cpc_values)
        insights = self._generate_cpc_insights(cpc_values, trend_info, daily_data)

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name", ""),
            "period": period,
            "data_points": len(daily_data),
            "daily_data": daily_data,
            "trend": trend_info,
            "insights": insights,
        }

    @staticmethod
    def _calculate_cpc_trend(
        cpc_values: list[float],
    ) -> dict[str, Any]:
        """Calculate trend information from a list of CPC values."""
        n = len(cpc_values)
        if n < 2:
            return {
                "direction": "insufficient_data",
                "slope_per_day": 0.0,
                "avg_cpc": cpc_values[0] if cpc_values else 0.0,
                "min_cpc": min(cpc_values) if cpc_values else 0.0,
                "max_cpc": max(cpc_values) if cpc_values else 0.0,
            }

        # Simple linear regression
        x_mean = (n - 1) / 2.0
        y_mean = sum(cpc_values) / n
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(cpc_values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0.0

        # Change rate (%/day)
        change_rate_per_day = (slope / y_mean * 100) if y_mean > 0 else 0.0

        # Trend direction determination
        if change_rate_per_day > 1.0:
            direction = "rising"
        elif change_rate_per_day < -1.0:
            direction = "falling"
        else:
            direction = "stable"

        return {
            "direction": direction,
            "slope_per_day": round(slope, 2),
            "change_rate_per_day_pct": round(change_rate_per_day, 2),
            "avg_cpc": round(y_mean, 1),
            "min_cpc": round(min(cpc_values), 1),
            "max_cpc": round(max(cpc_values), 1),
        }

    @staticmethod
    def _generate_cpc_insights(
        cpc_values: list[float],
        trend_info: dict[str, Any],
        daily_data: list[dict[str, Any]],
    ) -> list[str]:
        """Generate insights from CPC trends."""
        insights: list[str] = []
        direction = trend_info.get("direction", "stable")

        if direction == "rising":
            rate = trend_info["change_rate_per_day_pct"]
            insights.append(
                f"CPC is on a rising trend (approximately {rate}% increase per day). "
                "This may be due to increased competitor bidding or changes in auction environment."
            )
        elif direction == "falling":
            rate = abs(trend_info["change_rate_per_day_pct"])
            insights.append(
                f"CPC is on a declining trend (approximately {rate}% decrease per day). "
                "This may be due to competitor withdrawal or keyword quality score improvement."
            )

        # Recent 7 days vs previous 7 days comparison
        if len(cpc_values) >= 14:
            recent_7 = cpc_values[-7:]
            prev_7 = cpc_values[-14:-7]
            recent_avg = sum(recent_7) / len(recent_7)
            prev_avg = sum(prev_7) / len(prev_7)
            if prev_avg > 0:
                week_change = (recent_avg - prev_avg) / prev_avg * 100
                if week_change > 15:
                    insights.append(
                        f"The average CPC for the last 7 days ({round(recent_avg, 1)} yen) "
                        f"surged {round(week_change, 1)}% compared to the prior 7 days ({round(prev_avg, 1)} yen). "
                        "Urgent investigation is recommended."
                    )
                elif week_change < -15:
                    insights.append(
                        f"The average CPC for the last 7 days ({round(recent_avg, 1)} yen) "
                        f"decreased {round(abs(week_change), 1)}% compared to the prior 7 days ({round(prev_avg, 1)} yen)."
                    )

        # Spike detection (days exceeding 2x average)
        avg_cpc = trend_info.get("avg_cpc", 0)
        if avg_cpc > 0:
            spikes = [d for d in daily_data if d["average_cpc"] > avg_cpc * 2]
            if spikes:
                spike_dates = ", ".join(s["date"] for s in spikes[:3])
                insights.append(
                    f"CPC anomalies (>2x average) detected on {len(spikes)} days: {spike_dates}. "
                    "Possible causes include increased competition or quality score drops on specific days."
                )

        return insights

    # =================================================================
    # Auction Analysis (Auction Insights)
    # =================================================================

    async def get_auction_insights(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """Retrieve campaign auction insights data via GAQL."""
        self._validate_id(campaign_id, "campaign_id")
        date_clause = self._period_to_date_clause(period)

        query = f"""
            SELECT
                metrics.auction_insight_search_impression_share,
                metrics.auction_insight_search_overlap_rate,
                metrics.auction_insight_search_position_above_rate,
                metrics.auction_insight_search_top_impression_percentage,
                metrics.auction_insight_search_absolute_top_impression_percentage,
                metrics.auction_insight_search_outranking_share
            FROM campaign_auction_insight
            WHERE campaign.id = {campaign_id}
                AND segments.date {date_clause}
        """

        try:
            rows = await self._search(query)
        except Exception as exc:
            logger.warning("Failed to retrieve auction insights data: %s", exc)
            return [
                {
                    "error": "auction_insights_unavailable",
                    "reason": str(exc),
                    "hint": "Auction insights require sufficient impression data. "
                    "Try a longer period or a campaign with more traffic.",
                }
            ]

        if not rows:
            return [
                {
                    "error": "no_data",
                    "reason": "No auction insights data for this campaign and period.",
                    "hint": "The campaign may have insufficient impressions. "
                    "Try LAST_30_DAYS or a higher-traffic campaign.",
                }
            ]

        results: list[dict[str, Any]] = []
        for row in rows:
            m = row.metrics
            results.append(
                {
                    "display_url": row.segments.auction_insight_domain,
                    "impression_share": round(
                        float(m.auction_insight_search_impression_share) * 100, 1
                    ),
                    "overlap_rate": round(
                        float(m.auction_insight_search_overlap_rate) * 100, 1
                    ),
                    "position_above_rate": round(
                        float(m.auction_insight_search_position_above_rate) * 100, 1
                    ),
                    "top_impression_pct": round(
                        float(m.auction_insight_search_top_impression_percentage) * 100,
                        1,
                    ),
                    "abs_top_impression_pct": round(
                        float(
                            m.auction_insight_search_absolute_top_impression_percentage
                        )
                        * 100,
                        1,
                    ),
                    "outranking_share": round(
                        float(m.auction_insight_search_outranking_share) * 100, 1
                    ),
                }
            )

        results.sort(key=lambda x: x["impression_share"], reverse=True)
        return results

    async def analyze_auction_insights(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """Run campaign auction analysis and generate competitive insights."""
        self._validate_id(campaign_id, "campaign_id")

        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"Campaign ID {campaign_id} not found"}

        auction_data = await self.get_auction_insights(campaign_id, period)
        if not auction_data or (auction_data and "error" in auction_data[0]):
            return {
                "campaign_id": campaign_id,
                "campaign_name": campaign.get("name", ""),
                "period": period,
                "message": "No auction insights data available (non-search campaign or insufficient data)",
                "competitors": [],
                "insights": [],
            }

        # Extract own data (empty display_url = self)
        my_data: dict[str, Any] | None = None
        competitors: list[dict[str, Any]] = []
        for entry in auction_data:
            if entry["display_url"] == "":
                my_data = entry
            else:
                competitors.append(entry)

        insights: list[str] = []

        if my_data:
            is_pct = my_data["impression_share"]
            if is_pct < 50:
                insights.append(
                    f"Your impression share is {is_pct}%, missing more than half of display opportunities. "
                    "Consider reviewing budget or keyword bids."
                )
            elif is_pct < 70:
                insights.append(
                    f"Your impression share is {is_pct}%. "
                    "Some display opportunities are being taken by competitors."
                )

            abs_top = my_data["abs_top_impression_pct"]
            if abs_top < 20:
                insights.append(
                    f"Absolute top impression rate is {abs_top}%, rarely appearing at the very top of search results. "
                    "Consider increasing bids or improving ad quality."
                )

        # Competitor analysis
        strong_competitors = [c for c in competitors if c["impression_share"] > 30]
        if strong_competitors:
            top_comp = strong_competitors[0]
            insights.append(
                f"The top competitor is \"{top_comp['display_url']}\" "
                f"(IS: {top_comp['impression_share']}%, "
                f"top impression rate: {top_comp['top_impression_pct']}%)."
            )

        for comp in competitors[:5]:
            if comp["outranking_share"] > 50 and my_data:
                insights.append(
                    f"\"{comp['display_url']}\" is outranking you {comp['outranking_share']}% of the time. "
                    "Consider reviewing your bidding strategy."
                )

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name", ""),
            "period": period,
            "my_impression_share": my_data if my_data else None,
            "competitors": competitors[:10],
            "competitor_count": len(competitors),
            "insights": insights,
        }
