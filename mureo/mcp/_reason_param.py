"""The ``reason`` parameter every mutating tool takes (#758, phase 2).

An agent knows why it is pausing a campaign at the moment it dispatches
the call. Nothing downstream ever recovers that sentence, so it has to be
asked for at the boundary — and asked for on EVERY mutating tool, or the
one that forgot is the one an operator later needs.

Injected into the served tool list rather than written into each of the
~120 mutating schemas by hand. Two reasons, both about drift: a
hand-written property would be copied 120 times and reworded 120 ways,
and a tool added next month would silently ship without it. Here the
classification (:func:`mureo.core.strategy_reminder.is_mutating_builtin_tool`
for built-ins, the plugin's own declared semantics for plugin tools) is
the single decision, and it is the same one the dispatcher and the
journal already make.

Three rules, each of them a refusal to guess:

- **A tool that declares its own ``reason`` is left completely alone.**
  ``mureo_state_platform_not_collected_set`` takes a ``reason`` that is
  PERSISTED content — the operator-facing "why was this account not
  collected" note — not a rationale for a change. Injecting over it would
  change its meaning; stripping it before dispatch would delete the
  parameter the handler needs. So it is neither injected nor stripped,
  and such a tool produces no rationale.
- **The registry's ``Tool`` objects are never mutated.** They are shared
  module state that tests, the docs count and the plugin ABI all read;
  injection returns NEW tools with deep-copied schemas.
- **A schema that is not an object with a ``properties`` map is returned
  unchanged.** There is no correct place to put the property in it, and
  inventing one would produce a schema the tool's own author never wrote.
"""

from __future__ import annotations

import copy
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from mureo.core.actor import ACTION_REASON_MAX_CHARS, normalize_reason
from mureo.core.strategy_reminder import is_mutating_builtin_tool

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping

    from mcp.types import Tool

logger = logging.getLogger(__name__)

#: The property added to every mutating tool's ``inputSchema``. One
#: definition, so the wording an agent reads is the same on all of them —
#: read-only, because an in-place edit here would silently reword the
#: schema of all ~120 tools at once. :func:`with_reason_property` copies
#: it per tool, so each served schema still owns its own dict.
REASON_PROPERTY: Mapping[str, Any] = MappingProxyType(
    {
        "type": "string",
        "maxLength": ACTION_REASON_MAX_CHARS,
        "description": (
            "Why this change is being made: one or two sentences naming the "
            "evidence and the expected effect. Stored in the journal and on the "
            "action_log entry this call produces, for the operator and the next "
            "session."
        ),
    }
)

#: Built-in tools that write STATE.json rather than a live ad account, and
#: so are asked for a rationale even though the classifier does not call
#: them mutating.
#:
#: They are listed HERE and not added to
#: :func:`~mureo.core.strategy_reminder.is_mutating_builtin_tool` because
#: that predicate answers a different question. It drives the STRATEGY.md
#: reminder and the journal's ``mutating`` flag, where "mutating" means
#: "this changed something on a platform"; declaring a change set, teaching
#: mureo a conversion vocabulary or importing an observed history did not.
#: Widening it would mislabel every one of those records and nag the agent
#: to re-read its strategy after a bookkeeping call — a real cost for what
#: is only a rationale question here.
STATE_WRITING_BUILTINS: frozenset[str] = frozenset(
    {
        "mureo_batch_begin",
        "mureo_state_set_conversion_events",
        "mureo_external_changes_import",
    }
)

#: Built-in tools deliberately NOT asked for a call-level rationale.
#:
#: Both RECORD a rationale rather than being the change one explains.
#: ``mureo_state_action_log_append`` puts it on the entry it writes and
#: ``mureo_decision_record`` in the record's own ``rationale`` — the
#: reasoning for the thing that happened. A second sentence at call level
#: would be about a different event ("why am I writing this row"), landing
#: in the same column and quietly competing with it.
#:
#: ``mureo_decision_record`` is listed even though its name ends in no
#: mutating suffix and the classifier already leaves it alone: the
#: exemption is a decision about the tool, not an accident of its name,
#: and a later rename must not silently start injecting a second rationale
#: beside the one it exists to carry.
REASON_EXEMPT_BUILTINS: frozenset[str] = frozenset(
    {"mureo_state_action_log_append", "mureo_decision_record"}
)


