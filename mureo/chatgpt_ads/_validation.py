"""Argument checks shared by the read and the mutation handlers.

Every argument is checked before the first request, so a malformed call costs
no API quota and a path id can never steer a URL. The MCP server already
validates against the schema, but the provider is callable directly too, so
the handlers hold the same bounds the schemas state.
"""

from __future__ import annotations

import math
import re
from typing import Any

from mureo.chatgpt_ads.tools import (
    ID_PATTERN,
    NAME_MAX_CHARS,
    NAME_MIN_CHARS,
    NAME_PATTERN,
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


def name_value(arguments: dict[str, Any], key: str) -> str | None:
    """A ``name`` argument held to the API's bounds; ``None`` when absent.

    The API takes 3 to 1,000 characters on one line with at least one that
    is not a space (:data:`~mureo.chatgpt_ads.tools.NAME_PATTERN`; a line
    break anywhere is refused, as the API's own regex dialect refuses it).
    An empty string is refused rather than read as absent, so a caller that
    meant to filter never gets the unfiltered list.
    """
    value = arguments.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not NAME_MIN_CHARS <= len(value) <= NAME_MAX_CHARS
        or not _NAME_RE.search(value)
        or _LINE_BREAKS.intersection(value)
    ):
        raise ValueError(
            f"{key} must be {NAME_MIN_CHARS}-{NAME_MAX_CHARS} characters on one "
            "line, not all spaces"
        )
    return value


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


def number(value: object, key: str, minimum: float) -> float:
    """``value`` as a finite number of at least ``minimum``.

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
    if not math.isfinite(figure) or figure < minimum:
        raise ValueError(f"{key} must be a finite number of at least {minimum:g}")
    return figure


__all__ = ["id_value", "integer", "name_value", "number", "path_id"]
