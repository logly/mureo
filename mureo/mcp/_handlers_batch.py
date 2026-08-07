"""MCP handlers for the ``mureo_batch_*`` tool family (#549).

Three calls that declare the boundary of a bulk change: open one, close one,
ask which is open. Everything in between joins the batch automatically —
see :mod:`mureo.context.batch` for why the stamp is applied at the
``append_action_log`` choke point rather than through tool arguments.

Path resolution reuses ``_handlers_mureo_context._resolve_path`` rather than
re-implementing it. It is a security boundary — an MCP caller must not be able
to point these at a STATE.json outside the active workspace — and a second
copy of that check is a place for the two to drift apart silently, which is
the one failure mode a sandbox cannot afford.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.context.batch import (
    BatchError,
    active_batch,
    batch_members,
    batch_platforms,
)
from mureo.context.state import begin_batch, end_batch, read_state_file
from mureo.mcp._handlers_mureo_context import _resolve_path
from mureo.mcp._helpers import _json_result, _require

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
    path = _resolve_path(arguments, "STATE.json", store_attr="state_path")
    try:
        record = begin_batch(path, label=label)
    except BatchError as exc:
        return _json_result({"status": "refused", "error": str(exc)})
    return _json_result({"status": "open", **_record_to_dict(record)})


async def handle_batch_end(arguments: dict[str, Any]) -> list[TextContent]:
    """Close the open batch and return exactly what it collected.

    The member indices are the point of the response: they are the checklist
    that replaces reconstructing a change set from memory, and they are what
    ``rollback_plan_get`` will report on next.
    """
    path = _resolve_path(arguments, "STATE.json", store_attr="state_path")
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
    """Report the open batch (or ``null``) and how much it has collected."""
    path = _resolve_path(arguments, "STATE.json", store_attr="state_path")
    doc = read_state_file(path)
    record = active_batch(doc)
    if record is None:
        return _json_result({"active_batch": None, "member_count": 0})
    members = batch_members(doc, record.batch_id)
    return _json_result(
        {
            "active_batch": _record_to_dict(record),
            "member_count": len(members),
            "member_indices": [index for index, _ in members],
            "platforms": list(batch_platforms(doc, record.batch_id)),
        }
    )


__all__ = ["handle_batch_begin", "handle_batch_end", "handle_batch_status"]
