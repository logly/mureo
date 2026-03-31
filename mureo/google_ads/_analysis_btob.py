"""BtoB最適化提案 Mixin。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._analysis_constants import _INFORMATIONAL_PATTERNS

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _BtoBAnalysisMixin:
    """BtoB最適化提案系メソッドを提供する Mixin。"""

    # 親クラスが提供する属性・メソッドの型宣言
    _customer_id: str
    _client: "GoogleAdsClient"

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
    async def get_search_terms_report(
        self, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def list_schedule_targeting(
        self, campaign_id: str
    ) -> list[dict[str, Any]]: ...
    async def analyze_device_performance(
        self, campaign_id: str, period: str = "LAST_30_DAYS"
    ) -> dict[str, Any]: ...

    # =================================================================
    # BtoB最適化提案
    # =================================================================

    async def suggest_btob_optimizations(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """BtoBビジネス向けの最適化チェックを実行し、改善提案を生成する。"""
        self._validate_id(campaign_id, "campaign_id")

        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"キャンペーンID {campaign_id} が見つかりません"}

        suggestions: list[dict[str, Any]] = []

        # 1. 広告スケジュール（営業時間外配信チェック）
        await self._check_schedule_for_btob(campaign_id, suggestions)

        # 2. デバイス別CPA格差チェック
        await self._check_device_for_btob(campaign_id, period, suggestions)

        # 3. 検索語句の情報収集系比率チェック
        await self._check_search_terms_for_btob(campaign_id, period, suggestions)

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name", ""),
            "period": period,
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
        }

    async def _check_schedule_for_btob(
        self,
        campaign_id: str,
        suggestions: list[dict[str, Any]],
    ) -> None:
        """広告スケジュールのBtoB最適化チェック。"""
        try:
            schedules = await self.list_schedule_targeting(campaign_id)
        except Exception:
            return

        if not schedules:
            suggestions.append({
                "category": "schedule",
                "priority": "HIGH",
                "message": "広告スケジュールが未設定です。"
                "BtoBでは営業時間帯（平日9-18時）に集中配信することで"
                "無駄なコストを削減できます。",
            })
            return

        # 土日配信チェック
        weekend_days = {"SATURDAY", "SUNDAY"}
        weekend_schedules = [
            s for s in schedules
            if s.get("day_of_week", "") in weekend_days
        ]
        if weekend_schedules:
            suggestions.append({
                "category": "schedule",
                "priority": "MEDIUM",
                "message": "土日に広告が配信されています。"
                "BtoBでは土日のCV率が低い傾向があります。"
                "配信停止または入札調整率の引き下げを検討してください。",
            })

    async def _check_device_for_btob(
        self,
        campaign_id: str,
        period: str,
        suggestions: list[dict[str, Any]],
    ) -> None:
        """デバイス別CPAのBtoB最適化チェック。"""
        try:
            device_result = await self.analyze_device_performance(campaign_id, period)
        except Exception:
            return

        devices = device_result.get("devices", [])
        mobile = next(
            (d for d in devices if d["device_type"] in ("MOBILE", "2")),
            None,
        )
        desktop = next(
            (d for d in devices if d["device_type"] in ("DESKTOP", "1")),
            None,
        )

        if mobile and desktop:
            mobile_cpa = mobile.get("cpa")
            desktop_cpa = desktop.get("cpa")
            if mobile_cpa and desktop_cpa and desktop_cpa > 0:
                if mobile_cpa > desktop_cpa * 1.3:
                    suggestions.append({
                        "category": "device",
                        "priority": "MEDIUM",
                        "message": f"モバイルCPA（{mobile_cpa}円）がPC（{desktop_cpa}円）より高いです。"
                        "BtoBではPC経由のCVが多い傾向があります。"
                        "モバイルの入札調整率引き下げを検討してください。",
                    })

        # タブレットのCV0チェック
        tablet = next(
            (d for d in devices if d["device_type"] in ("TABLET", "6")),
            None,
        )
        if tablet and tablet.get("conversions", 0) == 0 and tablet.get("cost", 0) > 0:
            suggestions.append({
                "category": "device",
                "priority": "LOW",
                "message": f"タブレットはCV0で{tablet['cost']}円のコストが発生しています。"
                "BtoBではタブレットからの問い合わせは稀です。配信除外を検討してください。",
            })

    async def _check_search_terms_for_btob(
        self,
        campaign_id: str,
        period: str,
        suggestions: list[dict[str, Any]],
    ) -> None:
        """検索語句のBtoB最適化チェック。"""
        try:
            search_terms = await self.get_search_terms_report(
                campaign_id=campaign_id, period=period
            )
        except Exception:
            return

        if not search_terms:
            return

        total = len(search_terms)
        informational_count = 0
        for t in search_terms:
            term = t.get("search_term", "").lower()
            if any(p in term for p in _INFORMATIONAL_PATTERNS):
                informational_count += 1

        if total > 0:
            ratio = informational_count / total * 100
            if ratio > 20:
                suggestions.append({
                    "category": "search_terms",
                    "priority": "MEDIUM",
                    "message": f"情報収集系の検索語句が{round(ratio)}%を占めています。"
                    "BtoBでは「とは」「比較」「無料」等の語句は"
                    "CVに繋がりにくい傾向があります。除外キーワードの追加を検討してください。",
                })
