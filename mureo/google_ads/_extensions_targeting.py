"""ターゲティング・推奨事項・変更履歴 Mixin。

デバイスターゲティング、入札調整、地域ターゲティング、
スケジュールターゲティング、推奨事項、変更履歴を提供する。
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from google.protobuf.field_mask_pb2 import FieldMask as PbFieldMask

from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import map_change_event, map_recommendation

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

_RESOURCE_NAME_PATTERN = re.compile(r"customers/\d+/recommendations/\d+")

# Google Ads DeviceEnum の整数値→デバイス名マッピング
# API v23 の campaign_criterion.device.type_ は int を返す
_DEVICE_ENUM_MAP: dict[int, str] = {
    2: "MOBILE",
    3: "TABLET",
    4: "DESKTOP",
}


def _normalize_device_type(raw: Any) -> str:
    """device.type_ の値をデバイス名に正規化する。

    APIは整数(2,3,4)を返すが、Mockテスト等では文字列("DESKTOP"等)や
    "DeviceType.DESKTOP"形式を返す場合がある。全パターンに対応する。
    """
    # 整数の場合
    if isinstance(raw, int):
        return _DEVICE_ENUM_MAP.get(raw, f"UNKNOWN({raw})")
    s = str(raw)
    # "DeviceType.DESKTOP" 形式
    if "." in s:
        return s.split(".")[-1]
    # 整数文字列 "2", "3", "4"
    try:
        return _DEVICE_ENUM_MAP.get(int(s), s)
    except ValueError:
        pass
    # そのまま "DESKTOP" 等
    return s


class _TargetingMixin:
    """ターゲティング・推奨事項・変更履歴を提供する Mixin。"""

    # 親クラス (GoogleAdsApiClient) が提供する属性の型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _validate_date(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _validate_recommendation_type(rec_type: str) -> str: ...  # type: ignore[empty-body]
    @staticmethod
    def _validate_resource_name(  # type: ignore[empty-body]
        value: str, pattern: re.Pattern[str], field_name: str,
    ) -> str: ...

    def _get_service(self, service_name: str) -> Any: ...

    # === 推奨事項 ===

    async def list_recommendations(
        self,
        campaign_id: str | None = None,
        recommendation_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Google推奨事項一覧"""

        query = """
            SELECT
                recommendation.resource_name, recommendation.type,
                recommendation.impact, recommendation.campaign
            FROM recommendation
        """
        conditions = []
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            conditions.append(
                f"recommendation.campaign = 'customers/{self._customer_id}/campaigns/{campaign_id}'"
            )
        if recommendation_type:
            validated_type = self._validate_recommendation_type(recommendation_type)
            conditions.append(f"recommendation.type = '{validated_type}'")
        if conditions:
            query += "\n            WHERE " + " AND ".join(conditions)
        response = await self._search(query)
        return [map_recommendation(row.recommendation) for row in response]

    @_wrap_mutate_error("推奨事項適用")
    async def apply_recommendation(self, params: dict[str, Any]) -> dict[str, Any]:
        """推奨事項を適用"""
        resource_name = self._validate_resource_name(
            params["resource_name"],
            _RESOURCE_NAME_PATTERN,
            "resource_name",
        )
        rec_service = self._get_service("RecommendationService")
        op = self._client.get_type("ApplyRecommendationOperation")
        op.resource_name = resource_name
        response = rec_service.apply_recommendation(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}

    # === デバイスターゲティング ===

    async def get_device_targeting(self, campaign_id: str) -> list[dict[str, Any]]:
        """キャンペーンのデバイスターゲティング設定を取得

        全DEVICEタイプのcriterionを取得し、bid_modifierの値で配信状態を判定する。
        bid_modifier=0.0は配信停止(-100%)、それ以外は配信中。
        criterionが存在しないデバイスはデフォルト配信中として返す。
        """
        self._validate_id(campaign_id, "campaign_id")

        query = f"""
            SELECT
                campaign_criterion.criterion_id,
                campaign_criterion.device.type,
                campaign_criterion.bid_modifier
            FROM campaign_criterion
            WHERE campaign.id = {campaign_id}
                AND campaign_criterion.type = 'DEVICE'
        """
        response = await self._search(query)
        found: dict[str, dict[str, Any]] = {}
        for row in response:
            normalized = _normalize_device_type(
                row.campaign_criterion.device.type_,
            )
            bid_modifier = float(row.campaign_criterion.bid_modifier)
            found[normalized] = {
                "criterion_id": str(row.campaign_criterion.criterion_id),
                "device_type": normalized,
                "bid_modifier": bid_modifier,
                "enabled": not math.isclose(bid_modifier, 0.0, abs_tol=1e-9),
            }
        # 常に3デバイス全て返す（明示設定なし＝デフォルト配信中）
        all_devices = ["DESKTOP", "MOBILE", "TABLET"]
        return [
            found.get(d, {
                "criterion_id": None,
                "device_type": d,
                "bid_modifier": None,
                "enabled": True,
            })
            for d in all_devices
        ]

    @_wrap_mutate_error("デバイスターゲティング更新")
    async def set_device_targeting(self, params: dict[str, Any]) -> dict[str, Any]:
        """デバイスターゲティングを設定（指定デバイスのみ配信）

        全デバイスcriterionのbid_modifierを常に明示的に設定する。
        デバイスごとに個別にmutateを実行し、1件の失敗が他に影響しないようにする。
        """
        campaign_id = params["campaign_id"]
        self._validate_id(campaign_id, "campaign_id")

        enabled_devices = {d.upper() for d in params["enabled_devices"]}
        valid_devices = {"MOBILE", "DESKTOP", "TABLET"}
        invalid = enabled_devices - valid_devices
        if invalid:
            raise ValueError(f"無効なデバイスタイプ: {invalid}。有効値: {valid_devices}")
        if not enabled_devices:
            raise ValueError("最低1つのデバイスを有効にしてください")

        # 全デバイスcriterionのIDを取得（bid_modifier設定有無に関わらず）

        query = f"""
            SELECT
                campaign_criterion.criterion_id,
                campaign_criterion.device.type,
                campaign_criterion.bid_modifier
            FROM campaign_criterion
            WHERE campaign.id = {campaign_id}
                AND campaign_criterion.type = 'DEVICE'
        """
        response = await self._search(query)
        criterion_map: dict[str, dict[str, Any]] = {}
        for row in response:
            normalized = _normalize_device_type(
                row.campaign_criterion.device.type_,
            )
            criterion_map[normalized] = {
                "criterion_id": str(row.campaign_criterion.criterion_id),
                "bid_modifier": float(row.campaign_criterion.bid_modifier),
            }

        logger.info(
            "デバイスターゲティング設定: campaign=%s, 既存criteria=%s, 有効化=%s",
            campaign_id,
            {k: v["criterion_id"] for k, v in criterion_map.items()},
            sorted(enabled_devices),
        )

        cc_service = self._get_service("CampaignCriterionService")
        updated: list[str] = []
        errors: list[str] = []

        for device_type in sorted(valid_devices):
            new_modifier = 1.0 if device_type in enabled_devices else 0.0
            existing = criterion_map.get(device_type)

            op = self._client.get_type("CampaignCriterionOperation")

            if existing:
                criterion_id = existing["criterion_id"]
                criterion = op.update
                criterion.resource_name = cc_service.campaign_criterion_path(
                    self._customer_id, campaign_id, criterion_id,
                )
                criterion.bid_modifier = new_modifier
                self._client.copy_from(
                    op.update_mask, PbFieldMask(paths=["bid_modifier"]),
                )
                op_type = "UPDATE"
            else:
                criterion = op.create
                criterion.campaign = self._client.get_service(
                    "CampaignService",
                ).campaign_path(self._customer_id, campaign_id)
                criterion.device.type_ = getattr(
                    self._client.enums.DeviceEnum, device_type,
                )
                criterion.bid_modifier = new_modifier
                op_type = "CREATE"

            try:
                resp = cc_service.mutate_campaign_criteria(
                    customer_id=self._customer_id, operations=[op],
                )
                updated.extend(r.resource_name for r in resp.results)
                logger.info(
                    "デバイス %s: %s 成功 (bid_modifier=%.1f)",
                    device_type, op_type, new_modifier,
                )
            except Exception as exc:
                detail = (
                    self._extract_error_detail(exc)
                    if hasattr(exc, "failure")
                    else str(exc)
                )
                logger.error(
                    "デバイス %s: %s 失敗 (bid_modifier=%.1f): %s",
                    device_type, op_type, new_modifier, detail,
                )
                errors.append(f"{device_type}({op_type}): {detail}")

        if not updated and errors:
            raise ValueError(
                f"全デバイスの設定に失敗しました: {'; '.join(errors)}"
            )

        return {
            "message": "デバイスターゲティングを更新しました",
            "enabled_devices": sorted(enabled_devices),
            "disabled_devices": sorted(valid_devices - enabled_devices),
            "updated": updated,
            "errors": errors if errors else None,
        }

    # === 入札調整 ===

    async def get_bid_adjustments(self, campaign_id: str) -> list[dict[str, Any]]:
        """キャンペーンの入札調整率を取得"""
        self._validate_id(campaign_id, "campaign_id")

        query = f"""
            SELECT
                campaign_criterion.criterion_id,
                campaign_criterion.type,
                campaign_criterion.bid_modifier,
                campaign_criterion.device.type
            FROM campaign_criterion
            WHERE campaign.id = {campaign_id}
                AND campaign_criterion.bid_modifier IS NOT NULL
        """
        response = await self._search(query)
        return [
            {
                "criterion_id": str(row.campaign_criterion.criterion_id),
                "type": (
                    str(row.campaign_criterion.type_)
                    if hasattr(row.campaign_criterion, "type_")
                    else str(row.campaign_criterion.type)
                ),
                "bid_modifier": float(row.campaign_criterion.bid_modifier),
                "device_type": (
                    _normalize_device_type(row.campaign_criterion.device.type_)
                    if hasattr(row.campaign_criterion, "device")
                    and hasattr(row.campaign_criterion.device, "type_")
                    else None
                ),
            }
            for row in response
        ]

    @_wrap_mutate_error("入札調整率更新")
    async def update_bid_adjustment(self, params: dict[str, Any]) -> dict[str, Any]:
        """入札調整率を更新

        注意: BudgetGuardによるバリデーション（validate_bid_adjustment）はManaged側で実施する。
        """
        self._validate_id(params["campaign_id"], "campaign_id")
        self._validate_id(params["criterion_id"], "criterion_id")
        bid_modifier = float(params["bid_modifier"])
        if not (0.1 <= bid_modifier <= 10.0):
            raise ValueError(
                f"bid_modifier は 0.1 ~ 10.0 の範囲で指定してください: {bid_modifier}"
            )

        cc_service = self._get_service("CampaignCriterionService")
        op = self._client.get_type("CampaignCriterionOperation")
        criterion = op.update
        criterion.resource_name = self._client.get_service(
            "CampaignCriterionService"
        ).campaign_criterion_path(
            self._customer_id,
            params["campaign_id"],
            params["criterion_id"],
        )
        criterion.bid_modifier = bid_modifier
        self._client.copy_from(
            op.update_mask,
            PbFieldMask(paths=["bid_modifier"]),
        )
        response = cc_service.mutate_campaign_criteria(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}

    # === 変更履歴 ===

    async def list_change_history(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """変更履歴一覧

        APIは日付範囲フィルターを必須とするため、未指定時は直近14日間をデフォルトとする。
        """

        query = """
            SELECT
                change_event.change_date_time,
                change_event.change_resource_type,
                change_event.resource_change_operation,
                change_event.changed_fields,
                change_event.user_email
            FROM change_event
        """
        # APIは CHANGE_DATE_RANGE_INFINITE を拒否するため、デフォルト日付範囲を設定
        if not start_date:
            start_date = (date.today() - timedelta(days=14)).isoformat()
        if not end_date:
            end_date = date.today().isoformat()
        validated_start = self._validate_date(start_date, "start_date")
        validated_end = self._validate_date(end_date, "end_date")
        conditions = [
            f"change_event.change_date_time >= '{validated_start} 00:00:00'",
            f"change_event.change_date_time <= '{validated_end} 23:59:59'",
        ]
        query += "\n            WHERE " + " AND ".join(conditions)
        query += "\n            ORDER BY change_event.change_date_time DESC"
        query += "\n            LIMIT 100"
        response = await self._search(query)
        return [map_change_event(row.change_event) for row in response]

    # === 地域ターゲティング ===

    async def list_location_targeting(self, campaign_id: str) -> list[dict[str, Any]]:
        """キャンペーンの地域ターゲティング一覧"""
        self._validate_id(campaign_id, "campaign_id")

        query = f"""
            SELECT
                campaign_criterion.criterion_id,
                campaign_criterion.location.geo_target_constant,
                campaign_criterion.bid_modifier
            FROM campaign_criterion
            WHERE campaign_criterion.type = 'LOCATION'
                AND campaign.id = {campaign_id}
        """
        response = await self._search(query)
        return [
            {
                "criterion_id": str(row.campaign_criterion.criterion_id),
                "geo_target_constant": str(
                    row.campaign_criterion.location.geo_target_constant
                ),
                "bid_modifier": (
                    float(row.campaign_criterion.bid_modifier)
                    if hasattr(row.campaign_criterion, "bid_modifier")
                    and row.campaign_criterion.bid_modifier
                    else None
                ),
            }
            for row in response
        ]

    @_wrap_mutate_error("地域ターゲティング更新")
    async def update_location_targeting(
        self, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """地域ターゲティング更新（追加/削除）

        注意: BudgetGuardによるターゲティング拡大ガード（validate_targeting_expansion）はManaged側で実施する。
        """
        cc_service = self._get_service("CampaignCriterionService")
        operations = []

        # 追加
        for loc_id in params.get("add_locations", []):
            op = self._client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = self._client.get_service(
                "CampaignService"
            ).campaign_path(self._customer_id, params["campaign_id"])
            # "geoTargetConstants/2392" と "2392" の両方を受け付ける
            loc_str = str(loc_id)
            if not loc_str.startswith("geoTargetConstants/"):
                loc_str = f"geoTargetConstants/{loc_str}"
            criterion.location.geo_target_constant = loc_str
            operations.append(op)

        # 削除
        for cid in params.get("remove_criterion_ids", []):
            op = self._client.get_type("CampaignCriterionOperation")
            op.remove = self._client.get_service(
                "CampaignCriterionService"
            ).campaign_criterion_path(self._customer_id, params["campaign_id"], cid)
            operations.append(op)

        response = cc_service.mutate_campaign_criteria(
            customer_id=self._customer_id,
            operations=operations,
        )
        return [{"resource_name": r.resource_name} for r in response.results]

    # === 広告スケジュール ===

    async def list_schedule_targeting(self, campaign_id: str) -> list[dict[str, Any]]:
        """キャンペーンの広告スケジュール一覧"""
        self._validate_id(campaign_id, "campaign_id")

        query = f"""
            SELECT
                campaign_criterion.criterion_id,
                campaign_criterion.ad_schedule.day_of_week,
                campaign_criterion.ad_schedule.start_hour,
                campaign_criterion.ad_schedule.end_hour,
                campaign_criterion.ad_schedule.start_minute,
                campaign_criterion.ad_schedule.end_minute,
                campaign_criterion.bid_modifier
            FROM campaign_criterion
            WHERE campaign_criterion.type = 'AD_SCHEDULE'
                AND campaign.id = {campaign_id}
        """
        response = await self._search(query)
        return [
            {
                "criterion_id": str(row.campaign_criterion.criterion_id),
                "day_of_week": str(row.campaign_criterion.ad_schedule.day_of_week),
                "start_hour": int(row.campaign_criterion.ad_schedule.start_hour),
                "end_hour": int(row.campaign_criterion.ad_schedule.end_hour),
                "start_minute": str(row.campaign_criterion.ad_schedule.start_minute),
                "end_minute": str(row.campaign_criterion.ad_schedule.end_minute),
                "bid_modifier": (
                    float(row.campaign_criterion.bid_modifier)
                    if hasattr(row.campaign_criterion, "bid_modifier")
                    and row.campaign_criterion.bid_modifier
                    else None
                ),
            }
            for row in response
        ]

    @_wrap_mutate_error("広告スケジュール更新")
    async def update_schedule_targeting(
        self, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """広告スケジュール更新"""
        cc_service = self._get_service("CampaignCriterionService")
        operations = []

        # 追加
        for schedule in params.get("add_schedules", []):
            op = self._client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = self._client.get_service(
                "CampaignService"
            ).campaign_path(self._customer_id, params["campaign_id"])
            day_enum = self._client.enums.DayOfWeekEnum
            criterion.ad_schedule.day_of_week = getattr(
                day_enum, schedule["day"].upper()
            )
            criterion.ad_schedule.start_hour = schedule.get("start_hour", 0)
            criterion.ad_schedule.end_hour = schedule.get("end_hour", 24)
            minute_enum = self._client.enums.MinuteOfHourEnum
            criterion.ad_schedule.start_minute = minute_enum.ZERO
            criterion.ad_schedule.end_minute = minute_enum.ZERO
            operations.append(op)

        # 削除
        for cid in params.get("remove_criterion_ids", []):
            op = self._client.get_type("CampaignCriterionOperation")
            op.remove = self._client.get_service(
                "CampaignCriterionService"
            ).campaign_criterion_path(self._customer_id, params["campaign_id"], cid)
            operations.append(op)

        response = cc_service.mutate_campaign_criteria(
            customer_id=self._customer_id,
            operations=operations,
        )
        return [{"resource_name": r.resource_name} for r in response.results]
