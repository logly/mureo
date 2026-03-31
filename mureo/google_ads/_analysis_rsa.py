"""RSA asset analysis mixin."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _RsaAnalysisMixin:
    """Mixin providing RSA asset analysis methods."""

    # Type declarations for attributes/methods provided by parent class
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _period_to_date_clause(self, period: str) -> str: ...  # type: ignore[empty-body]
    async def _search(self, query: str) -> list[Any]: ...  # type: ignore[empty-body]

    # =================================================================
    # RSA asset performance analysis
    # =================================================================

    async def analyze_rsa_assets(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """Analyze RSA ad performance by asset."""
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

        # Sort by impressions descending
        headlines.sort(key=lambda x: x["impressions"], reverse=True)
        descriptions.sort(key=lambda x: x["impressions"], reverse=True)

        # Identify winning and losing assets
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

        # Insight generation
        insights: list[str] = []
        if best_headlines:
            texts = [h["text"] for h in best_headlines[:3]]
            insights.append(f"High-performance headlines: {', '.join(texts)}")
        if worst_headlines:
            texts = [h["text"] for h in worst_headlines[:3]]
            insights.append(
                f"Low-performance headlines (consider replacing): {', '.join(texts)}"
            )
        if not headlines:
            insights.append("Asset-level performance data has not yet been accumulated")

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
    # RSA asset audit
    # =================================================================

    async def audit_rsa_assets(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """Audit RSA assets and generate replacement/addition recommendations."""
        self._validate_id(campaign_id, "campaign_id")

        try:
            asset_data = await self.analyze_rsa_assets(campaign_id, period)
        except Exception as exc:
            return {"error": f"Failed to retrieve RSA asset data: {exc}"}

        if not asset_data.get("headlines") and not asset_data.get("descriptions"):
            return {
                "campaign_id": campaign_id,
                "period": period,
                "message": "No RSA asset data available",
                "recommendations": [],
            }

        headlines = asset_data.get("headlines", [])
        descriptions = asset_data.get("descriptions", [])

        recommendations: list[dict[str, Any]] = []
        label_dist = self._count_label_distribution(headlines, descriptions)

        # Check asset counts
        self._check_asset_counts(len(headlines), len(descriptions), recommendations)

        # Recommend replacing LOW/POOR assets
        self._recommend_asset_replacements(
            asset_data.get("worst_headlines", []),
            asset_data.get("worst_descriptions", []),
            recommendations,
        )

        # Warning when LEARNING/UNKNOWN assets are dominant
        learning_count = label_dist.get("LEARNING", 0) + label_dist.get("UNKNOWN", 0)
        total = sum(label_dist.values())
        if total > 0 and learning_count / total > 0.5:
            recommendations.append(
                {
                    "type": "wait_for_data",
                    "priority": "LOW",
                    "message": f"{round(learning_count / total * 100)}% of assets are still in learning/unevaluated state. "
                    "We recommend waiting for sufficient data before conducting an audit.",
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
        """Aggregate performance label distribution."""
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
        """Check asset count adequacy and add recommendations."""
        if headline_count < 8:
            recommendations.append(
                {
                    "type": "add_headlines",
                    "priority": "HIGH",
                    "message": f"Only {headline_count} headlines. "
                    "Google recommends at least 8 (ideally 15). Please add more headlines.",
                }
            )
        if description_count < 3:
            recommendations.append(
                {
                    "type": "add_descriptions",
                    "priority": "HIGH",
                    "message": f"Only {description_count} descriptions. "
                    "Google recommends at least 3 (ideally 4). Please add more descriptions.",
                }
            )

    @staticmethod
    def _recommend_asset_replacements(
        worst_headlines: list[dict[str, Any]],
        worst_descriptions: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
    ) -> None:
        """Add replacement recommendations for LOW/POOR assets."""
        for asset in worst_headlines:
            recommendations.append(
                {
                    "type": "replace_headline",
                    "priority": "MEDIUM",
                    "asset_text": asset["text"],
                    "performance_label": asset["performance_label"],
                    "message": f"Headline \"{asset['text']}\" has {asset['performance_label']} performance. "
                    "Consider replacing it.",
                }
            )
        for asset in worst_descriptions:
            recommendations.append(
                {
                    "type": "replace_description",
                    "priority": "MEDIUM",
                    "asset_text": asset["text"],
                    "performance_label": asset["performance_label"],
                    "message": f"Description \"{asset['text']}\" has {asset['performance_label']} performance. "
                    "Consider replacing it.",
                }
            )
