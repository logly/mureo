"""One coroutine per ChatGPT Ads read tool, the tool and handler tables and
``run_tool``.

Handlers return plain Python data; :mod:`mureo.chatgpt_ads.provider` turns it
(or a client exception) into the tool result. Every argument is checked
before the first request (:mod:`mureo.chatgpt_ads._validation`). The other
tool families live in their own modules (``handlers_mutations``,
``handlers_create``, ``handlers_creative``, ``handlers_audiences``,
``handlers_measurement`` and their ``tools_*``) and are
composed here: :data:`ALL_TOOLS` is the provider's tool list and
:data:`HANDLERS` its handler table, so :func:`run_tool` is the one way any
handler runs, and which tools change the account is read off the composed
list rather than kept per module. :func:`run_with_client` is the client
lifetime and deadline under it, shared with
:mod:`mureo.chatgpt_ads.change_feed`.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, TypeVar

from mureo.chatgpt_ads._api import (
    AD_ACCOUNT_PATH,
    PAGE_MAX_AUDIT_LOGS,
    PAGE_MAX_ENTITIES,
    PAGE_MAX_INSIGHTS,
    TOOL_DEADLINE_SECONDS,
)
from mureo.chatgpt_ads._errors import (
    MAY_HAVE_BEEN_APPLIED,
    REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY,
    REPEAT_WITH_IDEMPOTENCY_KEY,
    ChatGPTAdsAPIError,
)
from mureo.chatgpt_ads._period import resolve_period, today_in, unix_bounds
from mureo.chatgpt_ads._validation import (
    attribution_window_value,
    flag,
    granularity_value,
    limit_value,
    name_value,
    path_id,
    period_value,
)
from mureo.chatgpt_ads.handlers_audiences import AUDIENCE_HANDLERS
from mureo.chatgpt_ads.handlers_create import (
    CREATE_HANDLERS,
    idempotency_key_value,
)
from mureo.chatgpt_ads.handlers_creative import CREATIVE_HANDLERS
from mureo.chatgpt_ads.handlers_measurement import MEASUREMENT_HANDLERS
from mureo.chatgpt_ads.handlers_mutations import MUTATION_HANDLERS, Handler
from mureo.chatgpt_ads.tools import (
    CONVERSION_METRICS,
    DEFAULT_INSIGHTS_LIMIT,
    DEFAULT_LIST_LIMIT,
    DELIVERY_METRICS,
    TOOLS,
)
from mureo.chatgpt_ads.tools_audiences import AUDIENCE_TOOLS, MEMBERS_TOOL_NAMES
from mureo.chatgpt_ads.tools_create import CREATE_TOOLS
from mureo.chatgpt_ads.tools_creative import CREATIVE_TOOLS
from mureo.chatgpt_ads.tools_measurement import MEASUREMENT_TOOLS
from mureo.chatgpt_ads.tools_mutations import MUTATION_TOOLS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import Tool

    from mureo.chatgpt_ads.client import ChatGPTAdsClient

_T = TypeVar("_T")

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


def _optional_id(arguments: dict[str, Any], key: str) -> str | None:
    return None if arguments.get(key) is None else path_id(arguments, key)


def _list_filters(arguments: dict[str, Any], *keys: str) -> list[tuple[str, str]]:
    """The given ``name`` / parent-id filters that were supplied."""
    return [
        (key, value)
        for key in keys
        if (value := (name_value if key == "name" else _optional_id)(arguments, key))
    ]


def _include(arguments: dict[str, Any]) -> list[tuple[str, str]]:
    """``include[]=serving_issues`` when ``include_serving_issues`` is set."""
    wanted = flag(arguments, "include_serving_issues")
    return [("include[]", "serving_issues")] if wanted else []


async def _account_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    return await client.get(AD_ACCOUNT_PATH)


async def _campaigns_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    params = [*_list_filters(arguments, "name"), *_include(arguments)]
    limit = limit_value(arguments, DEFAULT_LIST_LIMIT)
    return await client.list_all(
        "/campaigns", params, limit=limit, page_max=PAGE_MAX_ENTITIES
    )


async def _campaigns_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    campaign_id = path_id(arguments, "campaign_id")
    return await client.get(f"/campaigns/{campaign_id}", _include(arguments))


async def _ad_groups_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    params = _list_filters(arguments, "campaign_id", "name")
    limit = limit_value(arguments, DEFAULT_LIST_LIMIT)
    return await client.list_all(
        "/ad_groups", params, limit=limit, page_max=PAGE_MAX_ENTITIES
    )


async def _ad_groups_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    return await client.get(f"/ad_groups/{path_id(arguments, 'ad_group_id')}")


async def _ads_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    params = _list_filters(arguments, "ad_group_id", "name")
    limit = limit_value(arguments, DEFAULT_LIST_LIMIT)
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


def _attribution(arguments: dict[str, Any]) -> list[tuple[str, str]]:
    """``attribution_window_days`` when given; omitted, the API default applies."""
    window = attribution_window_value(arguments)
    return [] if window is None else [("attribution_window_days", str(window))]


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
    period = period_value(arguments, "last_30d")
    scope, path = _insights_scope(arguments)
    level = _insights_level(arguments, scope)
    granularity = granularity_value(arguments)
    fields = _insights_fields(level, granularity, _metrics(arguments))
    attribution = _attribution(arguments)
    limit = limit_value(arguments, DEFAULT_INSIGHTS_LIMIT)
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
    period = period_value(arguments, "last_7d")
    filters = _list_filters(arguments, "campaign_id", "ad_group_id", "ad_id")
    limit = limit_value(arguments, DEFAULT_LIST_LIMIT)
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
    **CREATE_HANDLERS,
    **CREATIVE_HANDLERS,
    **AUDIENCE_HANDLERS,
    **MEASUREMENT_HANDLERS,
}

#: Every tool the provider lists, in order.
ALL_TOOLS: tuple[Tool, ...] = (
    *TOOLS,
    *MUTATION_TOOLS,
    *CREATE_TOOLS,
    *CREATIVE_TOOLS,
    *AUDIENCE_TOOLS,
    *MEASUREMENT_TOOLS,
)

#: Tools that change the account, read off their ``readOnlyHint``; one
#: set over every module, so a new module cannot be left out of the
#: deadline message.
MUTATING_TOOL_NAMES = frozenset(
    tool.name
    for tool in ALL_TOOLS
    if not (tool.annotations and tool.annotations.readOnlyHint)
)
#: Requests that carry an ``Idempotency-Key`` (the creates, and the audience
#: membership add and remove): the tools offering the ``idempotency_key``
#: argument.
_IDEMPOTENT_TOOL_NAMES = frozenset(
    tool.name
    for tool in ALL_TOOLS
    if "idempotency_key" in tool.inputSchema["properties"]
)


def _open_client(api_key: str) -> ChatGPTAdsClient:
    """A client for one tool call."""
    # Startup cost: the MCP server imports this package to list the tools;
    # httpx and the client are only needed once a tool is actually called.
    from mureo.chatgpt_ads.client import (  # noqa: PLC0415 — startup cost (#993)
        ChatGPTAdsClient,
    )

    return ChatGPTAdsClient(api_key)


async def run_with_client(
    work: Callable[[ChatGPTAdsClient], Awaitable[_T]],
    api_key: str,
    *,
    deadline: float = TOOL_DEADLINE_SECONDS,
    mutating: bool = False,
    idempotency_key: str | None = None,
    repeat_sentence: str = REPEAT_WITH_IDEMPOTENCY_KEY,
) -> _T:
    """Run ``work`` on a client of its own within ``deadline`` seconds.

    The one place a client is opened and timed: tool calls and the change
    feed both come through here. Client errors propagate. Running out of time
    is a :class:`ChatGPTAdsAPIError` raised after the ``except`` block, so
    nothing from the cancelled request is chained onto it; for ``mutating``
    work it ends with :data:`MAY_HAVE_BEEN_APPLIED`, because the request may
    have reached the platform before it was cancelled. For a request sent
    with ``idempotency_key`` it ends with ``repeat_sentence`` instead
    (:data:`REPEAT_WITH_IDEMPOTENCY_KEY` for a create,
    :data:`REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY` for an audience membership
    change): repeating with that key is the safe next step.
    """
    async with _open_client(api_key) as client:
        try:
            return await asyncio.wait_for(work(client), deadline)
        except asyncio.TimeoutError:
            pass
    message = f"the call did not finish within {deadline:g} seconds"
    if idempotency_key is not None:
        message = f"{message} {repeat_sentence.format(key=idempotency_key)}"
    elif mutating:
        message = f"{message} {MAY_HAVE_BEEN_APPLIED}"
    raise ChatGPTAdsAPIError(message, status=0)


async def run_tool(
    name: str,
    arguments: dict[str, Any],
    api_key: str,
    *,
    deadline: float = TOOL_DEADLINE_SECONDS,
) -> Any:
    """Run tool ``name`` within ``deadline`` seconds (see :func:`run_with_client`).

    Validation errors propagate like client errors. A create's idempotency
    key is resolved here, once per call, and handed to the handler, so the
    request and the deadline message name the same key.
    """
    handler = HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown ChatGPT Ads tool: {name}")
    key = None
    if name in _IDEMPOTENT_TOOL_NAMES:
        key = idempotency_key_value(arguments)
        arguments = {**arguments, "idempotency_key": key}
    return await run_with_client(
        lambda client: handler(client, arguments),
        api_key,
        deadline=deadline,
        mutating=name in MUTATING_TOOL_NAMES,
        idempotency_key=key,
        repeat_sentence=(
            REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY
            if name in MEMBERS_TOOL_NAMES
            else REPEAT_WITH_IDEMPOTENCY_KEY
        ),
    )


__all__ = [
    "ALL_TOOLS",
    "HANDLERS",
    "MUTATING_TOOL_NAMES",
    "run_tool",
    "run_with_client",
]