def with_reason_property(tool: Tool) -> Tool:
    """Return ``tool`` with a ``reason`` property, or ``tool`` itself.

    Unchanged — the SAME object, so a caller can test identity — when the
    schema is not an object schema with a ``properties`` dict, or when the
    tool already declares a ``reason`` of its own (see the module
    docstring for why that one keeps its own semantics).
    """
    schema = getattr(tool, "inputSchema", None)
    if not isinstance(schema, dict):
        return tool
    properties = schema.get("properties")
    if not isinstance(properties, dict) or "reason" in properties:
        return tool
    injected = copy.deepcopy(schema)
    injected["properties"]["reason"] = dict(REASON_PROPERTY)
    return tool.model_copy(update={"inputSchema": injected})


def _log_exemptions(skipped: Collection[str]) -> None:
    """Name the mutating tools that could not take the parameter.

    Silence is how a mutating tool ships with no way to record why it was
    called and nobody notices until an operator asks. One INFO line at
    import, listing the names, is enough for that to be findable.
    """
    if skipped:
        logger.info(
            "reason parameter not injected into %d mutating tool(s) with no "
            "schema properties map: %s",
            len(skipped),
            ", ".join(sorted(skipped)),
        )


def inject_reason_params(
    tools: Iterable[Tool], is_mutating: Callable[[str], bool]
) -> tuple[list[Tool], frozenset[str]]:
    """Add ``reason`` to every mutating tool in ``tools``.

    Returns the new tool list and the names that actually GAINED the
    parameter — which is what :func:`split_call_reason` needs, and is
    narrower than "the mutating names": a tool that declares its own
    ``reason`` is mutating and is not in the set.
    """
    result: list[Tool] = []
    injected: set[str] = set()
    skipped: set[str] = set()
    for tool in tools:
        mutating = is_mutating(tool.name)
        replacement = with_reason_property(tool) if mutating else tool
        if replacement is not tool:
            injected.add(tool.name)
        elif mutating and not _declares_reason(tool):
            skipped.add(tool.name)
        result.append(replacement)
    _log_exemptions(skipped)
    return result, frozenset(injected)


def _declares_reason(tool: Tool) -> bool:
    """Whether ``tool``'s own schema already names a ``reason`` property."""
    schema = getattr(tool, "inputSchema", None)
    properties = schema.get("properties") if isinstance(schema, dict) else None
    return isinstance(properties, dict) and "reason" in properties


def mutating_predicate(
    plugin_names: Collection[str], plugin_semantics: Mapping[str, Any]
) -> Callable[[str], bool]:
    """The dispatcher's own "is this a mutation" rule, as one callable.

    The plugin branch is the same answer
    :func:`mureo.mcp._journal_hook.tool_mutating` gives: the plugin's
    declared semantics, with the conservative "undeclared ⇒ mutating"
    default. The built-in branch is that classifier plus
    :data:`STATE_WRITING_BUILTINS` and minus
    :data:`REASON_EXEMPT_BUILTINS` — see those two for why the question
    "does this deserve a rationale" is not quite the question "did this
    change a live ad account".
    """

    def _mutating(name: str) -> bool:
        if name not in plugin_names:
            if name in REASON_EXEMPT_BUILTINS:
                return False
            return is_mutating_builtin_tool(name) or name in STATE_WRITING_BUILTINS
        semantics = plugin_semantics.get(name)
        return True if semantics is None else bool(semantics.mutating)

    return _mutating


def split_call_reason(
    name: str, arguments: dict[str, Any], injected: Collection[str]
) -> tuple[str | None, dict[str, Any]]:
    """Separate the injected ``reason`` from the arguments the handler gets.

    The handler declared its own parameters and must receive exactly
    those, so ``reason`` is popped out of a COPY — the caller's dict is
    never mutated, and the journal's entry snapshot stays intact.

    For a tool outside ``injected`` (a read-only tool, or one whose
    ``reason`` is its own) this is a no-op returning the caller's dict
    unchanged: the parameter, if present, belongs to the handler.

    Raises:
        ValueError: the rationale is over
            :data:`~mureo.core.actor.ACTION_REASON_MAX_CHARS`. Refused
            rather than truncated, matching the schema's ``maxLength``.
    """
    if name not in injected or not isinstance(arguments, dict):
        return (None, arguments)
    rest = dict(arguments)
    return (normalize_reason(rest.pop("reason", None)), rest)


__all__ = [
    "REASON_EXEMPT_BUILTINS",
    "REASON_PROPERTY",
    "STATE_WRITING_BUILTINS",
    "inject_reason_params",
    "mutating_predicate",
    "split_call_reason",
    "with_reason_property",
]
