"""MCP handler common helpers.

Provides utility functions and API error handling decorators
shared by Google Ads / Meta Ads handlers.

:func:`resolve_workspace_path` lives here rather than in whichever handler
happened to need it first: it is the workspace **sandbox boundary** every
STATE.json / STRATEGY.md tool relies on, so a second copy — or a sibling
module reaching into another's privates to borrow it — is a place for the
check to drift. One definition, imported by name.
"""

from __future__ import annotations

import contextvars
import dataclasses
import functools
import inspect
import json
import logging
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

from mcp.types import TextContent

# Read through the module (not bound to a name here) so a monkeypatched
# ``get_runtime_context`` is honoured at call time.
from mureo.core import runtime_context
from mureo.core.auth_failure import (
    AUTH_CAUSE_NO_CREDENTIALS,
    auth_failure_payload,
    classify_auth_exception,
)

# The envelope READER lives in ``mureo.core`` so the layers below this one
# (rollback, the Amazon bridge) can use it without importing the server
# (#863). Re-exported here, the same objects, next to the writer below.
from mureo.core.tool_failure import API_ERROR_CODE as API_ERROR_CODE
from mureo.core.tool_failure import API_ERROR_PREFIX as API_ERROR_PREFIX
from mureo.core.tool_failure import FAILURE_STATUSES as FAILURE_STATUSES
from mureo.core.tool_failure import Failure as Failure
from mureo.core.tool_failure import exception_text as exception_text
from mureo.core.tool_failure import failure_of as failure_of
from mureo.core.tool_failure import is_auth_error_result as is_auth_error_result
from mureo.core.tool_failure import is_error_result as is_error_result

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
        except Exception:  # noqa: BLE001 — cleanup must not mask the handler result
            logger.debug("client cleanup failed", exc_info=True)


def _require(arguments: dict[str, Any], key: str) -> Any:
    """Retrieve a required parameter. Raises ValueError if missing or empty.

    The two cases get distinct messages (#534): "not specified" is misleading
    for a parameter that WAS specified as ``""``, and it sends the caller
    looking for a missing argument instead of an empty one. Both still fail
    before any write.
    """
    value = arguments.get(key)
    if value is None:
        raise ValueError(f"Required parameter {key} is not specified")
    if value == "":
        raise ValueError(f"Required parameter {key} must not be empty")
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


def resolve_workspace_path(
    arguments: dict[str, Any], default_name: str, *, store_attr: str | None = None
) -> Path:
    """Resolve a user-supplied path, refusing anything outside the workspace.

    Resolution rules:

    - ``path`` argument missing or empty (``None`` or ``""``) → the
      workspace-derived default (``getattr(store, store_attr)`` when
      available, otherwise ``workspace / default_name``). Picks up
      any alternate :class:`StateStore` wired via the
      ``mureo.runtime_context_factory`` entry-point group without the
      caller having to know about it. Note: the empty-string case
      used to dispatch to ``Path(".")`` under the old ``_opt``-based
      implementation; the new behaviour is intentional and safer.
    - ``path`` argument present → resolved relative to the workspace
      (not the process CWD — they coincide in the default file-backed
      configuration but may diverge under an alternate runtime),
      then security-checked: ``Path.resolve()`` follows symlinks, so a
      file inside the workspace that symlinks to ``/etc/passwd``
      resolves to the target and is correctly refused.
    """
    store = runtime_context.get_runtime_context().state_store
    workspace = getattr(store, "workspace", Path.cwd()).resolve()
    raw = arguments.get("path")
    if not raw:
        if store_attr is not None:
            attr = getattr(store, store_attr, None)
            if attr is not None:
                # Backend-owned path: trusted output of an installed
                # ``StateStore`` (the entry-point factory is host code,
                # not an untrusted MCP caller). Skip the workspace
                # boundary check so a backend can legitimately point
                # outside ``workspace`` if its design requires it.
                return Path(attr)
        return workspace / default_name

    candidate = Path(raw)
    resolved = (
        workspace / candidate if not candidate.is_absolute() else candidate
    ).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to read/write outside workspace: "
            f"{resolved} is not inside {workspace}"
        ) from exc
    return resolved


