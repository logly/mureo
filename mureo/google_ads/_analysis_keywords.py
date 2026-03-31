"""キーワード棚卸し Mixin。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._analysis_constants import (
    _MATCH_TYPE_MAP,
    _STATUS_MAP,
    _resolve_enum,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _KeywordsAnalysisMixin:
    """キーワード棚卸し系メソッドを提供する Mixin。"""

    # 親クラスが提供する属性・メソッドの型宣言
    _customer_id: str
    _client: "GoogleAdsClient"

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _period_to_date_clause(self, period: str) -> str: ...
    async def _search(self, query: str) -> list[Any]: ...

    # PerformanceAnalysisMixin のメソッド
    async def _resolve_target_cpa(
        self, campaign_id: str, explicit: float | None = None
    ) -> tuple[float | None, str]: ...

    # =================================================================
    # キーワードパフォーマンス取得
    # =================================================================

    async def _get_keyword_performance(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """keyword_view から各キーワードのパフォーマンスを取得する。"""
        self._validate_id(campaign_id, "campaign_id")
        date_clause = self._period_to_date_clause(period)
        query = (
            "SELECT "
            "ad_group_criterion.criterion_id, "
            "ad_group_criterion.keyword.text, "
            "ad_group_criterion.keyword.match_type, "
            "ad_group_criterion.status, "
            "ad_group.id, "
            "metrics.impressions, "
            "metrics.clicks, "
            "metrics.cost_micros, "
            "metrics.conversions "
            f"FROM keyword_view "
            f"WHERE campaign.id = {campaign_id} "
            f"AND segments.date {date_clause} "
            "AND ad_group_criterion.status != 'REMOVED'"
        )
        try:
            response = await self._search(query)
        except Exception:
            logger.warning("キーワードパフォーマンス取得に失敗: campaign_id=%s", campaign_id)
            return []
        results: list[dict[str, Any]] = []
        for row in response:
            cost_micros = row.metrics.cost_micros
            raw_match = row.ad_group_criterion.keyword.match_type
            raw_status = row.ad_group_criterion.status
            results.append({
                "criterion_id": str(row.ad_group_criterion.criterion_id),
                "ad_group_id": str(row.ad_group.id),
                "text": row.ad_group_criterion.keyword.text,
                "match_type": _resolve_enum(raw_match, _MATCH_TYPE_MAP),
                "status": _resolve_enum(raw_status, _STATUS_MAP),
                "metrics": {
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost_micros / 1_000_000,
                    "conversions": row.metrics.conversions,
                },
            })
        return results

    # =================================================================
    # キーワード棚卸し
    # =================================================================

    async def audit_keywords(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
        target_cpa: float | None = None,
    ) -> dict[str, Any]:
        """キーワードの棚卸しを行い、改善アクションを提案する。"""
        self._validate_id(campaign_id, "campaign_id")

        effective_target = target_cpa

        # 目標CPA解決
        resolved_cpa, cpa_source = await self._resolve_target_cpa(
            campaign_id, explicit=effective_target
        )

        # キーワードパフォーマンス取得
        kw_perf = await self._get_keyword_performance(campaign_id, period)

        # 平均CVRを算出
        total_clicks = sum(float(k["metrics"]["clicks"]) for k in kw_perf)
        total_convs = sum(float(k["metrics"]["conversions"]) for k in kw_perf)
        avg_cvr = total_convs / total_clicks if total_clicks > 0 else 0.0

        recommendations: list[dict[str, Any]] = []

        for kw in kw_perf:
            rec = self._evaluate_keyword(kw, resolved_cpa, avg_cvr)
            if rec is not None:
                recommendations.append(rec)

        # 優先度順ソート
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        recommendations.sort(key=lambda x: priority_order.get(x["priority"], 99))

        return {
            "campaign_id": campaign_id,
            "period": period,
            "target_cpa": resolved_cpa,
            "target_cpa_source": cpa_source,
            "total_keywords": len(kw_perf),
            "avg_cvr": round(avg_cvr, 4),
            "recommendations": recommendations,
            "summary": {
                "high_priority": len([r for r in recommendations if r["priority"] == "HIGH"]),
                "medium_priority": len([r for r in recommendations if r["priority"] == "MEDIUM"]),
                "low_priority": len([r for r in recommendations if r["priority"] == "LOW"]),
            },
        }

    @staticmethod
    def _evaluate_keyword(
        kw: dict[str, Any],
        resolved_cpa: float | None,
        avg_cvr: float,
    ) -> dict[str, Any] | None:
        """キーワード1件を評価し、推奨アクションを返す。Noneの場合はアクション不要。"""
        m = kw["metrics"]
        conversions = float(m["conversions"])
        clicks = int(m["clicks"])
        cost = float(m["cost"])
        impressions = int(m["impressions"])
        match_type = kw["match_type"]
        cvr = conversions / clicks if clicks > 0 else 0.0

        base = {
            "keyword": kw["text"],
            "criterion_id": kw["criterion_id"],
            "ad_group_id": kw["ad_group_id"],
            "current_match_type": match_type,
            "metrics": m,
        }

        # Rule 1: BROAD & CV=0 & コスト>目標CPA → narrow_to_phrase (HIGH)
        if match_type == "BROAD" and conversions == 0 and resolved_cpa is not None and cost > resolved_cpa:
            return {
                **base,
                "action": "narrow_to_phrase",
                "priority": "HIGH",
                "reason": f"部分一致でCV0、コスト ¥{cost:,.0f} > 目標CPA ¥{resolved_cpa:,.0f}",
            }

        # Rule 2: 全タイプ & CV=0 & Click>50 → pause (HIGH)
        if conversions == 0 and clicks > 50:
            return {
                **base,
                "action": "pause",
                "priority": "HIGH",
                "reason": f"CV0でクリック{clicks}回（コスト ¥{cost:,.0f}）",
            }

        # Rule 3: PHRASE & CVR>平均CVR×1.5 → add_exact (MEDIUM)
        if match_type == "PHRASE" and avg_cvr > 0 and cvr > avg_cvr * 1.5:
            return {
                **base,
                "action": "add_exact",
                "priority": "MEDIUM",
                "reason": f"CVR {cvr:.2%} > 平均CVR×1.5 ({avg_cvr * 1.5:.2%})",
            }

        # Rule 4: EXACT & Imp<50 → expand_to_phrase (LOW)
        if match_type == "EXACT" and impressions < 50:
            return {
                **base,
                "action": "expand_to_phrase",
                "priority": "LOW",
                "reason": f"完全一致でインプレッション{impressions}回（トラフィック不足）",
            }

        return None

    # =================================================================
    # 広告グループ間キーワード重複検出
    # =================================================================

    async def find_cross_adgroup_duplicates(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """広告グループ間のキーワード重複を検出し、統合・削除の推奨を返す。"""
        self._validate_id(campaign_id, "campaign_id")
        date_clause = self._period_to_date_clause(period)

        query = (
            "SELECT "
            "ad_group_criterion.criterion_id, "
            "ad_group_criterion.keyword.text, "
            "ad_group_criterion.keyword.match_type, "
            "ad_group_criterion.status, "
            "ad_group.id, "
            "ad_group.name, "
            "metrics.impressions, "
            "metrics.clicks, "
            "metrics.cost_micros, "
            "metrics.conversions "
            "FROM keyword_view "
            f"WHERE campaign.id = {campaign_id} "
            f"AND segments.date {date_clause} "
            "AND ad_group_criterion.status != 'REMOVED'"
        )
        try:
            response = await self._search(query)
        except Exception:
            logger.warning(
                "キーワード重複検出用データ取得に失敗: campaign_id=%s",
                campaign_id,
            )
            return {
                "campaign_id": campaign_id,
                "error": "キーワードデータの取得に失敗しました",
            }

        # キーワードを正規化キーでグルーピング
        keyword_groups = self._group_keywords_by_normalized_key(response)

        # 重複を抽出
        duplicate_groups, total_removable, total_waste = (
            self._extract_duplicate_groups(keyword_groups)
        )

        # 重複数降順でソート
        duplicate_groups.sort(key=lambda g: g["duplicate_count"], reverse=True)

        return {
            "campaign_id": campaign_id,
            "period": period,
            "total_keywords": sum(len(v) for v in keyword_groups.values()),
            "duplicate_groups_count": len(duplicate_groups),
            "total_removable_keywords": total_removable,
            "estimated_waste": round(total_waste, 0),
            "duplicate_groups": duplicate_groups,
            "summary": (
                f"{len(duplicate_groups)}グループの重複キーワードを検出。"
                f"削除推奨: {total_removable}件、"
                f"推定無駄コスト: ¥{total_waste:,.0f}"
                if duplicate_groups
                else "広告グループ間のキーワード重複は検出されませんでした"
            ),
        }

    def _group_keywords_by_normalized_key(
        self, response: list[Any]
    ) -> dict[str, list[dict[str, Any]]]:
        """GAQLレスポンスをキーワード正規化キーでグルーピングする。"""
        keyword_groups: dict[str, list[dict[str, Any]]] = {}
        for row in response:
            cost_micros = row.metrics.cost_micros
            raw_match = row.ad_group_criterion.keyword.match_type
            raw_status = row.ad_group_criterion.status
            match_type = _resolve_enum(raw_match, _MATCH_TYPE_MAP)
            status = _resolve_enum(raw_status, _STATUS_MAP)
            text = row.ad_group_criterion.keyword.text
            kw_entry = {
                "criterion_id": str(row.ad_group_criterion.criterion_id),
                "ad_group_id": str(row.ad_group.id),
                "ad_group_name": str(row.ad_group.name),
                "text": text,
                "match_type": match_type,
                "status": status,
                "metrics": {
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": cost_micros / 1_000_000,
                    "conversions": row.metrics.conversions,
                },
            }

            group_key = f"{text.lower()}|{match_type}"
            if group_key not in keyword_groups:
                keyword_groups[group_key] = []
            keyword_groups[group_key].append(kw_entry)
        return keyword_groups

    @staticmethod
    def _extract_duplicate_groups(
        keyword_groups: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], int, float]:
        """重複キーワードグループを抽出し、keep/removeを決定する。

        Returns:
            (duplicate_groups, total_removable, total_waste)
        """
        duplicate_groups: list[dict[str, Any]] = []
        total_removable = 0
        total_waste = 0.0

        for _group_key, entries in keyword_groups.items():
            unique_adgroups = {e["ad_group_id"] for e in entries}
            if len(unique_adgroups) < 2:
                continue

            def _perf_score(entry: dict[str, Any]) -> float:
                m = entry["metrics"]
                return (
                    float(m["conversions"]) * 1000
                    + float(m["clicks"]) * 10
                    + float(m["impressions"]) * 0.01
                )

            sorted_entries = sorted(entries, key=_perf_score, reverse=True)
            best = sorted_entries[0]
            removable = sorted_entries[1:]

            waste = sum(
                float(e["metrics"]["cost"])
                for e in removable
                if float(e["metrics"]["conversions"]) == 0
            )
            total_waste += waste
            total_removable += len(removable)

            duplicate_groups.append({
                "keyword": best["text"],
                "match_type": best["match_type"],
                "duplicate_count": len(entries),
                "keep": {
                    "criterion_id": best["criterion_id"],
                    "ad_group_id": best["ad_group_id"],
                    "ad_group_name": best["ad_group_name"],
                    "status": best["status"],
                    "metrics": best["metrics"],
                    "reason": "パフォーマンスが最も高いため残す",
                },
                "remove": [
                    {
                        "criterion_id": e["criterion_id"],
                        "ad_group_id": e["ad_group_id"],
                        "ad_group_name": e["ad_group_name"],
                        "status": e["status"],
                        "metrics": e["metrics"],
                        "reason": (
                            "重複キーワード: "
                            f"「{best['ad_group_name']}」に同じKWがあり、"
                            "そちらのパフォーマンスが優れているため削除推奨"
                        ),
                    }
                    for e in removable
                ],
            })

        return duplicate_groups, total_removable, total_waste
