"""予算効率分析 Mixin。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._analysis_constants import _safe_metrics

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _BudgetAnalysisMixin:
    """予算配分効率分析系メソッドを提供する Mixin。"""

    # 親クラスが提供する属性・メソッドの型宣言
    _customer_id: str
    _client: GoogleAdsClient

    async def list_campaigns(
        self, status_filter: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def get_performance_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    async def get_budget(self, campaign_id: str) -> dict[str, Any] | None: ...

    # =================================================================
    # 予算配分効率分析
    # =================================================================

    async def analyze_budget_efficiency(
        self,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """全有効キャンペーンの予算配分効率を分析する。"""
        campaigns = await self.list_campaigns(status_filter="ENABLED")

        campaign_data: list[dict[str, Any]] = []
        total_cost: float = 0.0
        total_conversions: float = 0.0

        for camp in campaigns:
            cid = str(camp.get("id", ""))
            try:
                perf = await self.get_performance_report(campaign_id=cid, period=period)
                m = _safe_metrics(perf)
                cost = float(m.get("cost", 0))
                convs = float(m.get("conversions", 0))
            except Exception:
                logger.warning(
                    "キャンペーン %s のパフォーマンス取得に失敗",
                    cid,
                    exc_info=True,
                )
                cost = 0.0
                convs = 0.0

            total_cost += cost
            total_conversions += convs
            campaign_data.append(
                {
                    "campaign_id": cid,
                    "name": camp.get("name", ""),
                    "cost": cost,
                    "conversions": convs,
                }
            )

        # コストシェア・CVシェア・効率比を算出
        enriched_data: list[dict[str, Any]] = []
        for cd in campaign_data:
            cost_share = cd["cost"] / total_cost if total_cost > 0 else 0.0
            cv_share = (
                cd["conversions"] / total_conversions if total_conversions > 0 else 0.0
            )
            if cost_share > 0:
                ratio = round(cv_share / cost_share, 2)
                if ratio > 1.2:
                    verdict = "EFFICIENT"
                elif ratio < 0.8:
                    verdict = "INEFFICIENT"
                else:
                    verdict = "NORMAL"
            else:
                ratio = None
                verdict = "NO_COST"
            cpa = (
                round(cd["cost"] / cd["conversions"], 0)
                if cd["conversions"] > 0
                else None
            )
            enriched_data.append(
                {
                    **cd,
                    "cost_share": round(cost_share, 4),
                    "cv_share": round(cv_share, 4),
                    "efficiency_ratio": ratio,
                    "verdict": verdict,
                    "cpa": cpa,
                }
            )

        # 推奨事項
        recommendations: list[str] = []
        inefficient = [c for c in enriched_data if c.get("verdict") == "INEFFICIENT"]
        efficient = [c for c in enriched_data if c.get("verdict") == "EFFICIENT"]
        if inefficient:
            names = ", ".join(c["name"] for c in inefficient[:3])
            recommendations.append(
                f"非効率なキャンペーン（{names}）の予算を削減し、"
                "効率の良いキャンペーンへ再配分することを検討してください"
            )
        if efficient:
            names = ", ".join(c["name"] for c in efficient[:3])
            recommendations.append(
                f"効率の良いキャンペーン（{names}）の予算増額を検討してください"
            )

        # インサイト
        insights: list[str] = []
        if total_conversions > 0:
            overall_cpa = total_cost / total_conversions
            insights.append(f"全体CPAは ¥{overall_cpa:,.0f} です")
        if len(enriched_data) > 1:
            normal_count = len(
                [c for c in enriched_data if c.get("verdict") == "NORMAL"]
            )
            insights.append(
                f"効率的: {len(efficient)}件、通常: {normal_count}件、"
                f"非効率: {len(inefficient)}件"
            )

        return {
            "period": period,
            "total_cost": round(total_cost, 0),
            "total_conversions": round(total_conversions, 1),
            "campaigns": enriched_data,
            "recommendations": recommendations,
            "insights": insights,
        }

    # =================================================================
    # 予算再配分提案
    # =================================================================

    async def suggest_budget_reallocation(
        self,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """全キャンペーンの予算配分効率を分析し、具体的な再配分案を生成する。"""
        efficiency = await self.analyze_budget_efficiency(period=period)
        campaigns = efficiency.get("campaigns", [])
        total_cost = efficiency.get("total_cost", 0)

        if not campaigns or total_cost == 0:
            return {
                **efficiency,
                "reallocation_plan": [],
                "summary": "データ不足のため再配分提案を生成できません",
            }

        # 各キャンペーンの現在の日予算を取得
        for camp in campaigns:
            cid = camp.get("campaign_id", "")
            try:
                budget_info = await self.get_budget(cid)
                camp["current_daily_budget"] = (
                    budget_info.get("daily_budget", 0) if budget_info else 0
                )
                camp["budget_id"] = budget_info.get("id", "") if budget_info else ""
            except Exception:
                logger.warning("キャンペーン %s の予算取得に失敗", cid, exc_info=True)
                camp["current_daily_budget"] = 0
                camp["budget_id"] = ""

        # 再配分ロジック: 非効率→効率への移動
        inefficient = [
            c
            for c in campaigns
            if c.get("verdict") == "INEFFICIENT"
            and c.get("current_daily_budget", 0) > 0
        ]
        efficient = [c for c in campaigns if c.get("verdict") == "EFFICIENT"]

        reallocation_plan: list[dict[str, Any]] = []
        total_freed: float = 0.0

        # 非効率キャンペーンから最大20%削減
        for camp in inefficient:
            current = camp["current_daily_budget"]
            reduction = round(current * 0.2)
            if reduction < 100:
                continue
            new_budget = current - reduction
            reallocation_plan.append(
                {
                    "campaign_id": camp["campaign_id"],
                    "campaign_name": camp.get("name", ""),
                    "action": "DECREASE",
                    "current_daily_budget": current,
                    "proposed_daily_budget": new_budget,
                    "change_amount": -reduction,
                    "reason": (
                        f"効率比 {camp.get('efficiency_ratio', 0)} "
                        f"(CPA: ¥{camp.get('cpa', 0):,.0f})"
                    ),
                }
            )
            total_freed += reduction

        # 効率キャンペーンに均等配分
        if efficient and total_freed > 0:
            per_campaign = round(total_freed / len(efficient))
            for camp in efficient:
                current = camp.get("current_daily_budget", 0)
                new_budget = current + per_campaign
                reallocation_plan.append(
                    {
                        "campaign_id": camp["campaign_id"],
                        "campaign_name": camp.get("name", ""),
                        "action": "INCREASE",
                        "current_daily_budget": current,
                        "proposed_daily_budget": new_budget,
                        "change_amount": per_campaign,
                        "reason": (
                            f"効率比 {camp.get('efficiency_ratio', 0)} "
                            f"(CPA: ¥{camp.get('cpa', 0):,.0f})"
                        ),
                    }
                )

        summary_parts: list[str] = []
        decreases = [p for p in reallocation_plan if p["action"] == "DECREASE"]
        increases = [p for p in reallocation_plan if p["action"] == "INCREASE"]
        if decreases:
            summary_parts.append(
                f"削減対象: {len(decreases)}件（合計 ¥{total_freed:,.0f}/日）"
            )
        if increases:
            summary_parts.append(f"増額対象: {len(increases)}件")
        if not reallocation_plan:
            summary_parts.append("現在の予算配分は適切です。再配分の必要はありません")

        return {
            **efficiency,
            "reallocation_plan": reallocation_plan,
            "total_freed": total_freed,
            "summary": "。".join(summary_parts),
        }
