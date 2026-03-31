from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from mureo.google_ads.mappers import (
    map_ad_type,
    map_approval_status,
    map_bidding_strategy_type,
    map_criterion_approval_status,
    map_review_status,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# primary_status_reasons → 日本語説明マッピング
# ---------------------------------------------------------------------------

_PRIMARY_STATUS_REASON_JA: dict[str, str] = {
    "CAMPAIGN_DRAFT": "キャンペーンが下書き状態",
    "CAMPAIGN_PAUSED": "キャンペーンが一時停止中",
    "CAMPAIGN_REMOVED": "キャンペーンが削除済み",
    "CAMPAIGN_ENDED": "キャンペーンの終了日を過ぎている",
    "CAMPAIGN_PENDING": "キャンペーンの開始日がまだ到来していない",
    "BIDDING_STRATEGY_MISCONFIGURED": "入札戦略の設定に不備あり",
    "BIDDING_STRATEGY_LIMITED": "入札戦略がデータ不足等で制限されている",
    "BIDDING_STRATEGY_LEARNING": "入札戦略が学習期間中（1〜2週間）",
    "BIDDING_STRATEGY_CONSTRAINED": "入札戦略が制約を受けている",
    "BUDGET_CONSTRAINED": "予算不足で表示機会を逃している",
    "BUDGET_MISCONFIGURED": "予算の設定に不備あり",
    "SEARCH_VOLUME_LIMITED": "検索ボリュームが不足している",
    "AD_GROUPS_PAUSED": "すべての広告グループが一時停止中",
    "NO_AD_GROUPS": "広告グループが存在しない",
    "KEYWORDS_PAUSED": "すべてのキーワードが一時停止中",
    "NO_KEYWORDS": "キーワードが存在しない",
    "AD_GROUP_ADS_PAUSED": "すべての広告が一時停止中",
    "NO_AD_GROUP_ADS": "広告が存在しない",
    "HAS_ADS_LIMITED_BY_POLICY": "ポリシーにより一部の広告が制限されている",
    "HAS_ADS_DISAPPROVED": "不承認の広告がある",
    "MOST_ADS_UNDER_REVIEW": "大部分の広告が審査中",
    "MISSING_LEAD_FORM_EXTENSION": "リードフォーム拡張機能が未設定",
    "MISSING_CALL_EXTENSION": "電話番号拡張機能が未設定",
    "LEAD_FORM_EXTENSION_UNDER_REVIEW": "リードフォーム拡張機能が審査中",
    "LEAD_FORM_EXTENSION_DISAPPROVED": "リードフォーム拡張機能が不承認",
    "CALL_EXTENSION_UNDER_REVIEW": "電話番号拡張機能が審査中",
    "CALL_EXTENSION_DISAPPROVED": "電話番号拡張機能が不承認",
    "NO_ACTIVE_MOBILE_APP_STORE_LINKS": "有効なモバイルアプリストアリンクがない",
    "CAMPAIGN_GROUP_PAUSED": "キャンペーングループが一時停止中",
    "CAMPAIGN_GROUP_ALL_GROUP_BUDGETS_ENDED": "キャンペーングループの全予算が終了",
    "APP_NOT_RELEASED": "アプリが未公開",
    "APP_PARTIALLY_RELEASED": "アプリが一部地域でのみ公開",
    "HAS_ASSET_GROUPS_DISAPPROVED": "アセットグループが不承認",
    "HAS_ASSET_GROUPS_LIMITED_BY_POLICY": "ポリシーによりアセットグループが制限されている",
    "MOST_ASSET_GROUPS_UNDER_REVIEW": "大部分のアセットグループが審査中",
    "NO_ASSET_GROUPS": "アセットグループが存在しない",
    "ASSET_GROUPS_PAUSED": "すべてのアセットグループが一時停止中",
}

# primary_status_reasons のうち issue として扱うもの（配信不可に直結）
_REASON_IS_ISSUE: frozenset[str] = frozenset(
    {
        "CAMPAIGN_PAUSED",
        "CAMPAIGN_REMOVED",
        "CAMPAIGN_ENDED",
        "BIDDING_STRATEGY_MISCONFIGURED",
        "BUDGET_MISCONFIGURED",
        "NO_AD_GROUPS",
        "NO_KEYWORDS",
        "NO_AD_GROUP_ADS",
        "AD_GROUPS_PAUSED",
        "KEYWORDS_PAUSED",
        "AD_GROUP_ADS_PAUSED",
        "HAS_ADS_DISAPPROVED",
        "MISSING_LEAD_FORM_EXTENSION",
        "MISSING_CALL_EXTENSION",
        "LEAD_FORM_EXTENSION_DISAPPROVED",
        "CALL_EXTENSION_DISAPPROVED",
        "NO_ACTIVE_MOBILE_APP_STORE_LINKS",
        "APP_NOT_RELEASED",
        "HAS_ASSET_GROUPS_DISAPPROVED",
        "NO_ASSET_GROUPS",
    }
)

# bidding_strategy_system_status の学習中ステータス → 日本語理由
_LEARNING_STATUS_REASON: dict[str, str] = {
    "LEARNING_NEW": "新しい入札戦略が作成されたため、最適化に向けて調整中",
    "LEARNING_SETTING_CHANGE": "入札戦略の設定が変更されたため、再調整中",
    "LEARNING_BUDGET_CHANGE": "予算が変更されたため、再調整中",
    "LEARNING_COMPOSITION_CHANGE": "キャンペーン構成（キーワード・広告グループ等）が変更されたため、再調整中",
    "LEARNING_CONVERSION_TYPE_CHANGE": "コンバージョン設定が変更されたため、再調整中",
    "LEARNING_CONVERSION_SETTING_CHANGE": "コンバージョン設定が変更されたため、再調整中",
}

# スマート入札戦略（コンバージョントラッキングが前提）
_SMART_BIDDING_STRATEGIES: frozenset[str] = frozenset(
    {
        "MAXIMIZE_CONVERSIONS",
        "TARGET_CPA",
        "TARGET_ROAS",
        "MAXIMIZE_CONVERSION_VALUE",
    }
)


class _DiagnosticsMixin:
    """キャンペーン診断機能を提供する Mixin"""

    # 親クラス (GoogleAdsApiClient) が提供する属性の型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...

    # 親クラスのメソッド（Mixin が呼び出す）
    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
    async def list_ad_groups(  # type: ignore[empty-body]
        self, campaign_id: str = "", **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def get_performance_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]
    async def list_sitelinks(self, campaign_id: str) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]

    @staticmethod
    def _extract_bidding_details(campaign: Any) -> dict[str, Any]:
        """入札戦略の具体的なパラメータを抽出"""
        details: dict[str, Any] = {}
        strategy = map_bidding_strategy_type(campaign.bidding_strategy_type)
        details["strategy"] = strategy

        if strategy == "TARGET_IMPRESSION_SHARE":
            tis = campaign.target_impression_share
            loc_map = {
                0: "UNSPECIFIED",
                1: "UNKNOWN",
                2: "ANYWHERE_ON_PAGE",
                3: "TOP_OF_PAGE",
                4: "ABSOLUTE_TOP_OF_PAGE",
            }
            loc_val = (
                int(tis.location) if hasattr(tis.location, "__int__") else tis.location
            )
            details["location"] = loc_map.get(loc_val, str(loc_val))
            details["target_fraction_percent"] = tis.location_fraction_micros / 10_000
            details["cpc_bid_ceiling"] = tis.cpc_bid_ceiling_micros / 1_000_000
            # 設定不備の検出
            bid_issues: list[str] = []
            if tis.cpc_bid_ceiling_micros == 0:
                bid_issues.append("上限CPC=¥0: オークションに参加できません")
            if tis.location_fraction_micros == 0:
                bid_issues.append(
                    "目標インプレッションシェア=0%: 表示目標が設定されていません"
                )
            if bid_issues:
                details["issue"] = "; ".join(bid_issues)
        elif strategy == "TARGET_CPA":
            details["target_cpa"] = campaign.target_cpa.target_cpa_micros / 1_000_000
        elif strategy == "MAXIMIZE_CONVERSIONS":
            optional_cpa = campaign.maximize_conversions.target_cpa_micros
            if optional_cpa:
                details["optional_target_cpa"] = optional_cpa / 1_000_000
        elif strategy == "MAXIMIZE_CLICKS":
            ts = campaign.target_spend
            ceiling = getattr(ts, "cpc_bid_ceiling_micros", 0)
            if ceiling:
                details["cpc_bid_ceiling"] = ceiling / 1_000_000
        elif strategy == "TARGET_ROAS":
            details["target_roas"] = campaign.target_roas.target_roas
        return details

    async def diagnose_campaign_delivery(self, campaign_id: str) -> dict[str, Any]:
        """キャンペーンの配信状態を総合診断する

        配信されない原因を体系的にチェックし、問題点と推奨アクションを返す。
        """
        self._validate_id(campaign_id, "campaign_id")
        issues: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []

        # 1. キャンペーン基本情報 + 入札戦略詳細
        campaign_data = await self.get_campaign(campaign_id)
        if not campaign_data:
            return {"error": f"キャンペーンID {campaign_id} が見つかりません"}

        result: dict[str, Any] = {
            "campaign": campaign_data,
        }

        # ステータスチェック
        if campaign_data["status"] != "ENABLED":
            issues.append(
                f"キャンペーンのステータスが {campaign_data['status']} です。"
                "ENABLED でないと配信されません"
            )
        serving_st = campaign_data.get("serving_status", "")
        if serving_st and serving_st != "SERVING":
            issues.append(f"配信ステータスが {serving_st} です（SERVINGではない）")

        # --- NEW: primary_status / primary_status_reasons 分析 ---
        primary_st = campaign_data.get("primary_status", "")
        if primary_st and primary_st != "ELIGIBLE":
            issues.append(
                f"キャンペーンの primary_status が {primary_st} です"
                "（ELIGIBLE 以外は配信に問題がある可能性があります）"
            )

        primary_reasons: list[str] = campaign_data.get("primary_status_reasons", [])
        if primary_reasons:
            result["primary_status_reasons_detail"] = []
            for reason in primary_reasons:
                ja = _PRIMARY_STATUS_REASON_JA.get(reason, reason)
                result["primary_status_reasons_detail"].append(
                    {"reason": reason, "description": ja}
                )
                if reason in _REASON_IS_ISSUE:
                    issues.append(f"[{reason}] {ja}")
                elif reason not in ("UNSPECIFIED", "UNKNOWN"):
                    warnings.append(f"[{reason}] {ja}")

        # --- NEW: 入札戦略システムステータス ---
        bidding_sys_st = campaign_data.get("bidding_strategy_system_status", "")
        if bidding_sys_st:
            if bidding_sys_st.startswith("MISCONFIGURED"):
                issues.append(
                    f"入札戦略のシステムステータスが {bidding_sys_st} です。"
                    "入札戦略の設定を見直してください"
                )
            elif bidding_sys_st.startswith("LEARNING"):
                # 学習中は専用フィールドで目立つように表示
                learning_reason = _LEARNING_STATUS_REASON.get(
                    bidding_sys_st, "入札戦略が学習中です"
                )
                result["learning_status"] = {
                    "status": bidding_sys_st,
                    "description": learning_reason,
                    "message": (
                        "⚠️ このキャンペーンは現在【学習期間中】です。\n"
                        f"理由: {learning_reason}\n"
                        "学習期間中（通常1〜2週間）は以下の操作を控えてください:\n"
                        "• 入札戦略の設定変更（目標CPA/ROAS等）\n"
                        "• 予算の大幅な変更（20%以上）\n"
                        "• キーワードの大量追加・削除\n"
                        "• コンバージョン設定の変更\n"
                        "これらの変更は学習をリセットし、"
                        "パフォーマンスが不安定になる可能性があります。"
                    ),
                }
                warnings.append(
                    f"入札戦略が学習中です（{bidding_sys_st}）。"
                    "1〜2週間は安定するまで待つことを推奨します"
                )
            elif bidding_sys_st.startswith("LIMITED"):
                warnings.append(f"入札戦略が制限されています（{bidding_sys_st}）")

        # --- NEW: キャンペーン期間チェック ---
        today = date.today()
        start_date_str = campaign_data.get("start_date", "")
        end_date_str = campaign_data.get("end_date", "")
        if start_date_str:
            try:
                start_d = date.fromisoformat(start_date_str)
                if start_d > today:
                    issues.append(
                        f"キャンペーンの開始日が未来です（{start_date_str}）。"
                        "開始日まで配信されません"
                    )
            except ValueError:
                pass
        if end_date_str:
            try:
                end_d = date.fromisoformat(end_date_str)
                if end_d < today:
                    issues.append(
                        f"キャンペーンの終了日を過ぎています（{end_date_str}）。"
                        "配信は停止しています"
                    )
            except ValueError:
                pass

        # 予算チェック
        budget_daily = campaign_data.get("budget_daily", 0)
        budget_status = campaign_data.get("budget_status", "")
        if budget_status != "ENABLED":
            issues.append(f"予算のステータスが {budget_status} です")
        if budget_daily <= 0:
            issues.append("日予算が ¥0 です")

        # 入札戦略チェック
        bidding = campaign_data.get("bidding_details", {})
        if bidding.get("issue"):
            issues.append(f"入札戦略の問題: {bidding['issue']}")

        # 2. 広告グループチェック
        ad_groups = await self.list_ad_groups(
            campaign_id=campaign_id, status_filter="ENABLED"
        )
        result["ad_groups_enabled_count"] = len(ad_groups)
        if not ad_groups:
            issues.append("有効な広告グループがありません")

        # 3. キーワードチェック（system_serving_status 追加）
        kw_query = f"""
            SELECT
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.approval_status,
                ad_group_criterion.system_serving_status
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD'
                AND campaign.id = {campaign_id}
                AND ad_group_criterion.status = 'ENABLED'
        """
        kw_response = await self._search(kw_query)  # type: ignore[attr-defined]
        enabled_kws = []
        rarely_served_kws: list[str] = []
        for row in kw_response:
            kw = row.ad_group_criterion
            approval = map_criterion_approval_status(kw.approval_status)
            sys_status = (
                str(kw.system_serving_status)
                if hasattr(kw, "system_serving_status")
                else ""
            )
            enabled_kws.append(
                {
                    "text": kw.keyword.text,
                    "match_type": str(kw.keyword.match_type),
                    "approval_status": approval,
                    "system_serving_status": sys_status,
                }
            )
            if "RARELY_SERVED" in sys_status:
                rarely_served_kws.append(kw.keyword.text)
        result["keywords_enabled_count"] = len(enabled_kws)
        disapproved_kws = [
            k for k in enabled_kws if k["approval_status"] == "DISAPPROVED"
        ]
        if not enabled_kws:
            issues.append("有効なキーワードがありません")
        if disapproved_kws:
            warnings.append(
                f"{len(disapproved_kws)}件のキーワードが不承認です: "
                + ", ".join(k["text"] for k in disapproved_kws[:5])
            )
        # --- NEW: RARELY_SERVED キーワード検出 ---
        if rarely_served_kws:
            warnings.append(
                f"{len(rarely_served_kws)}件のキーワードがほとんど表示されていません"
                f"（RARELY_SERVED）: {', '.join(rarely_served_kws[:5])}"
            )

        # キーワード重複数 + 重複テキスト
        kw_texts = [k["text"].lower() for k in enabled_kws]
        seen: set[str] = set()
        duplicated: list[str] = []
        for t in kw_texts:
            if t in seen and t not in duplicated:
                duplicated.append(t)
            seen.add(t)
        result["keyword_duplicates_count"] = len(duplicated)
        result["keyword_duplicates"] = duplicated

        # 4. 広告チェック（RSA・広告グループ別集計含む）
        ad_query = f"""
            SELECT
                ad_group.id, ad_group.name,
                ad_group_ad.ad.id, ad_group_ad.ad.type,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad.responsive_search_ad.descriptions,
                ad_group_ad.ad.final_urls,
                ad_group_ad.status,
                ad_group_ad.policy_summary.approval_status,
                ad_group_ad.policy_summary.review_status
            FROM ad_group_ad
            WHERE campaign.id = {campaign_id}
                AND ad_group_ad.status = 'ENABLED'
        """
        ad_response = await self._search(ad_query)  # type: ignore[attr-defined]
        enabled_ads = []
        rsa_headline_counts: list[int] = []
        rsa_description_counts: list[int] = []
        rsa_headline_texts: list[str] = []
        rsa_description_texts: list[str] = []
        ad_group_ad_map: dict[str, dict[str, Any]] = {}
        final_urls_set: set[str] = set()
        for row in ad_response:
            ad = row.ad_group_ad
            approval = map_approval_status(ad.policy_summary.approval_status)
            review = map_review_status(ad.policy_summary.review_status)
            ad_type = map_ad_type(ad.ad.type_)
            enabled_ads.append(
                {
                    "ad_id": str(ad.ad.id),
                    "ad_type": ad_type,
                    "approval_status": approval,
                    "review_status": review,
                }
            )
            # final_urls収集
            for url in list(getattr(ad.ad, "final_urls", [])):
                final_urls_set.add(str(url))
            # RSA見出し・説明文数＋テキスト
            if ad_type == "RESPONSIVE_SEARCH_AD":
                headlines = list(getattr(ad.ad.responsive_search_ad, "headlines", []))
                descriptions = list(
                    getattr(ad.ad.responsive_search_ad, "descriptions", [])
                )
                rsa_headline_counts.append(len(headlines))
                rsa_description_counts.append(len(descriptions))
                for h in headlines:
                    text = getattr(h, "text", "")
                    if text and text not in rsa_headline_texts:
                        rsa_headline_texts.append(text)
                for d in descriptions:
                    text = getattr(d, "text", "")
                    if text and text not in rsa_description_texts:
                        rsa_description_texts.append(text)
            # 広告グループ別集計
            ag_id = str(row.ad_group.id)
            ag_name = str(row.ad_group.name)
            if ag_id not in ad_group_ad_map:
                ad_group_ad_map[ag_id] = {
                    "ad_group_id": ag_id,
                    "name": ag_name,
                    "ad_count": 0,
                }
            ad_group_ad_map[ag_id]["ad_count"] += 1

        result["ads_enabled_count"] = len(enabled_ads)
        result["has_rsa"] = len(rsa_headline_counts) > 0
        result["rsa_min_headlines"] = (
            min(rsa_headline_counts) if rsa_headline_counts else 0
        )
        result["rsa_min_descriptions"] = (
            min(rsa_description_counts) if rsa_description_counts else 0
        )
        result["rsa_headline_texts"] = rsa_headline_texts
        result["rsa_description_texts"] = rsa_description_texts
        result["ad_final_urls"] = sorted(final_urls_set)
        result["ad_group_ad_counts"] = list(ad_group_ad_map.values())

        disapproved_ads = [
            a for a in enabled_ads if a["approval_status"] == "DISAPPROVED"
        ]
        limited_ads = [
            a for a in enabled_ads if a["approval_status"] == "APPROVED_LIMITED"
        ]
        if not enabled_ads:
            issues.append("有効な広告がありません")
        if disapproved_ads:
            issues.append(f"{len(disapproved_ads)}件の広告が不承認です")
        if limited_ads:
            warnings.append(
                f"{len(limited_ads)}件の広告が制限付き承認（APPROVED_LIMITED）です。"
                "一部のオーディエンスに表示されない場合があります"
            )

        # 5. 地域ターゲティングチェック
        loc_query = f"""
            SELECT
                campaign_criterion.location.geo_target_constant,
                campaign_criterion.negative
            FROM campaign_criterion
            WHERE campaign.id = {campaign_id}
                AND campaign_criterion.type = 'LOCATION'
        """
        loc_response = await self._search(loc_query)  # type: ignore[attr-defined]
        locations = []
        for row in loc_response:
            cc = row.campaign_criterion
            locations.append(
                {
                    "geo_target": str(cc.location.geo_target_constant),
                    "negative": bool(cc.negative),
                }
            )
        result["location_targeting_count"] = len(locations)
        if not locations:
            warnings.append(
                "地域ターゲティングが未設定です（全世界対象）。"
                "日本限定の場合は geoTargetConstants/2392（日本）を設定してください"
            )

        # 6. パフォーマンス（直近30日）
        try:
            perf = await self.get_performance_report(
                campaign_id=campaign_id, period="LAST_30_DAYS"
            )
            if perf:
                result["performance_last_30_days"] = perf[0].get("metrics", {})
            else:
                result["performance_last_30_days"] = {
                    "impressions": 0,
                    "clicks": 0,
                    "cost": 0,
                }
        except Exception:
            result["performance_last_30_days"] = "取得失敗"

        # 7. サイトリンク数
        try:
            sitelinks = await self.list_sitelinks(campaign_id)
            result["sitelinks_count"] = len(sitelinks)
        except Exception:
            logger.debug("サイトリンク数の取得に失敗", exc_info=True)
            result["sitelinks_count"] = 0

        # 8. 請求設定チェック
        try:
            billing_query = """
                SELECT billing_setup.id, billing_setup.status
                FROM billing_setup
                WHERE billing_setup.status = 'APPROVED'
            """
            billing_response = await self._search(billing_query)  # type: ignore[attr-defined]
            has_billing = any(True for _ in billing_response)
            result["billing_setup"] = "APPROVED" if has_billing else "未設定"
            if not has_billing:
                issues.append(
                    "有効な請求設定がありません。"
                    "Google Ads管理画面で支払い方法を設定してください"
                )
        except Exception:
            result["billing_setup"] = "確認失敗"

        # --- NEW: 8. コンバージョントラッキングチェック（スマート入札時のみ） ---
        strategy = bidding.get("strategy", "")
        if strategy in _SMART_BIDDING_STRATEGIES:
            try:
                cv_query = """
                    SELECT
                        conversion_action.id,
                        conversion_action.status
                    FROM conversion_action
                    WHERE conversion_action.status = 'ENABLED'
                """
                cv_response = await self._search(cv_query)  # type: ignore[attr-defined]
                active_cv_count = sum(1 for _ in cv_response)
                result["active_conversion_actions"] = active_cv_count
                if active_cv_count == 0:
                    issues.append(
                        f"スマート入札（{strategy}）を使用していますが、"
                        "有効なコンバージョンアクションが0件です。"
                        "コンバージョントラッキングを設定してください"
                    )
            except Exception:
                result["active_conversion_actions"] = "確認失敗"

        # --- コンバージョンアクション別実績（直近30日） ---
        # cost_per_conversion は segments.conversion_action_name と同時取得不可のため、
        # キャンペーン全体のコストを別途取得しCV按分でCPAを算出する
        try:
            cv_by_action_query = f"""
                SELECT
                    segments.conversion_action_name,
                    metrics.conversions,
                    metrics.conversions_value
                FROM campaign
                WHERE campaign.id = {campaign_id}
                    AND segments.date DURING LAST_30_DAYS
                    AND metrics.conversions > 0
            """
            cv_by_action_response = await self._search(cv_by_action_query)  # type: ignore[attr-defined]

            # キャンペーン全体のコストとCV数を取得してCPA算出用に使う
            total_cost = float(
                result.get("performance_last_30_days", {}).get("cost", 0)
            )
            total_cv = float(
                result.get("performance_last_30_days", {}).get("conversions", 0)
            )
            campaign_cpa = total_cost / total_cv if total_cv > 0 else 0

            conversion_actions_detail: list[dict[str, Any]] = []
            for row in cv_by_action_response:
                action_name = str(getattr(row.segments, "conversion_action_name", ""))
                conversions = float(row.metrics.conversions)
                # CV按分でCPAを推定
                action_cpa = campaign_cpa if total_cv > 0 else 0
                conversion_actions_detail.append(
                    {
                        "name": action_name,
                        "conversions": conversions,
                        "conversions_value": float(
                            getattr(row.metrics, "conversions_value", 0)
                        ),
                        "cost_per_conversion": round(action_cpa, 0),
                    }
                )
            # CV数降順でソート
            conversion_actions_detail.sort(key=lambda x: x["conversions"], reverse=True)
            result["conversion_actions_detail"] = conversion_actions_detail
        except Exception:
            logger.debug("コンバージョンアクション別実績の取得に失敗", exc_info=True)
            result["conversion_actions_detail"] = []

        # --- NEW: 9. インプレッションシェアチェック ---
        try:
            is_query = f"""
                SELECT
                    metrics.search_impression_share,
                    metrics.search_rank_lost_impression_share,
                    metrics.search_budget_lost_impression_share
                FROM campaign
                WHERE campaign.id = {campaign_id}
                    AND segments.date DURING LAST_30_DAYS
            """
            is_response = await self._search(is_query)  # type: ignore[attr-defined]
            for row in is_response:
                m = row.metrics
                is_data: dict[str, Any] = {}
                search_is = getattr(m, "search_impression_share", None)
                if search_is is not None:
                    is_data["search_impression_share"] = round(
                        float(search_is) * 100, 1
                    )
                rank_lost = getattr(m, "search_rank_lost_impression_share", None)
                if rank_lost is not None:
                    is_data["rank_lost_pct"] = round(float(rank_lost) * 100, 1)
                budget_lost = getattr(m, "search_budget_lost_impression_share", None)
                if budget_lost is not None:
                    is_data["budget_lost_pct"] = round(float(budget_lost) * 100, 1)
                if is_data:
                    result["impression_share"] = is_data
                    if is_data.get("budget_lost_pct", 0) > 20:
                        warnings.append(
                            f"予算制限によりインプレッションの"
                            f"{is_data['budget_lost_pct']}%を逃しています"
                        )
                    if is_data.get("rank_lost_pct", 0) > 30:
                        warnings.append(
                            f"広告ランク不足によりインプレッションの"
                            f"{is_data['rank_lost_pct']}%を逃しています"
                        )
                break  # 最初の行のみ
        except Exception:
            logger.debug("インプレッションシェアの取得に失敗", exc_info=True)

        # 推奨アクション生成
        if bidding.get("strategy") == "TARGET_IMPRESSION_SHARE":
            if bidding.get("cpc_bid_ceiling", 0) == 0:
                recommendations.append(
                    "入札戦略の上限CPCを設定してください（例: ¥500〜¥2,000）。"
                    "¥0のままではオークションに参加できません"
                )
            if bidding.get("target_fraction_percent", 0) == 0:
                recommendations.append(
                    "目標インプレッションシェアを設定してください（例: 50%〜80%）"
                )
            if bidding.get("location", "UNSPECIFIED") == "UNSPECIFIED":
                recommendations.append(
                    "掲載位置を指定してください（ANYWHERE_ON_PAGE / TOP_OF_PAGE / "
                    "ABSOLUTE_TOP_OF_PAGE）"
                )
        if not locations:
            recommendations.append(
                "地域ターゲティングに日本（geoTargetConstants/2392）を追加してください"
            )

        # --- NEW: primary_status_reasons に基づく推奨アクション ---
        for reason in primary_reasons:
            if reason == "BIDDING_STRATEGY_MISCONFIGURED":
                recommendations.append(
                    "入札戦略の設定を確認してください。"
                    "campaigns.get で詳細パラメータを確認し、"
                    "上限CPC・目標CPA等の必須パラメータが設定されているか確認してください"
                )
            elif reason == "BUDGET_CONSTRAINED":
                recommendations.append(
                    "日予算の増額を検討してください。"
                    "現在の予算ではインプレッション機会を逃しています。"
                    "budget.update で予算を調整できます"
                )
            elif reason == "SEARCH_VOLUME_LIMITED":
                recommendations.append(
                    "キーワードの追加やマッチタイプの変更を検討してください。"
                    "部分一致への変更や関連キーワードの追加で検索ボリュームを拡大できます"
                )
            elif reason == "HAS_ADS_DISAPPROVED":
                recommendations.append(
                    "不承認の広告を確認・修正してください。"
                    "ads.policy で不承認理由を確認し、ポリシーに準拠した内容に修正してください"
                )

        # スマート入札 + CV未設定の推奨アクション
        if (
            strategy in _SMART_BIDDING_STRATEGIES
            and result.get("active_conversion_actions") == 0
        ):
            recommendations.append(
                "コンバージョンアクションを設定してください。"
                "Google Ads管理画面の「ツール > コンバージョン」から設定できます。"
                "設定後、Google Tag Manager等でタグを設置してください"
            )

        result["issues"] = issues
        result["warnings"] = warnings
        result["recommendations"] = recommendations
        result["diagnosis"] = (
            "問題なし" if not issues else f"{len(issues)}件の問題が見つかりました"
        )
        return result
