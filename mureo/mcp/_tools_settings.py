"""The ``mureo_state_settings_set`` tool (#848).

Writes STATE.json's ``settings`` section — today, the ops history switch.
A partial of the ``mureo_context`` family, spliced into its tool list and
handler table exactly as :mod:`mureo.mcp._tools_decisions` is, so it joins
that family's dispatch branch and journal label with no change to
``server.py``. Its name ends in ``_set``, so it is classified as a write:
the dispatcher asks it for a ``reason`` and the policy gates see it like
every other STATE.json writer (``mureo_state_display_set`` included).

It can only switch ops history ON. Switching it off removes the requirement
an operator chose to impose on the agent, so that is the operator's own
step, in ``mureo configure``; an agent asking for it is refused as
``invalid_args`` before anything is read or written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.context.settings import set_ops_history_enabled, settings_to_dict
from mureo.mcp._helpers import _json_result, _require, resolve_workspace_path

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

    from mcp.types import TextContent

    _Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, list[TextContent]]]

SETTINGS_SET_TOOL = "mureo_state_settings_set"
ENABLED_PARAM = "ops_history_enabled"

SWITCH_OFF_REFUSED = (
    "ops_history_enabled can only be set to true here. Switching ops history "
    "off is the operator's step: mureo configure -> Advanced -> Ops history."
)

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
            "Switch ops history on for this workspace "
            "(settings.ops_history.enabled in STATE.json; off by default). "
            "When on, every change-making tool must carry `reason` and "
            "`expected`, and a proposed / adopted mureo_decision_record must "
            "declare `expected`. Only `true` is accepted: switching it off is "
            "done by the operator in `mureo configure`. Use it only when the "
            "operator asks. Returns the stored settings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                ENABLED_PARAM: {
                    "type": "boolean",
                    "description": "true. Switching off is refused here.",
                },
                "path": _PATH_PROPERTY,
            },
            "required": [ENABLED_PARAM],
            "additionalProperties": False,
        },
    ),
]


def check_settings_call(name: str, arguments: Mapping[str, Any]) -> None:
    """Refuse an attempt to switch ops history off through the tool.

    Raises:
        ValueError: ``name`` is this tool and ``ops_history_enabled`` is
            ``false``.
    """
    if name == SETTINGS_SET_TOOL and arguments.get(ENABLED_PARAM) is False:
        raise ValueError(SWITCH_OFF_REFUSED)


async def handle_settings_set(arguments: dict[str, Any]) -> list[TextContent]:
    """Write the setting and return the stored ``settings`` section."""
    check_settings_call(SETTINGS_SET_TOOL, arguments)
    enabled = _require(arguments, ENABLED_PARAM)
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    doc = set_ops_history_enabled(path, enabled)
    stored = doc.settings
    return _json_result({"settings": settings_to_dict(stored) if stored else {}})


HANDLERS: dict[str, _Handler] = {SETTINGS_SET_TOOL: handle_settings_set}


__all__ = [
    "HANDLERS",
    "SETTINGS_SET_TOOL",
    "SWITCH_OFF_REFUSED",
    "TOOLS",
    "check_settings_call",
    "handle_settings_set",
]
