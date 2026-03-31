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


def _json_result(data: Any) -> list[TextContent]:
    """Convert a result to a list of TextContent containing a JSON string."""
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]


def _no_creds_result(msg: str) -> list[TextContent]:
    """Return a credentials-not-found error."""
    return [TextContent(type="text", text=msg)]


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
            return [TextContent(type="text", text=f"API error: {exc}")]

    return wrapper