def jsonable(value: Any) -> Any:
    """Recursively convert a result model into JSON-native data.

    Frozen dataclasses become dicts, enums become their ``.value``, and
    tuples become lists — so the mixed ``tuple[dataclass, ...]`` /
    nested-tuple shapes the models use serialize deterministically without
    leaking ``repr`` artifacts.
    """
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    return value


def read_kept_as_empty(rendered: dict[str, Any]) -> dict[str, Any]:
    """Return a rendered STATE.json with a kept non-list section read as empty.

    A hand-written ``action_log`` / ``decisions`` that is not a list is kept
    in the file and rendered back exactly as found (#882), so a reader that
    counts or filters the section would fail on it. Here it reads the way an
    empty section renders: ``action_log`` as ``[]``, ``decisions`` absent.
    The file is untouched, and recording into it stays refused until it is
    fixed by hand.
    """
    return {
        key: [] if key == "action_log" and not isinstance(value, list) else value
        for key, value in rendered.items()
        if key != "decisions" or isinstance(value, list)
    }


def _json_result(data: Any) -> list[TextContent]:
    """Convert a result to a list of TextContent containing a JSON string."""
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]


def _auth_error_result(cause: str, detail: str) -> list[TextContent]:
    """Return the machine-readable auth-failure envelope (#580).

    Every platform's auth failure leaves mureo through here or through
    :func:`api_error_handler`, so one shape covers all of them. See
    :mod:`mureo.core.auth_failure` for why the shape is a ``status`` field
    rather than a sentence.
    """
    return _json_result(auth_failure_payload(cause, detail))


def _failure_result(
    code: str, detail: str, /, *, refused: bool = False, **fields: Any
) -> list[TextContent]:
    """The one JSON envelope for a handler that returns a failure instead of raising (#862).

    ``status`` is ``"refused"`` when mureo declined before touching the platform
    and ``"error"`` otherwise; ``code`` is a stable snake_case identifier an
    agent can branch on, ``detail`` the operator-readable text. ``fields`` ride
    along beside the envelope (``findings``, ``plan`` ...) and never override it.
    :func:`failure_of` is the reader; keep the two in step.
    """
    payload: dict[str, Any] = {
        **fields,
        "status": "refused" if refused else "error",
        "error": code,
        "detail": detail,
    }
    return _json_result(payload)


def _no_creds_result(msg: str) -> list[TextContent]:
    """Return a credentials-not-found error.

    ``msg`` survives verbatim as the payload's ``detail``, so the operator
    still reads which env var to set — but it is a field of an
    ``auth_error`` payload now, not the whole body, so a report skill can
    tell "could not read this platform" from "this platform was quiet"
    (#580).
    """
    return _auth_error_result(AUTH_CAUSE_NO_CREDENTIALS, msg)


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
        except Exception as exc:  # noqa: BLE001 — becomes the error result
            # No traceback: it would print the exception's own text and its
            # ``__cause__`` chain, which for a platform failure carry the
            # request metadata (#603). The curated text is what the caller
            # gets back.
            logger.error(
                "%s failed (%s): %s",
                func.__name__,
                type(exc).__name__,
                exception_text(exc),
            )
            # An auth failure is a different outcome, not a worse error: it
            # means this platform produced NO data, so a report built on the
            # platforms that did answer is partial. Flattening it into the
            # same untyped string as a quota error is what let an expired
            # token read as a quiet account (#580).
            # Curated, never ``str(exc)``: see :func:`exception_text`.
            detail = exception_text(exc)
            cause = classify_auth_exception(exc)
            if cause is not None:
                return _auth_error_result(cause, detail)
            return [TextContent(type="text", text=f"{API_ERROR_PREFIX} {detail}")]
        finally:
            bucket = _active_clients.get() or []
            _active_clients.reset(token)
            await _close_clients(bucket)

    return wrapper
