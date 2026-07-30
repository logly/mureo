"""Shared vocabulary for reading intent out of a tool name.

Two safety surfaces need the same answer to "does this name describe a read?"
and they must not drift apart:

- :mod:`mureo.rollback.planner` — a read has nothing to undo, so it plans no
  rollback.
- :mod:`mureo.mcp.server`'s guardrail pattern-fallback registration — a read
  moves no money, so subjecting it to a heuristic budget/bid scan could only
  produce false DENIALS.

Two copies of the prefix list would eventually disagree, and the disagreement
would be silent in both directions (an unrollback-able read here, a denied
read there), so the list and the matcher live here once.

**Namespace-aware by construction.** A bridged MCP server commonly namespaces
its tools with a hyphen (``campaign_management-list_campaigns``), and a plain
``startswith`` against the whole name matches none of those. Matching anchors
per hyphen-delimited segment instead. A name without a hyphen is a single
segment, so native mureo tool names behave exactly as they did — including the
deliberate non-match of mid-word hits like ``listing_update``.

**Heuristic, and deliberately so.** These are name shapes, not declarations.
Where the answer gates a DENIAL the asymmetry matters: mutations on ad
platforms are consistently verb-named (``create_`` / ``update_`` / ``delete_``
/ ``set_``), so a name that reads like a read almost never is a mutation, while
treating a genuine read as a mutation breaks harmless calls. Hence the
exemption is keyed on read-shaped names rather than on a mutation allow-list.
"""

from __future__ import annotations

__all__ = ["READ_ONLY_PREFIXES", "is_read_only_tool_name"]

#: Verb prefixes that mark a tool name as a read. Anchored at the start of a
#: namespace segment (see :func:`is_read_only_tool_name`); the trailing
#: underscore is what keeps ``listing_update`` / ``getter_config`` from
#: matching.
READ_ONLY_PREFIXES: tuple[str, ...] = (
    "list_",
    "get_",
    "analyze_",
    "diagnose_",
    "inspect_",
    "report_",
    "check_",
    "search_",
    "query_",
)


def is_read_only_tool_name(name: str) -> bool:
    """Does ``name`` describe a read, by shape?

    Case-insensitive, and anchored per hyphen-delimited namespace segment so a
    bridged ``campaign_management-list_campaigns`` reads the same as a native
    ``list_campaigns``.
    """
    lowered = name.lower()
    return any(
        segment.startswith(prefix)
        for segment in lowered.split("-")
        for prefix in READ_ONLY_PREFIXES
    )
