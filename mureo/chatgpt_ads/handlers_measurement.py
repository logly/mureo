"""One coroutine per ChatGPT Ads conversion measurement tool (#995).

Merged into :data:`mureo.chatgpt_ads.handlers.HANDLERS`. The reference says
the pixel collection answers ``404 Not found`` when conversions are not
enabled for the account, a body that names no feature, so :func:`_gated`
re-raises a 404 on the pixel list and create as the feature gate the provider
reports as ``feature_not_enabled``. The event settings are left out of it:
the reference ties no such answer to them, and documents ``Client data source
not found`` for a ``source_ids`` entry that is not in the account, so a 404
there is an ordinary error. So is a 404 from the conversion report.

An event setting is always created with
:data:`~mureo.chatgpt_ads.tools_measurement.EVENT_ATTRIBUTION_WINDOW_DAYS`,
the only window the reference documents; a setting cannot be edited later.

The report sends only the keys the caller gave, plus the two the API
requires (``aggregation_level`` and ``time_ranges``), so every platform
default applies unless it was asked to change.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, TypeVar

from mureo.chatgpt_ads._api import PAGE_MAX_ENTITIES
from mureo.chatgpt_ads._errors import ChatGPTAdsAPIError
from mureo.chatgpt_ads._period import resolve_period, today_in, unix_bounds
from mureo.chatgpt_ads._validation import (
    attribution_window_value,
    flag,
    granularity_value,
    id_value,
    limit_value,
    line_text,
    path_id,
    period_value,
)
from mureo.chatgpt_ads.handlers_mutations import required_name
from mureo.chatgpt_ads.tools import DEFAULT_LIST_LIMIT
from mureo.chatgpt_ads.tools_measurement import (
    ATTRIBUTED_EVENTS,
    ATTRIBUTION_TIME_BASES,
    BREAKDOWNS,
    CONVERSION_LEVELS,
    CUSTOM_EVENT_NAME_MAX_CHARS,
    CUSTOM_EVENT_NAME_PATTERN,
    CUSTOM_EVENT_TYPE,
    EVENT_ATTRIBUTION_WINDOW_DAYS,
    EVENT_NAME_MAX_CHARS,
    EVENT_SETTING_NAME_MAX_CHARS,
    EVENT_SETTING_NAME_MIN_CHARS,
    MAX_EVENT_NAMES,
    MAX_REPORT_ENTITIES,
    PIXEL_CLIENT_TYPE,
    VIEW_THROUGH_WINDOWS,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from datetime import tzinfo

    from mureo.chatgpt_ads.client import ChatGPTAdsClient
    from mureo.chatgpt_ads.handlers_mutations import Handler

_T = TypeVar("_T")

_PIXELS_PATH = "/conversions/pixels"
_EVENT_SETTINGS_PATH = "/conversions/event_settings"
_CUSTOM_EVENT_NAME_RE = re.compile(CUSTOM_EVENT_NAME_PATTERN)
_NOT_FOUND = 404


async def _gated(call: Awaitable[_T]) -> _T:
    """``call`` on a pixel path, with a 404 read as conversions not enabled
    for the account."""
    try:
        return await call
    except ChatGPTAdsAPIError as exc:
        if exc.status != _NOT_FOUND or exc.is_feature_gate:
            raise
        gate = ChatGPTAdsAPIError(
            str(exc), status=exc.status, code=exc.code, is_feature_gate=True
        )
    raise gate


async def _pixels_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    limit = limit_value(arguments, DEFAULT_LIST_LIMIT)
    return await _gated(
        client.list_all(_PIXELS_PATH, [], limit=limit, page_max=PAGE_MAX_ENTITIES)
    )


async def _pixels_create(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    body = {"name": required_name(arguments), "client_type": PIXEL_CLIENT_TYPE}
    return await _gated(client.post(_PIXELS_PATH, body))


async def _events_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    limit = limit_value(arguments, DEFAULT_LIST_LIMIT)
    return await client.list_all(
        _EVENT_SETTINGS_PATH, [], limit=limit, page_max=PAGE_MAX_ENTITIES
    )


def _custom_event_name(arguments: dict[str, Any], event_type: str) -> dict[str, str]:
    """``custom_event_name``: required for a custom event, refused otherwise."""
    value = arguments.get("custom_event_name")
    if event_type != CUSTOM_EVENT_TYPE:
        if value is not None:
            raise ValueError(
                f"custom_event_name is only for event_type {CUSTOM_EVENT_TYPE!r}"
            )
        return {}
    if not isinstance(value, str) or not _CUSTOM_EVENT_NAME_RE.fullmatch(value):
        raise ValueError(
            f"custom_event_name is required for event_type {CUSTOM_EVENT_TYPE!r}: "
            f"1-{CUSTOM_EVENT_NAME_MAX_CHARS} letters, digits, '_' or '-', "
            "starting and ending with a letter or digit"
        )
    return {"custom_event_name": value}


async def _events_create(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    name = line_text(
        arguments.get("name"),
        "name",
        EVENT_SETTING_NAME_MIN_CHARS,
        EVENT_SETTING_NAME_MAX_CHARS,
    )
    event_type = id_value(arguments.get("event_type"), "event_type")
    custom = _custom_event_name(arguments, event_type)
    source_id = path_id(arguments, "source_id")
    body = {
        "name": name,
        "event_type": event_type,
        **custom,
        "attribution_window_days": EVENT_ATTRIBUTION_WINDOW_DAYS,
        "source_ids": [source_id],
    }
    return await client.post(_EVENT_SETTINGS_PATH, body)


def _choice(arguments: dict[str, Any], key: str, allowed: tuple[Any, ...]) -> Any:
    """A given enum argument; the caller sends it only when present."""
    value = arguments[key]
    # ``type() is``: a bool compares equal to 0 and 1 but is not the
    # integer the API documents.
    if value not in allowed or type(value) is not type(allowed[0]):
        raise ValueError(f"{key} must be one of {', '.join(map(str, allowed))}")
    return value


def _entity_ids(arguments: dict[str, Any]) -> dict[str, Any]:
    """``entity_ids`` (and ``group_by_entity`` when given), checked together."""
    body: dict[str, Any] = {}
    grouped = True  # the platform default
    if "group_by_entity" in arguments:
        grouped = body["group_by_entity"] = flag(arguments, "group_by_entity")
    ids = arguments.get("entity_ids")
    if ids is None:
        if grouped:
            raise ValueError(
                "entity_ids is required while group_by_entity is true (the "
                "default); set group_by_entity to false to report across the "
                "account"
            )
        return body
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_REPORT_ENTITIES:
        raise ValueError(
            f"entity_ids must be an array of 1 to {MAX_REPORT_ENTITIES} ids"
        )
    return {**body, "entity_ids": [id_value(item, "entity_ids[]") for item in ids]}


def _event_names(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_EVENT_NAMES:
        raise ValueError(
            f"event_names must be an array of 1 to {MAX_EVENT_NAMES} names"
        )
    for name in value:
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= EVENT_NAME_MAX_CHARS
            or not name.strip()
        ):
            raise ValueError(
                f"event_names holds names of 1 to {EVENT_NAME_MAX_CHARS} "
                "characters, not all spaces"
            )
    return value


def _events_selection(arguments: dict[str, Any]) -> dict[str, Any]:
    """``include`` and ``event_names``; names need the event details."""
    wanted = flag(arguments, "include_events")
    body: dict[str, Any] = {"include": [ATTRIBUTED_EVENTS]} if wanted else {}
    if "event_names" in arguments:
        if not wanted:
            raise ValueError("event_names needs include_events set to true")
        body["event_names"] = _event_names(arguments["event_names"])
    return body


def _report_options(arguments: dict[str, Any]) -> dict[str, Any]:
    """The optional report keys the caller gave, checked."""
    body: dict[str, Any] = {}
    if "time_granularity" in arguments:
        body["time_granularity"] = granularity_value(arguments)
    for key, allowed in (
        ("breakdown", BREAKDOWNS),
        ("attribution_time_basis", ATTRIBUTION_TIME_BASES),
        ("view_through_attribution_window_days", VIEW_THROUGH_WINDOWS),
    ):
        if key in arguments:
            body[key] = _choice(arguments, key, allowed)
    window = attribution_window_value(arguments)
    if window is not None:
        body["attribution_window_days"] = window
    if "include_zero_rows" in arguments:
        body["include_zero_rows"] = flag(arguments, "include_zero_rows")
    return body


def _time_range(period: str, zone: tzinfo) -> str:
    """One ``time_ranges`` entry: whole days in ``zone``, the end exclusive.

    The JSON-encoded string the reference's example shows, start and end as
    decimal strings of Unix seconds.
    """
    start, last = unix_bounds(*resolve_period(period, today_in(zone)), zone)
    window = {"type": "unix_range", "start": str(start), "end": str(last + 1)}
    return json.dumps(window, separators=(",", ":"))


async def _conversions_report(
    client: ChatGPTAdsClient, arguments: dict[str, Any]
) -> Any:
    period = period_value(arguments, "last_30d")
    level = arguments.get("level", CONVERSION_LEVELS[0])
    if level not in CONVERSION_LEVELS:
        raise ValueError(f"level must be one of {', '.join(CONVERSION_LEVELS)}")
    body = {
        "aggregation_level": level,
        **_entity_ids(arguments),
        **_report_options(arguments),
        **_events_selection(arguments),
    }
    zone = await client.account_timezone()
    body["time_ranges"] = [_time_range(period, zone)]
    return await client.post_read("/conversions/insights", body)


MEASUREMENT_HANDLERS: dict[str, Handler] = {
    "chatgpt_ads_pixels_list": _pixels_list,
    "chatgpt_ads_pixels_create": _pixels_create,
    "chatgpt_ads_conversion_events_list": _events_list,
    "chatgpt_ads_conversion_events_create": _events_create,
    "chatgpt_ads_conversions_report": _conversions_report,
}

__all__ = ["MEASUREMENT_HANDLERS"]
