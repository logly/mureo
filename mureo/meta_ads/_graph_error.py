"""The one rendering of a Meta Graph API error envelope (#866, #605).

``mureo.meta_ads.client``, ``mureo.meta_ads.accounts`` and ``mureo.auth``
all quote Graph's ``{"error": {...}}`` body in a raised message, and from
there in a log record. They share this formatter so the same envelope reads
the same way wherever it surfaces.

Everything Graph wrote is bounded and collapsed to one line before it is
quoted: ``error.message`` is text Meta chose, of unbounded length, and may
contain newlines — unbounded it floods the log, with newlines it can forge a
second log record. Only the six named fields are read. A body that carries
none of them yields the caller's ``fallback`` sentence, never the raw body:
the fallback to the body is the leak #605 closed.

This module sits on the ``mureo.auth`` import path, so it imports nothing
from :mod:`mureo.meta_ads.client` (``tests/test_mcp_startup_budget.py``).
"""

from __future__ import annotations

from typing import Any

from mureo.logging_setup import one_log_line, truncate_text

#: Cap on each Graph-authored text field quoted in an error detail.
GRAPH_ERROR_MESSAGE_MAX_CHARS = 200
#: Cap on each Graph-authored code quoted in an error detail. The codes are
#: numeric only by convention, so they are bounded rather than trusted.
GRAPH_ERROR_CODE_MAX_CHARS = 32

#: The ``fallback`` for a body that is not a usable error envelope — an HTML
#: proxy page, a Graph outage, plain junk. The status code still travels with
#: the caller's message; the body itself never does.
GRAPH_ERROR_NO_DETAIL = "no error detail in response body"

#: Text fields, quoted bare, in this order.
_TEXT_FIELDS = ("message", "error_user_title", "error_user_msg")
#: ``(field, label)`` of the code fields, quoted as ``label=value``.
_CODE_FIELDS = (
    ("code", "code"),
    ("error_subcode", "subcode"),
    ("fbtrace_id", "fbtrace_id"),
)
_SEPARATOR = " | "


def _bounded(value: str, limit: int) -> str:
    """One log line, at most ``limit`` characters.

    Reuses :func:`mureo.logging_setup.truncate_text` /
    :func:`~mureo.logging_setup.one_log_line` rather than re-deriving them —
    one definition of "what mureo does to text a platform wrote" (#605).
    """
    return truncate_text(one_log_line(value), limit)


def _field(value: Any, limit: int) -> str | None:
    """``str(value)`` bounded to ``limit``, or ``None`` when absent or blank.

    Bounded first, then tested: :func:`~mureo.logging_setup.one_log_line`
    turns whitespace-only text into ``""``, which must drop the field rather
    than quote an empty part.
    """
    if value is None:
        return None
    return _bounded(str(value), limit) or None


def format_graph_error(payload: Any, *, fallback: str) -> str:
    """Render the ``error`` object of a parsed Graph response body.

    ``payload`` is the parsed JSON body, or anything else (``None`` for a
    body that did not parse). When ``payload["error"]`` is a dict, the
    detail is ``message``, ``error_user_title`` and ``error_user_msg``
    (each bounded to :data:`GRAPH_ERROR_MESSAGE_MAX_CHARS`), then
    ``code=``, ``subcode=`` and ``fbtrace_id=`` (each bounded to
    :data:`GRAPH_ERROR_CODE_MAX_CHARS`), joined with ``" | "``. A field counts
    when it is present, not ``None`` and its ``str()`` is not blank once
    bounded, so ``code=0`` is kept. With no such field, or no dict ``error``, the
    result is ``fallback`` (bounded the same way) — pass a fixed sentence
    such as :data:`GRAPH_ERROR_NO_DETAIL`, never the response body.
    """
    err = payload.get("error") if isinstance(payload, dict) else None
    parts: list[str] = []
    if isinstance(err, dict):
        for key in _TEXT_FIELDS:
            text = _field(err.get(key), GRAPH_ERROR_MESSAGE_MAX_CHARS)
            if text is not None:
                parts.append(text)
        for key, label in _CODE_FIELDS:
            text = _field(err.get(key), GRAPH_ERROR_CODE_MAX_CHARS)
            if text is not None:
                parts.append(f"{label}={text}")
    if parts:
        return _SEPARATOR.join(parts)
    return _bounded(fallback, GRAPH_ERROR_MESSAGE_MAX_CHARS)
