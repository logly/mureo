"""The ``mureo_history_query`` tool definition (#758, phase 4b).

A partial of the ``mureo_context`` family rather than a family of its own,
exactly like ``mureo_decision_record``: it reads the same workspace as
every other tool there, so it joins their dispatch branch and their
journal label with no change to ``server.py``. Kept in its own module
because ``tools_mureo_context.py`` is well over the repo's 800-line limit.

**Read-only.** The name ends in no mutating suffix, so
:func:`mureo.core.strategy_reminder.is_mutating_builtin_tool` leaves it
alone: no strategy reminder is appended to its result and the dispatcher
injects no call-level ``reason`` into its schema. Asking an agent why it
is reading history would be noise on the one kind of call that changes
nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.core.report_kinds import REPORT_KINDS
from mureo.mcp._handlers_history import (
    HISTORY_DEFAULT_SOURCES,
    HISTORY_QUERY_DAILY_DEFAULT_LOOKBACK_MONTHS,
    HISTORY_QUERY_DEFAULT_LIMIT,
    HISTORY_QUERY_JOURNAL_SCAN_LINES,
    HISTORY_QUERY_MAX_LIMIT,
    HISTORY_SOURCES,
    handle_history_query,
)
from mureo.mcp._journal_hook import JOURNAL_OUTCOMES

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from mcp.types import TextContent

    #: The shape every handler in this family already has, spelled out so
    #: splicing HANDLERS into the family's table does not widen its value
    #: type to ``Any`` and silence the dispatcher's own return check.
    _Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, list[TextContent]]]

#: Same wording as the rest of the family's: one sentence, sandbox rule
#: stated rather than implied.
_PATH_PROPERTY = {
    "type": "string",
    "description": (
        "Optional path to STATE.json. Defaults to STATE.json in the MCP "
        "server's current working directory. Paths outside it are refused."
    ),
}

#: ``YYYY-MM-DD``, checked by the schema so a malformed bound is refused
#: before any file is opened.
_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

_DESCRIPTION = (
    "Read the PAST — the one tool for any question that reaches beyond "
    "what STATE.json currently holds: what was changed on a campaign in "
    "July, every version a report has had, what a session tried and was "
    "refused, daily spend from before the 35-day retention window. Four "
    "sources, one set of filters: `action_log` (the curated record of "
    "changes, each entry with its index in the full log — the index "
    "`related_actions` and `evaluation_of` name), `journal` (EVERY tool "
    "call and its outcome, including the denied and the failed, which "
    "action_log correctly never holds), `daily` (the day-grain series, "
    "the archived days and the ones still in the document merged into "
    "one), and `reports` (every version ever written of one report kind). "
    "`limit` applies PER source and each section says whether more "
    "matched than came back. Use `mureo_state_get` for the CURRENT state "
    "of the document; use this for what it no longer holds."
)

_SOURCES_DESCRIPTION = (
    "Which trails to read. Default "
    f"{list(HISTORY_DEFAULT_SOURCES)}. 'daily' requires `platform` and "
    "'reports' requires `kind`; both are refused without them rather "
    "than returned empty."
)

_JOURNAL_FILTER_NOTE = (
    "Journal only — the other sources record no such field, and a filter "
    "they cannot answer is ignored by them rather than applied."
)

TOOLS: list[Tool] = [
    Tool(
        name="mureo_history_query",
        description=_DESCRIPTION,
        inputSchema={
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(HISTORY_SOURCES)},
                    "minItems": 1,
                    "description": _SOURCES_DESCRIPTION,
                },
                "since": {
                    "type": "string",
                    "pattern": _DATE_PATTERN,
                    "description": (
                        "Only what happened on or after this UTC date "
                        "(YYYY-MM-DD, inclusive). A record whose own date "
                        "cannot be read is excluded by a dated query "
                        "rather than guessed into the window. Omitting it "
                        "reads the 'daily' archive back only "
                        f"{HISTORY_QUERY_DAILY_DEFAULT_LOOKBACK_MONTHS} "
                        "months from `until` (or today); that section's "
                        "`window` reports the dates it answered from and "
                        "`defaulted: true`. Say `since` to reach further "
                        "back."
                    ),
                },
                "until": {
                    "type": "string",
                    "pattern": _DATE_PATTERN,
                    "description": (
                        "Only what happened on or before this UTC date "
                        "(YYYY-MM-DD, inclusive). Earlier than `since` is "
                        "refused."
                    ),
                },
                "platform": {
                    "type": "string",
                    "description": (
                        "Platform key (google_ads / meta_ads / "
                        "plugin:<dist>:<provider> / ...). Required by the "
                        "'daily' source. On `action_log` it matches the "
                        "entry's platform exactly; on the journal it "
                        "matches the call's family, and for a plugin key "
                        "the distribution that served the tool — the "
                        "journal records which distribution answered, not "
                        "which of its providers, so two providers of one "
                        "bridge cannot be told apart there."
                    ),
                },
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign to filter on. Exact on `action_log`; on "
                        "the journal a best-effort match against the "
                        "call's `campaign_id` argument, since the journal "
                        "records arguments rather than resolved entities."
                    ),
                },
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Sub-campaign entity kind (ad_group / ad_set / "
                        "placement / ...). Must be given together with "
                        "`entity_id`."
                    ),
                },
                "entity_id": {
                    "type": "string",
                    "description": (
                        "The entity's id. Must be given together with "
                        "`entity_type`. On the journal it is matched "
                        "best-effort against the call's "
                        "`<entity_type>_id`, `entity_id` or `id` argument."
                    ),
                },
                "batch_id": {
                    "type": "string",
                    "description": (
                        "Only what belongs to this declared change set — "
                        "the `action_log` entries stamped with it and the "
                        "journal records made while it was open."
                    ),
                },
                "tool": {
                    "type": "string",
                    "description": (
                        f"Only calls of this tool, by exact name. "
                        f"{_JOURNAL_FILTER_NOTE}"
                    ),
                },
                "outcome": {
                    "type": "string",
                    "enum": list(JOURNAL_OUTCOMES),
                    "description": (
                        "Only calls that ended this way: 'ok', "
                        "'platform_error' (the platform refused), "
                        "'exception', 'denied' (a policy gate), 'refused' "
                        "(the exclusion preflight) or 'invalid_args'. "
                        f"{_JOURNAL_FILTER_NOTE}"
                    ),
                },
                "mutations_only": {
                    "type": "boolean",
                    "description": (
                        "Only calls classified as mutations. " f"{_JOURNAL_FILTER_NOTE}"
                    ),
                },
                "failures_only": {
                    "type": "boolean",
                    "description": (
                        "Only calls whose outcome is not 'ok' — what was "
                        "tried and did not happen. "
                        f"{_JOURNAL_FILTER_NOTE}"
                    ),
                },
                "kind": {
                    "type": "string",
                    "enum": list(REPORT_KINDS),
                    "description": (
                        "Which report kind's history to read. Required "
                        "when `sources` includes 'reports', and refused "
                        "without it."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": HISTORY_QUERY_MAX_LIMIT,
                    "description": (
                        f"Entries PER SOURCE, newest kept (default "
                        f"{HISTORY_QUERY_DEFAULT_LIMIT}, max "
                        f"{HISTORY_QUERY_MAX_LIMIT}). A source that had "
                        "more says `truncated: true` — narrow the window "
                        "rather than assuming you saw everything. The "
                        "journal is additionally read only to its last "
                        f"{HISTORY_QUERY_JOURNAL_SCAN_LINES} lines, "
                        "reported as `scanned_lines`."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
]

HANDLERS: dict[str, _Handler] = {"mureo_history_query": handle_history_query}


__all__ = ["HANDLERS", "TOOLS"]
