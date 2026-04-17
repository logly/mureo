"""Rollback MCP tool definitions and handler mapping.

Exposes two tools to MCP clients:

- ``rollback.plan.get`` — inspect the reversal plan for one
  ``action_log`` entry. Read-only; returns JSON.
- ``rollback.apply``    — execute the plan, re-entering the MCP
  dispatcher so the rollback call hits the same policy gate used
  for forward actions. Requires ``confirm=true`` as a second-factor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.mcp._handlers_rollback import handle_apply, handle_plan_get

if TYPE_CHECKING:
    from mcp.types import TextContent


TOOLS: list[Tool] = [
    Tool(
        name="rollback.plan.get",
        description=(
            "Inspect the reversal plan for a recorded action_log entry in "
            "STATE.json. Returns the planner's status (supported / partial / "
            "not_supported), the operation that would be dispatched, its "
            "parameters, and any caveats. Does not execute anything."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "state_file": {
                    "type": "string",
                    "description": (
                        "Path to STATE.json. Defaults to 'STATE.json' in the "
                        "current working directory."
                    ),
                },
                "index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Index into action_log (0-based).",
                },
            },
            "required": ["index"],
        },
    ),
    Tool(
        name="rollback.apply",
        description=(
            "Execute the rollback plan for action_log[index]. The reversal "
            "call is re-dispatched through the same MCP handler used for "
            "forward actions, so it re-enters auth, rate-limiting, and "
            "input validation. On success, appends a new action_log entry "
            "tagged with rollback_of=index. Requires confirm=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "state_file": {
                    "type": "string",
                    "description": "Path to STATE.json.",
                },
                "index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Index into action_log to reverse.",
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "Must be true to actually execute the rollback. "
                        "A second-factor against accidental or injected "
                        "apply calls."
                    ),
                },
            },
            "required": ["index", "confirm"],
        },
    ),
]

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)

_HANDLERS: dict[str, Any] = {
    "rollback.plan.get": handle_plan_get,
    "rollback.apply": handle_apply,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a rollback.* tool call to its handler."""
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)  # type: ignore[no-any-return]
