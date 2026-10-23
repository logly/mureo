"""Callables mureo.mcp.server publishes at load for the hook modules below it.

Same discipline as :mod:`mureo.mcp._plugin_tables` (#879 stage 1): the
server fills these at import, so a hook imports this module at top level
instead of reaching back up into the half-initialised server. Reloading the
server re-publishes them.

Three slots, one per hook that used to import ``server`` from inside a
function (#879 stage 2):

- :data:`tool_families` — the journal hook's family classification
  (:func:`mureo.mcp._journal_hook.tool_family`).
- :data:`dispatcher` — the call-tool dispatcher ``rollback_apply`` re-enters
  (:func:`mureo.mcp._handlers_rollback._get_dispatcher`).
- :data:`policy_evaluator` — the policy gates the automatic observation
  closure asks before it writes
  (:func:`mureo.mcp._auto_evaluation_hook._policy_denial`).

Each slot is ``None`` until ``server`` has finished loading. A hook reads it
through the matching ``require_*`` function, which raises rather than
falling back: a hook that ran without the server would classify, dispatch or
gate against nothing, and that has to be loud.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from mureo.core.policy import PolicyDecision

#: ``(tool names, family label)`` pairs, in ``server._dispatch_tool`` order.
ToolFamilies = Callable[[], Sequence[tuple[frozenset[str], str]]]
#: ``server.handle_call_tool``'s signature.
Dispatcher = Callable[[str, dict[str, Any]], Awaitable[list[Any]]]
#: ``server._evaluate_policy_gates``'s signature: the first deny, else ``None``.
PolicyEvaluator = Callable[[str, dict[str, Any]], PolicyDecision | None]

#: Filled by ``server`` at the end of its load.
tool_families: ToolFamilies | None = None
#: Filled by ``server`` at the end of its load.
dispatcher: Dispatcher | None = None
#: Filled by ``server`` at the end of its load.
policy_evaluator: PolicyEvaluator | None = None

_SlotT = TypeVar("_SlotT")


def _require(slot_value: _SlotT | None, name: str) -> _SlotT:
    """Return ``slot_value``, or raise when ``server`` has not filled it."""
    if slot_value is None:
        raise RuntimeError(f"mureo.mcp.server has not been loaded; {name} is unset")
    return slot_value


def require_tool_families() -> ToolFamilies:
    """The published family view. Raises ``RuntimeError`` when unset."""
    return _require(tool_families, "tool_families")


def require_dispatcher() -> Dispatcher:
    """The published dispatcher. Raises ``RuntimeError`` when unset."""
    return _require(dispatcher, "dispatcher")


def require_policy_evaluator() -> PolicyEvaluator:
    """The published policy evaluator. Raises ``RuntimeError`` when unset."""
    return _require(policy_evaluator, "policy_evaluator")
