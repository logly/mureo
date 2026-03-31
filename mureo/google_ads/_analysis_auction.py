"""オークション分析・CPC検出・デバイス分析 Mixin。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _AuctionAnalysisMixin:
    """オークション分析・CPC検出・デバイス分析系メソッドを提供する Mixin。"""

    # 親クラスが提供する属性・メソッドの型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _period_to_date_clause(self, period: str) -> str: ...  # type: ignore[empty-body]
    async def _search(self, query: str) -> list[Any]: ...  # type: ignore[empty-body]
    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...

    # =================================================================
    # デバイス別CPA分析
    # =================================================================

    async def analyze_device_performance(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """デバイス別（PC/モバイル/タブレット）のCPA・CVR等を比較分析する。"""
        self._validate_id(campaign_id, "campaign_id")

        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"キャンペーンID {campaign_id} が見つかりません"}

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
            return {"error": f"デバイス別パフォーマンスの取得に失敗しました: {exc}"}

        if not rows:
            return {
                "campaign_id": campaign_id,
                "campaign_name": campaign.get("name", ""),
                "period": period,
                "message": "デバイス別データがありません",
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

        # コスト降順ソート
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
        """デバイス別データからインサイトを生成する。"""
        insights: list[str] = []

        # CV0のデバイスにコストが発生している場合
        for d in devices:
            if d["conversions"] == 0 and d["cost"] > 0:
                insights.append(
                    f"{d['device_type']}はCV0で{d['cost']}円のコストが発生しています。"
                    "入札調整率の引き下げまたは配信除外を検討してください。"
                )

        # CPA が算出可能なデバイスのみ比較
        devices_with_cpa = [d for d in devices if d["cpa"] is not None]
        if len(devices_with_cpa) >= 2:
            best = min(devices_with_cpa, key=lambda x: x["cpa"])
            worst = max(devices_with_cpa, key=lambda x: x["cpa"])

            if best["device_type"] != worst["device_type"] and worst["cpa"] > 0:
                ratio = worst["cpa"] / best["cpa"]
                if ratio > 1.5:
                    insights.append(
                        f"{worst['device_type']}のCPA（{worst['cpa']}円）が"
                        f"{best['device_type']}（{best['cpa']}円）の{round(ratio, 1)}倍です。"
                        f"{worst['device_type']}の入札調整率引き下げを検討してください。"
                    )

        # モバイルvsPCのCTR比較
        mobile = next((d for d in devices if d["device_type"] in ("MOBILE", "2")), None)
        desktop = next(
            (d for d in devices if d["device_type"] in ("DESKTOP", "1")), None
        )
        if mobile and desktop and desktop["ctr"] > 0:
            ctr_ratio = mobile["ctr"] / desktop["ctr"]
            if ctr_ratio < 0.5:
                insights.append(
                    f"モバイルのCTR（{mobile['ctr']}%）がPC（{desktop['ctr']}%）の半分以下です。"
                    "モバイル向け広告文やLP最適化を検討してください。"
                )

        return insights

    # =================================================================
    # CPC上昇トレンド検出
    # =================================================================

    async def detect_cpc_trend(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """日別CPCデータを取得し、上昇トレンドを検出する。"""
        self._validate_id(campaign_id, "campaign_id")

        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"キャンペーンID {campaign_id} が見つかりません"}

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
            return {"error": f"日別CPCデータの取得に失敗しました: {exc}"}

        if not rows:
            return {
                "campaign_id": campaign_id,
                "campaign_name": campaign.get("name", ""),
                "period": period,
                "message": "CPC データがありません（クリック0日のみ）",
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
        """CPC値のリストからトレンド情報を計算する。"""
        n = len(cpc_values)
        if n < 2:
            return {
                "direction": "insufficient_data",
                "slope_per_day": 0.0,
                "avg_cpc": cpc_values[0] if cpc_values else 0.0,
                "min_cpc": min(cpc_values) if cpc_values else 0.0,
                "max_cpc": max(cpc_values) if cpc_values else 0.0,
            }

        # 簡易線形回帰
        x_mean = (n - 1) / 2.0
        y_mean = sum(cpc_values) / n
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(cpc_values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0.0

        # 変化率（%/日）
        change_rate_per_day = (slope / y_mean * 100) if y_mean > 0 else 0.0

        # トレンド方向判定
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
        """CPCトレンドからインサイトを生成する。"""
        insights: list[str] = []
        direction = trend_info.get("direction", "stable")

        if direction == "rising":
            rate = trend_info["change_rate_per_day_pct"]
            insights.append(
                f"CPCが上昇トレンドです（1日あたり約{rate}%上昇）。"
                "競合の入札強化やオークション環境の変化が考えられます。"
            )
        elif direction == "falling":
            rate = abs(trend_info["change_rate_per_day_pct"])
            insights.append(
                f"CPCが下降トレンドです（1日あたり約{rate}%低下）。"
                "競合の撤退やキーワード品質スコアの改善が考えられます。"
            )

        # 直近7日 vs 前7日の比較
        if len(cpc_values) >= 14:
            recent_7 = cpc_values[-7:]
            prev_7 = cpc_values[-14:-7]
            recent_avg = sum(recent_7) / len(recent_7)
            prev_avg = sum(prev_7) / len(prev_7)
            if prev_avg > 0:
                week_change = (recent_avg - prev_avg) / prev_avg * 100
                if week_change > 15:
                    insights.append(
                        f"直近7日の平均CPC（{round(recent_avg, 1)}円）が"
                        f"前7日（{round(prev_avg, 1)}円）比で{round(week_change, 1)}%急騰しています。"
                        "早急な原因調査を推奨します。"
                    )
                elif week_change < -15:
                    insights.append(
                        f"直近7日の平均CPC（{round(recent_avg, 1)}円）が"
                        f"前7日（{round(prev_avg, 1)}円）比で{round(abs(week_change), 1)}%低下しています。"
                    )

        # スパイク検出（平均の2倍超の日）
        avg_cpc = trend_info.get("avg_cpc", 0)
        if avg_cpc > 0:
            spikes = [d for d in daily_data if d["average_cpc"] > avg_cpc * 2]
            if spikes:
                spike_dates = ", ".join(s["date"] for s in spikes[:3])
                insights.append(
                    f"CPC異常値（平均の2倍超）を{len(spikes)}日検出: {spike_dates}。"
                    "特定日の競合激化や品質スコア低下の可能性があります。"
                )

        return insights

    # =================================================================
    # オークション分析（Auction Insights）
    # =================================================================

    async def get_auction_insights(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """キャンペーンのオークション分析データをGAQLで取得する。"""
        self._validate_id(campaign_id, "campaign_id")
        date_clause = self._period_to_date_clause(period)

        query = f"""
            SELECT
                auction_insight.display_domain,
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
            logger.warning("オークション分析データ取得失敗: %s", exc)
            return []

        results: list[dict[str, Any]] = []
        for row in rows:
            ai = row.auction_insight
            m = row.metrics
            results.append(
                {
                    "display_domain": ai.display_domain,
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
        """キャンペーンのオークション分析を実行し、競合状況のインサイトを生成する。"""
        self._validate_id(campaign_id, "campaign_id")

        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"キャンペーンID {campaign_id} が見つかりません"}

        auction_data = await self.get_auction_insights(campaign_id, period)
        if not auction_data:
            return {
                "campaign_id": campaign_id,
                "campaign_name": campaign.get("name", ""),
                "period": period,
                "message": "オークション分析データがありません（検索キャンペーン以外またはデータ不足）",
                "competitors": [],
                "insights": [],
            }

        # 自社データを取り出す（display_domain が空文字列 = 自社）
        my_data: dict[str, Any] | None = None
        competitors: list[dict[str, Any]] = []
        for entry in auction_data:
            if entry["display_domain"] == "":
                my_data = entry
            else:
                competitors.append(entry)

        insights: list[str] = []

        if my_data:
            is_pct = my_data["impression_share"]
            if is_pct < 50:
                insights.append(
                    f"自社のインプレッションシェアが{is_pct}%と低く、"
                    "表示機会の半分以上を逃しています。予算またはキーワード入札の見直しを検討してください。"
                )
            elif is_pct < 70:
                insights.append(
                    f"自社のインプレッションシェアは{is_pct}%です。"
                    "競合に一部の表示機会を奪われています。"
                )

            abs_top = my_data["abs_top_impression_pct"]
            if abs_top < 20:
                insights.append(
                    f"最上位表示率が{abs_top}%と低く、検索結果の最上位にほとんど表示されていません。"
                    "入札単価の引き上げや広告品質の改善を検討してください。"
                )

        # 競合分析
        strong_competitors = [c for c in competitors if c["impression_share"] > 30]
        if strong_competitors:
            top_comp = strong_competitors[0]
            insights.append(
                f"最大の競合は「{top_comp['display_domain']}」"
                f"（IS: {top_comp['impression_share']}%、"
                f"上位表示率: {top_comp['top_impression_pct']}%）です。"
            )

        for comp in competitors[:5]:
            if comp["outranking_share"] > 50 and my_data:
                insights.append(
                    f"「{comp['display_domain']}」に{comp['outranking_share']}%の"
                    "確率で上回られています。入札戦略の見直しを検討してください。"
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
