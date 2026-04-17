"""MCP handlers for the ``rollback.*`` tool family.

``rollback.plan.get`` — inspect the reversal plan for one action_log entry.
``rollback.apply``    — execute that plan, re-entering the same MCP
dispatch path used for forward actions.

The dispatcher used by ``rollback.apply`` is resolved lazily via
:func:`_get_dispatcher` so that ``mureo.mcp.server`` and this module
do not form an import cycle — ``server.handle_call_tool`` imports
this module transitively through ``tools_rollback`` at module load
time, and this module imports ``handle_call_tool`` only at call
time. Tests monkey-patch ``_get_dispatcher`` to inject a fake.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.context.errors import ContextFileError
from mureo.context.state import read_state_file
from mureo.mcp._helpers import _json_result, _opt, _require
from mureo.rollback import (
    RollbackExecutionError,
    execute_rollback,
    plan_rollback,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import TextContent


logger = logging.getLogger(__name__)


def _get_dispatcher() -> Callable[[str, dict[str, Any]], Awaitable[list[Any]]]:
    """Return the MCP call-tool dispatcher.

    Lazy import breaks the ``server → tools_rollback → _handlers_rollback
    → server`` cycle. Tests replace this via ``monkeypatch``.
    """
    from mureo.mcp.server import handle_call_tool

    return handle_call_tool


def _resolve_state_file(arguments: dict[str, Any]) -> Path:
    """Resolve ``state_file`` against the MCP server's working directory.

    The MCP caller is untrusted (a prompt-injected agent could point at
    an attacker-crafted STATE.json elsewhere on the filesystem). We
    require the argument to resolve to a path inside the current working
    directory so the agent cannot smuggle in a rogue action_log.
    """
    raw = _opt(arguments, "state_file", "STATE.json")
    candidate = Path(raw)
    cwd = Path.cwd().resolve()
    resolved = (cwd / candidate if not candidate.is_absolute() else candidate).resolve()
    try:
        resolved.relative_to(cwd)
    except ValueError as exc:
        raise ValueError(
            f"state_file must resolve inside the current working directory "
            f"({cwd}); got {resolved}."
        ) from exc
    return resolved


def _is_truthy_confirm(value: Any) -> bool:
    """Strict confirm check: only literal ``True`` counts.

    Rejects ``1``, ``"true"``, non-empty lists, etc. Defense against a
    client that bypasses the MCP schema's boolean type.
    """
    return value is True


async def handle_plan_get(arguments: dict[str, Any]) -> list[TextContent]:
    """Return the :class:`RollbackPlan` for ``action_log[index]`` as JSON."""
    try:
        state_file = _resolve_state_file(arguments)
    except ValueError as exc:
        return _json_result({"plan": None, "reason": str(exc)})
    index = int(_require(arguments, "index"))

    if not state_file.exists():
        return _json_result(
            {"plan": None, "reason": f"STATE.json not found: {state_file}"}
        )
    try:
        doc = read_state_file(state_file)
    except ContextFileError as exc:
        return _json_result({"plan": None, "reason": str(exc)})

    if index < 0 or index >= len(doc.action_log):
        return _json_result(
            {
                "plan": None,
                "reason": (
                    f"Index {index} is out of range "
                    f"(action_log has {len(doc.action_log)} entries)."
                ),
            }
        )

    entry = doc.action_log[index]
    plan = plan_rollback(entry)
    if plan is None:
        return _json_result(
            {
                "index": index,
                "plan": None,
                "reason": f"Entry #{index} ({entry.action}) is read-only.",
            }
        )
    return _json_result(
        {
            "index": index,
            "source_timestamp": plan.source_timestamp,
            "source_action": plan.source_action,
            "platform": plan.platform,
            "status": plan.status.value,
            "operation": plan.operation,
            "params": plan.params,
            "caveats": list(plan.caveats),
            "description": plan.description,
            "notes": plan.notes,
        }
    )


async def handle_apply(arguments: dict[str, Any]) -> list[TextContent]:
    """Execute the rollback plan for ``action_log[index]``.

    Pre-dispatch refusals (missing confirm, out-of-range index,
    unsupported plan, already-rolled-back) return
    ``{"status": "refused", "error": ...}``. Downstream API errors
    propagate as ``{"status": "error", "error": ...}``.
    """
    try:
        state_file = _resolve_state_file(arguments)
    except ValueError as exc:
        return _json_result({"status": "refused", "error": str(exc)})
    index = int(_require(arguments, "index"))
    confirm = _is_truthy_confirm(_require(arguments, "confirm"))

    try:
        result = await execute_rollback(
            state_file=state_file,
            index=index,
            confirm=confirm,
            dispatcher=_get_dispatcher(),
        )
    except RollbackExecutionError as exc:
        return _json_result({"status": "refused", "error": str(exc)})
    except Exception as exc:
        # Log the full exception (including type and message) server-side
        # only; the MCP response deliberately returns a generic message so
        # raw SDK errors cannot leak tokens or account identifiers to the
        # model context.
        logger.exception("rollback.apply dispatch failed")
        return _json_result(
            {
                "status": "error",
                "error": (
                    "The reversal call was dispatched but the downstream "
                    f"tool failed ({type(exc).__name__}). "
                    "See server logs for details."
                ),
            }
        )

    return _json_result(result)


__all__ = ["handle_apply", "handle_plan_get"]
