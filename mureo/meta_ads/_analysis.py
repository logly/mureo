"""Meta Ads analysis mixin.

Placement analysis, cost investigation, A/B comparison, and creative improvement suggestions.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def _extract_cv(row: dict[str, Any]) -> float:
    actions = row.get("actions")
    if not actions or not isinstance(actions, list):
        return 0.0
    cv_types = {"lead", "purchase", "complete_registration"}
    return sum(
        _safe_float(a.get("value")) for a in actions if a.get("action_type") in cv_types
    )


class AnalysisMixin:
    """Meta Ads analysis mixin.

    Used via multiple inheritance with MetaAdsApiClient.
    get_performance_report / get_breakdown_report are provided by InsightsMixin.
    """

    async def get_performance_report(  # type: ignore[empty-body]
        self,
        *,
        campaign_id: str | None = None,
        period: str = "last_7d",
        level: str = "campaign",
    ) -> list[dict[str, Any]]: ...

    async def get_breakdown_report(  # type: ignore[empty-body]
        self,
        campaign_id: str,
        breakdown: str = "age,gender",
        period: str = "last_7d",
    ) -> list[dict[str, Any]]: ...

    # =================================================================
    # Placement analysis
    # =================================================================

    async def analyze_placements(
        self,
        campaign_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """Analyze performance by placement."""
        data = await self.get_breakdown_report(
            campaign_id=campaign_id,
            breakdown="publisher_platform",
            period=period,
        )

        if not data:
            return {
                "campaign_id": campaign_id,
                "period": period,
                "message": "No placement data available",
                "placements": [],
                "insights": [],
            }

        placements: list[dict[str, Any]] = []
        for row in data:
            spend = _safe_float(row.get("spend"))
            clicks = _safe_float(row.get("clicks"))
            impressions = _safe_float(row.get("impressions"))
            cv = _extract_cv(row)
            cpa = round(spend / cv, 0) if cv > 0 else None

            placements.append(
                {
                    "publisher_platform": row.get("publisher_platform", ""),
                    "impressions": int(impressions),
                    "clicks": int(clicks),
                    "spend": round(spend, 2),
                    "ctr": round(_safe_float(row.get("ctr")), 2),
                    "conversions": cv,
                    "cpa": cpa,
                }
            )

        placements.sort(key=lambda x: x["spend"], reverse=True)

        insights: list[str] = []
        with_cpa = [p for p in placements if p["cpa"] is not None]
        if len(with_cpa) >= 2:
            best = min(with_cpa, key=lambda x: x["cpa"])
            worst = max(with_cpa, key=lambda x: x["cpa"])
            if worst["cpa"] > best["cpa"] * 2:
                insights.append(
                    f"{worst['publisher_platform']} CPA ({worst['cpa']}) is "
                    f"{round(worst['cpa'] / best['cpa'], 1)}x of "
                    f"{best['publisher_platform']} ({best['cpa']}). "
                    "Consider excluding this placement or adjusting bids."
                )

        for p in placements:
            if p["conversions"] == 0 and p["spend"] > 0:
                insights.append(
                    f"{p['publisher_platform']} has 0 CV with {p['spend']} in spend."
                )

        return {
            "campaign_id": campaign_id,
            "period": period,
            "placements": placements,
            "insights": insights,
        }

    # =================================================================
    # Cost investigation
    # =================================================================

    async def investigate_cost(
        self,
        campaign_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """Investigate causes of ad spend increase or CPA degradation."""
        prev_map = {"last_7d": "last_30d", "last_30d": "last_month"}
        prev_period = prev_map.get(period, "last_30d")

        current = await self.get_performance_report(
            campaign_id=campaign_id, period=period
        )
        previous = await self.get_performance_report(
            campaign_id=campaign_id, period=prev_period
        )

        if not current:
            return {
                "campaign_id": campaign_id,
                "message": "No performance data available",
            }

        def _sum(data: list[dict[str, Any]], key: str) -> float:
            return sum(_safe_float(r.get(key)) for r in data)

        cur_spend = _sum(current, "spend")
        prev_spend = _sum(previous, "spend")
        cur_cpc = _safe_float(current[0].get("cpc")) if current else 0
        prev_cpc = _safe_float(previous[0].get("cpc")) if previous else 0
        cur_clicks = _sum(current, "clicks")
        prev_clicks = _sum(previous, "clicks")

        def _pct(cur: float, prev: float) -> float | None:
            if prev == 0:
                return None
            return round((cur - prev) / prev * 100, 1)

        findings: list[str] = []
        spend_change = _pct(cur_spend, prev_spend)
        if spend_change is not None and spend_change > 20:
            findings.append(f"Ad spend increased {spend_change}% vs. previous period")
        cpc_change = _pct(cur_cpc, prev_cpc)
        if cpc_change is not None and cpc_change > 15:
            findings.append(
                f"CPC increased {cpc_change}% vs. previous period. Possible competitor bid escalation"
            )
        clicks_change = _pct(cur_clicks, prev_clicks)
        if clicks_change is not None and clicks_change > 20:
            findings.append(f"Clicks increased {clicks_change}% vs. previous period")

        return {
            "campaign_id": campaign_id,
            "period": period,
            "current": {
                "spend": round(cur_spend, 2),
                "cpc": round(cur_cpc, 2),
                "clicks": int(cur_clicks),
            },
            "previous": {
                "spend": round(prev_spend, 2),
                "cpc": round(prev_cpc, 2),
                "clicks": int(prev_clicks),
            },
            "changes": {
                "spend_change_pct": spend_change,
                "cpc_change_pct": cpc_change,
                "clicks_change_pct": clicks_change,
            },
            "findings": findings,
        }

    # =================================================================
    # A/B comparison
    # =================================================================

    async def compare_ads(
        self,
        ad_set_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """A/B compare ad performance within an ad set."""
        data = await self.get_performance_report(
            campaign_id=None, period=period, level="ad"
        )

        # Filter by ad_set_id (only when response includes adset_id)
        if ad_set_id:
            ads_data = [
                r
                for r in data
                if r.get("adset_id", "") == ad_set_id or not r.get("adset_id")
            ]
            # If filter result is empty, return as no data for the specified ad set
            if not ads_data:
                return {"error": "No ads found for the specified ad_set_id", "ads": []}
        else:
            ads_data = data

        if not ads_data:
            return {
                "ad_set_id": ad_set_id,
                "ads": [],
                "winner": None,
                "message": "No ad data available",
            }

        ads: list[dict[str, Any]] = []
        for r in ads_data:
            ctr = _safe_float(r.get("ctr"))
            cpc = _safe_float(r.get("cpc"))
            cv = _extract_cv(r)
            spend = _safe_float(r.get("spend"))
            # Score: CTR-weighted + CV bonus
            score = ctr * 10 + (cv * 5 if cv > 0 else 0)

            ads.append(
                {
                    "ad_id": r.get("ad_id", ""),
                    "ad_name": r.get("ad_name", ""),
                    "impressions": int(_safe_float(r.get("impressions"))),
                    "clicks": int(_safe_float(r.get("clicks"))),
                    "spend": round(spend, 2),
                    "ctr": round(ctr, 2),
                    "cpc": round(cpc, 2),
                    "conversions": cv,
                    "score": round(score, 1),
                }
            )

        ads.sort(key=lambda x: x["score"], reverse=True)

        winner = None
        if len(ads) >= 2:
            w = ads[0]
            loser = ads[-1]
            reasons: list[str] = []
            if w["ctr"] > loser["ctr"]:
                reasons.append(f"CTR {w['ctr']}% > {loser['ctr']}%")
            if w["conversions"] > loser["conversions"]:
                reasons.append(f"CV {w['conversions']} > {loser['conversions']}")
            winner = {
                "ad_id": w["ad_id"],
                "ad_name": w["ad_name"],
                "reason": ", ".join(reasons) if reasons else "Highest overall score",
            }

        return {
            "ad_set_id": ad_set_id,
            "ads": ads,
            "winner": winner,
            **(
                {"message": "At least 2 ads are required for comparison"}
                if len(ads) < 2
                else {}
            ),
        }

    # =================================================================
    # Creative improvement suggestions
    # =================================================================

    async def suggest_creative_improvements(
        self,
        campaign_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """Generate creative improvement suggestions based on ad performance."""
        data = await self.get_performance_report(
            campaign_id=campaign_id, period=period, level="ad"
        )

        if not data:
            return {
                "campaign_id": campaign_id,
                "ad_count": 0,
                "suggestions": [],
            }

        ads: list[dict[str, Any]] = []
        for r in data:
            ctr = _safe_float(r.get("ctr"))
            cv = _extract_cv(r)
            spend = _safe_float(r.get("spend"))
            cpa = round(spend / cv, 0) if cv > 0 else None

            ads.append(
                {
                    "ad_id": r.get("ad_id", ""),
                    "ad_name": r.get("ad_name", ""),
                    "ctr": ctr,
                    "conversions": cv,
                    "spend": spend,
                    "cpa": cpa,
                }
            )

        suggestions: list[dict[str, Any]] = []

        # Detect low-CTR ads
        avg_ctr = sum(a["ctr"] for a in ads) / len(ads) if ads else 0
        for a in ads:
            if avg_ctr > 0 and a["ctr"] < avg_ctr * 0.5:
                suggestions.append(
                    {
                        "type": "low_ctr",
                        "ad_id": a["ad_id"],
                        "ad_name": a["ad_name"],
                        "priority": "HIGH",
                        "message": f"'{a['ad_name']}' CTR ({a['ctr']}%) is less than half the average ({round(avg_ctr, 2)}%). "
                        "Consider revising the headline or image.",
                    }
                )

        # Ads with 0 CV and high cost
        for a in ads:
            if a["conversions"] == 0 and a["spend"] > 0:
                suggestions.append(
                    {
                        "type": "zero_cv",
                        "ad_id": a["ad_id"],
                        "ad_name": a["ad_name"],
                        "priority": "MEDIUM",
                        "message": f"'{a['ad_name']}' has 0 CV with {a['spend']} in spend. "
                        "Consider pausing or replacing the creative.",
                    }
                )

        # Detect CPA disparity
        with_cpa = [a for a in ads if a["cpa"] is not None]
        if len(with_cpa) >= 2:
            best = min(with_cpa, key=lambda x: x["cpa"])
            for a in with_cpa:
                if a["ad_id"] != best["ad_id"] and a["cpa"] > best["cpa"] * 2:
                    suggestions.append(
                        {
                            "type": "high_cpa",
                            "ad_id": a["ad_id"],
                            "ad_name": a["ad_name"],
                            "priority": "MEDIUM",
                            "message": f"'{a['ad_name']}' CPA ({a['cpa']}) is "
                            f"{round(a['cpa'] / best['cpa'], 1)}x of the best ad ({best['cpa']}).",
                        }
                    )

        return {
            "campaign_id": campaign_id,
            "ad_count": len(ads),
            "suggestions": suggestions,
        }
