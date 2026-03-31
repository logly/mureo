"""Targeting, recommendations, and change history mixin.

Provides device targeting, bid adjustments, geographic targeting,
schedule targeting, recommendations, and change history.
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

# Google Ads DeviceEnum integer -> device name mapping
# API v23 campaign_criterion.device.type_ returns int
_DEVICE_ENUM_MAP: dict[int, str] = {
    2: "MOBILE",
    3: "TABLET",
    4: "DESKTOP",
}


def _normalize_device_type(raw: Any) -> str:
    """Normalize device.type_ values to device name strings.

    The API returns integers (2,3,4), but mock tests may return strings
    ("DESKTOP", etc.) or "DeviceType.DESKTOP" format. Handle all patterns.
    """
    # Integer case
    if isinstance(raw, int):
        return _DEVICE_ENUM_MAP.get(raw, f"UNKNOWN({raw})")
    s = str(raw)
    # "DeviceType.DESKTOP" 形式
    if "." in s:
        return s.split(".")[-1]
    # Integer string "2", "3", "4"
    try:
        return _DEVICE_ENUM_MAP.get(int(s), s)
    except ValueError:
        pass
    # Already a string like "DESKTOP"
    return s


class _TargetingMixin:
    """Mixin providing targeting, recommendations, and change history."""

    # Type declarations for attributes provided by parent class (GoogleAdsApiClient)
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
        value: str,
        pattern: re.Pattern[str],
        field_name: str,
    ) -> str: ...

    def _get_service(self, service_name: str) -> Any: ...

    # === Recommendations ===

    async def list_recommendations(
        self,
        campaign_id: str | None = None,
        recommendation_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List Google recommendations."""

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
        response = await self._search(query)  # type: ignore[attr-defined]
        return [map_recommendation(row.recommendation) for row in response]

    @_wrap_mutate_error("recommendation application")
    async def apply_recommendation(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply recommendation."""
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

    # === Device Targeting ===

    async def get_device_targeting(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get campaign device targeting settings.

        Retrieves all DEVICE type criteria and determines delivery state from bid_modifier.
        bid_modifier=0.0 means delivery stopped (-100%), otherwise delivery active.
        Devices without criteria are returned as default active.
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
        response = await self._search(query)  # type: ignore[attr-defined]
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
        # Always return all 3 devices (no explicit setting = default active)
        all_devices = ["DESKTOP", "MOBILE", "TABLET"]
        return [
            found.get(
                d,
                {
                    "criterion_id": None,
                    "device_type": d,
                    "bid_modifier": None,
                    "enabled": True,
                },
            )
            for d in all_devices
        ]

    @_wrap_mutate_error("device targeting update")
    async def set_device_targeting(self, params: dict[str, Any]) -> dict[str, Any]:
        """Set device targeting (deliver only to specified devices).

        Always explicitly set bid_modifier for all device criteria.
        Execute mutate individually per device so one failure does not affect others.
        """
        campaign_id = params["campaign_id"]
        self._validate_id(campaign_id, "campaign_id")

        enabled_devices = {d.upper() for d in params["enabled_devices"]}
        valid_devices = {"MOBILE", "DESKTOP", "TABLET"}
        invalid = enabled_devices - valid_devices
        if invalid:
            raise ValueError(
                f"Invalid device type: {invalid}. Valid values: {valid_devices}"
            )
        if not enabled_devices:
            raise ValueError("At least one device must be enabled")

        # Get all device criterion IDs (regardless of bid_modifier setting)

        query = f"""
            SELECT
                campaign_criterion.criterion_id,
                campaign_criterion.device.type,
                campaign_criterion.bid_modifier
            FROM campaign_criterion
            WHERE campaign.id = {campaign_id}
                AND campaign_criterion.type = 'DEVICE'
        """
        response = await self._search(query)  # type: ignore[attr-defined]
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
            "Device targeting settings: campaign=%s, existing criteria=%s, enabling=%s",
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
                    self._customer_id,
                    campaign_id,
                    criterion_id,
                )
                criterion.bid_modifier = new_modifier
                self._client.copy_from(
                    op.update_mask,
                    PbFieldMask(paths=["bid_modifier"]),
                )
                op_type = "UPDATE"
            else:
                criterion = op.create
                criterion.campaign = self._client.get_service(
                    "CampaignService",
                ).campaign_path(self._customer_id, campaign_id)
                criterion.device.type_ = getattr(
                    self._client.enums.DeviceEnum,
                    device_type,
                )
                criterion.bid_modifier = new_modifier
                op_type = "CREATE"

            try:
                resp = cc_service.mutate_campaign_criteria(
                    customer_id=self._customer_id,
                    operations=[op],
                )
                updated.extend(r.resource_name for r in resp.results)
                logger.info(
                    "Device %s: %s success (bid_modifier=%.1f)",
                    device_type,
                    op_type,
                    new_modifier,
                )
            except Exception as exc:
                detail = (
                    self._extract_error_detail(exc)  # type: ignore[attr-defined]
                    if hasattr(exc, "failure")
                    else str(exc)
                )
                logger.error(
                    "Device %s: %s failed (bid_modifier=%.1f): %s",
                    device_type,
                    op_type,
                    new_modifier,
                    detail,
                )
                errors.append(f"{device_type}({op_type}): {detail}")

        if not updated and errors:
            raise ValueError(f"Failed to set all devices: {'; '.join(errors)}")

        return {
            "message": "Device targeting updated",
            "enabled_devices": sorted(enabled_devices),
            "disabled_devices": sorted(valid_devices - enabled_devices),
            "updated": updated,
            "errors": errors if errors else None,
        }

    # === Bid Adjustments ===

    async def get_bid_adjustments(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get campaign bid adjustments."""
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
        response = await self._search(query)  # type: ignore[attr-defined]
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

    @_wrap_mutate_error("bid adjustment update")
    async def update_bid_adjustment(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update bid adjustment.

        Note: BudgetGuard validation (validate_bid_adjustment) is performed on the Managed side.
        """
        self._validate_id(params["campaign_id"], "campaign_id")
        self._validate_id(params["criterion_id"], "criterion_id")
        bid_modifier = float(params["bid_modifier"])
        if not (0.1 <= bid_modifier <= 10.0):
            raise ValueError(
                f"bid_modifier must be between 0.1 and 10.0: {bid_modifier}"
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

    # === Change History ===

    async def list_change_history(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """List change history.

        API requires date range filter, so defaults to last 14 days when unspecified.
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
        # API rejects CHANGE_DATE_RANGE_INFINITE, so set default date range
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
        response = await self._search(query)  # type: ignore[attr-defined]
        return [map_change_event(row.change_event) for row in response]

    # === Geographic Targeting ===

    async def list_location_targeting(self, campaign_id: str) -> list[dict[str, Any]]:
        """List campaign location targeting."""
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
        response = await self._search(query)  # type: ignore[attr-defined]
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

    @_wrap_mutate_error("location targeting update")
    async def update_location_targeting(
        self, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Update location targeting (add/remove).

        Note: BudgetGuard targeting expansion guard (validate_targeting_expansion) is performed on the Managed side.
        """
        cc_service = self._get_service("CampaignCriterionService")
        operations = []

        # Add
        for loc_id in params.get("add_locations", []):
            op = self._client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = self._client.get_service(
                "CampaignService"
            ).campaign_path(self._customer_id, params["campaign_id"])
            # Accept both "geoTargetConstants/2392" and "2392" formats
            loc_str = str(loc_id)
            if not loc_str.startswith("geoTargetConstants/"):
                loc_str = f"geoTargetConstants/{loc_str}"
            criterion.location.geo_target_constant = loc_str
            operations.append(op)

        # Remove
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

    # === Ad Schedule ===

    async def list_schedule_targeting(self, campaign_id: str) -> list[dict[str, Any]]:
        """List campaign ad schedule."""
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
        response = await self._search(query)  # type: ignore[attr-defined]
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

    @_wrap_mutate_error("ad schedule update")
    async def update_schedule_targeting(
        self, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Update ad schedule."""
        cc_service = self._get_service("CampaignCriterionService")
        operations = []

        # Add
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

        # Remove
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
