"""Enum-name resolution: the one resolver and the SDK-derived maps it reads.

mureo builds its Google Ads client with the SDK default
``use_proto_plus=False`` (``GoogleAdsClient(...)`` in
:mod:`mureo.google_ads.client` passes no such argument), so the SDK's response
interceptor converts every row to raw protobuf before a mapper sees it and an
enum field arrives as a plain ``int`` with no ``.name``. A bare ``str()`` on
that field yields "2", which no consumer keys on; ``map_enum_name`` recovers
the API spelling from these maps (#588).

Every map is derived from the vendored SDK enum rather than transcribed by
hand, so it cannot go stale against the API version. The maps that predate
#588 still live beside their mappers in :mod:`mureo.google_ads.mappers`, which
is at its 800-line budget; new ones belong here.
"""

from __future__ import annotations

from typing import Any

from google.ads.googleads.v23.enums.types.ad_network_type import AdNetworkTypeEnum
from google.ads.googleads.v23.enums.types.asset_field_type import AssetFieldTypeEnum
from google.ads.googleads.v23.enums.types.asset_link_status import AssetLinkStatusEnum
from google.ads.googleads.v23.enums.types.asset_performance_label import (
    AssetPerformanceLabelEnum,
)
from google.ads.googleads.v23.enums.types.change_client_type import ChangeClientTypeEnum
from google.ads.googleads.v23.enums.types.change_event_resource_type import (
    ChangeEventResourceTypeEnum,
)
from google.ads.googleads.v23.enums.types.conversion_action_category import (
    ConversionActionCategoryEnum,
)
from google.ads.googleads.v23.enums.types.conversion_action_type import (
    ConversionActionTypeEnum,
)
from google.ads.googleads.v23.enums.types.criterion_system_serving_status import (
    CriterionSystemServingStatusEnum,
)
from google.ads.googleads.v23.enums.types.day_of_week import DayOfWeekEnum
from google.ads.googleads.v23.enums.types.device import DeviceEnum
from google.ads.googleads.v23.enums.types.keyword_match_type import (
    KeywordMatchTypeEnum,
)
from google.ads.googleads.v23.enums.types.keyword_plan_competition_level import (
    KeywordPlanCompetitionLevelEnum,
)
from google.ads.googleads.v23.enums.types.minute_of_hour import MinuteOfHourEnum
from google.ads.googleads.v23.enums.types.placement_type import PlacementTypeEnum
from google.ads.googleads.v23.enums.types.recommendation_type import (
    RecommendationTypeEnum,
)
from google.ads.googleads.v23.enums.types.resource_change_operation import (
    ResourceChangeOperationEnum,
)
from google.ads.googleads.v23.enums.types.tracking_code_type import (
    TrackingCodeTypeEnum,
)


def map_enum_name(value: Any, mapping: dict[int, str]) -> str:
    """Convert a proto enum value to its bare name, whatever its shape.

    Handles every representation the google-ads client can produce:
    raw protobuf ints (use_proto_plus=False — the production path),
    proto-plus members stringifying as 'EnumClass.NAME' (Python <= 3.10),
    and members stringifying as the bare number (IntEnum on Python 3.11+).

    The name is never read off the value: a proto-plus member *is* an ``int``,
    so the mapping resolves it too, and ``getattr(value, "name", None)`` would
    answer with a truthy stand-in for any ``MagicMock`` a test hands in (#588).
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return mapping.get(value, str(value))
    s = str(value)
    if s.isdigit():
        return mapping.get(int(s), s)
    return s.rsplit(".", 1)[-1]


KEYWORD_MATCH_TYPE_MAP: dict[int, str] = {
    member.value: member.name for member in KeywordMatchTypeEnum.KeywordMatchType  # type: ignore[attr-defined]
}

CONVERSION_ACTION_TYPE_MAP: dict[int, str] = {
    member.value: member.name
    for member in ConversionActionTypeEnum.ConversionActionType  # type: ignore[attr-defined]
}

CONVERSION_ACTION_CATEGORY_MAP: dict[int, str] = {
    member.value: member.name
    for member in ConversionActionCategoryEnum.ConversionActionCategory  # type: ignore[attr-defined]
}

TRACKING_CODE_TYPE_MAP: dict[int, str] = {
    member.value: member.name for member in TrackingCodeTypeEnum.TrackingCodeType  # type: ignore[attr-defined]
}

RECOMMENDATION_TYPE_MAP: dict[int, str] = {
    member.value: member.name for member in RecommendationTypeEnum.RecommendationType  # type: ignore[attr-defined]
}

CHANGE_EVENT_RESOURCE_TYPE_MAP: dict[int, str] = {
    member.value: member.name
    for member in ChangeEventResourceTypeEnum.ChangeEventResourceType  # type: ignore[attr-defined]
}

RESOURCE_CHANGE_OPERATION_MAP: dict[int, str] = {
    member.value: member.name
    for member in ResourceChangeOperationEnum.ResourceChangeOperation  # type: ignore[attr-defined]
}

CHANGE_CLIENT_TYPE_MAP: dict[int, str] = {
    member.value: member.name for member in ChangeClientTypeEnum.ChangeClientType  # type: ignore[attr-defined]
}

CRITERION_SYSTEM_SERVING_STATUS_MAP: dict[int, str] = {
    member.value: member.name
    for member in CriterionSystemServingStatusEnum.CriterionSystemServingStatus  # type: ignore[attr-defined]
}

PLACEMENT_TYPE_MAP: dict[int, str] = {
    member.value: member.name for member in PlacementTypeEnum.PlacementType  # type: ignore[attr-defined]
}

ASSET_FIELD_TYPE_MAP: dict[int, str] = {
    member.value: member.name for member in AssetFieldTypeEnum.AssetFieldType  # type: ignore[attr-defined]
}

#: The status of an asset LINK (``asset_group_asset.status`` and the other
#: ``*_asset.status`` fields) — not the status of the asset itself (#590).
ASSET_LINK_STATUS_MAP: dict[int, str] = {
    member.value: member.name for member in AssetLinkStatusEnum.AssetLinkStatus  # type: ignore[attr-defined]
}

ASSET_PERFORMANCE_LABEL_MAP: dict[int, str] = {
    member.value: member.name
    for member in AssetPerformanceLabelEnum.AssetPerformanceLabel  # type: ignore[attr-defined]
}

DEVICE_MAP: dict[int, str] = {
    member.value: member.name for member in DeviceEnum.Device  # type: ignore[attr-defined]
}

KEYWORD_PLAN_COMPETITION_LEVEL_MAP: dict[int, str] = {
    member.value: member.name
    for member in KeywordPlanCompetitionLevelEnum.KeywordPlanCompetitionLevel  # type: ignore[attr-defined]
}

DAY_OF_WEEK_MAP: dict[int, str] = {
    member.value: member.name for member in DayOfWeekEnum.DayOfWeek  # type: ignore[attr-defined]
}

MINUTE_OF_HOUR_MAP: dict[int, str] = {
    member.value: member.name for member in MinuteOfHourEnum.MinuteOfHour  # type: ignore[attr-defined]
}

AD_NETWORK_TYPE_MAP: dict[int, str] = {
    member.value: member.name for member in AdNetworkTypeEnum.AdNetworkType  # type: ignore[attr-defined]
}
