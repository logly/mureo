"""The result of one configure-UI action, and where it becomes HTTP (#864).

Every setup / provider / demo / BYOD action returns an :class:`ActionResult`.
A result that succeeded carries one of :data:`ACTION_STATUSES` and is sent
as HTTP 200 ``{"status": ..., "detail"?: ...}``. A result that did not is
built with :meth:`ActionResult.refused` (the request was refused: HTTP 400)
or :meth:`ActionResult.failed` (the action was attempted and failed:
HTTP 500), and :func:`send_result` sends it through ``send_error_json`` as
``{"error": <code>, "detail"?: <exception class name or short code>}`` —
the one failure contract of the configure web API (see
``docs/plugin-authoring.md``, "Failure contract").

The multi-step routes (basic setup, clear-all) report one result per step
in one body; :func:`send_steps` sends it as HTTP 200, or as the 500
failure contract with the steps under ``steps`` when every step failed
(#891).

Imports nothing from ``mureo.web`` but ``_helpers``, so any action module
can use it without pulling in the others.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from mureo.web._helpers import send_error_json, send_json

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

#: Every non-error ``status`` an action answers with (HTTP 200).
ACTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "ok",
        "noop",
        "manual_required",
        "skipped",
        "needs_credentials",
        "manual",
        "not_connected",
        "unverifiable",
    }
)

#: The status of a result that did not succeed. Never sent as a 200 body.
ERROR_STATUS: Final = "error"

#: HTTP status of a refused request (bad, missing or unknown input).
REFUSED_HTTP_STATUS: Final = 400

#: HTTP status of an action that was attempted and failed.
FAILED_HTTP_STATUS: Final = 500

#: HTTP status of every non-error result.
SUCCESS_HTTP_STATUS: Final = 200

#: The form of an ``error`` code: snake_case, starting with a letter.
ERROR_CODE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*$")

#: The form of a failure's ``detail``: a code or an exception class name.
DETAIL_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: The 500 code of a basic setup in which every step failed (#891).
BASIC_SETUP_FAILED: Final = "basic_setup_failed"

#: The 500 code of a clear-all in which every step failed (#891).
BASIC_CLEAR_FAILED: Final = "basic_clear_failed"

#: The status of a step that was not attempted (it neither did nor failed).
_SKIPPED_STATUS: Final = "skipped"


@dataclass(frozen=True)
class ActionResult:
    """JSON-friendly result of one configure-UI action.

    ``code`` and ``http_status`` are used only by an error result; build one
    with :meth:`refused` or :meth:`failed` rather than by hand.
    """

    status: str
    detail: str | None = None
    code: str | None = None
    http_status: int = SUCCESS_HTTP_STATUS

    def __post_init__(self) -> None:
        if self.status == ERROR_STATUS:
            if self.code is None or not ERROR_CODE_PATTERN.fullmatch(self.code):
                raise ValueError(f"an error result needs a snake_case code: {self!r}")
            if self.detail is not None and not DETAIL_PATTERN.fullmatch(self.detail):
                raise ValueError(f"an error detail is a code or class name: {self!r}")
            if self.http_status not in (REFUSED_HTTP_STATUS, FAILED_HTTP_STATUS):
                raise ValueError(f"an error result needs 400 or 500: {self!r}")
            return
        if self.status not in ACTION_STATUSES:
            raise ValueError(f"unknown action status {self.status!r}")
        if self.code is not None or self.http_status != SUCCESS_HTTP_STATUS:
            raise ValueError(f"code / http_status are for errors only: {self!r}")

    @classmethod
    def refused(cls, code: str, detail: str | None = None) -> ActionResult:
        """The request was refused (HTTP 400)."""
        return cls(
            status=ERROR_STATUS,
            detail=detail,
            code=code,
            http_status=REFUSED_HTTP_STATUS,
        )

    @classmethod
    def failed(cls, code: str, detail: str | None = None) -> ActionResult:
        """The action was attempted and failed (HTTP 500)."""
        return cls(
            status=ERROR_STATUS,
            detail=detail,
            code=code,
            http_status=FAILED_HTTP_STATUS,
        )

    def as_dict(self) -> dict[str, Any]:
        """The result as one step of a multi-step envelope.

        A single-action route sends the result with :func:`send_result`
        instead; this form is for the envelopes that report several steps
        in one body (basic setup, clear-all; see :func:`send_steps`), where
        an error step keeps its ``status`` next to the contract's
        ``error`` / ``detail``.
        """
        out: dict[str, Any] = {"status": self.status}
        if self.code is not None:
            out["error"] = self.code
        if self.detail is not None:
            out["detail"] = self.detail
        return out


class SuccessBody(Protocol):
    """A success result with a richer body than ``ActionResult`` carries.

    ``ByodResult`` / ``DemoInitResult`` / ``DemoListResult`` / ``PickResult``
    succeed with their own fields (platforms, scenarios, a path) and fail
    with an ``ActionResult``, so :func:`send_result` takes either.
    """

    def as_dict(self) -> dict[str, Any]: ...


def refuse_error_status(result: object, status: object) -> None:
    """Raise when a success-only result carries ``status="error"``.

    A failure is an :class:`ActionResult` (``refused`` / ``failed``): a
    success result type calls this from its ``__post_init__``, and
    :func:`send_result` calls it on every 200 body.
    """
    if status == ERROR_STATUS:
        raise ValueError(f"a failure is an ActionResult, not {result!r}")


def returncode_detail(action: str, returncode: int) -> str:
    """The ``detail`` of a subprocess that exited non-zero.

    ``<action>_returncode_<n>``, or ``<action>_signal_<n>`` for the negative
    return code of a process killed by signal ``n`` (a detail has no ``-``).
    """
    if returncode < 0:
        return f"{action}_signal_{-returncode}"
    return f"{action}_returncode_{returncode}"


def send_result(
    handler: BaseHTTPRequestHandler,
    result: ActionResult | SuccessBody | Mapping[str, Any],
) -> None:
    """Send ``result``: 200 with its body, or the failure contract.

    A success body (a ``SuccessBody`` or a plain mapping) that carries
    ``status="error"`` is a programming error and raises ``ValueError``
    before anything is sent: a failure must be an :class:`ActionResult`.
    """
    if isinstance(result, ActionResult) and result.status == ERROR_STATUS:
        # ``__post_init__`` guarantees an error result carries its code.
        send_error_json(
            handler,
            result.http_status,
            str(result.code),
            detail=result.detail,
        )
        return
    body = dict(result) if isinstance(result, Mapping) else result.as_dict()
    refuse_error_status(result, body.get("status"))
    send_json(handler, body)


def _steps(envelope: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """The steps of a multi-step envelope, as ``(name, step)``.

    A mapping with a ``status`` is a step; a mapping without one
    (``providers``) holds one step per key, so it is flattened one level,
    and there too only a mapping with a ``status`` is a step. The page
    reads an envelope by the same rule (``stepFailures`` in ``app.js``).
    """
    steps: list[tuple[str, Mapping[str, Any]]] = []
    for name, value in envelope.items():
        if not isinstance(value, Mapping):
            continue
        if "status" in value:
            steps.append((name, value))
            continue
        steps.extend(
            (inner, step)
            for inner, step in value.items()
            if isinstance(step, Mapping) and "status" in step
        )
    return steps


def every_step_failed(envelope: Mapping[str, Any]) -> bool:
    """True when a step failed and no step did anything else (#891).

    A ``skipped`` step was not attempted, so it neither rescues nor makes
    the failure; any other non-error status (``ok``, ``noop``,
    ``manual_required``, ...) is a step that went right. No steps at all is
    not a failure.
    """
    statuses = [step.get("status") for _name, step in _steps(envelope)]
    return ERROR_STATUS in statuses and all(
        status in (ERROR_STATUS, _SKIPPED_STATUS) for status in statuses
    )


def send_steps(
    handler: BaseHTTPRequestHandler,
    envelope: Mapping[str, Any],
    failure_code: str,
) -> None:
    """Send a multi-step envelope: 200 as is, or 500 when every step failed.

    The 500 is the failure contract with ``failure_code`` and the envelope
    under the ``steps`` context key, so the UI can still name each step.
    """
    if not every_step_failed(envelope):
        send_json(handler, dict(envelope))
        return
    failed = ", ".join(
        f"{name}={step.get('error')}"
        for name, step in _steps(envelope)
        if step.get("status") == ERROR_STATUS
    )
    logger.warning("%s: every step failed: %s", failure_code, failed)
    send_error_json(
        handler, FAILED_HTTP_STATUS, failure_code, extra={"steps": dict(envelope)}
    )


__all__ = [
    "ACTION_STATUSES",
    "BASIC_CLEAR_FAILED",
    "BASIC_SETUP_FAILED",
    "DETAIL_PATTERN",
    "ERROR_CODE_PATTERN",
    "ERROR_STATUS",
    "FAILED_HTTP_STATUS",
    "REFUSED_HTTP_STATUS",
    "SUCCESS_HTTP_STATUS",
    "ActionResult",
    "SuccessBody",
    "every_step_failed",
    "refuse_error_status",
    "returncode_detail",
    "send_result",
    "send_steps",
]
