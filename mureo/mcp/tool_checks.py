"""Answer three questions about a tool call before it is dispatched (#983, #984).

A caller that stores a call and dispatches it later — an approval queue, a
scheduled run, a list of pending changes — needs to know, when it stores the
call, whether the call will touch a platform account, whether dispatch takes
the ops-history parameters it would attach, and whether dispatch would turn
it away as malformed. All three answers come from what the dispatcher itself
uses (:func:`mureo.mcp.server.handle_call_tool`), called in dispatch order;
the parity tests in ``tests/test_tool_checks.py`` pin that the answers and
messages stay equal:

* :func:`writes_to_platform` — the journal's family label and the
  dispatcher's own mutating classification.
* :func:`in_ops_history_scope` — the set of tools dispatch takes
  ``expected`` / ``decision_id`` / ``approval`` (and ``reason``) off.
* :func:`check_tool_call` — the same parameter split, schema validation,
  settings check and ops-history enforcement, in the same order and with
  the same messages.

None runs a policy gate, calls a platform or writes anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from mureo.core.strategy_reminder import is_mutating_builtin_tool
from mureo.mcp import server as _server
from mureo.mcp._journal_hook import (
    PLUGIN_FAMILY,
    UNKNOWN_FAMILY,
    tool_family,
    tool_mutating,
)
from mureo.mcp._ops_history_param import (
    PLATFORM_FAMILIES,
    check_ops_call,
    split_ops_params,
)
from mureo.mcp._reason_param import split_call_reason
from mureo.mcp._tools_settings import check_settings_call

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Built-in families whose mutating tools change a platform account.
#: ``rollback`` is one: ``rollback_apply`` re-applies, on the platform, the
#: inverse of the change it reverses.
_PLATFORM_WRITE_FAMILIES: Final[frozenset[str]] = PLATFORM_FAMILIES | {"rollback"}


def _known_family(name: str) -> str:
    """The journal family of ``name``, refusing a name dispatch would refuse."""
    family = tool_family(name)
    if family == UNKNOWN_FAMILY:
        raise ValueError(f"Unknown tool: {name}")
    return family


def writes_to_platform(name: str) -> bool:
    """True if dispatching this tool can change something on a platform account.

    A platform account is one on Google Ads, Meta Ads, Search Console or a
    plugin platform. A plugin tool answers with its declared semantics; a
    plugin tool that declares none counts as writing, the dispatcher's own
    default. A built-in tool writes when it is mutating and belongs to a
    platform family or to ``rollback``: ``rollback_apply`` re-applies a
    change on the platform it reverses, while ``rollback_plan_get`` only
    reads. Tools that write mureo's local state (``mureo_state_*``,
    ``mureo_strategy_set``, ``mureo_batch_*``, ``mureo_team_learn``),
    analysis tools and ``creative_studio_*`` (paid, but not a platform
    account) answer False.

    Raises:
        ValueError: ``name`` is not a tool this server dispatches, so a typo
            is never reported as safe.
    """
    family = _known_family(name)
    if family == PLUGIN_FAMILY:
        return tool_mutating(name, family)
    return family in _PLATFORM_WRITE_FAMILIES and is_mutating_builtin_tool(name)


def in_ops_history_scope(name: str) -> bool:
    """True if dispatch takes ``expected`` / ``decision_id`` / ``approval`` for this tool.

    A tool in ops-history scope is served with those three properties and
    ``reason``; dispatch removes all four from the arguments before the
    handler runs and can link the call to a decision in operations history;
    whether it does depends on what the call carries (a reason, an
    approval, a decision id or an open batch) and on the workspace having a
    STATE.json. Answer False: read tools; ``rollback_apply``, which undoes
    a decision rather than making one; every ``mureo_*`` bookkeeping tool
    except ``mureo_batch_begin``; and a mutating tool whose own schema has
    no ``properties`` object or already declares ``reason`` or one of the
    three, which keeps what it declared. Outside scope the three are not
    removed. A built-in tool's schema is closed, so it rejects them as
    unknown properties. A plugin tool whose schema allows additional
    properties lets them through to its handler, which passes them to the
    platform; for that tool :func:`check_tool_call` passes and cannot tell
    the caller. A caller that attaches them to a stored call does so only
    when this answers True.

    Raises:
        ValueError: ``name`` is not a tool this server dispatches.
    """
    _known_family(name)
    return name in _server._OPS_TOOLS


def check_tool_call(name: str, arguments: Mapping[str, Any]) -> None:
    """Raise ValueError if dispatch would reject this call as a caller error.

    Runs, in dispatch order, the steps that turn a call away as malformed:
    the ``reason`` / ``expected`` / ``decision_id`` / ``approval`` split,
    the ``inputSchema`` check on the full arguments, the ops-history
    switch-off refusal and, for a tool in ops-history scope, the
    ``reason`` / ``expected`` requirement. Runs no policy gate, no platform
    call, writes nothing and journals nothing; it reads the workspace's
    STATE.json only to learn whether operations history is enabled, as
    dispatch does — that setting decides whether ``expected`` is required.
    A call that passes can still be refused by a policy gate or fail on
    the platform when it is dispatched.

    Raises:
        ValueError: the call would be rejected; the message is the one
            dispatch raises.
        ToolSchemaUnusableError: the tool's ``inputSchema`` cannot check the
            call. Not a caller error, so it is not turned into ValueError.
    """
    _known_family(name)
    reason, handler_args = split_call_reason(
        name, dict(arguments), _server._REASON_TOOLS
    )
    ops, handler_args = split_ops_params(name, handler_args, _server._OPS_TOOLS)
    # The injected-parameter sets and the schema check live on the server
    # module, which is frozen in size, so they are read from there rather than
    # re-exported.
    _server._validate_tool_input(name, dict(arguments))
    check_settings_call(name, handler_args)
    if name in _server._OPS_TOOLS:
        check_ops_call(name, reason, ops, handler_args)


__all__ = ["check_tool_call", "in_ops_history_scope", "writes_to_platform"]
