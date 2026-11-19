"""One coroutine per ChatGPT Ads read tool, the handler table and ``run_tool``.

Handlers return plain Python data; :mod:`mureo.chatgpt_ads.provider` turns it
(or a client exception) into the tool result. Every argument is checked
before the first request (:mod:`mureo.chatgpt_ads._validation`). The handlers
that change the account live in :mod:`mureo.chatgpt_ads.handlers_mutations`
and are merged into :data:`HANDLERS` here, so :func:`run_tool` is the one way
any handler runs.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timezone
from typing import TYPE_CHECKING, Any

from mureo.chatgpt_ads._api import (
    PAGE_MAX_AUDIT_LOGS,
    PAGE_MAX_ENTITIES,
    PAGE_MAX_INSIGHTS,
    TOOL_DEADLINE_SECONDS,
)
from mureo.chatgpt_ads._errors import MAY_HAVE_BEEN_APPLIED, ChatGPTAdsAPIError
from mureo.chatgpt_ads._period import resolve_period, today_in, unix_bounds
from mureo.chatgpt_ads._validation import integer, name_value, path_id
from mureo.chatgpt_ads.handlers_mutations import (
    MUTATING_TOOL_NAMES,
    MUTATION_HANDLERS,
    Handler,
)
from mureo.chatgpt_ads.tools import (
    CONVERSION_METRICS,
    DEFAULT_INSIGHTS_LIMIT,
    DEFAULT_LIST_LIMIT,
    DELIVERY_METRICS,
    MAX_TOOL_LIMIT,
)

if TYPE_CHECKING:
    from mureo.chatgpt_ads.client import ChatGPTAdsClient

#: Tool ``level`` → the API's ``aggregation_level``, in hierarchy order.
_AGGREGATION_LEVELS = {
    "account": "ad_account",
    "campaign": "campaign",
    "ad_group": "ad_group",
    "ad": "ad",
}
_LEVEL_RANK = {level: rank for rank, level in enumerate(_AGGREGATION_LEVELS)}
#: Scope argument → (its level, its insights path prefix).
_SCOPES = (
    ("campaign_id", "campaign", "/campaigns"),
    ("ad_group_id", "ad_group", "/ad_groups"),
    ("ad_id", "ad", "/ads"),
)
_GRANULARITIES = ("none", "daily")
_ATTRIBUTION_WINDOWS = (7, 14, 30)


def _optional_id(arguments: dict[str, Any], key: str) -> str | None:
    return None if arguments.get(key) is None else path_id(arguments, key)


def _flag(arguments: dict[str, Any], key: str) -> bool:
    value = arguments.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def _limit(arguments: dict[str, Any], default: int) -> int:
    return integer(arguments.get("limit", default), "limit", 1, MAX_TOOL_LIMIT)


def _period(arguments: dict[str, Any], default: str) -> str:
    """The ``period`` argument, checked before any request.

    Every preset is valid on any day, so resolving against the UTC day here
    only rejects malformed values and over-long ranges; the window itself is
    resolved again in the account's zone once that is known.
    """
    period = arguments.get("period", default)
    resolve_period(period, today_in(timezone.utc))
    return str(period)


def _list_filters(arguments: dict[str, Any], *keys: str) -> list[tuple[str, str]]:
    """The given ``name`` / parent-id filters that were supplied."""
    return [
        (key, value)
        for key in keys
        if (value := (name_value if key == "name" else _optional_id)(arguments, key))
    ]


def _include(arguments: dict[str, Any]) -> list[tuple[str, str]]:
    """``include[]=serving_issues`` when ``include_serving_issues`` is set."""
    wanted = _flag(arguments, "include_serving_issues")
    return [("include[]", "serving_issues")] if wanted else []


async def _account_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    return await client.get("/ad_account")


async def _campaigns_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    params = [*_list_filters(arguments, "name"), *_include(arguments)]
    limit = _limit(arguments, DEFAULT_LIST_LIMIT)
    return await client.list_all(
        "/campaigns", params, limit=limit, page_max=PAGE_MAX_ENTITIES
    )


async def _campaigns_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    campaign_id = path_id(arguments, "campaign_id")
    return await client.get(f"/campaigns/{campaign_id}", _include(arguments))


async def _ad_groups_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    # The reference marks campaign_id required (the OpenAPI document does
    # not); required is the reading that cannot be rejected.
    params = [("campaign_id", path_id(arguments, "campaign_id"))]
    params += _list_filters(arguments, "name")
    limit = _limit(arguments, DEFAULT_LIST_LIMIT)
    return await client.list_all(
        "/ad_groups", params, limit=limit, page_max=PAGE_MAX_ENTITIES
    )


async def _ad_groups_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    return await client.get(f"/ad_groups/{path_id(arguments, 'ad_group_id')}")


async def _ads_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    params = _list_filters(arguments, "ad_group_id", "name")
    limit = _limit(arguments, DEFAULT_LIST_LIMIT)
    return await client.list_all(
        "/ads", params, limit=limit, page_max=PAGE_MAX_ENTITIES
    )


async def _ads_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    return await client.get(f"/ads/{path_id(arguments, 'ad_id')}")


def _insights_scope(arguments: dict[str, Any]) -> tuple[str, str]:
    """``(scope level, insights path)``; at most one scope id may be given."""
    given = [
        (level, f"{prefix}/{value}/insights")
        for key, level, prefix in _SCOPES
        if (value := _optional_id(arguments, key)) is not None
    ]
    if len(given) > 1:
        raise ValueError("give at most one of campaign_id, ad_group_id, ad_id")
    return given[0] if given else ("account", "/ad_account/insights")


def _insights_level(arguments: dict[str, Any], scope: str) -> str:
    default = scope if scope in ("ad_group", "ad") else "campaign"
    level = arguments.get("level", default)
    if not isinstance(level, str) or level not in _AGGREGATION_LEVELS:
        raise ValueError(f"level must be one of {', '.join(_AGGREGATION_LEVELS)}")
    if _LEVEL_RANK[level] < _LEVEL_RANK[scope]:
        raise ValueError(f"level {level!r} is above the {scope!r} scope")
    return str(level)


def _metrics(arguments: dict[str, Any]) -> tuple[str, ...]:
    value = arguments.get("metrics", list(DELIVERY_METRICS))
    allowed = (*DELIVERY_METRICS, *CONVERSION_METRICS)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(m, str) and m in allowed for m in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(
            f"metrics must be a non-empty list of distinct names from: "
            f"{', '.join(allowed)}"
        )
    return tuple(value)


def _granularity(arguments: dict[str, Any]) -> str:
    granularity = arguments.get("time_granularity", "none")
    if granularity not in _GRANULARITIES:
        raise ValueError(f"time_granularity must be one of {', '.join(_GRANULARITIES)}")
    return str(granularity)


def _attribution(arguments: dict[str, Any]) -> list[tuple[str, str]]:
    """``attribution_window_days`` when given; omitted, the API default applies."""
    window = arguments.get("attribution_window_days")
    if window is None:
        return []
    # ``type() is int``: a bool or ``7.0`` compares equal to an allowed
    # value but is not the integer the API documents.
    if type(window) is not int or window not in _ATTRIBUTION_WINDOWS:
        raise ValueError("attribution_window_days must be 7, 14 or 30")
    return [("attribution_window_days", str(window))]


def _insights_fields(
    level: str, granularity: str, metrics: tuple[str, ...]
) -> list[str]:
    row = _AGGREGATION_LEVELS[level]
    time_field = ["metadata.readable_time"] if granularity == "daily" else []
    return [
        f"{row}.id",
        f"{row}.name",
        *time_field,
        *(f"{row}.{m}" if m in DELIVERY_METRICS else m for m in metrics),
    ]


async def _insights_report(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    period = _period(arguments, "last_30d")
    scope, path = _insights_scope(arguments)
    level = _insights_level(arguments, scope)
    granularity = _granularity(arguments)
    fields = _insights_fields(level, granularity, _metrics(arguments))
    attribution = _attribution(arguments)
    limit = _limit(arguments, DEFAULT_INSIGHTS_LIMIT)
    since, until = resolve_period(period, today_in(await client.account_timezone()))
    window = {"type": "date_range", "since": str(since), "until": str(until)}
    params = [
        ("aggregation_level", _AGGREGATION_LEVELS[level]),
        ("time_granularity", granularity),
        *attribution,
        ("time_ranges[]", json.dumps(window)),
        *(("fields[]", field) for field in fields),
    ]
    return await client.list_all(path, params, limit=limit, page_max=PAGE_MAX_INSIGHTS)


async def _change_history_list(
    client: ChatGPTAdsClient, arguments: dict[str, Any]
) -> Any:
    period = _period(arguments, "last_7d")
    filters = _list_filters(arguments, "campaign_id", "ad_group_id", "ad_id")
    limit = _limit(arguments, DEFAULT_LIST_LIMIT)
    zone = await client.account_timezone()
    start, end = unix_bounds(*resolve_period(period, today_in(zone)), zone)
    params = [*filters, ("start_time", str(start)), ("end_time", str(end))]
    return await client.list_all(
        "/audit_logs", params, limit=limit, page_max=PAGE_MAX_AUDIT_LOGS
    )


HANDLERS: dict[str, Handler] = {
    "chatgpt_ads_account_get": _account_get,
    "chatgpt_ads_campaigns_list": _campaigns_list,
    "chatgpt_ads_campaigns_get": _campaigns_get,
    "chatgpt_ads_ad_groups_list": _ad_groups_list,
    "chatgpt_ads_ad_groups_get": _ad_groups_get,
    "chatgpt_ads_ads_list": _ads_list,
    "chatgpt_ads_ads_get": _ads_get,
    "chatgpt_ads_insights_report": _insights_report,
    "chatgpt_ads_change_history_list": _change_history_list,
    **MUTATION_HANDLERS,
}


def _open_client(api_key: str) -> ChatGPTAdsClient:
    """A client for one tool call."""
    # Startup cost: the MCP server imports this package to list the tools;
    # httpx and the client are only needed once a tool is actually called.
    from mureo.chatgpt_ads.client import (  # noqa: PLC0415 — startup cost (#993)
        ChatGPTAdsClient,
    )

    return ChatGPTAdsClient(api_key)


async def run_tool(
    name: str,
    arguments: dict[str, Any],
    api_key: str,
    *,
    deadline: float = TOOL_DEADLINE_SECONDS,
) -> Any:
    """Run tool ``name`` within ``deadline`` seconds.

    Client and validation errors propagate. Running out of time is a
    :class:`ChatGPTAdsAPIError` raised after the ``except`` block, so nothing
    from the cancelled request is chained onto it; for a tool that changes the
    account it ends with :data:`MAY_HAVE_BEEN_APPLIED`, because the request
    may have reached the platform before it was cancelled.
    """
    handler = HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown ChatGPT Ads tool: {name}")
    async with _open_client(api_key) as client:
        try:
            return await asyncio.wait_for(handler(client, arguments), deadline)
        except asyncio.TimeoutError:
            pass
    message = f"the call did not finish within {deadline:g} seconds"
    if name in MUTATING_TOOL_NAMES:
        message = f"{message} {MAY_HAVE_BEEN_APPLIED}"
    raise ChatGPTAdsAPIError(message, status=0)


__all__ = ["HANDLERS", "run_tool"]
