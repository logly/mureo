"""Soft strategy-driven enforcement via dispatcher-injected reminders.

Background
----------

mureo advertises "every decision references STRATEGY.md" as one of its
six core strengths. v0.9.23 audit found this claim was prompt-only:
the diagnostic skills instruct the agent to read STRATEGY.md at
workflow start, but MCP tool handlers themselves never consult it. If
the agent forgets, drifts, or is interrupted between calls, nothing in
the codebase re-surfaces the strategy.

This module closes that gap with the **lowest-cost, least-invasive**
approach: when the dispatcher runs a built-in *mutating* tool, it
appends a short reminder TextContent block to the tool's response that
lists the STRATEGY.md section titles the operator has declared. The
agent re-sees them after every mutation, lowering drift risk across
multi-step workflows.

This is **soft enforcement**:

- No refusal — every operation that would have succeeded before still
  succeeds. The reminder is purely additive context.
- Section titles only — never the full content, so the context cost
  is small (one short paragraph regardless of STRATEGY.md size).
- Best-effort — a corrupted STATE.json, missing strategy file, or any
  exception in the reminder builder is swallowed; the dispatch result
  is returned unchanged.

For *hard* enforcement (refuse mutating calls that violate declared
constraints), see the matching tracker issue — that requires a schema
addition to STRATEGY.md and an opt-in PolicyGate. Out of scope for
v0.9.24.

Opt-out
-------

Set the env var ``MUREO_DISABLE_STRATEGY_REMINDER=1`` (exact string
``"1"``, matching the established ``MUREO_DISABLE_*`` pattern in
``mureo.mcp.server``) to suppress the reminder entirely. Useful when:

- The skill's first step already reads STRATEGY.md and the operator
  prefers to keep the context window slim.
- A non-Claude-Code MCP client renders the appended TextContent
  oddly.

Default is enabled.

Classification
--------------

:func:`is_mutating_builtin_tool` classifies built-in tool names by
explicit suffix matching against a curated set. Plugin tools and any
tool the classifier does not recognise default to NOT mutating — the
reminder does not fire spuriously. Plugin tools use their own
``derive_semantics`` machinery for similar concerns; cross-applying
the reminder to plugin tools is deliberately out of scope for v1.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from mureo.core.runtime_context import get_runtime_context

if TYPE_CHECKING:
    from mureo.context.models import StrategyEntry

logger = logging.getLogger(__name__)


_OPT_OUT_ENV_VAR = "MUREO_DISABLE_STRATEGY_REMINDER"

# Max number of section titles included in the reminder. A pathological
# 100-section STRATEGY.md still produces a bounded payload; the
# operator sees "+N more" when truncated so the cap is observable.
_MAX_SECTIONS_IN_REMINDER = 20


# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------

# Curated set of mutating built-in tool name suffixes. Maintained
# manually rather than via name heuristics so a new built-in tool that
# does NOT fit the typical patterns (e.g. ``*_send`` for conversions
# upload) is classified explicitly. The test suite pins this set
# against the FULL built-in tool name catalogue (every name in
# ``mureo/mcp/_tools_*.py``) so a new tool added without classifier
# update fails CI.
_MUTATING_BUILTIN_SUFFIXES: frozenset[str] = frozenset(
    {
        # Generic CRUD-style mutators
        "_create",
        "_update",
        "_delete",
        "_remove",
        "_add",
        "_pause",
        "_enable",
        "_disable",
        "_apply",
        "_submit",
        "_upload",
        "_send",
        "_set",
        "_tag",
        "_boost",
        "_activate",
        "_revoke",
        "_append",
        # v0.9.24 round-2 review: real Meta Ads tools that the
        # initial suffix list missed (caught by the cross-check
        # against the registry; both are platform-state mutators).
        "_duplicate",  # meta_ads_lead_forms_duplicate
        "_end",  # meta_ads_split_tests_end
        # Specific compound suffixes that appear in real tool names
        "_create_lookalike",
        "_create_display",
        "_create_carousel",
        "_create_collection",
        "_create_dynamic",
        "_create_lead",
        "_update_status",
        "_update_users",
        "_upload_file",
        "_upload_image",
        "_send_lead",
        "_send_purchase",
        "_add_to_ad_group",
        "_upsert_campaign",
    }
)

# Explicit individual mutating tool names that do NOT match any of the
# suffixes above. Kept in a separate set so a future maintainer who
# adds an explicit name does not accidentally turn it into a suffix
# match against unrelated tools (the v1 design conflated these into
# the same frozenset, which the round-2 review flagged as confusing).
_MUTATING_BUILTIN_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "rollback_apply",
    }
)

# Plugin tools are out of scope for the reminder — they have their
# own ``derive_semantics`` mechanism. Detect by the ``mcp__`` prefix
# the MCP server applies to plugin tool names.
_PLUGIN_PREFIX = "mcp__"


def is_mutating_builtin_tool(name: str) -> bool:
    """Return True iff ``name`` is a built-in mutating tool that
    warrants a strategy reminder.

    Plugin tools (``mcp__...``) always return False — they are out of
    scope for v1. Unknown tool names default to False so the reminder
    never fires spuriously.
    """
    if name.startswith(_PLUGIN_PREFIX):
        return False
    if name in _MUTATING_BUILTIN_EXACT_NAMES:
        return True
    return any(name.endswith(s) for s in _MUTATING_BUILTIN_SUFFIXES)


# ---------------------------------------------------------------------------
# Reminder text builder
# ---------------------------------------------------------------------------


def build_reminder_text(entries: list[StrategyEntry]) -> str | None:
    """Render the strategy reminder body, or ``None`` if empty.

    Lists only section titles + context_type, never the content. Caps
    at :data:`_MAX_SECTIONS_IN_REMINDER` with an explicit "+N more"
    indicator when truncated so the cap is observable to the agent.
    """
    if not entries:
        return None
    truncated = entries[:_MAX_SECTIONS_IN_REMINDER]
    overflow = len(entries) - len(truncated)
    lines = [
        "(STRATEGY reminder: this is a mutating operation. Verify your "
        "action aligns with the STRATEGY.md sections you've already "
        "read at the start of this workflow:"
    ]
    for entry in truncated:
        lines.append(f"  - [{entry.context_type}] {entry.title}")
    if overflow > 0:
        lines.append(f"  - ... +{overflow} more section(s) not shown")
    lines.append(
        "If your action conflicts with any of these, stop and ask the "
        "operator before proceeding to the next mutating call.)"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatcher hook
# ---------------------------------------------------------------------------


def _read_strategy_reminder(tool_name: str) -> str | None:
    """Env-gated STRATEGY.md reminder body shared by the built-in and
    plugin entry points. Returns ``None`` when opted out, on a state-read
    failure, or when STRATEGY.md is empty.

    The state read AND the text build are both inside the try: any
    exception is caught and logged at DEBUG, so a broken reminder can
    never break a mutating tool dispatch (the callers that append the
    result do not wrap it in their own try/except).
    """
    if os.environ.get(_OPT_OUT_ENV_VAR) == "1":
        return None
    try:
        ctx = get_runtime_context()
        entries = list(ctx.state_store.read_strategy())
        return build_reminder_text(entries)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "strategy reminder: build failed for tool %s (%s); skipping reminder",
            tool_name,
            exc,
        )
        return None


def maybe_build_reminder(tool_name: str) -> str | None:
    """Best-effort: return the reminder text for ``tool_name`` if the
    tool is a mutating *built-in*, the env var has not opted out,
    STRATEGY.md is non-empty, and the state read succeeds. Returns
    ``None`` in every other case so the caller can simply do
    ``if text is not None: append`` without further error handling.
    """
    if not is_mutating_builtin_tool(tool_name):
        return None
    return _read_strategy_reminder(tool_name)


def maybe_build_reminder_for_plugin(tool_name: str) -> str | None:
    """Plugin counterpart of :func:`maybe_build_reminder` (guardrail
    parity, #114 follow-up).

    The dispatcher only calls this after a plugin tool has *already* been
    classified as mutating by :func:`mureo.mcp.plugin_semantics.derive_semantics`
    (standard MCP ``readOnlyHint``/``meta`` metadata). So unlike the built-in
    entry point, it deliberately does NOT run :func:`is_mutating_builtin_tool`
    — that classifier excludes the ``mcp__`` plugin namespace by design. Same
    env opt-out and best-effort contract; the reminder body is identical, so a
    plugin mutation re-surfaces STRATEGY.md exactly like a built-in one.
    """
    return _read_strategy_reminder(tool_name)


__all__ = [
    "build_reminder_text",
    "is_mutating_builtin_tool",
    "maybe_build_reminder",
    "maybe_build_reminder_for_plugin",
]
