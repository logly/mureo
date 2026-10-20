"""The failure-envelope reader for MCP tool results (#862, #863).

A tool call that fails without raising leaves mureo in one of three shapes:

- the ``API error: <detail>`` text that ``api_error_handler`` stamps on a
  caught exception (:data:`API_ERROR_PREFIX`);
- the :data:`~mureo.core.auth_failure.AUTH_ERROR_STATUS` JSON payload of a
  missing or rejected credential (:mod:`mureo.core.auth_failure`);
- the ``{"status": "refused" | "error", "error": <code>, "detail": <text>}``
  JSON envelope (:data:`FAILURE_STATUSES`).

:func:`failure_of` is the single reader of all three; :func:`is_error_result`
and :func:`is_auth_error_result` are its yes/no forms. They only read
``.text`` off the result items, so nothing here needs the MCP SDK and the
layers below :mod:`mureo.mcp` (rollback, the Amazon bridge) can ask "did this
call fail?" without importing the server.

The writer stays in :mod:`mureo.mcp._helpers` (``_failure_result``,
``_auth_error_result``, ``_json_result``, ``api_error_handler``) because it
builds MCP ``TextContent``; that module re-exports every name defined here,
so the two halves keep one vocabulary.
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple

from mureo.core.auth_failure import AUTH_ERROR_STATUS, is_auth_failure_payload

#: The ``status`` words of the JSON failure envelope :func:`_failure_result`
#: writes (#862). ``"refused"``: mureo declined before touching the platform
#: (a preflight, a batch or rollback precondition). ``"error"``: the call
#: could not be evaluated, or the operation it attempted failed.
FAILURE_STATUSES: frozenset[str] = frozenset({"refused", "error"})


# The single prefix ``api_error_handler`` stamps onto a caught-exception
# result. Detectors key off this exact string to recognise "the API call
# failed but was returned as content instead of raised" — kept with the
# reader, as the one source of truth.
API_ERROR_PREFIX = "API error:"

#: The :class:`Failure` ``code`` :func:`failure_of` gives the ``API error:``
#: text envelope, which carries no code of its own.
API_ERROR_CODE = "api_error"


def is_auth_error_result(result: list[Any] | None) -> bool:
    """True if ``result`` is the :data:`AUTH_ERROR_STATUS` envelope (#580)."""
    if not result:
        return False
    text = getattr(result[0], "text", "")
    if not isinstance(text, str) or AUTH_ERROR_STATUS not in text:
        return False
    try:
        return is_auth_failure_payload(json.loads(text))
    except ValueError:
        return False


class Failure(NamedTuple):
    """What :func:`failure_of` read out of a failure envelope."""

    #: ``"error"`` | ``"refused"`` | ``"auth_error"``.
    status: str
    #: The envelope's ``error``; the ``auth_cause`` for an auth failure;
    #: :data:`API_ERROR_CODE` for the ``API error:`` text envelope.
    code: str
    #: The envelope's ``detail``; the full text for the text envelope.
    detail: str


def failure_of(result: list[Any] | None) -> Failure | None:
    """Read the failure envelope out of ``result``, or ``None`` for a success.

    The one spelling of "this result is a failure" (#862). Three envelopes
    count, all written by :mod:`mureo.mcp._helpers`: the ``API error:`` text of
    :func:`api_error_handler`, the :data:`AUTH_ERROR_STATUS` JSON of
    :func:`_auth_error_result`, and the ``refused`` / ``error`` JSON of
    :func:`_failure_result`. Anything else — plain text, a list, a success
    payload whose ``status`` is a state word (``"ok"``, ``"open"``,
    ``"capability_not_available"``) — is not a failure. Never raises.
    """
    if not result:
        return None
    text = getattr(result[0], "text", "")
    if not isinstance(text, str):
        return None
    if text.startswith(API_ERROR_PREFIX):
        return Failure("error", API_ERROR_CODE, text)
    # Cheap pre-check: every JSON failure envelope is an object that carries
    # an ``error`` key or is the auth envelope, so a success body without
    # either is never parsed.
    if not text.lstrip().startswith("{"):
        return None
    if '"error"' not in text and AUTH_ERROR_STATUS not in text:
        return None
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):  # malformed, or nested past the limit
        return None
    if not isinstance(payload, dict):
        return None
    if is_auth_failure_payload(payload):
        return Failure(
            AUTH_ERROR_STATUS,
            str(payload.get("auth_cause") or ""),
            str(payload.get("detail") or ""),
        )
    status, code = payload.get("status"), payload.get("error")
    # ``isinstance`` first: an unhashable ``status`` must not reach ``in``.
    if not isinstance(status, str) or status not in FAILURE_STATUSES:
        return None
    if not isinstance(code, str):
        return None
    return Failure(status, code, str(payload.get("detail") or ""))


def is_error_result(result: list[Any] | None) -> bool:
    """True if ``result`` is an :func:`api_error_handler` error envelope.

    An ``api_error_handler``-wrapped mutation turns an API-level failure into
    an ``"API error: ..."`` TextContent instead of raising. Detecting it lets
    the dispatch paths skip recording an ``action_log`` entry for a mutation
    that did not actually change platform state. Shared by the native
    (:mod:`mureo.mcp.native_reversal`) and plugin (:mod:`mureo.mcp.server`)
    promotion paths so both skip the identical envelope.

    The auth-failure envelope counts too: a mutation refused for a missing
    or rejected credential never reached the platform either, and recording
    it would put a change that did not happen into ``action_log`` — with an
    ``observation_due`` and a reversal plan for it (#580).

    So does the ``refused`` / ``error`` JSON envelope of
    :func:`_failure_result`: a handler that returns it changed nothing
    either (#862). :func:`failure_of` is the one reader of all three.
    """
    return failure_of(result) is not None
