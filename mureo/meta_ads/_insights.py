from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Meta APIのdate_presetマッピング
_PERIOD_TO_DATE_PRESET: dict[str, str] = {
    "today": "today",
    "yesterday": "yesterday",
    "last_7d": "last_7d",
    "last_30d": "last_30d",
    "this_month": "this_month",
    "last_month": "last_month",
}

# Insightsの共通取得フィールド
_INSIGHTS_FIELDS = (
    "campaign_name,campaign_id,adset_name,adset_id,ad_name,ad_id,"
    "impressions,clicks,spend,cpc,cpm,ctr,"
    "actions,cost_per_action_type,"
    "reach,frequency"
)


class InsightsMixin:
    """Meta Ads インサイト（パフォーマンスレポート）操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def get_performance_report(
        self,
        *,
        campaign_id: str | None = None,
        period: str = "last_7d",
        level: str = "campaign",
    ) -> list[dict[str, Any]]:
        """パフォーマンスレポートを取得する

        Args:
            campaign_id: キャンペーンID（指定時はそのキャンペーンのみ）
            period: 期間（today, yesterday, last_7d, last_30d, this_month, last_month）
            level: 集計レベル（campaign, adset, ad）

        Returns:
            インサイトデータのリスト
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
        return result.get("data", [])

    async def analyze_performance(
        self,
        *,
        campaign_id: str | None = None,
        period: str = "last_7d",
    ) -> dict[str, Any]:
        """キャンペーンのパフォーマンスを総合分析する。

        当期と前期のインサイトを比較し、問題点とインサイトを生成する。
        """
        current = await self.get_performance_report(
            campaign_id=campaign_id, period=period
        )

        # 前期データ取得
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
            insights.append(f"表示回数が前期比{imp_change}%減少しています")

        click_change = _change_pct(cur_clicks, prev_clicks)
        if click_change is not None and click_change < -20:
            insights.append(f"クリック数が前期比{click_change}%減少しています")

        spend_change = _change_pct(cur_spend, prev_spend)
        if spend_change is not None and spend_change > 30:
            insights.append(f"広告費が前期比{spend_change}%増加しています")

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
        """年齢×性別のブレイクダウンからオーディエンス効率を分析する。"""
        breakdown_data = await self.get_breakdown_report(
            campaign_id=campaign_id,
            breakdown="age,gender",
            period=period,
        )

        if not breakdown_data:
            return {
                "campaign_id": campaign_id,
                "period": period,
                "message": "ブレイクダウンデータがありません",
                "segments": [],
                "insights": [],
            }

        segments: list[dict[str, Any]] = []
        for row in breakdown_data:
            spend = float(row.get("spend", 0) or 0)
            clicks = int(row.get("clicks", 0) or 0)
            impressions = int(row.get("impressions", 0) or 0)
            ctr = float(row.get("ctr", 0) or 0)

            # actionsからCV数を抽出
            actions = row.get("actions", [])
            conversions = 0.0
            if actions:
                for a in actions:
                    if a.get("action_type") in ("lead", "purchase", "complete_registration"):
                        conversions += float(a.get("value", 0))

            cpa = round(spend / conversions, 0) if conversions > 0 else None

            segments.append({
                "age": row.get("age", ""),
                "gender": row.get("gender", ""),
                "impressions": impressions,
                "clicks": clicks,
                "spend": round(spend, 2),
                "ctr": round(ctr, 2),
                "conversions": conversions,
                "cpa": cpa,
            })

        # コスト降順ソート
        segments.sort(key=lambda x: x["spend"], reverse=True)

        insights: list[str] = []

        # CPA算出可能なセグメントでベスト・ワーストを比較
        with_cpa = [s for s in segments if s["cpa"] is not None]
        if len(with_cpa) >= 2:
            best = min(with_cpa, key=lambda x: x["cpa"])
            worst = max(with_cpa, key=lambda x: x["cpa"])
            if worst["cpa"] > best["cpa"] * 2:
                insights.append(
                    f"{worst['age']}・{worst['gender']}のCPA（{worst['cpa']}円）が"
                    f"{best['age']}・{best['gender']}（{best['cpa']}円）の"
                    f"{round(worst['cpa'] / best['cpa'], 1)}倍です。"
                    "ターゲティングの見直しを検討してください。"
                )

        # CV0で高コストのセグメント
        for s in segments:
            if s["conversions"] == 0 and s["spend"] > 0:
                insights.append(
                    f"{s['age']}・{s['gender']}はCV0で{s['spend']}円のコストが発生しています。"
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
        """ブレイクダウン付きレポートを取得する

        Args:
            campaign_id: キャンペーンID
            breakdown: ブレイクダウン種別（age, gender, age,gender,
                       country, region, publisher_platform等）
            period: 期間（today, yesterday, last_7d, last_30d, this_month, last_month）

        Returns:
            ブレイクダウン付きインサイトデータのリスト
        """
        date_preset = _PERIOD_TO_DATE_PRESET.get(period, "last_7d")

        params: dict[str, Any] = {
            "fields": _INSIGHTS_FIELDS,
            "date_preset": date_preset,
            "breakdowns": breakdown,
        }

        result = await self._get(f"/{campaign_id}/insights", params)
        return result.get("data", [])
