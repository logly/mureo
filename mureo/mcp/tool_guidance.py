"""A plugin tool's own note on when to consider it, on the always-on route.

Why a note needs the always-on route
------------------------------------
A host that defers MCP tool loading shows the model only tool *names* until a
tool is searched for. A plugin tool that the agent is meant to *offer* at the
right moment of a conversation, rather than wait to be asked for, is then
never considered: the description that says when to use it is not in context,
and a skill contributed through ``mureo.skills`` is description-matched and
read on demand. The MCP server's ``instructions`` are the only prose the client
receives unconditionally, inside the ``initialize`` response and before any
tool call, so that is where a note has to be for the agent to see it in time.

A plugin tool declares its note as ``Tool.meta["mureo"]["guidance"]`` — one
paragraph of plain prose addressed to the agent, saying when to consider using
the tool. It is read through the same ``meta["mureo"]`` reader
:mod:`mureo.mcp.plugin_semantics` uses, so the ``_meta`` and ``meta``
spellings behave identically. Ownership needs no registry: scope comes from
the same tool-ownership map the platform delivery models use
(:func:`~mureo.mcp.tool_provider.served_tool_owners`), which holds only the
plugin tools this server serves. A tool outside that map — any tool of mureo's
own catalog — is not even inspected. A note is rendered under its own tool's
name, and tool names are already first-wins deduplicated by
:func:`~mureo.mcp.tool_provider.collect_plugin_tools`.

The tool name is rendered, so it is validated
---------------------------------------------
A line reads ``- {tool name}: {note}``, and plugin collection only requires a
tool name to be a non-empty string. A name carrying a line break could forge a
heading or another tool's entry, and a long name would carry free text past
the per-note cap. So a note is rendered only when its tool's name passes
:func:`~mureo.policy.always_on_block.is_renderable_name` (ASCII letters,
digits, ``_``, ``.``, ``-``; 1 to 128 characters), the rule every
always-on line that quotes a plugin-supplied name applies.

Bounded by construction, and shared fairly
------------------------------------------
Always-on text is a budget shared with everything else the model reads, so a
single note is capped at :data:`MAX_GUIDANCE_CHARS` and the rendered block at
:data:`MAX_TOTAL_CHARS`. Notes that do not fit are dropped whole, with an
omission notice on the block itself, using the same fitter the platform
delivery models use (:mod:`mureo.policy.always_on_block`).

Entries are fitted one note for each provider in turn: every provider's first
note (by tool name), then every provider's second, and so on. Ordering by
tool name alone would let a provider that ships several long notes, or picks
names that sort early, fill the block and silently push out another
provider's only note. The unit is the provider that owns the tool, so a
distribution that registers several providers takes a turn for each.

Dropped with a warning, never truncated
---------------------------------------
A note is declared in tool metadata, not registered through a call that could
raise, and a bad note must not stop the server or cost the plugin its tool. So
an unusable note — not a string, blank, over the cap, or containing any line
boundary (see :func:`~mureo.policy.always_on_block.is_single_line`) — or a note
on a tool whose name cannot be rendered is dropped, logged, and reported with a
:class:`~mureo.plugin_warnings.PluginToolWarning` naming the tool and the
reason. It is never cut to fit: half a sentence about when to act still reads
as a complete instruction.

Prose, not call semantics
-------------------------
A note is text for the agent and is deliberately **not** part of
:class:`~mureo.mcp.plugin_semantics.ToolSemantics`, which classifies how safe a
call is (read or mutation, throttling, reversal). A note changes nothing about
how a call is gated, and it grants no permission: every confirmation the
tool's own description requires still applies, which the block's heading
states to the agent.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Hashable
from typing import TYPE_CHECKING, Final

from mureo.mcp.plugin_semantics import _meta_mureo
from mureo.plugin_warnings import PluginToolWarning
from mureo.policy.always_on_block import (
    MAX_RENDERED_NAME_CHARS,
    is_renderable_name,
    is_single_line,
    render_block,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from mcp.types import Tool

logger = logging.getLogger(__name__)

#: Longest one tool's note may be — the same per-entry allowance a platform
#: delivery model gets: one sentence or two on when to consider the tool, not
#: a manual.
MAX_GUIDANCE_CHARS = 400

#: Longest the whole rendered block may be — heading, note lines, the newlines
#: joining them and the omission notice, all counted. Room for a few full
#: notes; past that, whole notes are dropped rather than letting the always-on
#: block grow with the plugin list.
MAX_TOTAL_CHARS = 1200

#: Longest tool-name text quoted in a fault report: the name that failed the
#: rule above may be arbitrarily long, and the report is a log line.
_MAX_REPORTED_NAME_CHARS: Final = 160

_GUIDANCE_KEY = "guidance"

_HEADING = (
    "Tool notes — each line is supplied by the plugin that provides the named "
    "tool and says when to consider using it. A note grants no permission: "
    "every confirmation that tool's own description requires still applies."
)


def _omission_note(count: int) -> str:
    """The line that stops a truncated block reading as a complete one."""
    return (
        f"NOTE: this list is INCOMPLETE — {count} further tool note(s) did not "
        f"fit in this block's length budget."
    )


def _unrenderable_name_reason(name: object) -> str | None:
    """Why a note cannot be rendered under ``name``, or ``None`` if it can."""
    if is_renderable_name(name):
        return None
    return (
        f"the tool name must be 1-{MAX_RENDERED_NAME_CHARS} characters of "
        f"[A-Za-z0-9_.-] to be rendered"
    )


def _unusable_reason(value: object) -> str | None:
    """Why ``value`` cannot be rendered as a note, or ``None`` if it can."""
    if not isinstance(value, str):
        return f"must be a string, got {type(value).__name__}"
    if not value.strip():
        return "is blank"
    if len(value) > MAX_GUIDANCE_CHARS:
        return (
            f"is {len(value)} characters; the always-on budget per note is "
            f"{MAX_GUIDANCE_CHARS}"
        )
    if not is_single_line(value):
        return "must be one paragraph of plain prose (no line breaks)"
    return None


def _report(name: object, reason: str) -> None:
    """Log, then warn: strict mode raises at the warning, the record stays."""
    shown = repr(name)
    if len(shown) > _MAX_REPORTED_NAME_CHARS:
        shown = f"{shown[:_MAX_REPORTED_NAME_CHARS]}…"
    message = f"plugin tool {shown}: guidance {reason}; the note is dropped"
    logger.warning("%s", message)
    # stacklevel=1 for the reason mureo.mcp._tool_validation gives: the note
    # arrived as data, so no caller frame is the culprit.
    warnings.warn(message, PluginToolWarning, stacklevel=1)


def tool_guidance(tool: Tool) -> str | None:
    """Return ``tool``'s usable ``meta["mureo"]["guidance"]``, or ``None``.

    An absent key is silent. A present note that is unusable, or that sits on
    a tool whose name cannot be rendered, is dropped: it is logged and
    reported with a :class:`PluginToolWarning` naming the tool and the reason.
    A bad note neither stops the server nor drops the tool — except in a
    deployment that promoted ``PluginToolWarning`` to an error, which then gets
    that error when the server is created; that is what strict mode is for.
    """
    section = _meta_mureo(tool)
    if _GUIDANCE_KEY not in section:
        return None
    name = getattr(tool, "name", None)
    value = section[_GUIDANCE_KEY]
    reason = _unrenderable_name_reason(name) or _unusable_reason(value)
    if reason is None and isinstance(value, str):
        return value
    _report(name, str(reason))
    return None


def _take_turns(
    notes: Iterable[tuple[str, str, str]],
) -> list[tuple[str, str]]:
    """Order ``(owner, name, note)`` so each owner takes one note in turn.

    Sort key: (rank of the note within its owner by tool name, tool name), so
    every owner's first note comes before any owner's second.
    """
    ranked: list[tuple[int, str, str]] = []
    seen: dict[str, int] = {}
    for owner, name, note in sorted(notes, key=lambda item: item[1]):
        rank = seen.get(owner, 0)
        seen[owner] = rank + 1
        ranked.append((rank, name, note))
    return [(name, note) for _, name, note in sorted(ranked)]


def _owned_notes(
    tools: Iterable[Tool], tool_owners: Mapping[str, str]
) -> list[tuple[str, str, str]]:
    """``(owner, name, note)`` for each in-scope tool with a usable note."""
    notes: list[tuple[str, str, str]] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if not isinstance(name, Hashable) or name not in tool_owners:
            continue
        note = tool_guidance(tool)
        # A usable note implies a validated ``str`` name.
        if note is not None and isinstance(name, str):
            notes.append((tool_owners[name], name, note))
    return notes


def tool_guidance_instructions(
    tools: Iterable[Tool], tool_owners: Mapping[str, str]
) -> str:
    """Render the always-on tool-notes block for ``tools``, within budget.

    ``tool_owners`` is the ownership map ``platform_model_instructions`` takes
    (tool name → owning provider, served plugin tools only); a tool that is
    not a key of it is not inspected. Lines read ``- {tool name}: {note}``,
    each owning provider taking one note in turn. The returned string never
    exceeds
    :data:`MAX_TOTAL_CHARS` characters, counting the heading, the lines, the
    newlines joining them and the omission notice. Returns ``""`` when no
    in-scope tool carries a usable note, which keeps a default install's
    ``InitializeResult`` byte-identical.
    """
    entries = [
        (name, f"- {name}: {note}")
        for name, note in _take_turns(_owned_notes(tools, tool_owners))
    ]
    block, dropped = render_block(_HEADING, entries, MAX_TOTAL_CHARS, _omission_note)
    if dropped:
        logger.warning(
            "tool note block exceeds %d characters; omitted: %s",
            MAX_TOTAL_CHARS,
            ", ".join(dropped),
        )
    return block


__all__ = [
    "MAX_GUIDANCE_CHARS",
    "MAX_TOTAL_CHARS",
    "tool_guidance",
    "tool_guidance_instructions",
]
