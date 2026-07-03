"""MCP handler common helpers.

Provides utility functions and API error handling decorators
shared by Google Ads / Meta Ads handlers.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

from mcp.types import TextContent

logger = logging.getLogger(__name__)


# Per-call registry of platform clients whose async resources must be released
# once the handler returns. Handlers open a fresh client per tool call (Meta /
# Search Console clients each hold a persistent ``httpx.AsyncClient``); without
# an explicit close, the long-lived native MCP server accumulates idle
# keep-alive sockets/file descriptors for the whole session. ``api_error_handler``
# scopes a bucket around each handler; ``_get_client`` helpers register into it.
_active_clients: contextvars.ContextVar[list[Any] | None] = contextvars.ContextVar(
    "mureo_active_mcp_clients", default=None
)


def register_client_for_cleanup(client: Any) -> None:
    """Register ``client`` for close after the current handler completes.

    No-op when called outside a handler scope (no active bucket), so it is safe
    for callers that may run without the ``api_error_handler`` wrapper.
    """
    bucket = _active_clients.get()
    if bucket is not None and client is not None:
        bucket.append(client)


async def _close_clients(bucket: list[Any]) -> None:
    """Best-effort close of every registered client. Never raises."""
    for client in bucket:
        close = getattr(client, "close", None)
        if close is None:
            continue
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - cleanup must not mask the handler result
            logger.debug("client cleanup failed", exc_info=True)


def _require(arguments: dict[str, Any], key: str) -> Any:
    """Retrieve a required parameter. Raises ValueError if missing."""
    value = arguments.get(key)
    if value is None or value == "":
        raise ValueError(f"Required parameter {key} is not specified")
    return value


def _opt(arguments: dict[str, Any], key: str, default: Any = None) -> Any:
    """Retrieve an optional parameter."""
    return arguments.get(key, default)


def _validate_positive_money(arguments: dict[str, Any], *keys: str) -> None:
    """Reject non-positive monetary values before a real-spend mutation.

    For each key present and not ``None``, require a positive number. Guards
    against ``0`` (which silently halts delivery) and negatives reaching a
    live budget/bid. ``bool`` is rejected even though it is an ``int``
    subclass. No-op for absent keys (the field is simply not being changed).
    """
    for key in keys:
        if key not in arguments or arguments[key] is None:
            continue
        value = arguments[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a positive number (got {value!r})")
        if value <= 0:
            raise ValueError(f"{key} must be greater than 0 (got {value!r})")


def _json_result(data: Any) -> list[TextContent]:
    """Convert a result to a list of TextContent containing a JSON string."""
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]


def _no_creds_result(msg: str) -> list[TextContent]:
    """Return a credentials-not-found error."""
    return [TextContent(type="text", text=msg)]


# The single prefix ``api_error_handler`` stamps onto a caught-exception
# result. Detectors key off this exact string to recognise "the API call
# failed but was returned as content instead of raised" — kept here, next to
# the producer, as the one source of truth.
API_ERROR_PREFIX = "API error:"


def is_error_result(result: list[Any] | None) -> bool:
    """True if ``result`` is an :func:`api_error_handler` error envelope.

    An ``api_error_handler``-wrapped mutation turns an API-level failure into
    an ``"API error: ..."`` TextContent instead of raising. Detecting it lets
    the dispatch paths skip recording an ``action_log`` entry for a mutation
    that did not actually change platform state. Shared by the native
    (:mod:`mureo.mcp.native_reversal`) and plugin (:mod:`mureo.mcp.server`)
    promotion paths so both skip the identical envelope.
    """
    if not result:
        return False
    text = getattr(result[0], "text", "")
    return isinstance(text, str) and text.startswith(API_ERROR_PREFIX)


def api_error_handler(
    func: Callable[..., Coroutine[Any, Any, list[TextContent]]],
) -> Callable[..., Coroutine[Any, Any, list[TextContent]]]:
    """Decorator that converts API call exceptions to TextContent error messages."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> list[TextContent]:
        # Scope a per-call client-cleanup bucket so any client opened via
        # ``_get_client`` during this handler is closed on the way out,
        # regardless of success/exception.
        token = _active_clients.set([])
        try:
            return await func(*args, **kwargs)
        except ValueError:
            # Re-raise errors such as missing required parameters for the caller to handle
            raise
        except Exception as exc:
            logger.exception("%s failed", func.__name__)
            return [TextContent(type="text", text=f"{API_ERROR_PREFIX} {exc}")]
        finally:
            bucket = _active_clients.get() or []
            _active_clients.reset(token)
            await _close_clients(bucket)

    return wrapper
