"""コンバージョンアクション操作 Mixin。

list / get / create / update / remove / tag / performance を提供する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from google.protobuf.field_mask_pb2 import FieldMask as PbFieldMask

from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import map_conversion_action, map_tag_snippet

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

_VALID_CONVERSION_ACTION_TYPES = frozenset({
    "WEBPAGE", "UPLOAD_CLICKS", "UPLOAD_CALLS", "AD_CALL",
    "WEBSITE_CALL", "STORE_SALES_DIRECT_UPLOAD", "STORE_SALES",
})
_VALID_CONVERSION_ACTION_CATEGORIES = frozenset({
    "DEFAULT", "PAGE_VIEW", "PURCHASE", "SIGNUP", "DOWNLOAD",
    "ADD_TO_CART", "BEGIN_CHECKOUT", "SUBSCRIBE_PAID", "PHONE_CALL_LEAD",
    "IMPORTED_LEAD", "SUBMIT_LEAD_FORM", "BOOK_APPOINTMENT",
    "REQUEST_QUOTE", "GET_DIRECTIONS", "OUTBOUND_CLICK", "CONTACT",
    "ENGAGEMENT", "STORE_VISIT", "STORE_SALE",
    "QUALIFIED_LEAD", "CONVERTED_LEAD",
})
_VALID_CONVERSION_ACTION_STATUSES = frozenset({"ENABLED", "HIDDEN", "REMOVED"})


class _ConversionsMixin:
    """コンバージョンアクション操作を提供する Mixin。"""

    # 親クラス (GoogleAdsApiClient) が提供する属性の型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    def _get_service(self, service_name: str) -> Any: ...

    async def list_conversion_actions(self) -> list[dict[str, Any]]:
        """コンバージョンアクション一覧"""

        query = """
            SELECT
                conversion_action.id, conversion_action.name,
                conversion_action.type, conversion_action.status,
                conversion_action.category
            FROM conversion_action
            ORDER BY conversion_action.id
        """
        response = await self._search(query)
        return [map_conversion_action(row.conversion_action) for row in response]

    async def get_conversion_performance(
        self,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """コンバージョンアクション別の実績を取得する。

        キャンペーン単位またはアカウント全体のコンバージョンアクション別
        CV数・CV値を日別ブレイクダウン付きで返す。
        cost_per_conversion は segments.conversion_action_name と同時取得
        できないため、別クエリでキャンペーン別コストを取得しCPAを算出する。
        """
        date_clause = self._period_to_date_clause(period)
        campaign_filter = ""
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            campaign_filter = f"AND campaign.id = {campaign_id}"

        # CV アクション別 × 日別 実績
        cv_query = f"""
            SELECT
                campaign.id,
                campaign.name,
                segments.date,
                segments.conversion_action_name,
                segments.conversion_action,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date {date_clause}
                AND metrics.conversions > 0
                {campaign_filter}
            ORDER BY segments.date DESC
        """
        response = await self._search(cv_query)

        # 日別明細とアクション別サマリーを同時構築
        daily_details: list[dict[str, Any]] = []
        action_summary: dict[str, dict[str, Any]] = {}
        campaign_cv_totals: dict[str, float] = {}

        for row in response:
            cid = str(row.campaign.id)
            cname = str(row.campaign.name)
            action_name = str(
                getattr(row.segments, "conversion_action_name", "")
            )
            cv_date = str(getattr(row.segments, "date", ""))
            cvs = float(row.metrics.conversions)
            cv_value = float(
                getattr(row.metrics, "conversions_value", 0)
            )

            campaign_cv_totals[cid] = campaign_cv_totals.get(cid, 0) + cvs

            # 日別明細
            daily_details.append({
                "date": cv_date,
                "campaign_id": cid,
                "campaign_name": cname,
                "conversion_action_name": action_name,
                "conversions": cvs,
                "conversions_value": cv_value,
            })

            # アクション別サマリー集計
            summary_key = f"{cid}:{action_name}"
            if summary_key not in action_summary:
                action_summary[summary_key] = {
                    "campaign_id": cid,
                    "campaign_name": cname,
                    "conversion_action_name": action_name,
                    "conversions": 0.0,
                    "conversions_value": 0.0,
                    "first_date": cv_date,
                    "last_date": cv_date,
                }
            s = action_summary[summary_key]
            s["conversions"] += cvs
            s["conversions_value"] += cv_value
            # 日付範囲を更新（降順なので最初が最新）
            if cv_date < s["first_date"]:
                s["first_date"] = cv_date
            if cv_date > s["last_date"]:
                s["last_date"] = cv_date

        actions = list(action_summary.values())

        # キャンペーン別コストを別クエリで取得（CPA算出用）
        cost_query = f"""
            SELECT
                campaign.id,
                metrics.cost_micros
            FROM campaign
            WHERE segments.date {date_clause}
                {campaign_filter}
        """
        try:
            cost_response = await self._search(cost_query)
            campaign_costs: dict[str, float] = {}
            for row in cost_response:
                cid = str(row.campaign.id)
                cost = row.metrics.cost_micros / 1_000_000
                campaign_costs[cid] = campaign_costs.get(cid, 0) + cost

            for action in actions:
                cid = action["campaign_id"]
                total_cost = campaign_costs.get(cid, 0)
                total_cv = campaign_cv_totals.get(cid, 0)
                if total_cv > 0 and total_cost > 0:
                    action["cost_per_conversion"] = round(
                        total_cost / total_cv, 0
                    )
                else:
                    action["cost_per_conversion"] = 0
        except Exception:
            logger.warning("キャンペーン別コスト取得に失敗、CPAは0で返却")
            for action in actions:
                action["cost_per_conversion"] = 0

        # ランディングページ別CV実績を取得
        lp_campaign_filter = ""
        if campaign_id:
            lp_campaign_filter = f"AND campaign.id = {campaign_id}"
        lp_query = f"""
            SELECT
                landing_page_view.unexpanded_final_url,
                campaign.id,
                campaign.name,
                segments.date,
                metrics.conversions,
                metrics.conversions_value,
                metrics.clicks
            FROM landing_page_view
            WHERE segments.date {date_clause}
                AND metrics.conversions > 0
                {lp_campaign_filter}
            ORDER BY metrics.conversions DESC
        """
        landing_pages: list[dict[str, Any]] = []
        try:
            lp_response = await self._search(lp_query)
            for row in lp_response:
                landing_pages.append({
                    "date": str(getattr(row.segments, "date", "")),
                    "landing_page_url": str(
                        row.landing_page_view.unexpanded_final_url
                    ),
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": str(row.campaign.name),
                    "conversions": float(row.metrics.conversions),
                    "conversions_value": float(
                        getattr(row.metrics, "conversions_value", 0)
                    ),
                    "clicks": int(row.metrics.clicks),
                })
        except Exception:
            logger.warning("ランディングページ別CV取得に失敗")

        # CV数降順でソート
        actions.sort(key=lambda x: x["conversions"], reverse=True)

        total_conversions = sum(a["conversions"] for a in actions)
        return {
            "period": period,
            "campaign_id": campaign_id,
            "total_conversions": total_conversions,
            "actions": actions,
            "daily_details": daily_details,
            "landing_pages": landing_pages,
        }

    async def get_conversion_action(
        self, conversion_action_id: str
    ) -> dict[str, Any] | None:
        """コンバージョンアクション詳細"""
        self._validate_id(conversion_action_id, "conversion_action_id")

        query = f"""
            SELECT
                conversion_action.id, conversion_action.name,
                conversion_action.type, conversion_action.status,
                conversion_action.category
            FROM conversion_action
            WHERE conversion_action.id = {conversion_action_id}
        """
        response = await self._search(query)
        for row in response:
            return map_conversion_action(row.conversion_action)
        return None

    @_wrap_mutate_error("コンバージョンアクション作成")
    async def create_conversion_action(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """コンバージョンアクション作成"""
        name = params.get("name", "")
        if not name:
            raise ValueError("name は必須です")
        if len(name) > 256:
            raise ValueError("name は256文字以内で指定してください")

        action_type = params.get("type", "WEBPAGE").upper()
        if action_type not in _VALID_CONVERSION_ACTION_TYPES:
            raise ValueError(
                f"不正な type: {action_type}。"
                f"有効な値: {sorted(_VALID_CONVERSION_ACTION_TYPES)}"
            )

        category = params.get("category", "DEFAULT").upper()
        if category not in _VALID_CONVERSION_ACTION_CATEGORIES:
            raise ValueError(
                f"不正な category: {category}。"
                f"有効な値: {sorted(_VALID_CONVERSION_ACTION_CATEGORIES)}"
            )

        ca_service = self._get_service("ConversionActionService")
        op = self._client.get_type("ConversionActionOperation")
        action = op.create
        action.name = name
        action.type_ = getattr(
            self._client.enums.ConversionActionTypeEnum, action_type
        )
        action.category = getattr(
            self._client.enums.ConversionActionCategoryEnum, category
        )

        if "default_value" in params:
            action.value_settings.default_value = float(params["default_value"])
        if "always_use_default_value" in params:
            action.value_settings.always_use_default_value = bool(
                params["always_use_default_value"]
            )

        if "click_through_lookback_window_days" in params:
            days = int(params["click_through_lookback_window_days"])
            if not (1 <= days <= 90):
                raise ValueError(
                    "click_through_lookback_window_days は 1〜90 の範囲で指定してください"
                )
            action.click_through_lookback_window_days = days
        if "view_through_lookback_window_days" in params:
            days = int(params["view_through_lookback_window_days"])
            if not (1 <= days <= 30):
                raise ValueError(
                    "view_through_lookback_window_days は 1〜30 の範囲で指定してください"
                )
            action.view_through_lookback_window_days = days

        response = ca_service.mutate_conversion_actions(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}

    @_wrap_mutate_error("コンバージョンアクション更新")
    async def update_conversion_action(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """コンバージョンアクション更新"""
        self._validate_id(params["conversion_action_id"], "conversion_action_id")

        ca_service = self._get_service("ConversionActionService")
        op = self._client.get_type("ConversionActionOperation")
        action = op.update
        action.resource_name = self._client.get_service(
            "ConversionActionService"
        ).conversion_action_path(
            self._customer_id, params["conversion_action_id"]
        )

        paths: list[str] = []

        if "name" in params:
            if len(params["name"]) > 256:
                raise ValueError("name は256文字以内で指定してください")
            action.name = params["name"]
            paths.append("name")
        if "category" in params:
            cat = params["category"].upper()
            if cat not in _VALID_CONVERSION_ACTION_CATEGORIES:
                raise ValueError(
                    f"不正な category: {cat}。"
                    f"有効な値: {sorted(_VALID_CONVERSION_ACTION_CATEGORIES)}"
                )
            action.category = getattr(
                self._client.enums.ConversionActionCategoryEnum, cat
            )
            paths.append("category")
        if "status" in params:
            status = params["status"].upper()
            if status not in _VALID_CONVERSION_ACTION_STATUSES:
                raise ValueError(
                    f"不正な status: {status}。"
                    f"有効な値: {sorted(_VALID_CONVERSION_ACTION_STATUSES)}"
                )
            action.status = getattr(
                self._client.enums.ConversionActionStatusEnum, status
            )
            paths.append("status")
        if "default_value" in params:
            action.value_settings.default_value = float(params["default_value"])
            paths.append("value_settings.default_value")
        if "always_use_default_value" in params:
            action.value_settings.always_use_default_value = bool(
                params["always_use_default_value"]
            )
            paths.append("value_settings.always_use_default_value")
        if "click_through_lookback_window_days" in params:
            days = int(params["click_through_lookback_window_days"])
            if not (1 <= days <= 90):
                raise ValueError(
                    "click_through_lookback_window_days は 1〜90 の範囲で指定してください"
                )
            action.click_through_lookback_window_days = days
            paths.append("click_through_lookback_window_days")
        if "view_through_lookback_window_days" in params:
            days = int(params["view_through_lookback_window_days"])
            if not (1 <= days <= 30):
                raise ValueError(
                    "view_through_lookback_window_days は 1〜30 の範囲で指定してください"
                )
            action.view_through_lookback_window_days = days
            paths.append("view_through_lookback_window_days")

        if not paths:
            raise ValueError("更新するフィールドを1つ以上指定してください")

        self._client.copy_from(
            op.update_mask,
            PbFieldMask(paths=paths),
        )
        response = ca_service.mutate_conversion_actions(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}

    @_wrap_mutate_error("コンバージョンアクション削除")
    async def remove_conversion_action(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """コンバージョンアクション削除"""
        self._validate_id(params["conversion_action_id"], "conversion_action_id")
        ca_service = self._get_service("ConversionActionService")
        op = self._client.get_type("ConversionActionOperation")
        op.remove = self._client.get_service(
            "ConversionActionService"
        ).conversion_action_path(
            self._customer_id, params["conversion_action_id"]
        )
        response = ca_service.mutate_conversion_actions(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}

    async def get_conversion_action_tag(
        self, conversion_action_id: str
    ) -> list[dict[str, Any]]:
        """コンバージョンアクションのタグスニペット取得"""
        self._validate_id(conversion_action_id, "conversion_action_id")

        query = f"""
            SELECT
                conversion_action.id,
                conversion_action.name,
                conversion_action.tag_snippets
            FROM conversion_action
            WHERE conversion_action.id = {conversion_action_id}
        """
        response = await self._search(query)
        for row in response:
            snippets = row.conversion_action.tag_snippets
            return [map_tag_snippet(s) for s in snippets]
        return []
