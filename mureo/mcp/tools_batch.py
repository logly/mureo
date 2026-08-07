"""Batch MCP tool definitions and handler mapping (#549).

Three tools that make a bulk change one named, reviewable unit:

- ``mureo_batch_begin``  — declare the start of a change set.
- ``mureo_batch_end``    — close it and get the exact member list back.
- ``mureo_batch_status`` — ask which batch, if any, is currently collecting.

Platform-agnostic on purpose. Membership is stamped where every recording path
already converges (``append_action_log``), so a native Google/Meta mutation, a
hosted-connector mutation an agent records by hand, and a bridged / plugin tool
call all join the same batch without any of them knowing it exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.mcp._handlers_batch import (
    handle_batch_begin,
    handle_batch_end,
    handle_batch_status,
)

if TYPE_CHECKING:
    from mcp.types import TextContent


_PATH_PROPERTY = {
    "type": "string",
    "description": (
        "Optional path to STATE.json. Defaults to STATE.json in the MCP "
        "server's current working directory. Paths outside it are refused."
    ),
}


TOOLS: list[Tool] = [
    Tool(
        name="mureo_batch_begin",
        description=(
            "Declare the start of a bulk change so it can be reviewed and "
            "reversed as ONE unit. Every action_log entry recorded until "
            "mureo_batch_end — on any platform, native, hosted connector or "
            "bridged/plugin — is tagged with the returned batch_id. Call this "
            "BEFORE a multi-entity pass (N placement exclusions, N keywords, "
            "N ad status changes); afterwards, rollback_plan_get with that "
            "batch_id reports what can and cannot be reversed. Refused if a "
            "batch is already open."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "What this change set is, in the operator's words "
                        "(e.g. 'exclude low-quality display placements'). "
                        "Stored with the batch so the id still means "
                        "something weeks later."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["label"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_batch_end",
        description=(
            "Close the open batch and return its exact membership: the "
            "action_log indices it collected and the platforms they span. "
            "Keep that list — it is the record that removes the need to "
            "reconstruct a change set from memory later. Refused if no batch "
            "is open."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": _PATH_PROPERTY},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_batch_status",
        description=(
            "Report which batch is currently collecting action_log entries "
            "(null when none is), how many members it holds so far, and "
            "which platforms they span. Read-only."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": _PATH_PROPERTY},
            "additionalProperties": False,
        },
    ),
]

_HANDLERS: dict[str, Any] = {
    "mureo_batch_begin": handle_batch_begin,
    "mureo_batch_end": handle_batch_end,
    "mureo_batch_status": handle_batch_status,
}

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a ``mureo_batch_*`` tool call to its handler."""
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    handler = _HANDLERS[name]
    return await handler(arguments)  # type: ignore[no-any-return]
