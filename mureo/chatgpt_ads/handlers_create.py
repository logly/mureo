"""One coroutine per ChatGPT Ads create and archive tool (#995).

Merged into :data:`mureo.chatgpt_ads.handlers.HANDLERS`, so every handler here
runs through :func:`~mureo.chatgpt_ads.handlers.run_tool`. Each one checks its
arguments before the first request with the same checks the update tools use
(:mod:`mureo.chatgpt_ads.handlers_mutations`) and sends the API objects as
given. ``status`` is always ``paused`` and never taken from the caller: a
create that could start serving would spend before any operator-approved
enable.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

from mureo.chatgpt_ads._validation import (
    http_url,
    id_value,
    line_text,
    number,
    path_id,
)
from mureo.chatgpt_ads.handlers_mutations import (
    Handler,
    bidding_config_value,
    budget_value,
    required_name,
    schedule_value,
    status_handler,
)
from mureo.chatgpt_ads.tools_create import (
    BIDDING_TYPES,
    CHAT_CARD,
    COUNTRY_PATTERN,
    CREATIVE,
    CREATIVE_BODY_MAX_CHARS,
    CREATIVE_TITLE_MAX_CHARS,
    CREATIVE_TITLE_MIN_CHARS,
    IDEMPOTENCY_KEY_MAX_CHARS,
    IDEMPOTENCY_KEY_PATTERN,
    IMAGE_CROP_KEYS,
    LOCATION_KEYS,
    MAX_CONTEXT_HINT_CHARS,
    MAX_CONTEXT_HINTS,
    MAX_COUNTRIES,
    MAX_LISTED_IDS,
    MAX_LOCATION_IDS,
    MAX_LOCATION_LABEL_CHARS,
    TARGET_URL_MAX_CHARS,
    TARGETING,
    TARGETING_PLATFORMS,
)
from mureo.chatgpt_ads.tools_mutations import CONVENTION_TOTAL_KEY, SCHEDULE_KEYS

if TYPE_CHECKING:
    from mureo.chatgpt_ads.client import ChatGPTAdsClient

_PAUSED = "paused"
_KEY_RE = re.compile(IDEMPOTENCY_KEY_PATTERN)
_COUNTRY_RE = re.compile(COUNTRY_PATTERN)
_TARGETING_KEYS = frozenset(TARGETING["properties"])
_GEO_KEYS = frozenset({"countries", "include"})
_CREATIVE_KEYS = frozenset(CREATIVE["properties"])


def idempotency_key_value(arguments: dict[str, Any]) -> str:
    """The ``idempotency_key`` argument, or a fresh one when it is absent.

    :func:`~mureo.chatgpt_ads.handlers.run_tool` resolves the key once per
    call and hands it to the handler, so the request, every retry of it and
    the deadline message all carry the same key.
    """
    value = arguments.get("idempotency_key")
    if value is None:
        return uuid.uuid4().hex
    if not isinstance(value, str) or not _KEY_RE.fullmatch(value):
        raise ValueError(
            f"idempotency_key must be 1-{IDEMPOTENCY_KEY_MAX_CHARS} letters, "
            "digits, '_' or '-'"
        )
    return value


def _no_status(arguments: dict[str, Any], entity: str) -> None:
    if "status" in arguments:
        raise ValueError(
            f"status is not an argument: a new {entity} is always created "
            f"paused; enable it with chatgpt_ads_{entity}s_enable"
        )


def _object(value: object, key: str, allowed: frozenset[str]) -> dict[str, Any]:
    """``value`` as an object with only ``allowed`` keys."""
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(
            f"{key} must be an object with only: {', '.join(sorted(allowed))}"
        )
    return value


def _list(value: object, key: str, maximum: int | None = None) -> list[Any]:
    if not isinstance(value, list) or (maximum is not None and len(value) > maximum):
        bound = f" of at most {maximum} items" if maximum is not None else ""
        raise ValueError(f"{key} must be an array{bound}")
    return value


def _ids(value: object, key: str) -> None:
    for item in _list(value, key, MAX_LISTED_IDS):
        id_value(item, f"{key}[]")


def _location(value: object, key: str) -> None:
    location = _object(value, key, frozenset(LOCATION_KEYS))
    id_value(location.get("id"), f"{key}.id")
    for field in LOCATION_KEYS[1:]:
        text = location.get(field, "")
        if not isinstance(text, str) or len(text) > MAX_LOCATION_LABEL_CHARS:
            raise ValueError(
                f"{key}.{field} must be a string of at most "
                f"{MAX_LOCATION_LABEL_CHARS} characters"
            )


def _geo(value: object, key: str) -> None:
    geo = _object(value, key, _GEO_KEYS)
    for code in _list(geo.get("countries", []), f"{key}.countries", MAX_COUNTRIES):
        if not isinstance(code, str) or not _COUNTRY_RE.fullmatch(code):
            raise ValueError(f"{key}.countries holds ISO 3166-1 alpha-2 codes, e.g. US")
    for item in _list(geo.get("include", []), f"{key}.include", MAX_LOCATION_IDS):
        _location(item, f"{key}.include[]")


def _targeting(value: object) -> dict[str, Any]:
    """A ``targeting`` object closed at every documented level."""
    targeting = _object(value, "targeting", _TARGETING_KEYS)
    for key in ("locations", "excluded_locations"):
        if key in targeting:
            _geo(targeting[key], f"targeting.{key}")
    for key in ("custom_audiences", "excluded_custom_audiences"):
        if key in targeting:
            audiences = _object(targeting[key], f"targeting.{key}", frozenset({"ids"}))
            _ids(audiences.get("ids", []), f"targeting.{key}.ids")
    if "platforms" in targeting:
        platforms = _object(
            targeting["platforms"], "targeting.platforms", frozenset({"included"})
        )
        for item in _list(
            platforms.get("included", []), "targeting.platforms.included"
        ):
            if item not in TARGETING_PLATFORMS:
                raise ValueError(
                    "targeting.platforms.included holds: "
                    f"{', '.join(TARGETING_PLATFORMS)}"
                )
    return targeting


def _campaign_budget(arguments: dict[str, Any]) -> dict[str, Any]:
    """The budget: one amount, because the API refuses both and neither."""
    budget = budget_value(arguments.get("budget"))
    if len(budget) != 1:
        raise ValueError(
            "budget on a create takes exactly one of daily_spend_limit_micros "
            "or lifetime_spend_limit_micros"
        )
    return budget


def _campaign_options(arguments: dict[str, Any]) -> dict[str, Any]:
    """The optional campaign fields given, checked."""
    body: dict[str, Any] = {}
    if "targeting" in arguments:
        body["targeting"] = _targeting(arguments["targeting"])
    for key in SCHEDULE_KEYS:
        if key in arguments:
            if arguments[key] is None:
                raise ValueError(
                    f"{key} must be Unix seconds; omit it to leave it unset"
                )
            body[key] = schedule_value(arguments[key], key)
    if "conversion_event_setting_ids" in arguments:
        ids = arguments["conversion_event_setting_ids"]
        _ids(ids, "conversion_event_setting_ids")
        body["conversion_event_setting_ids"] = ids
    return body


async def _campaigns_create(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    _no_status(arguments, "campaign")
    name = required_name(arguments)
    budget = _campaign_budget(arguments)
    bidding_type = arguments.get("bidding_type")
    if bidding_type not in BIDDING_TYPES:
        raise ValueError(f"bidding_type is required: {', '.join(BIDDING_TYPES)}")
    options = _campaign_options(arguments)
    # Checked for the STRATEGY.md account-total cap; never sent.
    if CONVENTION_TOTAL_KEY in arguments:
        number(arguments[CONVENTION_TOTAL_KEY], CONVENTION_TOTAL_KEY, 0)
    key = idempotency_key_value(arguments)
    body = {
        "name": name,
        "status": _PAUSED,
        "budget": budget,
        "bidding_type": bidding_type,
        **options,
    }
    return await client.post("/campaigns", body, idempotency_key=key)


def _context_hints(value: object) -> list[Any]:
    hints = _list(value, "context_hints", MAX_CONTEXT_HINTS)
    if not all(
        isinstance(hint, str) and 1 <= len(hint) <= MAX_CONTEXT_HINT_CHARS
        for hint in hints
    ):
        raise ValueError(
            f"context_hints must be an array of strings of 1 to "
            f"{MAX_CONTEXT_HINT_CHARS} characters"
        )
    return hints


async def _ad_groups_create(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    _no_status(arguments, "ad_group")
    body: dict[str, Any] = {
        "campaign_id": path_id(arguments, "campaign_id"),
        "name": required_name(arguments),
        "status": _PAUSED,
        "bidding_config": bidding_config_value(arguments.get("bidding_config")),
    }
    if "context_hints" in arguments:
        body["context_hints"] = _context_hints(arguments["context_hints"])
    key = idempotency_key_value(arguments)
    return await client.post("/ad_groups", body, idempotency_key=key)


def _image_crop(value: object) -> None:
    crop = _object(value, "creative.image_crop", frozenset(IMAGE_CROP_KEYS))
    for edge in IMAGE_CROP_KEYS:
        number(crop.get(edge), f"creative.image_crop.{edge}", 0, 1)


def _creative(value: object) -> dict[str, Any]:
    """A single-image chat card in the request shape."""
    creative = _object(value, "creative", _CREATIVE_KEYS)
    if creative.get("type") != CHAT_CARD:
        raise ValueError(f"creative.type must be {CHAT_CARD!r}")
    line_text(
        creative.get("title"),
        "creative.title",
        CREATIVE_TITLE_MIN_CHARS,
        CREATIVE_TITLE_MAX_CHARS,
    )
    body = creative.get("body")
    if not isinstance(body, str) or len(body) > CREATIVE_BODY_MAX_CHARS:
        raise ValueError(
            f"creative.body must be a string of at most {CREATIVE_BODY_MAX_CHARS} "
            "characters"
        )
    http_url(creative.get("target_url"), "creative.target_url", TARGET_URL_MAX_CHARS)
    if "file_id" in creative:
        id_value(creative["file_id"], "creative.file_id")
    if "image_crop" in creative:
        if "file_id" not in creative:
            raise ValueError("creative.image_crop needs creative.file_id")
        _image_crop(creative["image_crop"])
    return creative


async def _ads_create(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    _no_status(arguments, "ad")
    body = {
        "ad_group_id": path_id(arguments, "ad_group_id"),
        "name": required_name(arguments),
        "status": _PAUSED,
        "creative": _creative(arguments.get("creative")),
    }
    key = idempotency_key_value(arguments)
    return await client.post("/ads", body, idempotency_key=key)


CREATE_HANDLERS: dict[str, Handler] = {
    "chatgpt_ads_campaigns_create": _campaigns_create,
    "chatgpt_ads_ad_groups_create": _ad_groups_create,
    "chatgpt_ads_ads_create": _ads_create,
    "chatgpt_ads_campaigns_archive": status_handler(
        "/campaigns", "campaign_id", "archive"
    ),
    "chatgpt_ads_ad_groups_archive": status_handler(
        "/ad_groups", "ad_group_id", "archive"
    ),
    "chatgpt_ads_ads_archive": status_handler("/ads", "ad_id", "archive"),
}

__all__ = [
    "CREATE_HANDLERS",
    "idempotency_key_value",
]
