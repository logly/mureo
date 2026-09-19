"""MCP handler for ``mureo_history_query`` (#758, phase 4b).

Four records answer "what happened before today", and each had its own
door: ``action_log`` and the `daily` window only inside the whole
``mureo_state_get`` document, the journal only through the ``mureo
journal`` CLI, and the phase-4a archives through no tool at all. An agent
on a Bash-less host could not ask "what did we change on this campaign in
July" at all; one that could had to read a whole document to find out.
This handler is that one question, over all four, with one set of filters.

Read-only, and bounded on purpose:

- **``limit`` is per source.** A query over three sources returns at most
  three times ``limit``, and each section says whether more matched than
  it returned. Silence about truncation is how a partial answer gets read
  as a complete one.
- **the journal scan is capped.** ``JOURNAL.jsonl`` grows one line per
  tool call, so only the last :data:`HISTORY_QUERY_JOURNAL_SCAN_LINES`
  lines are looked at and the section reports how many that was. Since
  #758 phase 6 a full journal is rotated away, and the rotated files are
  part of the record: the cap is spent newest file first and counts
  across all of them.
- **a dateless ``daily`` query is bounded too.** The archive is one file
  per month, so without a floor the cheapest-looking question — no dates
  at all — would open every month a years-old account ever had. With no
  ``since`` the section reads back
  :data:`HISTORY_QUERY_DAILY_DEFAULT_LOOKBACK_MONTHS` months and says so
  in its ``window``.
- **the newest wins.** Every source returns the LAST matches, because a
  question about the past is nearly always a question about the recent
  past — and for ``action_log`` each entry keeps its index in the FULL
  log, which is what ``related_actions`` and ``evaluation_of`` refer to.

What the sources can and cannot be asked:

- ``action_log`` and ``daily`` read STATE.json, so a workspace without one
  answers with ``"state": "missing"`` rather than raising — "no document"
  is a fact about the workspace, not a failure of the query;
- ``daily`` merges the days still inside the document's retention window
  with the archived ones so the caller sees ONE series; a day present in
  both is the document's, since that is the copy the dashboard renders;
- the journal's ``platform``, ``campaign_id`` and ``entity_id`` filters
  are a **best-effort argument match**, not an index: a journal record is
  a record of a CALL, and mureo does not resolve the entities a call
  touched. The `action_log` filters are exact, because those fields are
  stored on the entry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Final

from mureo.context.history import read_daily_archive, read_report_history
from mureo.context.models import DAILY_DATE_KEY_PATTERN
from mureo.context.state import read_state_file, render_state
from mureo.core import clock
from mureo.core.platform_keys import is_plugin_platform_key, plugin_distribution
from mureo.core.report_kinds import REPORT_KINDS
from mureo.core.rotation import sibling_files
from mureo.mcp import journal
from mureo.mcp._helpers import _json_result, resolve_workspace_path
from mureo.mcp._journal_hook import JOURNAL_OUTCOMES
from mureo.mcp.journal_read import (
    JOURNAL_SCAN_LINES,
    read_records_tail_files,
    record_matches,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mcp.types import TextContent

#: The trails a query may ask about, in the order they are returned.
HISTORY_SOURCES: Final[tuple[str, ...]] = (
    "action_log",
    "journal",
    "daily",
    "reports",
)

#: What a query with no ``sources`` asks for: the two trails that answer
#: "what happened" without a further parameter. ``daily`` needs a platform
#: and ``reports`` needs a kind, so neither can be a default.
HISTORY_DEFAULT_SOURCES: Final[tuple[str, ...]] = ("action_log", "journal")

#: Entries per source when the caller does not say, and the ceiling. The
#: cap is a context budget, not a storage one: 200 action_log entries is
#: already a long read for an agent that has to hold the answer.
HISTORY_QUERY_DEFAULT_LIMIT: Final[int] = 50
HISTORY_QUERY_MAX_LIMIT: Final[int] = 200

#: How many TAIL lines of the journal one query may look at, counted
#: across the live file and its rotated siblings. Without this bound the
#: cost of a query would grow with the age of the workspace. The number
#: itself lives in :mod:`mureo.mcp.journal_read`, shared with
#: ``mureo journal --all``; this name is what callers already import.
HISTORY_QUERY_JOURNAL_SCAN_LINES: Final[int] = JOURNAL_SCAN_LINES

#: The same bound for a report ledger, counted in entries rather than
#: lines. One report kind gains a line per write — daily at the most — so
#: this is years of history, and it keeps ``until`` honest: the filter is
#: applied to what was read, and what was read has to be more than the
#: window asked for.
HISTORY_QUERY_REPORT_SCAN_ENTRIES: Final[int] = 1_000

#: How far back a `daily` query with no ``since`` reads, counted in whole
#: months including the anchor's own. The archive is one file per month
#: and is selected by name, so without this a dateless question would open
#: every month the account ever had — a cost that grows with its age,
#: while the journal and the report ledger are both capped. A caller that
#: wants further back says so with an explicit ``since``.
HISTORY_QUERY_DAILY_DEFAULT_LOOKBACK_MONTHS: Final[int] = 12

#: The document's own rule for what counts as a day key, so this reader
#: cannot admit a key the writer would have refused.
_DAILY_DATE_KEY_RE = re.compile(DAILY_DATE_KEY_PATTERN)


@dataclass(frozen=True)
class HistoryQuery:
    """The effective filters of one query, defaults resolved.

    Echoed back to the caller in full — including the fields it did not
    set — because an agent reading a short answer has to be able to tell
    "nothing matched" from "I filtered on something I did not mean to".
    """

    sources: tuple[str, ...]
    limit: int
    since: date | None = None
    until: date | None = None
    platform: str | None = None
    campaign_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    batch_id: str | None = None
    tool: str | None = None
    outcome: str | None = None
    kind: str | None = None
    mutations_only: bool = False
    failures_only: bool = False

    def echo(self) -> dict[str, Any]:
        """The filters as JSON, dates as ``YYYY-MM-DD``."""
        return {
            "sources": list(self.sources),
            "limit": self.limit,
            "since": None if self.since is None else self.since.isoformat(),
            "until": None if self.until is None else self.until.isoformat(),
            "platform": self.platform,
            "campaign_id": self.campaign_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "batch_id": self.batch_id,
            "tool": self.tool,
            "outcome": self.outcome,
            "kind": self.kind,
            "mutations_only": self.mutations_only,
            "failures_only": self.failures_only,
        }


def _text(arguments: dict[str, Any], key: str) -> str | None:
    """An optional string argument, with empty read as absent."""
    value = arguments.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _parse_day(arguments: dict[str, Any], key: str) -> date | None:
    """An optional ``YYYY-MM-DD`` bound. The schema checks the shape too.

    Raises:
        ValueError: the value is not a calendar date.
    """
    raw = _text(arguments, key)
    if raw is None:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{key} must be a date as YYYY-MM-DD; got {raw!r}") from exc


def _parse_sources(value: Any) -> tuple[str, ...]:
    """The requested sources, deduplicated into the canonical order.

    Raises:
        ValueError: an unknown source, or an empty list.
    """
    if value is None:
        return HISTORY_DEFAULT_SOURCES
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"sources must be a non-empty array of {list(HISTORY_SOURCES)}"
        )
    unknown = [item for item in value if item not in HISTORY_SOURCES]
    if unknown:
        raise ValueError(f"unknown sources {unknown}: use {list(HISTORY_SOURCES)}")
    return tuple(source for source in HISTORY_SOURCES if source in value)


def _parse_limit(value: Any) -> int:
    """The per-source cap.

    Raises:
        ValueError: not an integer, or outside 1..:data:`HISTORY_QUERY_MAX_LIMIT`.
    """
    if value is None:
        return HISTORY_QUERY_DEFAULT_LIMIT
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"limit must be an integer; got {value!r}")
    if not 1 <= value <= HISTORY_QUERY_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {HISTORY_QUERY_MAX_LIMIT}")
    return value


def _parse_kind(arguments: dict[str, Any], sources: tuple[str, ...]) -> str | None:
    """The report kind, required by ``reports`` and refused without it.

    Refused rather than ignored: a ``kind`` passed with no ``reports``
    source means the caller expected report history back, and returning
    the other sources as though nothing were wrong answers a question
    nobody asked.

    Raises:
        ValueError: the pairing is wrong, or the kind is outside the
            vocabulary.
    """
    kind = _text(arguments, "kind")
    if "reports" in sources and kind is None:
        raise ValueError("sources includes 'reports', so kind is required")
    if kind is not None and "reports" not in sources:
        raise ValueError("kind applies to the 'reports' source; add it to sources")
    if kind is not None and kind not in REPORT_KINDS:
        raise ValueError(f"kind must be one of {list(REPORT_KINDS)}")
    return kind


def build_history_query(arguments: dict[str, Any]) -> HistoryQuery:
    """Validate one call's arguments into the filters it means.

    Every refusal here is a caller error the dispatcher reports as
    ``invalid_args``, and every one of them happens before a file is
    opened — an unanswerable query must not cost a read.

    Raises:
        ValueError: an unknown source, a bad bound, half an entity pair,
            ``daily`` without a platform, or ``kind`` without ``reports``.
    """
    sources = _parse_sources(arguments.get("sources"))
    since = _parse_day(arguments, "since")
    until = _parse_day(arguments, "until")
    if since is not None and until is not None and until < since:
        raise ValueError(f"until ({until}) is before since ({since})")
    entity_type = _text(arguments, "entity_type")
    entity_id = _text(arguments, "entity_id")
    if (entity_type is None) != (entity_id is None):
        raise ValueError("entity_type and entity_id must be given together")
    platform = _text(arguments, "platform")
    if "daily" in sources and platform is None:
        raise ValueError("the 'daily' source is per platform, so platform is required")
    outcome = _text(arguments, "outcome")
    if outcome is not None and outcome not in JOURNAL_OUTCOMES:
        raise ValueError(f"outcome must be one of {list(JOURNAL_OUTCOMES)}")
    return HistoryQuery(
        sources=sources,
        limit=_parse_limit(arguments.get("limit")),
        since=since,
        until=until,
        platform=platform,
        campaign_id=_text(arguments, "campaign_id"),
        entity_type=entity_type,
        entity_id=entity_id,
        batch_id=_text(arguments, "batch_id"),
        tool=_text(arguments, "tool"),
        outcome=outcome,
        kind=_parse_kind(arguments, sources),
        mutations_only=bool(arguments.get("mutations_only", False)),
        failures_only=bool(arguments.get("failures_only", False)),
    )


def _in_window(day: date | None, query: HistoryQuery) -> bool:
    """Whether ``day`` falls inside the query's inclusive bounds.

    An undatable record passes an unbounded query and fails a bounded one:
    it cannot be SHOWN to fall inside a window, and a record placed in one
    it might not belong to is worse than one left out of it.
    """
    if query.since is None and query.until is None:
        return True
    if day is None:
        return False
    return (query.since is None or day >= query.since) and (
        query.until is None or day <= query.until
    )


def _iso_date(value: Any) -> date | None:
    """The UTC date of an ISO 8601 timestamp, or ``None`` if unreadable.

    ``Z`` is normalised by hand: ``fromisoformat`` only learned to read it
    in 3.11 and mureo still supports 3.10, where an unconverted ``Z``
    would drop the record out of every bounded query.
    """
    if not isinstance(value, str) or not value:
        return None
    text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# action_log
# ---------------------------------------------------------------------------


def _rendered_action_log(path: Path) -> list[dict[str, Any]]:
    """The log exactly as ``mureo_state_get`` emits it.

    Rendered through the document codec rather than read field by field,
    so an entry gained by a later phase appears here without this module
    being taught about it.
    """
    entries = json.loads(render_state(read_state_file(path))).get("action_log", [])
    return [entry for entry in entries if isinstance(entry, dict)]


def _action_log_matches(entry: dict[str, Any], query: HistoryQuery) -> bool:
    """Whether one rendered entry survives the query's filters."""
    if query.platform is not None and entry.get("platform") != query.platform:
        return False
    if query.campaign_id is not None and entry.get("campaign_id") != query.campaign_id:
        return False
    if query.entity_type is not None and (
        entry.get("entity_type") != query.entity_type
        or entry.get("entity_id") != query.entity_id
    ):
        return False
    if query.batch_id is not None and entry.get("batch_id") != query.batch_id:
        return False
    return _in_window(_iso_date(entry.get("timestamp")), query)


