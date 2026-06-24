"""MCP handler common helpers.

Provides utility functions and API error handling decorators
shared by Google Ads / Meta Ads handlers.
"""

from __future__ import annotations

import functools
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

from mcp.types import TextContent

logger = logging.getLogger(__name__)


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
        try:
            return await func(*args, **kwargs)
        except ValueError:
            # Re-raise errors such as missing required parameters for the caller to handle
            raise
        except Exception as exc:
            logger.exception("%s failed", func.__name__)
            return [TextContent(type="text", text=f"{API_ERROR_PREFIX} {exc}")]

    return wrapper
