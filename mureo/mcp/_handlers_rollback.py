"""MCP handlers for the ``rollback.*`` tool family.

``rollback_plan_get`` — inspect the reversal plan for one action_log entry
(``index``), or for a whole declared batch (``batch_id``, #549). The batch
form reports every member's verdict and the overall / per-platform coverage,
so partial reversibility is known before anything is applied.
``rollback_apply``    — execute that plan, re-entering the same MCP
dispatch path used for forward actions. Deliberately still one ``index`` per
call: applying a batch is a loop over the plan's ``apply_order``, so each
reversal keeps its own result instead of being folded into one summary status
that would have to gloss over partial failure.

The dispatcher used by ``rollback_apply`` is resolved lazily via
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
from mureo.mcp._helpers import _json_result, _require
from mureo.rollback import (
    RollbackExecutionError,
    execute_rollback,
    plan_batch_rollback,
    plan_rollback,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import TextContent

    from mureo.rollback import BatchMemberPlan, BatchRollbackPlan


logger = logging.getLogger(__name__)


def _get_dispatcher() -> Callable[[str, dict[str, Any]], Awaitable[list[Any]]]:
    """Return the MCP call-tool dispatcher.

    Lazy import breaks the ``server → tools_rollback → _handlers_rollback
    → server`` cycle. Tests replace this via ``monkeypatch``.
    """
    from mureo.mcp.server import handle_call_tool

    return handle_call_tool


def _resolve_state_file(arguments: dict[str, Any]) -> Path:
    """Resolve ``state_file`` against the active workspace.

    The active workspace is
    ``getattr(get_runtime_context().state_store, "workspace", Path.cwd())``
    — CWD in the default file-backed configuration, or whatever
    filesystem-backed :class:`StateStore` an alternate backend
    registers via the ``mureo.runtime_context_factory`` entry-point
    group.

    The MCP caller is untrusted (a prompt-injected agent could point
    at an attacker-crafted STATE.json elsewhere on the filesystem).
    We require the argument to resolve to a path inside the workspace
    so the agent cannot smuggle in a rogue action_log. ``Path.resolve()``
    follows symlinks, so a file inside the workspace that symlinks to
    ``/etc/passwd`` resolves to the target and is correctly refused.
    """
    from mureo.core.runtime_context import get_runtime_context

    store = get_runtime_context().state_store
    workspace = getattr(store, "workspace", Path.cwd()).resolve()
    raw = arguments.get("state_file")
    if not raw:
        attr = getattr(store, "state_path", None)
        if attr is not None:
            # Backend-owned path: trusted output of an installed
            # ``StateStore`` (the entry-point factory is host code,
            # not an untrusted MCP caller). Skip the workspace
            # boundary check so a backend can legitimately point
            # outside ``workspace`` if its design requires it.
            # ``.resolve()`` normalises relative backend paths so
            # downstream ``execute_rollback`` is not surprised by a
            # CWD-relative interpretation later.
            return Path(attr).resolve()
        return workspace / "STATE.json"
    candidate = Path(raw)
    resolved = (
        workspace / candidate if not candidate.is_absolute() else candidate
    ).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(
            f"state_file must resolve inside the active workspace "
            f"({workspace}); got {resolved}."
        ) from exc
    return resolved


def _is_truthy_confirm(value: Any) -> bool:
    """Strict confirm check: only literal ``True`` counts.

    Rejects ``1``, ``"true"``, non-empty lists, etc. Defense against a
    client that bypasses the MCP schema's boolean type.
    """
    return value is True


def _batch_plan_payload(plan: BatchRollbackPlan) -> dict[str, Any]:
    """Serialize a whole-batch plan, gaps and all.

    Every member appears — including the ones mureo cannot reverse, each with
    the reason. A response that listed only the reversible members would read
    as a complete revert and is exactly the failure #549 exists to prevent.
    """
    return {
        "batch_id": plan.batch_id,
        "label": plan.label,
        "coverage": plan.coverage.value,
        "counts": plan.counts,
        "platform_coverage": {
            platform: coverage.value for platform, coverage in plan.platform_coverage
        },
        # Reverse-chronological: feed these to rollback_apply in this order.
        "apply_order": list(plan.apply_order),
        "members": [_batch_member_payload(member) for member in plan.members],
    }


def _batch_member_payload(member: BatchMemberPlan) -> dict[str, Any]:
    """Serialize one batch member: its verdict first, its plan second."""
    payload: dict[str, Any] = {
        "index": member.index,
        "timestamp": member.timestamp,
        "action": member.action,
        "platform": member.platform,
        "reversibility": member.status.value,
        "reason": member.reason,
        "plan_status": None,
        "operation": None,
        "params": None,
        "caveats": [],
    }
    if member.plan is not None:
        payload["plan_status"] = member.plan.status.value
        payload["operation"] = member.plan.operation
        payload["params"] = member.plan.params
        payload["caveats"] = list(member.plan.caveats)
    return payload


def _selector(arguments: dict[str, Any]) -> tuple[str, Any]:
    """Return ``("index", int)`` or ``("batch_id", str)``.

    The MCP schema declares the exclusivity, but the schema is not the only
    caller: rejecting both-or-neither here keeps a direct handler invocation
    from silently planning something the operator did not ask for.
    """
    raw_index = arguments.get("index")
    raw_batch = arguments.get("batch_id")
    has_index = raw_index is not None
    has_batch = isinstance(raw_batch, str) and bool(raw_batch.strip())
    if has_index == has_batch:
        raise ValueError(
            "Provide exactly one of 'index' (a single action_log entry) or "
            "'batch_id' (a whole batch)."
        )
    if raw_index is not None:
        return ("index", int(raw_index))
    return ("batch_id", str(raw_batch).strip())


async def handle_plan_get(arguments: dict[str, Any]) -> list[TextContent]:
    """Return the reversal plan for one entry, or for a whole batch, as JSON."""
    try:
        state_file = _resolve_state_file(arguments)
        kind, selector = _selector(arguments)
    except ValueError as exc:
        return _json_result({"plan": None, "reason": str(exc)})

    if not state_file.exists():
        return _json_result(
            {"plan": None, "reason": f"STATE.json not found: {state_file}"}
        )
    try:
        doc = read_state_file(state_file)
    except ContextFileError as exc:
        return _json_result({"plan": None, "reason": str(exc)})

    if kind == "batch_id":
        return _json_result(_batch_plan_payload(plan_batch_rollback(doc, selector)))

    index = selector
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
        logger.exception("rollback_apply dispatch failed")
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
