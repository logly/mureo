"""Meta Ads 分析系Mixin

プレースメント分析・コスト調査・A/B比較・クリエイティブ改善提案。
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
    """Meta Ads 分析系Mixin

    MetaAdsApiClientに多重継承して使用する。
    get_performance_report / get_breakdown_report は InsightsMixin が提供。
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
    # プレースメント分析
    # =================================================================

    async def analyze_placements(
        self,
        campaign_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """配信面別パフォーマンスを分析する。"""
        data = await self.get_breakdown_report(
            campaign_id=campaign_id,
            breakdown="publisher_platform",
            period=period,
        )

        if not data:
            return {
                "campaign_id": campaign_id,
                "period": period,
                "message": "配信面データがありません",
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
                    f"{worst['publisher_platform']}のCPA（{worst['cpa']}円）が"
                    f"{best['publisher_platform']}（{best['cpa']}円）の"
                    f"{round(worst['cpa'] / best['cpa'], 1)}倍です。"
                    "配信面の除外または入札調整を検討してください。"
                )

        for p in placements:
            if p["conversions"] == 0 and p["spend"] > 0:
                insights.append(
                    f"{p['publisher_platform']}はCV0で{p['spend']}円のコストが発生しています。"
                )

        return {
            "campaign_id": campaign_id,
            "period": period,
            "placements": placements,
            "insights": insights,
        }

    # =================================================================
    # コスト調査
    # =================================================================

    async def investigate_cost(
        self,
        campaign_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """広告費増加・CPA悪化の原因を調査する。"""
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
                "message": "パフォーマンスデータがありません",
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
            findings.append(f"広告費が前期比{spend_change}%増加しています")
        cpc_change = _pct(cur_cpc, prev_cpc)
        if cpc_change is not None and cpc_change > 15:
            findings.append(
                f"CPCが前期比{cpc_change}%上昇しています。競合の入札強化の可能性があります"
            )
        clicks_change = _pct(cur_clicks, prev_clicks)
        if clicks_change is not None and clicks_change > 20:
            findings.append(f"クリック数が前期比{clicks_change}%増加しています")

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
    # A/B比較
    # =================================================================

    async def compare_ads(
        self,
        ad_set_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """広告セット内の広告パフォーマンスをA/B比較する。"""
        data = await self.get_performance_report(
            campaign_id=None, period=period, level="ad"
        )

        # ad_set_id でフィルタ（レスポンスにadset_idが含まれる場合のみ）
        if ad_set_id:
            ads_data = [
                r
                for r in data
                if r.get("adset_id", "") == ad_set_id or not r.get("adset_id")
            ]
            # フィルタ結果が空なら該当広告セットのデータなしとして返す
            if not ads_data:
                return {"error": "No ads found for the specified ad_set_id", "ads": []}
        else:
            ads_data = data

        if not ads_data:
            return {
                "ad_set_id": ad_set_id,
                "ads": [],
                "winner": None,
                "message": "広告データがありません",
            }

        ads: list[dict[str, Any]] = []
        for r in ads_data:
            ctr = _safe_float(r.get("ctr"))
            cpc = _safe_float(r.get("cpc"))
            cv = _extract_cv(r)
            spend = _safe_float(r.get("spend"))
            # スコア: CTR重視 + CV加点
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
                "reason": "、".join(reasons) if reasons else "総合スコアが最も高い",
            }

        return {
            "ad_set_id": ad_set_id,
            "ads": ads,
            "winner": winner,
            **({"message": "比較には2つ以上の広告が必要です"} if len(ads) < 2 else {}),
        }

    # =================================================================
    # クリエイティブ改善提案
    # =================================================================

    async def suggest_creative_improvements(
        self,
        campaign_id: str,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """広告パフォーマンスに基づくクリエイティブ改善提案を生成する。"""
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

        # 低CTR広告の検出
        avg_ctr = sum(a["ctr"] for a in ads) / len(ads) if ads else 0
        for a in ads:
            if avg_ctr > 0 and a["ctr"] < avg_ctr * 0.5:
                suggestions.append(
                    {
                        "type": "low_ctr",
                        "ad_id": a["ad_id"],
                        "ad_name": a["ad_name"],
                        "priority": "HIGH",
                        "message": f"「{a['ad_name']}」のCTR（{a['ctr']}%）が平均（{round(avg_ctr, 2)}%）の半分以下です。"
                        "見出しや画像の見直しを検討してください。",
                    }
                )

        # CV0で高コストの広告
        for a in ads:
            if a["conversions"] == 0 and a["spend"] > 0:
                suggestions.append(
                    {
                        "type": "zero_cv",
                        "ad_id": a["ad_id"],
                        "ad_name": a["ad_name"],
                        "priority": "MEDIUM",
                        "message": f"「{a['ad_name']}」はCV0で{a['spend']}円のコストが発生しています。"
                        "一時停止またはクリエイティブの差し替えを検討してください。",
                    }
                )

        # CPA格差の検出
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
                            "message": f"「{a['ad_name']}」のCPA（{a['cpa']}円）が"
                            f"最良広告（{best['cpa']}円）の{round(a['cpa'] / best['cpa'], 1)}倍です。",
                        }
                    )

        return {
            "campaign_id": campaign_id,
            "ad_count": len(ads),
            "suggestions": suggestions,
        }
