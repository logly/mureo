"""Reading an Advertiser API error answer into one bounded line.

The ONE place an error body is read. The published reference defines no
error-body schema, so a JSON object body is read in every shape the
documentation and its examples show — ``{"error": {"message", "code",
"type"}}``, ``{"error": "<text>"}``, and top-level ``message`` / ``detail`` /
``code``.

A body that is not a JSON object is never quoted: the message carries the
status and :data:`NO_ERROR_DETAIL` instead. A non-JSON answer is usually an
error page from a proxy or load balancer between mureo and the API, and such
a page can echo the request it received, ``Authorization`` header included.
Quoting it would put the operator's API key into a tool result and a log
line; the same rule :mod:`mureo.meta_ads._graph_error` holds for Graph.

The message text that is quoted is still platform-authored, so it is cleaned
before it travels: non-printable characters are dropped (control bytes,
terminal escape introducers, bidirectional overrides), newlines collapse to
one line, secret-shaped ``key=value`` text is scrubbed by
:func:`mureo.core.scrub.scrub_capped`, and the result is cut at 200
characters (the bound :mod:`mureo.meta_ads._graph_error` uses). The error
``code`` is kept only when it looks like a code. The client replaces the API
key value in the body before calling :func:`error_from_response`, so an
echoed key is gone before any of this runs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from mureo.core.auth_failure import PlatformAuthError
from mureo.core.scrub import PROSE, scrub_capped
from mureo.logging_setup import one_log_line, truncate_text

#: Longest platform text kept in a message.
_MAX_TEXT_CHARS = 200

#: What a message says in place of a body it will not quote. The status code
#: still travels; the body itself never does.
NO_ERROR_DETAIL = "no readable error detail in the response body"

#: Ends the message of a change that ended without a readable answer: a 5xx,
#: a transport error or the call deadline. The platform may have applied the
#: change before the answer was lost, so repeating it blind could apply it
#: twice, and the operator needs to know to look before trying again.
MAY_HAVE_BEEN_APPLIED = (
    "The change may have been applied; read the entity before retrying."
)

#: Ends the message of a create sent with an idempotency key that ended
#: without a readable answer, in place of :data:`MAY_HAVE_BEEN_APPLIED`. The
#: platform returns the existing object for a repeat with the same key when
#: it can see the matching earlier create, so that repeat is the safest next
#: step; a new key could create a duplicate. The sentence keeps that
#: condition rather than promising more. Filled with ``.format(key=...)``;
#: the key is not a secret.
REPEAT_WITH_IDEMPOTENCY_KEY = (
    "The entity may have been created; repeat the call with "
    'idempotency_key="{key}" and the same arguments: when the platform can '
    "see the earlier create it returns that entity instead of creating a "
    "second one."
)

#: A platform error code worth quoting and matching on. Anything else (a
#: newline, a 100k-character value, prose) is treated as no code at all.
_CODE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")

#: Statuses on which a "feature not enabled" body means a per-account gate.
#: Any other status keeps its ordinary meaning even with such a body.
_GATE_STATUSES = frozenset({403, 404})
_GATE_CODE_SUFFIXES = ("_disabled", "_not_enabled")
_GATE_PHRASES = ("is not enabled", "not enabled for")


class ChatGPTAdsAPIError(RuntimeError):
    """A failed Advertiser API call that is not an auth failure.

    ``status`` is the HTTP status, or ``0`` when the failure is not one HTTP
    answer (a transport error, the call deadline, the page cap). ``code`` is
    the platform's error code, when the body carried a well-formed one.
    ``is_feature_gate`` marks a 403 / 404 saying a feature is not enabled for
    this ad account, which the provider reports as ``feature_not_enabled``
    rather than as an API error.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str | None = None,
        is_feature_gate: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.is_feature_gate = is_feature_gate


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _code(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return text if _CODE_PATTERN.fullmatch(text) else None


def _read_object(body: dict[str, Any]) -> tuple[str | None, str | None]:
    """``(message, code)`` out of a JSON object body."""
    error = body.get("error")
    if isinstance(error, dict):
        return _text(error.get("message")), _code(error.get("code"))
    message = _text(error) or _text(body.get("message")) or _text(body.get("detail"))
    return message, _code(body.get("code"))


def _read_body(body_text: str) -> tuple[str | None, str | None]:
    """``(message, code)`` out of a JSON object body; nothing out of any other."""
    try:
        body = json.loads(body_text)
    except (ValueError, RecursionError):  # not JSON, or nested past the limit
        return None, None
    if isinstance(body, dict):
        return _read_object(body)
    return None, None


def _clean(message: str) -> str:
    """Platform text made safe to quote on one line.

    Whitespace runs (newlines included) collapse to one space first, so a
    line break still separates words; every remaining non-printable
    character is then dropped before the scrub and the cut.
    """
    line = one_log_line(message)
    printable = "".join(ch for ch in line if ch.isprintable() or ch == " ")
    scrubbed = scrub_capped(printable, _MAX_TEXT_CHARS + 1, mode=PROSE)
    return truncate_text(scrubbed, _MAX_TEXT_CHARS)


def _is_gate(status: int, message: str | None, code: str | None) -> bool:
    if status not in _GATE_STATUSES:
        return False
    if code is not None and code.endswith(_GATE_CODE_SUFFIXES):
        return True
    lowered = (message or "").lower()
    return any(phrase in lowered for phrase in _GATE_PHRASES)


def _summary(status: int, message: str | None, code: str | None) -> str:
    head = f"HTTP {status}" + (f" ({code})" if code else "")
    cleaned = _clean(message) if message is not None else ""
    return f"{head}: {cleaned or NO_ERROR_DETAIL}"


def error_from_response(
    status: int, body_text: str, *, note: str = ""
) -> ChatGPTAdsAPIError | PlatformAuthError:
    """Classify a non-success answer.

    401, and a 403 that is not a feature gate, are :class:`PlatformAuthError`
    (``token_invalid``): the key is wrong, revoked or lacks access to the
    account. Everything else is a :class:`ChatGPTAdsAPIError`, whose message
    ends with ``note`` when one is given (the client passes
    :data:`MAY_HAVE_BEEN_APPLIED`, or :data:`REPEAT_WITH_IDEMPOTENCY_KEY`
    for a create sent with a key, when a change is answered with 5xx).
    """
    message, code = _read_body(body_text)
    summary = _summary(status, message, code)
    if note:
        summary = f"{summary} {note}"
    gate = _is_gate(status, message, code)
    if status == 401 or (status == 403 and not gate):
        return PlatformAuthError(summary)
    return ChatGPTAdsAPIError(summary, status=status, code=code, is_feature_gate=gate)


__all__ = [
    "MAY_HAVE_BEEN_APPLIED",
    "NO_ERROR_DETAIL",
    "REPEAT_WITH_IDEMPOTENCY_KEY",
    "ChatGPTAdsAPIError",
    "error_from_response",
]
