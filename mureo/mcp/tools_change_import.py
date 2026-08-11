"""Change-import MCP tool definition and handler mapping (#545).

One tool, ``mureo_external_changes_import``: poll each configured platform's
change feed and record anything mureo did not do into ``action_log``.

Platform-agnostic by construction. The tool takes no platform-specific
argument and knows about no platform: it drives whatever feeds are
registered, native or plugin, through the
:class:`~mureo.change_import.protocol.ChangeFeedProvider` ABI. Platforms
without a feed come back ``change_import_unavailable_for_<platform>`` rather
than being left out of the answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.mcp._handlers_change_import import handle_external_changes_import

if TYPE_CHECKING:
    from mcp.types import TextContent


TOOLS: list[Tool] = [
    Tool(
        name="mureo_external_changes_import",
        description=(
            "Import changes made OUTSIDE mureo (a platform's own UI, its "
            "editor, another tool) into STATE.json's action_log, so manual "
            "operation is visible to daily-check instead of showing up only "
            "as unexplained movement in the numbers. Polls each configured "
            "platform's change feed, skips changes already imported and "
            "changes mureo itself made, and records the rest with "
            "origin='external' plus an observation window anchored on when "
            "the change actually happened. Imported entries are NOT "
            "reversible by mureo — it never saw the prior value. Every "
            "configured platform appears in the response: a platform with no "
            "change feed returns status='unavailable' with reason "
            "'change_import_unavailable_for_<platform>', which means mureo is "
            "BLIND there, not that nothing happened. Read "
            "'truncated': true as 'older changes in this window are "
            "unreachable' — change history cannot be backfilled, so poll "
            "often. Safe to call repeatedly; importing the same change twice "
            "is a no-op."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platforms": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "description": (
                        "Platform keys to poll (e.g. ['google_ads']). Omit to "
                        "cover EVERY platform in STATE.json, which is what "
                        "surfaces the ones mureo cannot poll. Use the "
                        "canonical key — 'plugin:<dist>:<provider>' for a "
                        "plugin platform."
                    ),
                },
                "since": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "ISO 8601 date or datetime to start the window at. "
                        "Omit to resume from the newest change already "
                        "imported for each platform (or a short default "
                        "lookback on the first run). Use it to re-check a "
                        "period, not to backfill: a row-capped feed cannot "
                        "answer a wide window, and history that has aged out "
                        "is gone."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Optional path to STATE.json. Defaults to STATE.json "
                        "in the MCP server's current working directory. Paths "
                        "outside it are refused."
                    ),
                },
            },
            "additionalProperties": False,
        },
    ),
]

_HANDLERS: dict[str, Any] = {
    "mureo_external_changes_import": handle_external_changes_import,
}

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a change-import tool call to its handler."""
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    handler = _HANDLERS[name]
    return await handler(arguments)  # type: ignore[no-any-return]


__all__ = ["TOOLS", "handle_tool"]
