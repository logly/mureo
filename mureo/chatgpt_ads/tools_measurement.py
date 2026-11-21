"""The ChatGPT Ads conversion measurement tools (#995).

Pure data, built by :func:`mureo.chatgpt_ads.tools.build_tool`. Pixels and
conversion event settings are created and listed; neither can be edited or
deleted through the API, so their create tools lead with that. The
conversion report is a POST that only reads, which is why it is marked
``readOnlyHint`` and sent through ``client.post_read``. Its period, level,
time granularity and click window take the argument names and the period
resolver of ``chatgpt_ads_insights_report``, so one concept has one name
across both reports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.chatgpt_ads.tools import (
    ATTRIBUTION_WINDOWS,
    ENTITY_LIMIT,
    ID_PATTERN,
    NAME_MAX_CHARS,
    NAME_MIN_CHARS,
    NAME_PATTERN,
    PERIOD_DESCRIPTION,
    TIME_GRANULARITY,
    build_tool,
    id_param,
)
from mureo.chatgpt_ads.tools_mutations import MUTATES, NAME

if TYPE_CHECKING:
    from mcp.types import Tool

#: The only ``client_type`` the reference documents for a pixel.
PIXEL_CLIENT_TYPE = "web"
#: ``event_type`` values the reference documents; the OpenAPI document
#: states no enum, so the handler holds the value to the id pattern only.
EVENT_TYPES = (
    "app_installed",
    "app_opened",
    "appointment_scheduled",
    "checkout_started",
    "contents_viewed",
    "custom",
    "items_added",
    "lead_created",
    "order_created",
    "page_viewed",
    "registration_completed",
    "subscription_created",
    "trial_started",
)
CUSTOM_EVENT_TYPE = "custom"
#: An event setting name: the OpenAPI document states a minimum of 1 and no
#: maximum; this bounds one request body at the other names' limit.
EVENT_SETTING_NAME_MIN_CHARS = 1
EVENT_SETTING_NAME_MAX_CHARS = NAME_MAX_CHARS
#: A custom event name: 1-64 letters, digits, '_' or '-', starting and
#: ending with a letter or digit, as the reference states.
CUSTOM_EVENT_NAME_MAX_CHARS = 64
CUSTOM_EVENT_NAME_PATTERN = (
    f"^[A-Za-z0-9](?:[A-Za-z0-9_-]{{0,{CUSTOM_EVENT_NAME_MAX_CHARS - 2}}}"
    "[A-Za-z0-9])?$"
)
#: The click window every event setting is created with: the only value the
#: reference documents ("Use 30"), and a setting cannot be edited later.
EVENT_ATTRIBUTION_WINDOW_DAYS = 30
#: ``aggregation_level`` values of the conversion report.
CONVERSION_LEVELS = ("campaign", "ad_group", "ad")
#: Entities one conversion report names: the reference states none; this
#: bounds one request body.
MAX_REPORT_ENTITIES = 100
BREAKDOWNS = ("country", "device")
ATTRIBUTION_TIME_BASES = ("ad_event_time", "conversion_time")
VIEW_THROUGH_WINDOWS = (0, 1)
#: ``event_names`` bounds, from the reference: 1-500 names of up to 256
#: characters each.
MAX_EVENT_NAMES = 500
EVENT_NAME_MAX_CHARS = 256
ATTRIBUTED_EVENTS = "attributed_events"
#: Summary rows (and event rows) one report answers before the platform
#: refuses it with 413; there is no pagination.
MAX_REPORT_ROWS = 2000

#: Only the pixel paths: the reference ties its ``404 Not found`` answer for
#: an account without conversions to them, not to the event settings.
_GATE_NOTE = (
    "Answers feature_not_enabled when conversions are not enabled for the account."
)

_PIXELS_LIST = build_tool(
    "chatgpt_ads_pixels_list",
    "Lists the conversion pixels (web sources) of the ChatGPT Ads account. "
    "Returns a JSON array of pixel objects as the platform returns them: id "
    "(the source id an event setting takes), name, client_type and pixel_id "
    f"(what the JavaScript Pixel is initialised with). Read-only. {_GATE_NOTE}",
    {"limit": ENTITY_LIMIT},
    [],
)

_PIXELS_CREATE = build_tool(
    "chatgpt_ads_pixels_create",
    "Creates one web conversion pixel; it cannot be edited or deleted through "
    "the API. Returns the new platform object unchanged: id (pass it as "
    "source_id to chatgpt_ads_conversion_events_create) and pixel_id (to "
    "initialise the JavaScript Pixel). Mutates the account. client_type is "
    f"always '{PIXEL_CLIENT_TYPE}', the only documented value. No idempotency "
    "key is offered: if the answer is lost, check chatgpt_ads_pixels_list "
    f"before creating another. No reversal is recorded. {_GATE_NOTE}",
    {
        "name": {
            **NAME,
            "description": (
                f"Pixel name: {NAME_MIN_CHARS} to {NAME_MAX_CHARS} characters on "
                "one line, not all spaces."
            ),
        }
    },
    ["name"],
    annotations=MUTATES,
)

_EVENTS_LIST = build_tool(
    "chatgpt_ads_conversion_events_list",
    "Lists the conversion event settings of the ChatGPT Ads account. Returns "
    "a JSON array of event setting objects as the platform returns them (id, "
    "name, event_type, custom_event_name, attribution_window_days, "
    "source_ids, archived). Read-only. An id here is what "
    "conversion_event_setting_ids of chatgpt_ads_campaigns_create takes.",
    {"limit": ENTITY_LIMIT},
    [],
)

_EVENTS_CREATE = build_tool(
    "chatgpt_ads_conversion_events_create",
    "Creates one conversion event setting, permanently: the API offers no "
    "edit or delete, so check every argument first. Returns the new platform "
    "object unchanged. Mutates the account. Documented event_type values: "
    f"{', '.join(EVENT_TYPES)}; custom needs custom_event_name. source_id is "
    "a pixel's id from chatgpt_ads_pixels_list (not its pixel_id); an answer "
    "'Client data source not found' means it is not a pixel of this account. "
    "attribution_window_days is always "
    f"{EVENT_ATTRIBUTION_WINDOW_DAYS}, the only documented value. No "
    "idempotency key is offered: if the answer is lost, check "
    "chatgpt_ads_conversion_events_list before creating another. No reversal "
    "is recorded.",
    {
        "name": {
            "type": "string",
            "minLength": EVENT_SETTING_NAME_MIN_CHARS,
            "maxLength": EVENT_SETTING_NAME_MAX_CHARS,
            "pattern": NAME_PATTERN,
            "description": (
                f"Event setting name: {EVENT_SETTING_NAME_MIN_CHARS} to "
                f"{EVENT_SETTING_NAME_MAX_CHARS} characters on one line, not "
                "all spaces."
            ),
        },
        "event_type": {
            "type": "string",
            "pattern": ID_PATTERN,
            "description": (
                "The standard event to count (e.g. 'order_created'), or "
                "'custom' for an event of your own named by custom_event_name."
            ),
        },
        "source_id": id_param("Pixel (conversion source)", "clidsrc_123"),
        "custom_event_name": {
            "type": "string",
            "minLength": 1,
            "maxLength": CUSTOM_EVENT_NAME_MAX_CHARS,
            "pattern": CUSTOM_EVENT_NAME_PATTERN,
            "description": (
                "Required when event_type is 'custom', refused otherwise: 1-"
                f"{CUSTOM_EVENT_NAME_MAX_CHARS} letters, digits, '_' or '-', "
                "starting and ending with a letter or digit, not a standard "
                "event name. The platform lowercases it."
            ),
        },
    },
    ["name", "event_type", "source_id"],
    annotations=MUTATES,
)


def _enum(
    values: tuple[Any, ...], description: str, kind: str = "string"
) -> dict[str, Any]:
    return {"type": kind, "enum": list(values), "description": description}


_REPORT_PROPERTIES: dict[str, Any] = {
    "period": {
        "type": "string",
        "description": f"{PERIOD_DESCRIPTION} Default 'last_30d'.",
    },
    "level": _enum(
        CONVERSION_LEVELS,
        "Row entity and the level of entity_ids: campaign (default), ad_group "
        "or ad.",
    ),
    "entity_ids": {
        "type": "array",
        "minItems": 1,
        "maxItems": MAX_REPORT_ENTITIES,
        "items": {"type": "string", "pattern": ID_PATTERN},
        "description": (
            f"Ids at the chosen level, 1 to {MAX_REPORT_ENTITIES}. Required "
            "unless group_by_entity is false; omit it then to report across the "
            "account."
        ),
    },
    "group_by_entity": {
        "type": "boolean",
        "description": (
            "Default true: one row per entity. false combines the entities "
            "into rows keyed by the ad account id."
        ),
    },
    "time_granularity": TIME_GRANULARITY,
    "breakdown": _enum(BREAKDOWNS, "Split rows by country or device. Omit for none."),
    "attribution_time_basis": _enum(
        ATTRIBUTION_TIME_BASES,
        "ad_event_time (platform default) dates a conversion by its ad "
        "interaction; conversion_time by the conversion, with limited "
        "non-goal event coverage.",
    ),
    "attribution_window_days": _enum(
        ATTRIBUTION_WINDOWS,
        "Click attribution window. Omit for the platform default (30).",
        "integer",
    ),
    "view_through_attribution_window_days": _enum(
        VIEW_THROUGH_WINDOWS,
        "View-through window: 0 excludes views, 1 is one day (platform default).",
        "integer",
    ),
    "include_events": {
        "type": "boolean",
        "description": (
            "Also return attributed_events, per-event details for each row "
            "(standard and custom, goal and non-goal). Default false."
        ),
    },
    "event_names": {
        "type": "array",
        "minItems": 1,
        "maxItems": MAX_EVENT_NAMES,
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": EVENT_NAME_MAX_CHARS,
            "pattern": r"\S",
        },
        "description": (
            "Only with include_events: the events whose details to return, "
            f"1 to {MAX_EVENT_NAMES} names of up to {EVENT_NAME_MAX_CHARS} "
            "characters, matched exactly. Goal counts and sales are unchanged."
        ),
    },
    "include_zero_rows": {
        "type": "boolean",
        "description": (
            "Platform default true. With include_events and false, only rows "
            "with a nonzero goal count, sales or selected event count remain."
        ),
    },
}

_CONVERSIONS_REPORT = build_tool(
    "chatgpt_ads_conversions_report",
    "Reports ChatGPT Ads goal conversions: per row, conversions (click plus "
    "view-through within the chosen windows), click_through_conversions, "
    "view_through_conversions and order_created_attributed_sales; optionally "
    "per-event details. Returns the platform object unchanged (data, count, "
    "account_currency). Read-only: a POST that changes nothing. No "
    f"pagination: more than {MAX_REPORT_ROWS:,} rows is refused by the "
    "platform, so narrow entity_ids or the period. Conversions are attributed "
    "late, so recent days can still grow; allow at least one day. For "
    "conversions next to spend and delivery use chatgpt_ads_insights_report, "
    "whose conversions metric also counts click plus view-through; compare "
    "the two only over the same entities, dates, windows and time basis.",
    _REPORT_PROPERTIES,
    [],
)

MEASUREMENT_TOOLS: tuple[Tool, ...] = (
    _PIXELS_LIST,
    _PIXELS_CREATE,
    _EVENTS_LIST,
    _EVENTS_CREATE,
    _CONVERSIONS_REPORT,
)

__all__ = [
    "ATTRIBUTED_EVENTS",
    "ATTRIBUTION_TIME_BASES",
    "BREAKDOWNS",
    "CONVERSION_LEVELS",
    "CUSTOM_EVENT_NAME_MAX_CHARS",
    "CUSTOM_EVENT_NAME_PATTERN",
    "CUSTOM_EVENT_TYPE",
    "EVENT_ATTRIBUTION_WINDOW_DAYS",
    "EVENT_NAME_MAX_CHARS",
    "EVENT_SETTING_NAME_MAX_CHARS",
    "EVENT_SETTING_NAME_MIN_CHARS",
    "EVENT_TYPES",
    "MAX_EVENT_NAMES",
    "MAX_REPORT_ENTITIES",
    "MAX_REPORT_ROWS",
    "MEASUREMENT_TOOLS",
    "PIXEL_CLIENT_TYPE",
    "VIEW_THROUGH_WINDOWS",
]