def _action_log_section(path: Path, query: HistoryQuery) -> dict[str, Any]:
    """The ``action_log`` section: the newest matching entries, indexed."""
    matched = [
        {**entry, "index": index}
        for index, entry in enumerate(_rendered_action_log(path))
        if _action_log_matches(entry, query)
    ]
    returned = matched[-query.limit :]
    section: dict[str, Any] = {
        "entries": returned,
        "matched": len(matched),
        "returned": len(returned),
        "truncated": len(matched) > query.limit,
    }
    if not path.exists():
        section["state"] = "missing"
    return section


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------


def _journal_platform_matches(record: dict[str, Any], platform: str) -> bool:
    """Whether a journal record belongs to ``platform``.

    A built-in platform key IS the journal's ``family`` label. A
    ``plugin:<dist>:<provider>`` key is not: every plugin call is filed
    under the ``plugin`` family, and the distribution that supplied the
    tool is in ``source``. The provider half cannot be matched at all —
    the journal records which distribution answered, not which of its
    accounts — so a two-provider bridge matches on both keys, and the tool
    description says so rather than implying a precision that is not there.
    """
    if is_plugin_platform_key(platform):
        return record.get("source") == plugin_distribution(platform)
    return record.get("family") == platform


def _journal_entity_matches(record: dict[str, Any], query: HistoryQuery) -> bool:
    """Best-effort match of a campaign / entity id against a call's args.

    The journal records the ARGUMENTS of a call, not the entities it
    touched, so this reads the three spellings mureo's own tools use
    (``campaign_id``, ``<entity_type>_id``, ``id``). A call that named its
    target some other way does not match — which is why the tool describes
    this as best-effort rather than as an index.
    """
    args = record.get("args")
    if not isinstance(args, dict):
        args = {}
    if query.campaign_id is not None and str(args.get("campaign_id")) != (
        query.campaign_id
    ):
        return False
    if query.entity_id is None:
        return True
    spellings = (f"{query.entity_type}_id", "entity_id", "id")
    return any(str(args.get(key)) == query.entity_id for key in spellings)


