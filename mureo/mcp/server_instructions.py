"""The MCP server's ``instructions``: the sections and how they are joined.

``instructions`` is the only always-on prose slot an MCP server has: the
client receives it inside the ``initialize`` response, before any tool call,
and it does not depend on a tool or skill description matching. Each section
below is one contribution to it, returned as ``""`` when it has nothing to
say, so a default install sends no ``instructions`` at all.

Kept apart from :mod:`mureo.mcp.server`, which passes in what it owns (the
served tool list and the plugin tool-ownership map); this module never
imports the server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Read through the module (not bound to a name here) so a monkeypatched
# ``get_runtime_context`` is honoured at call time.
from mureo.core import runtime_context
from mureo.mcp.knowledge_instructions import knowledge_instructions
from mureo.mcp.serving_providers import served_platforms_instructions
from mureo.mcp.tool_guidance import tool_guidance_instructions
from mureo.mcp.tools_learning import advisors_configured, saved_insights_present
from mureo.policy.platform_model import platform_model_instructions

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from mcp.types import Tool


def workspace_instruction() -> str:
    """Server-level instructions that name the workspace this server is bound to.

    Some hosts expose *every* configured MCP server to *every* conversation at
    once, with no way to scope a conversation to one of them. When more than one
    mureo server is configured (one per workspace), the model has no signal about
    which workspace a given server is bound to and can route a tool call to the
    wrong one. Single-process, cwd-scoped hosts (e.g. Claude Code) are unaffected.

    Naming the bound workspace in the server's ``instructions`` (part of the MCP
    ``InitializeResult`` the client shows the model) gives the model the signal it
    needs to pick the right server and to notice a mismatch instead of proceeding.

    Returns ``""`` for the default single-workspace install — see
    :func:`server_instructions` for why that matters.
    """
    try:
        workspace_id = runtime_context.get_runtime_context().workspace_id
    except runtime_context.RuntimeContextFactoryError:
        # A misconfigured factory is a real error, but it must surface where it
        # already does (first tool call), not by refusing to start the server.
        # Omit instructions and let startup proceed unchanged.
        return ""
    if workspace_id == runtime_context.DEFAULT_WORKSPACE_ID:
        return ""
    return (
        f"This mureo server is bound to workspace {workspace_id!r}. Every tool "
        f"here reads and writes ONLY that workspace's data. If the user is "
        f"working on a different client/workspace, do NOT use this server — use "
        f"the mureo server bound to that workspace instead. Never assume a tool "
        f"call here acts on any workspace other than {workspace_id!r}."
    )


def platform_model_instruction(tool_owners: Mapping[str, str]) -> str:
    """The registered platform delivery models this server actually serves (#648).

    A contributed ``SKILL.md`` is description-matched and read on demand, so a
    plugin's account of how its platform really works was never read on the
    routine reporting paths where a borrowed mental model does its damage; the
    always-on slot is read every time.

    Scoped to what this server serves and to who contributed it, so a platform
    this server does not serve (uninstalled, or switched off by
    ``MUREO_DISABLE_*``) contributes nothing, and no plugin can publish text
    under another platform's name. Returns ``""`` when no in-scope platform has
    registered a model — which is every install with no such plugin, mureo core
    shipping none of its own.
    """
    return platform_model_instructions(tool_owners)


def tool_guidance_instruction(
    tools: Iterable[Tool], tool_owners: Mapping[str, str]
) -> str:
    """The served plugin tools' own notes on when to consider them."""
    return tool_guidance_instructions(tools, tool_owners)


def knowledge_instruction() -> str:
    """Saved-knowledge block, fixed at ``initialize``: new knowledge shows next session."""
    try:
        has_insights = saved_insights_present()
    except runtime_context.RuntimeContextFactoryError:  # as workspace_instruction
        return ""
    advisors = advisors_configured()
    return knowledge_instructions(has_insights=has_insights, has_advisors=advisors)


def server_instructions(
    tools: Iterable[Tool], tool_owners: Mapping[str, str]
) -> str | None:
    """Compose the server's MCP ``instructions``, or ``None`` if there is none.

    Five contributions, in this order — the bound-workspace notice, the
    platform tool families (which family reaches this workspace's account on a
    built-in platform a plugin also serves), the platform delivery models
    (#648), the plugin tool notes and the saved knowledge — joined by a blank
    line, each only when non-empty. ``tools`` is the served tool list and
    ``tool_owners`` the plugin tool-ownership map, both from the server.

    Returns ``None`` when all are empty, which is the default single-workspace
    install with no serving plugin, platform model, tool note, insight or
    advisor source: its ``InitializeResult`` stays byte-identical, so
    standalone OSS users see no change. A multi-workspace install with none of
    the others gets exactly the workspace string it got before.
    """
    sections = [
        section
        for section in (
            workspace_instruction(),
            served_platforms_instructions(),
            platform_model_instruction(tool_owners),
            tool_guidance_instruction(tools, tool_owners),
            knowledge_instruction(),
        )
        if section
    ]
    if not sections:
        return None
    return "\n\n".join(sections)


__all__ = [
    "knowledge_instruction",
    "platform_model_instruction",
    "server_instructions",
    "tool_guidance_instruction",
    "workspace_instruction",
]
