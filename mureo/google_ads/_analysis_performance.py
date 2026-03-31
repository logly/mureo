"""パフォーマンス分析・コスト調査 Mixin。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._analysis_constants import (
    _calc_change_rate,
    _get_comparison_date_ranges,
    _safe_metrics,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _PerformanceAnalysisMixin:
    """パフォーマンス分析・コスト調査系メソッドを提供する Mixin。"""

    # 親クラス (GoogleAdsApiClient) が提供する属性・メソッドの型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...
    def _period_to_date_clause(self, period: str) -> str: ...  # type: ignore[empty-body]

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
    async def list_campaigns(  # type: ignore[empty-body]
        self, status_filter: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def get_performance_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]
    async def get_search_terms_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]
    async def list_recommendations(  # type: ignore[empty-body]
        self, campaign_id: str | None = None, recommendation_type: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def list_change_history(  # type: ignore[empty-body]
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def list_negative_keywords(  # type: ignore[empty-body]
        self, campaign_id: str
    ) -> list[dict[str, Any]]: ...
    async def get_ad_performance_report(  # type: ignore[empty-body]
        self,
        ad_group_id: str | None = None,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]: ...

    # =================================================================
    # 目標CPA解決ヘルパー
    # =================================================================

    async def _resolve_target_cpa(
        self,
        campaign_id: str,
        explicit: float | None = None,
    ) -> tuple[float | None, str]:
        """目標CPAを解決する。

        優先順: 引数 → 入札戦略(target_cpa) → 実績CPA(cost/conversions)

        Returns:
            (cpa値, ソース種別: "explicit"|"bidding_strategy"|"actual"|"none")
        """
        if explicit is not None:
            return explicit, "explicit"

        # 入札戦略から取得
        try:
            campaign = await self.get_campaign(campaign_id)
            if campaign:
                bidding = campaign.get("bidding_details") or {}
                target_cpa = bidding.get("target_cpa")
                if target_cpa is None:
                    target_cpa = None
                if target_cpa is not None and target_cpa > 0:
                    return float(target_cpa), "bidding_strategy"
        except Exception:
            logger.debug("入札戦略からの目標CPA取得に失敗: %s", campaign_id)

        # 実績CPAから算出
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_30_DAYS"
            )
            m = _safe_metrics(perf)
            cost = float(m.get("cost", 0))
            convs = float(m.get("conversions", 0))
            if convs > 0:
                return round(cost / convs, 0), "actual"
        except Exception:
            logger.debug("実績CPAの算出に失敗: %s", campaign_id)

        return None, "none"

    # =================================================================
    # 共通ヘルパー
    # =================================================================

    async def _fetch_performance_comparison(
        self,
        campaign_id: str,
        period: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, float | None]]:
        """当期・前期のパフォーマンスを取得し、変化率を算出する。

        Returns:
            (current_metrics, previous_metrics, changes_pct)
        """
        current_period, previous_period = _get_comparison_date_ranges(period)
        current_perf = await self.get_performance_report(
            campaign_id=campaign_id, period=current_period
        )
        previous_perf = await self.get_performance_report(
            campaign_id=campaign_id, period=previous_period
        )
        current_m = _safe_metrics(current_perf)
        previous_m = _safe_metrics(previous_perf)

        changes: dict[str, float | None] = {}
        for key in ("impressions", "clicks", "cost", "conversions"):
            cur = float(current_m.get(key, 0))
            prev = float(previous_m.get(key, 0))
            changes[f"{key}_change_pct"] = _calc_change_rate(cur, prev)

        return current_m, previous_m, changes

    @staticmethod
    def _generate_performance_insights(
        changes: dict[str, float | None],
        current_m: dict[str, Any],
        previous_m: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        """パフォーマンス変化率からインサイトとCPA情報を生成する。"""
        insights: list[str] = []
        cpa_info: dict[str, Any] = {}

        imp_change = changes.get("impressions_change_pct")
        if imp_change is not None and imp_change < -20:
            insights.append(f"インプレッションが前期比 {imp_change}% 減少しています")
        click_change = changes.get("clicks_change_pct")
        if click_change is not None and click_change < -20:
            insights.append(f"クリック数が前期比 {click_change}% 減少しています")
        cost_change = changes.get("cost_change_pct")
        if cost_change is not None and cost_change > 30:
            insights.append(f"広告費が前期比 {cost_change}% 増加しています")
        conv_change = changes.get("conversions_change_pct")
        if conv_change is not None and conv_change < -20:
            insights.append(f"コンバージョンが前期比 {conv_change}% 減少しています")

        # CPA 比較
        cur_cost = float(current_m.get("cost", 0))
        cur_conv = float(current_m.get("conversions", 0))
        prev_cost = float(previous_m.get("cost", 0))
        prev_conv = float(previous_m.get("conversions", 0))
        cur_cpa = cur_cost / cur_conv if cur_conv > 0 else None
        prev_cpa = prev_cost / prev_conv if prev_conv > 0 else None
        if cur_cpa is not None:
            cpa_info["cpa_current"] = round(cur_cpa, 0)
        if prev_cpa is not None:
            cpa_info["cpa_previous"] = round(prev_cpa, 0)
        if cur_cpa is not None and prev_cpa is not None:
            cpa_change = _calc_change_rate(cur_cpa, prev_cpa)
            cpa_info["cpa_change_pct"] = cpa_change
            if cpa_change is not None and cpa_change > 20:
                insights.append(f"CPAが前期比 {cpa_change}% 悪化しています")

        return insights, cpa_info

    async def _analyze_search_term_changes(
        self,
        campaign_id: str,
    ) -> dict[str, Any]:
        """検索語句の変動を分析し、新規語句と無駄な語句を特定する。"""
        current_period, previous_period = _get_comparison_date_ranges("LAST_7_DAYS")
        current_terms = await self.get_search_terms_report(
            campaign_id=campaign_id, period=current_period
        )
        previous_terms = await self.get_search_terms_report(
            campaign_id=campaign_id, period=previous_period
        )

        # 前期に存在しない検索語句を特定
        prev_term_set = {t.get("search_term", "") for t in previous_terms}
        new_terms = [
            t for t in current_terms if t.get("search_term", "") not in prev_term_set
        ]
        new_terms_sorted = sorted(
            new_terms,
            key=lambda x: x.get("metrics", {}).get("cost", 0),
            reverse=True,
        )

        # CVなしで高コストの語句を候補として抽出
        wasteful_terms = [
            t
            for t in current_terms
            if t.get("metrics", {}).get("cost", 0) > 0
            and t.get("metrics", {}).get("conversions", 0) == 0
        ]
        wasteful_sorted = sorted(
            wasteful_terms,
            key=lambda x: x.get("metrics", {}).get("cost", 0),
            reverse=True,
        )

        finding = None
        if new_terms_sorted:
            total_new_cost = sum(
                t.get("metrics", {}).get("cost", 0) for t in new_terms_sorted
            )
            finding = (
                f"新規流入検索語句が{len(new_terms)}件あり、"
                f"合計 ¥{total_new_cost:,.0f} のコストが発生しています"
            )

        return {
            "new_search_terms": new_terms_sorted[:20],
            "wasteful_search_terms": wasteful_sorted[:20],
            "finding": finding,
        }

    # =================================================================
    # 1. パフォーマンス総合分析
    # =================================================================

    async def analyze_performance(
        self,
        campaign_id: str,
        period: str = "LAST_7_DAYS",
    ) -> dict[str, Any]:
        """キャンペーンのパフォーマンスを総合分析する。"""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        insights: list[str] = []
        recs: list[str] = []

        result: dict[str, Any] = {"campaign_id": campaign_id, "period": period}

        # 1. キャンペーン基本情報
        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"キャンペーンID {campaign_id} が見つかりません"}
        result["campaign"] = campaign
        if campaign.get("status") != "ENABLED":
            issues.append(f"キャンペーンのステータスが {campaign.get('status')} です")

        # 2. パフォーマンス比較（当期 vs 前期、非重複期間）
        try:
            current_m, previous_m, changes = await self._fetch_performance_comparison(
                campaign_id, period
            )
            result["performance_current"] = current_m
            result["performance_previous"] = previous_m
            result["changes"] = changes
            perf_insights, cpa_info = self._generate_performance_insights(
                changes, current_m, previous_m
            )
            insights.extend(perf_insights)
            result.update(cpa_info)
        except Exception:
            logger.warning("パフォーマンス比較の取得に失敗", exc_info=True)
            result["performance_current"] = "取得失敗"

        # 3. 検索語句 上位20件
        try:
            search_terms = await self.get_search_terms_report(
                campaign_id=campaign_id, period=period
            )
            sorted_terms = sorted(
                search_terms,
                key=lambda x: x.get("metrics", {}).get("cost", 0),
                reverse=True,
            )
            result["top_search_terms"] = sorted_terms[:20]
        except Exception:
            logger.warning("検索語句レポートの取得に失敗", exc_info=True)
            result["top_search_terms"] = "取得失敗"

        # 4. Google 推奨事項
        try:
            recommendations = await self.list_recommendations(campaign_id=campaign_id)
            result["recommendations_from_google"] = recommendations[:10]
            if recommendations:
                recs.append(f"Googleから{len(recommendations)}件の推奨事項があります")
        except Exception:
            logger.warning("推奨事項の取得に失敗", exc_info=True)
            result["recommendations_from_google"] = "取得失敗"

        # 5. 直近の変更履歴
        try:
            changes_history = await self.list_change_history()
            result["recent_changes"] = changes_history[:10]
        except Exception:
            logger.warning("変更履歴の取得に失敗", exc_info=True)
            result["recent_changes"] = "取得失敗"

        # 6. 分析サマリー
        result["issues"] = issues
        result["insights"] = insights
        result["recommendations"] = recs
        return result

    # =================================================================
    # 2. 広告費増加・CPA悪化調査
    # =================================================================

    async def investigate_cost_increase(
        self,
        campaign_id: str,
    ) -> dict[str, Any]:
        """広告費増加・CPA悪化の原因を調査する。"""
        self._validate_id(campaign_id, "campaign_id")
        findings: list[str] = []
        actions: list[str] = []

        result: dict[str, Any] = {"campaign_id": campaign_id}

        # 1. 7日 vs 前7日のパフォーマンス比較（非重複期間）
        current_m: dict[str, Any] = {}
        previous_m: dict[str, Any] = {}
        changes: dict[str, float | None] = {}
        try:
            current_m, previous_m, changes = await self._fetch_performance_comparison(
                campaign_id, "LAST_7_DAYS"
            )
            result["performance_current_7d"] = current_m
            result["performance_previous_7d"] = previous_m
            result["changes"] = changes
        except Exception:
            logger.warning("パフォーマンス比較の取得に失敗", exc_info=True)
            result["performance_current_7d"] = "取得失敗"

        # 2. コスト増加の内訳（CPC上昇 vs クリック数増加）
        cost_breakdown, breakdown_findings, cpc_change, clicks_change = (
            self._build_cost_breakdown(current_m, previous_m)
        )
        result["cost_breakdown"] = cost_breakdown
        findings.extend(breakdown_findings)

        # 3. 検索語句の変動分析
        try:
            term_analysis = await self._analyze_search_term_changes(campaign_id)
            result["new_search_terms"] = term_analysis["new_search_terms"]
            result["wasteful_search_terms"] = term_analysis["wasteful_search_terms"]
            if term_analysis["finding"]:
                findings.append(term_analysis["finding"])
        except Exception:
            logger.warning("検索語句分析に失敗", exc_info=True)
            result["new_search_terms"] = "取得失敗"
            result["wasteful_search_terms"] = "取得失敗"

        # 4. 入札・予算の変更履歴
        try:
            change_history = await self.list_change_history()
            bid_budget_changes = [
                c
                for c in change_history
                if c.get("resource_type", "")
                in (
                    "CAMPAIGN_BUDGET",
                    "CAMPAIGN",
                    "AD_GROUP",
                    "CAMPAIGN_BID_MODIFIER",
                )
            ]
            result["bid_budget_changes"] = bid_budget_changes[:10]
            if bid_budget_changes:
                findings.append(
                    f"直近の入札・予算関連の変更が{len(bid_budget_changes)}件あります"
                )
        except Exception:
            logger.warning("変更履歴の取得に失敗", exc_info=True)
            result["bid_budget_changes"] = "取得失敗"

        # 5. 除外キーワード候補
        await self._find_negative_keyword_candidates(campaign_id, result, actions)

        # サマリー
        if cpc_change is not None and cpc_change > 10:
            actions.append("入札戦略の見直しや上限CPCの調整を検討してください")

        result["findings"] = findings
        result["recommended_actions"] = actions
        return result

    @staticmethod
    def _build_cost_breakdown(
        current_m: dict[str, Any],
        previous_m: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str], float | None, float | None]:
        """コスト内訳（CPC vs クリック数変動）を構築する。

        Returns:
            (cost_breakdown, findings, cpc_change, clicks_change)
        """
        cur_cpc = float(current_m.get("average_cpc", 0))
        prev_cpc = float(previous_m.get("average_cpc", 0))
        cur_clicks = float(current_m.get("clicks", 0))
        prev_clicks = float(previous_m.get("clicks", 0))

        cpc_change = _calc_change_rate(cur_cpc, prev_cpc)
        clicks_change = _calc_change_rate(cur_clicks, prev_clicks)

        cost_breakdown = {
            "cpc_current": cur_cpc,
            "cpc_previous": prev_cpc,
            "cpc_change_pct": cpc_change,
            "clicks_current": cur_clicks,
            "clicks_previous": prev_clicks,
            "clicks_change_pct": clicks_change,
        }

        findings: list[str] = []
        if cpc_change is not None and cpc_change > 10:
            findings.append(
                f"平均CPCが {cpc_change}% 上昇しています。"
                "競合の入札強化やオークション環境の変化が考えられます"
            )
        if clicks_change is not None and clicks_change > 20:
            findings.append(
                f"クリック数が {clicks_change}% 増加しています。"
                "検索語句の拡がりや新規流入語句の影響が考えられます"
            )
        return cost_breakdown, findings, cpc_change, clicks_change

    async def _find_negative_keyword_candidates(
        self,
        campaign_id: str,
        result: dict[str, Any],
        actions: list[str],
    ) -> None:
        """除外キーワード候補を特定する。"""
        try:
            existing_negatives = await self.list_negative_keywords(campaign_id)
            existing_neg_texts = {n.get("text", "").lower() for n in existing_negatives}
            result["existing_negative_keywords_count"] = len(existing_negatives)

            if isinstance(result.get("wasteful_search_terms"), list):
                neg_candidates = [
                    t
                    for t in result["wasteful_search_terms"]
                    if t.get("search_term", "").lower() not in existing_neg_texts
                ]
                result["negative_keyword_candidates"] = neg_candidates[:10]
                if neg_candidates:
                    actions.append(
                        f"CVなしで広告費が発生している検索語句が{len(neg_candidates)}件あります。"
                        "除外キーワードへの追加を検討してください"
                    )
        except Exception:
            logger.warning("除外キーワード分析に失敗", exc_info=True)
            result["negative_keyword_candidates"] = "取得失敗"

    # =================================================================
    # 3. 全キャンペーン横断健全性チェック
    # =================================================================

    async def health_check_all_campaigns(self) -> dict[str, Any]:
        """全キャンペーンの健全性を横断チェックする。"""
        # --- 1. 全キャンペーン一覧 ---
        campaigns = await self.list_campaigns()
        result: dict[str, Any] = {
            "total_campaigns": len(campaigns),
        }

        # ENABLEDのみ対象
        enabled = [c for c in campaigns if c.get("status") == "ENABLED"]
        paused = [c for c in campaigns if c.get("status") == "PAUSED"]
        removed = [c for c in campaigns if c.get("status") == "REMOVED"]

        result["enabled_count"] = len(enabled)
        result["paused_count"] = len(paused)
        result["removed_count"] = len(removed)

        # --- 2. primary_status による分類 ---
        healthy: list[dict[str, Any]] = []
        warning: list[dict[str, Any]] = []
        problem: list[dict[str, Any]] = []

        for camp in enabled:
            primary_status = camp.get("primary_status", "")
            camp_summary = {
                "campaign_id": camp.get("id", ""),
                "name": camp.get("name", ""),
                "primary_status": primary_status,
            }
            if primary_status == "ELIGIBLE":
                healthy.append(camp_summary)
            elif primary_status in ("NOT_ELIGIBLE", "ENDED", "REMOVED"):
                problem.append(camp_summary)
            else:
                warning.append(camp_summary)

        result["healthy_campaigns"] = healthy
        result["warning_campaigns"] = warning
        result["problem_campaigns"] = problem

        # --- 3. 問題キャンペーンの詳細診断 ---
        targets = (problem + warning)[:5]
        detailed_diagnostics: list[dict[str, Any]] = []
        for camp_summary in targets:
            cid = str(camp_summary["campaign_id"])
            try:
                diag = await self.diagnose_campaign_delivery(cid)  # type: ignore[attr-defined]
                detailed_diagnostics.append(
                    {
                        "campaign_id": cid,
                        "name": camp_summary["name"],
                        "issues": diag.get("issues", []),
                        "warnings": diag.get("warnings", []),
                        "recommendations": diag.get("recommendations", []),
                    }
                )
            except Exception:
                logger.warning("キャンペーン %s の詳細診断に失敗", cid, exc_info=True)
                detailed_diagnostics.append(
                    {
                        "campaign_id": cid,
                        "name": camp_summary["name"],
                        "error": "詳細診断の取得に失敗",
                    }
                )
        result["detailed_diagnostics"] = detailed_diagnostics

        # --- 4. 横断サマリー ---
        result["summary"] = {
            "total_enabled": len(enabled),
            "healthy": len(healthy),
            "warning": len(warning),
            "problem": len(problem),
        }

        if problem:
            result["summary"]["message"] = (
                f"{len(problem)}件のキャンペーンに問題があります。"
                "詳細診断を確認してください"
            )
        elif warning:
            result["summary"][
                "message"
            ] = f"{len(warning)}件のキャンペーンに注意事項があります"
        else:
            result["summary"]["message"] = "全キャンペーンが正常に稼働しています"

        return result

    # =================================================================
    # 広告A/B比較
    # =================================================================

    async def compare_ad_performance(
        self,
        ad_group_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """広告グループ内の広告パフォーマンスを比較する。"""
        self._validate_id(ad_group_id, "ad_group_id")

        ad_perf = await self.get_ad_performance_report(
            ad_group_id=ad_group_id, period=period
        )

        # ENABLED の広告のみ
        enabled_ads = [a for a in ad_perf if a.get("status") == "ENABLED"]

        ads_data: list[dict[str, Any]] = []
        for a in enabled_ads:
            m = a.get("metrics", {})
            impressions = int(m.get("impressions", 0))
            clicks = int(m.get("clicks", 0))
            conversions = float(m.get("conversions", 0))
            cost = float(m.get("cost", 0))

            ctr = clicks / impressions if impressions > 0 else 0.0
            cvr = conversions / clicks if clicks > 0 else 0.0
            cpa = cost / conversions if conversions > 0 else None

            # スコア: CVがあれば ctr*cvr、なければ ctr のみ
            score = ctr * cvr if conversions > 0 else ctr

            entry: dict[str, Any] = {
                "ad_id": a.get("ad_id", ""),
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
                "cost": cost,
                "ctr": round(ctr, 4),
                "cvr": round(cvr, 4),
                "cpa": round(cpa, 0) if cpa is not None else None,
                "score": round(score, 6),
            }
            # RSA情報があれば含める
            if "headlines" in a:
                entry["headlines"] = a["headlines"]
            if "descriptions" in a:
                entry["descriptions"] = a["descriptions"]
            ads_data.append(entry)

        # スコアでソートしてランク・verdict を付与
        sorted_ads = sorted(ads_data, key=lambda x: x["score"], reverse=True)
        best_score = sorted_ads[0]["score"] if sorted_ads else 0.0
        ranked_ads: list[dict[str, Any]] = []
        for rank, ad in enumerate(sorted_ads, start=1):
            if ad["impressions"] < 100:
                verdict = "INSUFFICIENT_DATA"
            elif ad["score"] == best_score:
                verdict = "WINNER"
            else:
                verdict = "LOSER"
            ranked_ads.append({**ad, "rank": rank, "verdict": verdict})

        winner = next((a for a in ranked_ads if a.get("verdict") == "WINNER"), None)

        # 推奨アクション
        if len(ads_data) < 2:
            recommendation = (
                "比較対象の広告が不足しています。"
                "A/Bテストのために広告を追加してください"
            )
        elif winner:
            recommendation = (
                f"広告 {winner['ad_id']} が最もパフォーマンスが高いです。"
                "LOSERの広告を停止し、新しいバリエーションでテストすることを推奨します"
            )
        else:
            recommendation = "十分なデータが蓄積されるまでテストを継続してください"

        # インサイト
        insights: list[str] = []
        insufficient = [
            a for a in ranked_ads if a.get("verdict") == "INSUFFICIENT_DATA"
        ]
        if insufficient:
            insights.append(
                f"{len(insufficient)}件の広告がデータ不足です"
                "（インプレッション100未満）"
            )
        losers = [a for a in ranked_ads if a.get("verdict") == "LOSER"]
        if losers and winner:
            insights.append(
                f"WINNER（広告 {winner['ad_id']}）のCTRは{winner['ctr']:.2%}で、"
                f"他の{len(losers)}件の広告を上回っています"
            )

        return {
            "ad_group_id": ad_group_id,
            "period": period,
            "ads": ranked_ads,
            "winner": winner,
            "recommendation": recommendation,
            "insights": insights,
        }