def _journal_matches(record: dict[str, Any], query: HistoryQuery) -> bool:
    """Whether one journal record survives every filter."""
    if not record_matches(
        record,
        tool=query.tool,
        since=query.since,
        failures=query.failures_only,
        mutations=query.mutations_only,
        until=query.until,
        batch_id=query.batch_id,
        outcome=query.outcome,
    ):
        return False
    if query.platform is not None and not _journal_platform_matches(
        record, query.platform
    ):
        return False
    return _journal_entity_matches(record, query)


def _journal_section(_path: Path, query: HistoryQuery) -> dict[str, Any]:
    """The ``journal`` section: the newest matches inside the scan bound.

    The path is reported even when the file does not exist: "no journal"
    is only informative if the reader can see WHICH journal was looked for
    — a session started in another directory reads another one. The
    rotated siblings of that path are read too (#758 phase 6) — what was
    rotated away is still what happened — and the scan bound is spent
    over all of them, newest first.
    """
    path = journal.journal_path()
    files = sibling_files(path)
    if not files:
        return {
            "records": [],
            "returned": 0,
            "truncated": False,
            "scanned_lines": 0,
            "skipped_lines": 0,
            "path": str(path),
        }
    tail = read_records_tail_files(files, HISTORY_QUERY_JOURNAL_SCAN_LINES)
    matched = [record for record in tail.records if _journal_matches(record, query)]
    returned = matched[-query.limit :]
    return {
        "records": returned,
        "returned": len(returned),
        "truncated": len(matched) > query.limit,
        "scanned_lines": tail.scanned_lines,
        "skipped_lines": tail.skipped_lines,
        "path": str(path),
    }


