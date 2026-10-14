"""The ``mureo_state_settings_set`` tool (#848).

Writes STATE.json's ``settings`` section — today, the ops history switch.
A partial of the ``mureo_context`` family, spliced into its tool list and
handler table exactly as :mod:`mureo.mcp._tools_decisions` is, so it joins
that family's dispatch branch and journal label with no change to
``server.py``. Its name ends in ``_set``, so it is classified as a write:
the dispatcher asks it for a ``reason`` and the policy gates see it like
every other STATE.json writer (``mureo_state_display_set`` included).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.context.settings import set_ops_history_enabled, settings_to_dict
from mureo.mcp._helpers import _json_result, _require, resolve_workspace_path

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from mcp.types import TextContent

    _Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, list[TextContent]]]

SETTINGS_SET_TOOL = "mureo_state_settings_set"

_PATH_PROPERTY = {
    "type": "string",
    "description": (
        "Optional path to STATE.json. Defaults to STATE.json in the MCP "
        "server's current working directory. Paths outside it are refused."
    ),
}

TOOLS: list[Tool] = [
    Tool(
        name=SETTINGS_SET_TOOL,
        description=(
            "Switch ops history on or off for this workspace "
            "(settings.ops_history.enabled in STATE.json; off by default). "
            "When on, every change-making tool must carry `reason` and "
            "`expected`, and a proposed / adopted mureo_decision_record must "
            "declare `expected`. Change it only when the operator asks. "
            "Returns the stored settings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ops_history_enabled": {
                    "type": "boolean",
                    "description": "true to switch ops history on, false for off.",
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["ops_history_enabled"],
            "additionalProperties": False,
        },
    ),
]


async def handle_settings_set(arguments: dict[str, Any]) -> list[TextContent]:
    """Write the setting and return the stored ``settings`` section."""
    enabled = _require(arguments, "ops_history_enabled")
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    doc = set_ops_history_enabled(path, enabled)
    stored = doc.settings
    return _json_result({"settings": settings_to_dict(stored) if stored else {}})


HANDLERS: dict[str, _Handler] = {SETTINGS_SET_TOOL: handle_settings_set}


__all__ = ["HANDLERS", "SETTINGS_SET_TOOL", "TOOLS", "handle_settings_set"]
