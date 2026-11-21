"""Argument checks shared by the read and the mutation handlers.

Every argument is checked before the first request, so a malformed call costs
no API quota and a path id can never steer a URL. The MCP server already
validates against the schema, but the provider is callable directly too, so
the handlers hold the same bounds the schemas state.
"""

from __future__ import annotations

import math
import re
from datetime import timezone
from typing import Any
from urllib.parse import urlsplit

from mureo.chatgpt_ads._period import resolve_period, today_in
from mureo.chatgpt_ads.tools import (
    ATTRIBUTION_WINDOWS,
    ID_PATTERN,
    MAX_TOOL_LIMIT,
    NAME_MAX_CHARS,
    NAME_MIN_CHARS,
    NAME_PATTERN,
    TIME_GRANULARITIES,
)

_ID_RE = re.compile(ID_PATTERN)
_NAME_RE = re.compile(NAME_PATTERN)
#: The line terminators the pattern's ``.`` stops at in JSON Schema (ECMA
#: 262). Python's ``.`` stops at ``\n`` only and its ``$`` also matches
#: before a final ``\n``, so the pattern alone would let these through.
_LINE_BREAKS = frozenset("\n\r\u2028\u2029")


def id_value(value: object, key: str) -> str:
    """``value`` as a platform id: the one shape every id argument takes."""
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{key} is required: letters, digits, '_' or '-', 1-128 chars")
    return value


def path_id(arguments: dict[str, Any], key: str) -> str:
    """A required id, checked before it is put into a URL path."""
    return id_value(arguments.get(key), key)


def line_text(value: object, key: str, minimum: int, maximum: int) -> str:
    """``value`` as ``minimum`` to ``maximum`` characters on one line.

    At least one character is not a space
    (:data:`~mureo.chatgpt_ads.tools.NAME_PATTERN`, the API's pattern for a
    name and a creative title), and a line break anywhere is refused, as the
    API's own regex dialect refuses it.
    """
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= maximum
        or not _NAME_RE.search(value)
        or _LINE_BREAKS.intersection(value)
    ):
        raise ValueError(
            f"{key} must be {minimum}-{maximum} characters on one line, not all "
            "spaces"
        )
    return value


def name_value(arguments: dict[str, Any], key: str) -> str | None:
    """A ``name`` argument held to the API's bounds; ``None`` when absent.

    The API takes 3 to 1,000 characters (:func:`line_text`). An empty string
    is refused rather than read as absent, so a caller that meant to filter
    never gets the unfiltered list.
    """
    value = arguments.get(key)
    if value is None:
        return None
    return line_text(value, key, NAME_MIN_CHARS, NAME_MAX_CHARS)


def integer(value: object, key: str, minimum: int, maximum: int | None = None) -> int:
    """``value`` as an integer within ``[minimum, maximum]``.

    ``type() is int``: a bool or ``5.0`` compares equal to an integer but is
    not the integer the API documents, and a float amount of micros would be
    refused or rounded by the platform.
    """
    if (
        type(value) is not int
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        bound = (
            f"from {minimum} to {maximum}"
            if maximum is not None
            else f"of at least {minimum}"
        )
        raise ValueError(f"{key} must be an integer {bound}")
    return value


def number(
    value: object, key: str, minimum: float, maximum: float | None = None
) -> float:
    """``value`` as a finite number within ``[minimum, maximum]``.

    An integer or a float, never a bool: ``True`` compares equal to 1 but is
    not a figure anyone meant. An integer too large for a float counts as
    not finite.
    """
    figure = math.nan
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            figure = float(value)
        except OverflowError:
            figure = math.inf
    if (
        not math.isfinite(figure)
        or figure < minimum
        or (maximum is not None and figure > maximum)
    ):
        bound = (
            f"from {minimum:g} to {maximum:g}"
            if maximum is not None
            else f"of at least {minimum:g}"
        )
        raise ValueError(f"{key} must be a finite number {bound}")
    return figure


def limit_value(arguments: dict[str, Any], default: int) -> int:
    """A list or report tool's ``limit``: rows to collect, 1 to the tool cap."""
    return integer(arguments.get("limit", default), "limit", 1, MAX_TOOL_LIMIT)


def flag(arguments: dict[str, Any], key: str) -> bool:
    """A boolean argument; absent is ``False``."""
    value = arguments.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def period_value(arguments: dict[str, Any], default: str) -> str:
    """The ``period`` argument, checked before any request.

    Every preset is valid on any day, so resolving against the UTC day here
    only rejects malformed values and over-long ranges; the window itself is
    resolved again in the account's zone once that is known.
    """
    period = arguments.get("period", default)
    resolve_period(period, today_in(timezone.utc))
    return str(period)


def granularity_value(arguments: dict[str, Any]) -> str:
    """The ``time_granularity`` argument; absent is ``none``."""
    granularity = arguments.get("time_granularity", "none")
    if granularity not in TIME_GRANULARITIES:
        raise ValueError(
            f"time_granularity must be one of {', '.join(TIME_GRANULARITIES)}"
        )
    return str(granularity)


def attribution_window_value(arguments: dict[str, Any]) -> int | None:
    """The ``attribution_window_days`` argument; ``None`` when absent."""
    window = arguments.get("attribution_window_days")
    if window is None:
        return None
    # ``type() is int``: a bool or ``7.0`` compares equal to an allowed
    # value but is not the integer the API documents.
    if type(window) is not int or window not in ATTRIBUTION_WINDOWS:
        *head, last = (str(days) for days in ATTRIBUTION_WINDOWS)
        raise ValueError(f"attribution_window_days must be {', '.join(head)} or {last}")
    return window


def http_url(value: object, key: str, max_chars: int) -> str:
    """``value`` as an absolute http(s) URL of at most ``max_chars``.

    A destination the platform sends people to: a host is required, and no
    whitespace, control character, backslash (read as a separator by some
    clients) or user-info (``user:password@``) may hide in it. This is a
    shape check, not :mod:`mureo.core.url_guard`: mureo never fetches the
    landing page; the platform does, in its own review.
    """
    if not (isinstance(value, str) and _is_http_url(value, max_chars)):
        raise ValueError(
            f"{key} must be an http or https URL with a host, without "
            f"credentials, at most {max_chars} characters"
        )
    return value


def _is_http_url(value: str, max_chars: int) -> bool:
    if (
        len(value) > max_chars
        or "\\" in value
        or any(ch.isspace() or not ch.isprintable() for ch in value)
    ):
        return False
    try:
        parts = urlsplit(value)
        _ = parts.port  # raises ValueError on a malformed port
        return (
            parts.scheme.lower() in ("http", "https")
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        # urlsplit and .port refuse a malformed authority ("https://[::1");
        # that is the same argument error as any other bad URL.
        return False


__all__ = [
    "attribution_window_value",
    "flag",
    "granularity_value",
    "http_url",
    "id_value",
    "integer",
    "limit_value",
    "line_text",
    "name_value",
    "number",
    "path_id",
    "period_value",
]
