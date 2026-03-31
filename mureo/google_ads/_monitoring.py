from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _MonitoringMixin:
    """監視目標の評価マクロツールを提供する Mixin"""

    # 親クラス (GoogleAdsApiClient) が提供する属性・メソッドの型宣言
    # ランタイムでは存在させない（MROで実装メソッドを上書きしないよう TYPE_CHECKING 内に配置）
    if TYPE_CHECKING:
        _customer_id: str
        _client: GoogleAdsClient

        @staticmethod
        def _validate_id(value: str, field_name: str) -> str: ...
        async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
        async def get_performance_report(
            self, **kwargs: Any
        ) -> list[dict[str, Any]]: ...
        async def diagnose_campaign_delivery(
            self, campaign_id: str
        ) -> dict[str, Any]: ...
        async def analyze_performance(
            self, campaign_id: str, period: str = "LAST_7_DAYS"
        ) -> dict[str, Any]: ...
        async def investigate_cost_increase(
            self, campaign_id: str
        ) -> dict[str, Any]: ...
        async def get_search_terms_report(
            self, **kwargs: Any
        ) -> list[dict[str, Any]]: ...
        async def list_conversion_actions(self) -> list[dict[str, Any]]: ...

    # =================================================================
    # 1. 配信目標の評価
    # =================================================================

    async def evaluate_delivery_goal(self, campaign_id: str) -> dict[str, Any]:
        """配信目標を評価し、配信状態・パフォーマンスを統合して判定する。"""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        result: dict[str, Any] = {"campaign_id": campaign_id}

        # 1. キャンペーン基本情報
        campaign: dict[str, Any] | None = None
        try:
            campaign = await self.get_campaign(campaign_id)
        except Exception:
            logger.warning("キャンペーン情報の取得に失敗", exc_info=True)
        result["campaign"] = campaign

        # 2. 配信診断
        diagnosis: dict[str, Any] = {}
        try:
            diagnosis = await self.diagnose_campaign_delivery(campaign_id)
        except Exception:
            logger.warning("配信診断の取得に失敗", exc_info=True)
            issues.append("配信診断の取得に失敗しました")
        result["diagnosis"] = diagnosis

        # 3. 前日パフォーマンス
        performance: list[dict[str, Any]] = []
        try:
            performance = await self.get_performance_report(
                campaign_id=campaign_id, period="YESTERDAY"
            )
        except Exception:
            logger.warning("前日パフォーマンスの取得に失敗", exc_info=True)
            issues.append("前日パフォーマンスの取得に失敗しました")
        result["performance"] = performance

        # メトリクス抽出
        metrics = performance[0].get("metrics", {}) if performance else {}
        impressions = int(metrics.get("impressions", 0))

        # status 判定
        has_issues = bool(diagnosis.get("issues"))
        has_warnings = bool(diagnosis.get("warnings"))
        campaign_status = (campaign or {}).get("status", "")

        if has_issues:
            issues.append("配信診断で問題が検出されました")
        if campaign_status and campaign_status != "ENABLED":
            issues.append(f"キャンペーンのステータスが {campaign_status} です")
        if impressions == 0:
            issues.append("前日のインプレッションが0件です")

        is_critical = (
            has_issues
            or (campaign_status and campaign_status != "ENABLED")
            or impressions == 0
        )
        is_warning = has_warnings or (
            not is_critical and impressions > 0 and impressions < 10
        )

        if is_critical:
            status = "critical"
        elif is_warning:
            status = "warning"
            if has_warnings:
                issues.append("配信診断で警告が検出されました")
        else:
            status = "healthy"

        result["status"] = status
        result["issues"] = issues

        if status in ("critical", "warning"):
            result["suggested_workflow"] = "delivery_fix"

        # サマリー生成
        if status == "critical":
            result["summary"] = (
                f"キャンペーン {campaign_id} の配信に重大な問題があります。"
                f"検出された問題: {', '.join(issues)}"
            )
        elif status == "warning":
            result["summary"] = (
                f"キャンペーン {campaign_id} の配信に注意が必要です。"
                f"検出された警告: {', '.join(issues)}"
            )
        else:
            result["summary"] = (
                f"キャンペーン {campaign_id} の配信は正常に稼働しています。"
                f"前日インプレッション: {impressions:,}件"
            )

        return result

    # =================================================================
    # 2. CPA目標の評価
    # =================================================================

    async def evaluate_cpa_goal(
        self, campaign_id: str, target_cpa: float
    ) -> dict[str, Any]:
        """CPA目標に対する現在のパフォーマンスを評価する。"""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        result: dict[str, Any] = {
            "campaign_id": campaign_id,
            "target_cpa": target_cpa,
        }

        # 1. 直近7日パフォーマンス
        perf: list[dict[str, Any]] = []
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_7_DAYS"
            )
        except Exception:
            logger.warning("パフォーマンスレポートの取得に失敗", exc_info=True)
            issues.append("パフォーマンスレポートの取得に失敗しました")

        metrics = perf[0].get("metrics", {}) if perf else {}
        cost = float(metrics.get("cost", 0))
        conversions = float(metrics.get("conversions", 0))

        # 2. CPA算出
        if conversions > 0:
            current_cpa = round(cost / conversions, 1)
            result["current_cpa"] = current_cpa
        else:
            current_cpa = None
            result["current_cpa"] = None
            issues.append("直近7日間のコンバージョンが0件のためCPAを算出できません")

        # 3. コスト分析
        cost_analysis: dict[str, Any] = {}
        try:
            cost_analysis = await self.investigate_cost_increase(campaign_id)
        except Exception:
            logger.warning("コスト分析の取得に失敗", exc_info=True)
            issues.append("コスト分析の取得に失敗しました")
        result["cost_analysis"] = cost_analysis

        # 無駄な検索語句（上位5件）
        wasteful_terms = cost_analysis.get("wasteful_search_terms", [])
        if isinstance(wasteful_terms, list):
            result["wasteful_terms"] = wasteful_terms[:5]
        else:
            result["wasteful_terms"] = []

        # 4. 乖離率算出・status判定
        if current_cpa is not None:
            deviation_pct = round((current_cpa - target_cpa) / target_cpa * 100, 1)
            result["deviation_pct"] = deviation_pct

            if current_cpa <= target_cpa:
                status = "healthy"
            elif current_cpa <= target_cpa * 1.2:
                status = "warning"
                issues.append(
                    f"CPAが目標を {deviation_pct}% 超過しています"
                    f"（現在: {current_cpa:,.0f}円 / 目標: {target_cpa:,.0f}円）"
                )
            else:
                status = "critical"
                issues.append(
                    f"CPAが目標を大幅に超過しています（{deviation_pct}%超過）。"
                    f"現在: {current_cpa:,.0f}円 / 目標: {target_cpa:,.0f}円"
                )
        else:
            # CVなしの場合
            status = "warning"
            result["deviation_pct"] = None

        result["status"] = status
        result["issues"] = issues

        if status in ("critical", "warning"):
            result["suggested_workflow"] = "cpa_optimization"

        # サマリー生成
        if current_cpa is not None:
            if status == "healthy":
                result["summary"] = (
                    f"キャンペーン {campaign_id} のCPAは目標内です。"
                    f"現在CPA: {current_cpa:,.0f}円 / 目標: {target_cpa:,.0f}円"
                    f"（乖離率: {result['deviation_pct']}%）"
                )
            elif status == "warning":
                result["summary"] = (
                    f"キャンペーン {campaign_id} のCPAが目標をやや超過しています。"
                    f"現在CPA: {current_cpa:,.0f}円 / 目標: {target_cpa:,.0f}円"
                    f"（乖離率: {result['deviation_pct']}%）。早めの対策を推奨します"
                )
            else:
                result["summary"] = (
                    f"キャンペーン {campaign_id} のCPAが目標を大幅に超過しています。"
                    f"現在CPA: {current_cpa:,.0f}円 / 目標: {target_cpa:,.0f}円"
                    f"（乖離率: {result['deviation_pct']}%）。緊急の対策が必要です"
                )
        else:
            result["summary"] = (
                f"キャンペーン {campaign_id} は直近7日間のコンバージョンが0件のため"
                f"CPAを評価できません。配信状態とコンバージョン計測の確認を推奨します"
            )

        return result

    # =================================================================
    # 3. CV目標の評価
    # =================================================================

    async def evaluate_cv_goal(
        self, campaign_id: str, target_cv_daily: float
    ) -> dict[str, Any]:
        """日次CV目標に対する現在のパフォーマンスを評価する。"""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        result: dict[str, Any] = {
            "campaign_id": campaign_id,
            "target_cv_daily": target_cv_daily,
        }

        # 1. 直近7日パフォーマンス
        perf: list[dict[str, Any]] = []
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_7_DAYS"
            )
        except Exception:
            logger.warning("パフォーマンスレポートの取得に失敗", exc_info=True)
            issues.append("パフォーマンスレポートの取得に失敗しました")

        metrics = perf[0].get("metrics", {}) if perf else {}
        impressions = int(metrics.get("impressions", 0))
        clicks = int(metrics.get("clicks", 0))
        conversions = float(metrics.get("conversions", 0))

        # 2. 日平均CV算出
        daily_cv = round(conversions / 7, 2)
        result["current_cv_daily"] = daily_cv

        # 3. パフォーマンス総合分析
        performance_analysis: dict[str, Any] = {}
        try:
            performance_analysis = await self.analyze_performance(campaign_id)
        except Exception:
            logger.warning("パフォーマンス分析の取得に失敗", exc_info=True)
            issues.append("パフォーマンス分析の取得に失敗しました")
        result["performance_analysis"] = performance_analysis

        # 4. 乖離率算出
        if target_cv_daily > 0:
            deviation_pct = round(
                (daily_cv - target_cv_daily) / target_cv_daily * 100, 1
            )
        else:
            deviation_pct = 0.0
        result["deviation_pct"] = deviation_pct

        # 5. status判定
        if daily_cv >= target_cv_daily:
            status = "healthy"
        elif daily_cv >= target_cv_daily * 0.8:
            status = "warning"
            issues.append(
                f"日次CVが目標を下回っています"
                f"（現在: {daily_cv:.1f}件/日 / 目標: {target_cv_daily:.1f}件/日）"
            )
        else:
            status = "critical"
            issues.append(
                f"日次CVが目標を大幅に下回っています"
                f"（現在: {daily_cv:.1f}件/日 / 目標: {target_cv_daily:.1f}件/日、"
                f"乖離率: {deviation_pct}%）"
            )

        result["status"] = status

        # 6. ボトルネック特定
        analysis_insights = performance_analysis.get("insights", [])
        impression_issue_in_insights = any(
            "インプレッション" in insight for insight in analysis_insights
        )

        if impression_issue_in_insights or (clicks > 0 and impressions < clicks * 10):
            bottleneck = "impression"
            if status != "healthy":
                issues.append("インプレッション不足がボトルネックの可能性があります")
        elif impressions > 0 and (clicks / impressions) < 0.02:
            bottleneck = "ctr"
            if status != "healthy":
                ctr_value = round(clicks / impressions * 100, 2)
                issues.append(f"CTRが低い状態です（{ctr_value}%、業界平均2%未満）")
        elif clicks > 0 and (conversions / clicks) < 0.01:
            bottleneck = "cvr"
            if status != "healthy":
                cvr_value = round(conversions / clicks * 100, 2)
                issues.append(f"CVRが低い状態です（{cvr_value}%、1%未満）")
        else:
            bottleneck = "cvr"

        result["bottleneck"] = bottleneck
        result["issues"] = issues

        if status in ("critical", "warning"):
            result["suggested_workflow"] = "cv_increase"

        # サマリー生成
        bottleneck_label = {
            "impression": "インプレッション不足",
            "ctr": "CTR（クリック率）の低下",
            "cvr": "CVR（コンバージョン率）の低下",
        }
        if status == "healthy":
            result["summary"] = (
                f"キャンペーン {campaign_id} のCV数は目標を達成しています。"
                f"日次CV: {daily_cv:.1f}件 / 目標: {target_cv_daily:.1f}件"
            )
        elif status == "warning":
            result["summary"] = (
                f"キャンペーン {campaign_id} のCV数が目標をやや下回っています。"
                f"日次CV: {daily_cv:.1f}件 / 目標: {target_cv_daily:.1f}件"
                f"（乖離率: {deviation_pct}%）。"
                f"主なボトルネック: {bottleneck_label[bottleneck]}"
            )
        else:
            result["summary"] = (
                f"キャンペーン {campaign_id} のCV数が目標を大幅に下回っています。"
                f"日次CV: {daily_cv:.1f}件 / 目標: {target_cv_daily:.1f}件"
                f"（乖離率: {deviation_pct}%）。"
                f"主なボトルネック: {bottleneck_label[bottleneck]}。緊急の対策が必要です"
            )

        return result

    # =================================================================
    # 4. CV獲得改善の診断
    # =================================================================

    async def diagnose_zero_conversions(self, campaign_id: str) -> dict[str, Any]:
        """CV=0問題の診断。LLMが改善戦略を立案するために必要なデータを一括収集する。"""
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        result: dict[str, Any] = {"campaign_id": campaign_id}

        # 1. キャンペーン基本情報
        campaign: dict[str, Any] | None = None
        try:
            campaign = await self.get_campaign(campaign_id)
        except Exception:
            logger.warning("キャンペーン情報の取得に失敗", exc_info=True)

        # 2. CV計測設定
        cv_actions: list[dict[str, Any]] = []
        try:
            cv_actions = await self.list_conversion_actions()
        except Exception:
            logger.warning("コンバージョンアクション一覧の取得に失敗", exc_info=True)
            issues.append("コンバージョンアクション一覧の取得に失敗しました")

        total_actions = len(cv_actions)
        enabled_actions = sum(
            1 for a in cv_actions if a.get("status", "").upper() == "ENABLED"
        )
        has_cv_issue = total_actions == 0 or enabled_actions == 0
        result["conversion_tracking"] = {
            "total_actions": total_actions,
            "enabled_actions": enabled_actions,
            "has_issue": has_cv_issue,
            "actions": cv_actions,
        }
        if has_cv_issue:
            issues.append("有効なコンバージョンアクションが設定されていません")

        # 3. 入札×CV整合性チェック
        bidding_strategy = (campaign or {}).get("bidding_strategy", "")
        smart_bidding_types = {
            "MAXIMIZE_CONVERSIONS",
            "TARGET_CPA",
            "TARGET_ROAS",
            "MAXIMIZE_CONVERSION_VALUE",
        }
        is_smart = bidding_strategy.upper() in smart_bidding_types
        bidding_issue: str | None = None
        if is_smart and has_cv_issue:
            bidding_issue = (
                f"スマート入札（{bidding_strategy}）が設定されていますが、"
                "有効なコンバージョン計測がありません"
            )
            issues.append(bidding_issue)
        result["bidding_cv_alignment"] = {
            "strategy": bidding_strategy,
            "is_smart_bidding": is_smart,
            "cv_tracking_configured": not has_cv_issue,
            "issue": bidding_issue,
        }

        # 4. ファネルデータ（直近7日）
        perf: list[dict[str, Any]] = []
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_7_DAYS"
            )
        except Exception:
            logger.warning("パフォーマンスレポートの取得に失敗", exc_info=True)
            issues.append("パフォーマンスレポートの取得に失敗しました")

        metrics = perf[0].get("metrics", {}) if perf else {}
        impressions = int(metrics.get("impressions", 0))
        clicks = int(metrics.get("clicks", 0))
        conversions = float(metrics.get("conversions", 0))
        cost = float(metrics.get("cost", 0))
        ctr = round(clicks / impressions * 100, 2) if impressions > 0 else None
        cvr = round(conversions / clicks * 100, 2) if clicks > 0 else None

        if impressions == 0:
            bottleneck = "no_delivery"
            issues.append("直近7日間のインプレッションが0件です")
        elif clicks == 0:
            bottleneck = "no_clicks"
            issues.append("直近7日間のクリックが0件です")
        elif conversions == 0:
            bottleneck = "no_conversions"
        else:
            bottleneck = None

        result["funnel"] = {
            "period": "LAST_7_DAYS",
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "cost": cost,
            "ctr": ctr,
            "cvr": cvr,
            "bottleneck": bottleneck,
        }

        # 5. 配信診断
        diagnosis: dict[str, Any] = {}
        try:
            diagnosis = await self.diagnose_campaign_delivery(campaign_id)
        except Exception:
            logger.warning("配信診断の取得に失敗", exc_info=True)
            issues.append("配信診断の取得に失敗しました")

        result["delivery_diagnosis"] = {
            "issues": diagnosis.get("issues", []),
            "warnings": diagnosis.get("warnings", []),
            "recommendations": diagnosis.get("recommendations", []),
        }

        # 6. 検索語句品質（clicks>0時のみ）
        search_term_quality: dict[str, Any] | None = None
        if clicks > 0:
            try:
                terms = await self.get_search_terms_report(
                    campaign_id=campaign_id, period="LAST_7_DAYS"
                )
                zero_cv_terms = [
                    t
                    for t in terms
                    if float(t.get("metrics", {}).get("conversions", 0)) == 0
                ]
                zero_cv_cost = sum(
                    float(t.get("metrics", {}).get("cost", 0)) for t in zero_cv_terms
                )
                # CVなし高コスト上位10件
                sorted_wasteful = sorted(
                    zero_cv_terms,
                    key=lambda t: float(t.get("metrics", {}).get("cost", 0)),
                    reverse=True,
                )
                search_term_quality = {
                    "total_terms": len(terms),
                    "zero_cv_terms": len(zero_cv_terms),
                    "zero_cv_cost": zero_cv_cost,
                    "top_wasteful_terms": sorted_wasteful[:10],
                }
                # CVなし高コスト語句が50%超の場合
                if cost > 0 and zero_cv_cost / cost > 0.5:
                    issues.append(
                        f"CVなし検索語句のコストが全体の"
                        f"{round(zero_cv_cost / cost * 100, 1)}%を占めています"
                    )
            except Exception:
                logger.warning("検索語句レポートの取得に失敗", exc_info=True)
                issues.append("検索語句レポートの取得に失敗しました")
        result["search_term_quality"] = search_term_quality

        # ステータス判定
        if (
            has_cv_issue
            or bidding_issue
            or bottleneck == "no_delivery"
            or bottleneck == "no_clicks"
        ):
            status = "critical"
        elif conversions == 0:
            status = "warning"
        else:
            status = "healthy"

        result["status"] = status
        result["issues"] = issues

        if status != "healthy":
            result["suggested_workflow"] = "cv_acquisition"

        # 推奨アクション
        result["recommended_actions"] = self._build_cv_recommendations(
            has_cv_issue=has_cv_issue,
            bidding_issue=bidding_issue,
            bottleneck=bottleneck,
            search_term_quality=search_term_quality,
            cost=cost,
        )

        # サマリー生成
        if status == "critical":
            result["summary"] = (
                f"キャンペーン {campaign_id} でCVが獲得できていません。"
                f"重大な問題が検出されました: {', '.join(issues[:3])}"
            )
        elif status == "warning":
            result["summary"] = (
                f"キャンペーン {campaign_id} でCVが0件です。"
                f"Imp={impressions:,}, Click={clicks:,}, CV=0。"
                f"改善戦略の立案を推奨します"
            )
        else:
            result["summary"] = (
                f"キャンペーン {campaign_id} はCVが発生しています。"
                f"直近7日間のCV数: {conversions:.1f}件"
            )

        return result

    @staticmethod
    def _build_cv_recommendations(
        *,
        has_cv_issue: bool,
        bidding_issue: str | None,
        bottleneck: str | None,
        search_term_quality: dict[str, Any] | None,
        cost: float,
    ) -> list[dict[str, Any]]:
        """CV改善の推奨アクションを優先順位付きで生成する。"""
        actions: list[dict[str, Any]] = []
        priority = 1

        if has_cv_issue:
            actions.append(
                {
                    "priority": priority,
                    "action": "fix_cv_tracking",
                    "description": "コンバージョン計測の設定・修正",
                }
            )
            priority += 1

        if bidding_issue:
            actions.append(
                {
                    "priority": priority,
                    "action": "fix_bidding_strategy",
                    "description": "入札戦略とCV計測の整合性を修正",
                }
            )
            priority += 1

        if search_term_quality and search_term_quality["zero_cv_terms"] > 0:
            actions.append(
                {
                    "priority": priority,
                    "action": "add_negative_keywords",
                    "description": "CVなし検索語句の除外キーワード追加",
                }
            )
            priority += 1

        if bottleneck in ("no_delivery", "no_clicks"):
            actions.append(
                {
                    "priority": priority,
                    "action": "fix_delivery",
                    "description": "配信・クリック獲得の改善",
                }
            )
            priority += 1

        # 常に提案候補
        actions.append(
            {
                "priority": priority,
                "action": "improve_ads_and_keywords",
                "description": "広告文改善・キーワード拡張",
            }
        )
        priority += 1

        actions.append(
            {
                "priority": priority,
                "action": "review_landing_page",
                "description": "ランディングページの改善（テキストアドバイス）",
            }
        )

        return actions
