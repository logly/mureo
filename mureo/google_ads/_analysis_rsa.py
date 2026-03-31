"""RSAアセット分析 Mixin。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _RsaAnalysisMixin:
    """RSAアセット分析系メソッドを提供する Mixin。"""

    # 親クラスが提供する属性・メソッドの型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _period_to_date_clause(self, period: str) -> str: ...  # type: ignore[empty-body]
    async def _search(self, query: str) -> list[Any]: ...  # type: ignore[empty-body]

    # =================================================================
    # RSAアセット別パフォーマンス分析
    # =================================================================

    async def analyze_rsa_assets(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """RSA広告のアセット別パフォーマンスを分析する。"""
        self._validate_id(campaign_id, "campaign_id")

        date_clause = self._period_to_date_clause(period)

        query = f"""
            SELECT
                ad_group_ad_asset_view.ad_group_ad,
                ad_group_ad_asset_view.asset,
                ad_group_ad_asset_view.field_type,
                ad_group_ad_asset_view.performance_label,
                asset.text_asset.text,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.cost_micros
            FROM ad_group_ad_asset_view
            WHERE campaign.id = {campaign_id}
                AND ad_group_ad_asset_view.enabled = TRUE
                AND segments.date {date_clause}
        """

        response = await self._search(query)

        headlines: list[dict[str, Any]] = []
        descriptions: list[dict[str, Any]] = []

        for row in response:
            view = row.ad_group_ad_asset_view
            asset_text = row.asset.text_asset.text if row.asset.text_asset else ""
            field_type = str(view.field_type).split(".")[-1] if view.field_type else ""
            perf_label = (
                str(view.performance_label).split(".")[-1]
                if view.performance_label
                else "UNKNOWN"
            )

            entry = {
                "text": asset_text,
                "performance_label": perf_label,
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": float(row.metrics.conversions),
                "cost": row.metrics.cost_micros / 1_000_000,
                "ctr": (
                    round(row.metrics.clicks / row.metrics.impressions * 100, 2)
                    if row.metrics.impressions > 0
                    else 0
                ),
            }

            if field_type == "HEADLINE":
                headlines.append(entry)
            elif field_type == "DESCRIPTION":
                descriptions.append(entry)

        # インプレッション降順でソート
        headlines.sort(key=lambda x: x["impressions"], reverse=True)
        descriptions.sort(key=lambda x: x["impressions"], reverse=True)

        # 勝ち・負けアセットの特定
        best_headlines = [h for h in headlines if h["performance_label"] == "BEST"]
        worst_headlines = [
            h for h in headlines if h["performance_label"] in ("LOW", "POOR")
        ]
        best_descriptions = [
            d for d in descriptions if d["performance_label"] == "BEST"
        ]
        worst_descriptions = [
            d for d in descriptions if d["performance_label"] in ("LOW", "POOR")
        ]

        # インサイト生成
        insights: list[str] = []
        if best_headlines:
            texts = [h["text"] for h in best_headlines[:3]]
            insights.append(f"高パフォーマンス見出し: {', '.join(texts)}")
        if worst_headlines:
            texts = [h["text"] for h in worst_headlines[:3]]
            insights.append(
                f"低パフォーマンス見出し（差し替え検討）: {', '.join(texts)}"
            )
        if not headlines:
            insights.append("アセット別パフォーマンスデータがまだ蓄積されていません")

        return {
            "campaign_id": campaign_id,
            "period": period,
            "headlines": headlines,
            "descriptions": descriptions,
            "best_headlines": best_headlines,
            "worst_headlines": worst_headlines,
            "best_descriptions": best_descriptions,
            "worst_descriptions": worst_descriptions,
            "insights": insights,
        }

    # =================================================================
    # RSAアセット棚卸し
    # =================================================================

    async def audit_rsa_assets(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """RSAアセットの棚卸しを行い、差し替え・追加の推奨を生成する。"""
        self._validate_id(campaign_id, "campaign_id")

        try:
            asset_data = await self.analyze_rsa_assets(campaign_id, period)
        except Exception as exc:
            return {"error": f"RSAアセットデータの取得に失敗しました: {exc}"}

        if not asset_data.get("headlines") and not asset_data.get("descriptions"):
            return {
                "campaign_id": campaign_id,
                "period": period,
                "message": "RSAアセットデータがありません",
                "recommendations": [],
            }

        headlines = asset_data.get("headlines", [])
        descriptions = asset_data.get("descriptions", [])

        recommendations: list[dict[str, Any]] = []
        label_dist = self._count_label_distribution(headlines, descriptions)

        # アセット数チェック
        self._check_asset_counts(len(headlines), len(descriptions), recommendations)

        # LOW/POORアセットの差し替え推奨
        self._recommend_asset_replacements(
            asset_data.get("worst_headlines", []),
            asset_data.get("worst_descriptions", []),
            recommendations,
        )

        # LEARNING/UNKNOWNが多い場合の注意
        learning_count = label_dist.get("LEARNING", 0) + label_dist.get("UNKNOWN", 0)
        total = sum(label_dist.values())
        if total > 0 and learning_count / total > 0.5:
            recommendations.append(
                {
                    "type": "wait_for_data",
                    "priority": "LOW",
                    "message": f"アセットの{round(learning_count / total * 100)}%がまだ学習中・未評価です。"
                    "十分なデータが蓄積されてから棚卸しを行うことを推奨します。",
                }
            )

        return {
            "campaign_id": campaign_id,
            "period": period,
            "headline_count": len(headlines),
            "description_count": len(descriptions),
            "label_distribution": label_dist,
            "best_headlines": asset_data.get("best_headlines", []),
            "worst_headlines": asset_data.get("worst_headlines", []),
            "best_descriptions": asset_data.get("best_descriptions", []),
            "worst_descriptions": asset_data.get("worst_descriptions", []),
            "recommendations": recommendations,
            "recommendation_count": len(recommendations),
        }

    @staticmethod
    def _count_label_distribution(
        headlines: list[dict[str, Any]],
        descriptions: list[dict[str, Any]],
    ) -> dict[str, int]:
        """パフォーマンスラベルの分布を集計する。"""
        dist: dict[str, int] = {}
        for asset in headlines + descriptions:
            label = asset.get("performance_label", "UNKNOWN")
            dist[label] = dist.get(label, 0) + 1
        return dist

    @staticmethod
    def _check_asset_counts(
        headline_count: int,
        description_count: int,
        recommendations: list[dict[str, Any]],
    ) -> None:
        """アセット数の過不足をチェックし推奨を追加する。"""
        if headline_count < 8:
            recommendations.append(
                {
                    "type": "add_headlines",
                    "priority": "HIGH",
                    "message": f"見出しが{headline_count}本しかありません。"
                    "Google推奨は最低8本（理想15本）です。見出しを追加してください。",
                }
            )
        if description_count < 3:
            recommendations.append(
                {
                    "type": "add_descriptions",
                    "priority": "HIGH",
                    "message": f"説明文が{description_count}本しかありません。"
                    "Google推奨は最低3本（理想4本）です。説明文を追加してください。",
                }
            )

    @staticmethod
    def _recommend_asset_replacements(
        worst_headlines: list[dict[str, Any]],
        worst_descriptions: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
    ) -> None:
        """LOW/POORアセットの差し替え推奨を追加する。"""
        for asset in worst_headlines:
            recommendations.append(
                {
                    "type": "replace_headline",
                    "priority": "MEDIUM",
                    "asset_text": asset["text"],
                    "performance_label": asset["performance_label"],
                    "message": f"見出し「{asset['text']}」がパフォーマンス{asset['performance_label']}です。"
                    "差し替えを検討してください。",
                }
            )
        for asset in worst_descriptions:
            recommendations.append(
                {
                    "type": "replace_description",
                    "priority": "MEDIUM",
                    "asset_text": asset["text"],
                    "performance_label": asset["performance_label"],
                    "message": f"説明文「{asset['text']}」がパフォーマンス{asset['performance_label']}です。"
                    "差し替えを検討してください。",
                }
            )
