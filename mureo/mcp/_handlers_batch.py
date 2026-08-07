"""MCP handlers for the ``mureo_batch_*`` tool family (#549).

Three calls that declare the boundary of a bulk change: open one, close one,
ask which is open. Everything in between joins the batch automatically —
see :mod:`mureo.context.batch` for why the stamp is applied at the
``append_action_log`` choke point rather than through tool arguments.

Path resolution uses the shared :func:`mureo.mcp._helpers.resolve_workspace_path`.
It is a security boundary — an MCP caller must not be able to point these at a
STATE.json outside the active workspace — and a second copy of that check is a
place for the two to drift apart silently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.context.batch import (
    BatchError,
    active_batch,
    batch_members,
    batch_platforms,
    stale_batch_warning,
)
from mureo.context.state import begin_batch, end_batch, read_state_file
from mureo.mcp._helpers import _json_result, _require, resolve_workspace_path

if TYPE_CHECKING:
    from mcp.types import TextContent

    from mureo.context.models import BatchRecord


def _record_to_dict(record: BatchRecord) -> dict[str, Any]:
    """Serialize a batch record; ``ended_at`` is absent while it is open."""
    payload: dict[str, Any] = {
        "batch_id": record.batch_id,
        "label": record.label,
        "started_at": record.started_at,
    }
    if record.ended_at is not None:
        payload["ended_at"] = record.ended_at
    return payload


async def handle_batch_begin(arguments: dict[str, Any]) -> list[TextContent]:
    """Open a batch. Refuses when one is already open."""
    label = _require(arguments, "label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label must be a non-empty string")
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    try:
        record = begin_batch(path, label=label)
    except BatchError as exc:
        return _json_result({"status": "refused", "error": str(exc)})
    return _json_result({"status": "open", **_record_to_dict(record)})


async def handle_batch_end(arguments: dict[str, Any]) -> list[TextContent]:
    """Close the open batch and return exactly what it collected.

    The member indices are the point of the response: they are the checklist
    that replaces reconstructing a change set from memory, and they are what
    ``rollback_plan_get`` will report on next. Closing is final — no later
    append can join a closed batch (see
    :func:`mureo.context.batch.ensure_joinable`), so the ``member_count``
    returned here stays true.
    """
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    try:
        record, indices = end_batch(path)
    except BatchError as exc:
        return _json_result({"status": "refused", "error": str(exc)})
    doc = read_state_file(path)
    return _json_result(
        {
            "status": "closed",
            **_record_to_dict(record),
            "member_count": len(indices),
            "member_indices": list(indices),
            "platforms": list(batch_platforms(doc, record.batch_id)),
        }
    )


async def handle_batch_status(arguments: dict[str, Any]) -> list[TextContent]:
    """Report the open batch (or ``null``) and how much it has collected.

    Carries the staleness ``warning`` when one has been open too long — the
    pull half of the signal, for a caller who does think to ask. The push half
    (a reminder appended to mutating tool results) is what reaches the caller
    who does not; see :func:`maybe_build_batch_reminder`.
    """
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    doc = read_state_file(path)
    record = active_batch(doc)
    if record is None:
        return _json_result({"active_batch": None, "member_count": 0, "warning": None})
    members = batch_members(doc, record.batch_id)
    return _json_result(
        {
            "active_batch": _record_to_dict(record),
            "member_count": len(members),
            "member_indices": [index for index, _ in members],
            "platforms": list(batch_platforms(doc, record.batch_id)),
            "warning": stale_batch_warning(record),
        }
    )


def maybe_build_batch_reminder() -> str | None:
    """Text to append to a mutating tool result when a batch is stale, else None.

    Best-effort and read-only: any failure (no STATE.json, unreadable, corrupt)
    returns ``None`` and the tool result is untouched. Opt out with
    ``MUREO_DISABLE_BATCH_REMINDER=1`` (exact string, matching the established
    ``MUREO_DISABLE_*`` pattern).
    """
    import os

    if os.environ.get("MUREO_DISABLE_BATCH_REMINDER") == "1":
        return None
    try:
        path = resolve_workspace_path({}, "STATE.json", store_attr="state_path")
        if not path.is_file():
            return None
        return stale_batch_warning(active_batch(read_state_file(path)))
    except Exception:  # noqa: BLE001 — a reminder must never break a tool call
        return None


__all__ = [
    "handle_batch_begin",
    "handle_batch_end",
    "handle_batch_status",
    "maybe_build_batch_reminder",
]
