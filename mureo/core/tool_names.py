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

import unicodedata

__all__ = [
    "MUTATION_PREFIXES",
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


#: Mutation method-name prefixes: the authoritative mutation vocabulary
#: (AGENTS.md). The list lives here, in ``core``, and the BYOD clients
#: (:mod:`mureo.byod._client_common`) import it to refuse a mutation in
#: read-only mode, so the two cannot drift and ``core`` imports nothing from
#: ``byod`` (#879).
#:
#: Anything matching one of these returns ``skipped_in_byod_readonly`` in BYOD
#: mode instead of an empty list, so a curious agent never mistakes a mutation
#: for a successful call.
MUTATION_PREFIXES: tuple[str, ...] = (
    "create_",
    "update_",
    "delete_",
    "remove_",
    "add_",
    "send_",
    "upload_",
    "pause_",
    "resume_",
    "enable_",
    "disable_",
    "apply_",
    "publish_",
    "submit_",
    "attach_",
    "detach_",
    "approve_",
    "reject_",
    "cancel_",
    "set_",
    "patch_",
    # A Performance Max text swap (#590): a text Asset is immutable, so the
    # client method is named for what it does — replace_ matches no generic
    # prefix above, and without this entry a BYOD call would fall through to
    # the empty-list read stub and read as a write that quietly did nothing.
    "replace_",
    # Meta-specific mutation verbs whose method names do not match any
    # of the generic prefixes above: boost_post / boost_instagram_post,
    # end_split_test, duplicate_lead_form, and export_leads_to_csv (the
    # last writes a local file only, but is still a state-producing
    # operation that must not silently no-op as an empty read).
    "boost_",
    "end_",
    "duplicate_",
    "export_",
)


#: Verbs that make a name a write whatever else it says.
#:
#: Single-sourced from :data:`MUTATION_PREFIXES` above, so the two cannot
#: drift and a verb learned in one place is known in the other. The extras
#: below are shapes that vocabulary has no reason to carry (it names Python
#: client methods, not MCP tools).
#:
#: Only ever used to REFUSE a reading, never to assert that a name is a write,
#: so an omission costs a missed read rather than a missed mutation.
#:
#: Computed once at import, from :data:`MUTATION_PREFIXES`.
def _write_verbs() -> frozenset[str]:
    return frozenset(p.rstrip("_") for p in MUTATION_PREFIXES) | {
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
        # Abbreviations and blunt synonyms. A review defeated an earlier
        # version of this list with `campaign_del_list` and `budget_rm_check`:
        # the trailing verb read as a report while the real verb was a
        # shortening of one already listed.
        "del",
        "rm",
        "kill",
        "nuke",
        "terminate",
        "revert",
        "undo",
        "wipe",
        "flush",
        "prune",
        "truncate",
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
    and safety-relevant: ``mcp._plugin_declarations._register_plugin_pattern_fallbacks``
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
    # NFKC first: a fullwidth `ｄｅｌ` is the same verb as `del` to a reader and
    # a different string to `in`, and the whole guard is a string comparison.
    # It does not make the vocabulary complete — a verb written in another
    # script (the Japanese word for "delete" followed by `_list`) is not
    # reachable from a list of English words, and this predicate does not
    # pretend otherwise; see the honesty note above about what a misread
    # costs on this surface.
    lowered = unicodedata.normalize("NFKC", name).lower()
    for segment in lowered.split("-"):
        if any(segment.startswith(prefix) for prefix in READ_ONLY_PREFIXES):
            return True
        tokens = segment.split("_")
        if tokens[-1] in _READ_VERBS and not (set(tokens) & WRITE_VERBS):
            return True
    return False
