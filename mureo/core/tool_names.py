"""Shared vocabulary for reading intent out of a tool name.

FOUR surfaces need an answer to "does this name describe a read?", and they
must not drift apart:

- :mod:`mureo.mcp.server`'s guardrail pattern-fallback registration — a read
  moves no money, so subjecting it to a heuristic budget/bid scan could only
  produce false DENIALS.
- :func:`mureo.mcp.plugin_semantics.derive_semantics` — a read is not promoted
  into ``action_log`` (#517).
- :mod:`mureo.policy.learning_reset` — a read cannot restart a learning
  period on any platform.
- :mod:`mureo.rollback.planner` — a read has nothing to undo, so it plans no
  rollback.

Copies of the prefix list would eventually disagree, and the disagreement
would be silent in both directions (an unrollback-able read here, a denied
read there), so the list and the matcher live here once.

**The first three take the strict answer; the fourth takes a looser one.**
:func:`is_read_only_tool_name` matches a verb at the START of a segment and
nothing else. :func:`reads_as_a_report_only_action` also accepts a verb at the
END, which is how mureo names its own tools, and is used by the rollback
planner alone. The split is deliberate and is documented on that function:
the first three decide things about PLUGIN tools, whose names mureo does not
choose, and a mutation admitted there loses a ``## Guardrails`` cap in
silence. Do not collapse the two.

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

__all__ = [
    "READ_ONLY_PREFIXES",
    "WRITE_VERBS",
    "is_read_only_tool_name",
    "reads_as_a_report_only_action",
]

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


#: Verbs that make a name a write whatever else it says.
#:
#: Single-sourced from ``mureo.byod._client_common._MUTATION_PREFIXES``, which
#: AGENTS.md calls the authoritative mutation vocabulary, so the two cannot
#: drift and a verb learned in one place is known in the other. The extras
#: below are shapes that vocabulary has no reason to carry (it names Python
#: client methods, not MCP tools).
#:
#: Only ever used to REFUSE a reading, never to assert that a name is a write,
#: so an omission costs a missed read rather than a missed mutation.
def _write_verbs() -> frozenset[str]:
    from mureo.byod._client_common import _MUTATION_PREFIXES

    return frozenset(p.rstrip("_") for p in _MUTATION_PREFIXES) | {
        "put",
        "post",
        "write",
        "insert",
        "replace",
        "upsert",
        "mutate",
        "purge",
        "drop",
        "clear",
        "reset",
        "restore",
        "archive",
        "stop",
        "start",
        "activate",
        "deactivate",
        "toggle",
        "promote",
        "install",
        "uninstall",
        "register",
        "deregister",
        "revoke",
        "grant",
        "link",
        "unlink",
        "assign",
        "schedule",
        "rename",
        "move",
        "copy",
        "merge",
        "execute",
        "run",
        "sync",
        "import",
    }


WRITE_VERBS: frozenset[str] = _write_verbs()

#: The same verbs as :data:`READ_ONLY_PREFIXES`, as bare tokens.
_READ_VERBS: frozenset[str] = frozenset(p.rstrip("_") for p in READ_ONLY_PREFIXES)


def reads_as_a_report_only_action(name: str) -> bool:
    """Like :func:`is_read_only_tool_name`, but also reads a TRAILING verb.

    **Do not use this to gate a denial or an exemption from one.** It exists
    for exactly one caller — the rollback planner deciding whether an
    ``action_log`` entry is something the operator could be asked to undo —
    and the separation from :func:`is_read_only_tool_name` is the whole design,
    not tidiness.

    The problem it solves. mureo's own tools put the verb LAST
    (``google_ads_campaigns_list``) while the bridged convention puts it first
    (``list_campaigns``), so the prefix-only rule read every native read as a
    write. In a rollback batch that surfaced as a read listed among the items
    the operator "cannot revert", and a change set that was in fact fully
    revertible reporting ``partial`` coverage.

    Why it is not simply added to :func:`is_read_only_tool_name`. That
    predicate has three other callers and every one of them is plugin-facing
    and safety-relevant: ``mcp.server._register_plugin_pattern_fallbacks``
    skips the guardrail money pattern-scan for a name that reads as a read,
    ``mcp.plugin_semantics.derive_semantics`` decides whether a call is
    promoted into ``action_log`` at all, and ``policy.learning_reset``
    decides whether a change can restart a learning period. Loosening the
    shared predicate widens all three at once, on names mureo does not
    control — a plugin can ship any verb it likes. A mutation admitted there
    silently loses a ``## Guardrails`` cap, which is the failure this
    vocabulary exists to prevent, so those three keep the strict rule.

    The trailing reading is still guarded by :data:`WRITE_VERBS`, because this
    surface has its own honesty to keep: a plugin mutation misread here would
    be reported as nothing to revert, hiding a real gap in a batch's coverage.
    That is a smaller harm than losing a money guardrail, which is why the
    guarded rule is acceptable here and not there.
    """
    lowered = name.lower()
    for segment in lowered.split("-"):
        if any(segment.startswith(prefix) for prefix in READ_ONLY_PREFIXES):
            return True
        tokens = segment.split("_")
        if tokens[-1] in _READ_VERBS and not (set(tokens) & WRITE_VERBS):
            return True
    return False