# ---------------------------------------------------------------------------
# daily
# ---------------------------------------------------------------------------


def _document_daily(path: Path, query: HistoryQuery) -> dict[str, dict[str, Any]]:
    """The platform's in-window days still inside STATE.json.

    Undated keys are skipped rather than returned: this section is a time
    series, and a key that is not a date has no place on it.
    """
    platforms = read_state_file(path).platforms or {}
    state = platforms.get(str(query.platform))
    stored = getattr(state, "daily", None) or {}
    return {
        day: bucket
        for day, bucket in stored.items()
        if _DAILY_DATE_KEY_RE.match(day) and _in_window(_iso_date(day), query)
    }


def _daily_lookback_since(until: date | None) -> date:
    """The first day of the default lookback, anchored on ``until`` or today.

    Anchored on ``until`` when there is one, so "the second half of last
    year" answers from around last year rather than from an empty window
    twelve months before today.
    """
    anchor = until or clock.server_now().date()
    months = (
        anchor.year * 12
        + anchor.month
        - 1
        - (HISTORY_QUERY_DAILY_DEFAULT_LOOKBACK_MONTHS - 1)
    )
    return date(months // 12, months % 12 + 1, 1)


def _daily_section(path: Path, query: HistoryQuery) -> dict[str, Any]:
    """The ``daily`` section: archive and document as one series.

    STATE.json wins for a day held in both. The archive is written BEFORE
    the trimming document write (#758 phase 4a), so a day can legitimately
    be in both places — and the document's copy is the one every other
    reader, the dashboard included, is looking at.

    A query with no ``since`` gets the default lookback rather than the
    whole archive, and the section reports the window it answered from:
    a bound the caller cannot see is a bound they will read as "there was
    nothing older". The same window bounds the document half, so the
    series never contradicts the window printed above it.
    """
    platform = str(query.platform)
    defaulted = query.since is None
    window = (
        replace(query, since=_daily_lookback_since(query.until)) if defaulted else query
    )
    archived = read_daily_archive(path, platform, window.since, window.until)
    days = dict(archived.days)
    days.update(_document_daily(path, window))
    ordered = sorted(days.items())
    returned = ordered[-query.limit :]
    section: dict[str, Any] = {
        "platform": platform,
        "window": {
            "since": None if window.since is None else window.since.isoformat(),
            "until": None if window.until is None else window.until.isoformat(),
            "defaulted": defaulted,
        },
        "days": dict(returned),
        "returned": len(returned),
        "truncated": len(ordered) > query.limit,
        "skipped_files": list(archived.skipped_files),
    }
    if not path.exists():
        section["state"] = "missing"
    return section


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


def _reports_section(path: Path, query: HistoryQuery) -> dict[str, Any]:
    """The ``reports`` section: the newest versions of one report kind.

    ``since`` is applied by the ledger reader; ``until`` here, over the
    scanned entries, because the reader has no upper bound of its own.
    """
    read = read_report_history(
        path,
        str(query.kind),
        limit=HISTORY_QUERY_REPORT_SCAN_ENTRIES,
        since=query.since,
    )
    matched = [
        entry
        for entry in read.entries
        if _in_window(_iso_date(entry.get("recorded_at")), query)
    ]
    returned = matched[-query.limit :]
    return {
        "kind": query.kind,
        "entries": list(returned),
        "returned": len(returned),
        "truncated": len(matched) > query.limit,
        "skipped_lines": read.skipped_lines,
    }


_SECTIONS: dict[str, Callable[[Path, HistoryQuery], dict[str, Any]]] = {
    "action_log": _action_log_section,
    "journal": _journal_section,
    "daily": _daily_section,
    "reports": _reports_section,
}


async def handle_history_query(arguments: dict[str, Any]) -> list[TextContent]:
    """Answer one bounded question about the past, over the asked sources.

    The response leads with the effective query — defaults resolved — so a
    short answer can be told apart from a mis-filtered one without a
    second call.
    """
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    query = build_history_query(arguments)
    payload: dict[str, Any] = {"query": query.echo()}
    for source in query.sources:
        payload[source] = _SECTIONS[source](path, query)
    return _json_result(payload)


__all__ = [
    "HISTORY_DEFAULT_SOURCES",
    "HISTORY_QUERY_DAILY_DEFAULT_LOOKBACK_MONTHS",
    "HISTORY_QUERY_DEFAULT_LIMIT",
    "HISTORY_QUERY_JOURNAL_SCAN_LINES",
    "HISTORY_QUERY_MAX_LIMIT",
    "HISTORY_QUERY_REPORT_SCAN_ENTRIES",
    "HISTORY_SOURCES",
    "HistoryQuery",
    "build_history_query",
    "handle_history_query",
]
