"""``mureo journal`` — read back the dispatcher journal (#758).

Every MCP tool call leaves one line in ``JOURNAL.jsonl``
(:mod:`mureo.mcp.journal`); this is the operator's way to read it without
a JSON tool. Read-only: the file is never rewritten, compacted or
rotated by this command.

Two shapes of question, two output modes:

- the default table answers "what happened, and what failed" at a glance;
- ``--json`` emits the matching records verbatim, one per line, for
  ``jq`` and for an agent that wants the masked arguments.

**Malformed lines are skipped, never fatal.** The journal is appended by
a best-effort writer, so a crash can leave a half-written final line.
Refusing to read the file for one bad line would cost the operator the
other ten thousand; instead the bad lines are counted and reported on
stderr, so the damage is visible without hiding the rest.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import typer

journal_app = typer.Typer(
    name="journal",
    help="Show the append-only journal of MCP tool calls.",
    invoke_without_command=True,
)

#: How many records the default view keeps. Applied AFTER filtering, so
#: ``--failures --last 20`` means "the last 20 failures", not "the failures
#: among the last 20 calls" — the second is a different, much less useful
#: question that reads identically on the command line.
DEFAULT_LAST = 50

#: Reason column budget. The full text stays in ``--json``.
REASON_WIDTH = 80

_HEADERS = ("ts", "outcome", "tool", "family", "ms", "batch_id", "reason")

_LAST_OPTION = typer.Option(
    DEFAULT_LAST,
    "--last",
    min=1,
    help="Show only the last N matching records (N >= 1).",
)
_TOOL_OPTION = typer.Option(None, "--tool", help="Only this tool name (exact match).")
_SINCE_OPTION = typer.Option(
    None, "--since", help="Only calls on or after this UTC date (YYYY-MM-DD)."
)
_FAILURES_OPTION = typer.Option(
    False, "--failures", help="Only calls whose outcome is not 'ok'."
)
_MUTATIONS_OPTION = typer.Option(
    False, "--mutations", help="Only calls classified as mutations."
)
_JSON_OPTION = typer.Option(
    False, "--json", help="Print the raw records as JSON lines instead of a table."
)
_PATH_OPTION = typer.Option(
    None, "--path", help="Read this journal file instead of the resolved one."
)


def _read_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Return the parsed records and the number of unparseable lines."""
    records: list[dict[str, Any]] = []
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                skipped += 1
    return records, skipped


def _record_date(record: dict[str, Any]) -> date | None:
    """The record's UTC date, or ``None`` when its ``ts`` is unusable."""
    try:
        parsed = datetime.fromisoformat(str(record.get("ts", "")))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date()


def _matches(
    record: dict[str, Any],
    *,
    tool: str | None,
    since: date | None,
    failures: bool,
    mutations: bool,
) -> bool:
    """Whether ``record`` survives every filter that was asked for."""
    if tool is not None and record.get("tool") != tool:
        return False
    if failures and record.get("outcome") == "ok":
        return False
    if mutations and record.get("mutating") is not True:
        return False
    if since is not None:
        recorded = _record_date(record)
        # A record with no usable timestamp cannot be shown to be on or
        # after a date, so a date filter excludes it rather than guessing.
        if recorded is None or recorded < since:
            return False
    return True


def _row(record: dict[str, Any]) -> tuple[str, ...]:
    reason = str(record.get("reason") or "")
    return (
        str(record.get("ts", "")),
        str(record.get("outcome", "")),
        str(record.get("tool", "")),
        str(record.get("family", "")),
        str(record.get("duration_ms", "")),
        str(record.get("batch_id") or "-"),
        reason[:REASON_WIDTH],
    )


def _print_table(records: list[dict[str, Any]]) -> None:
    """Print a plain, colour-free table — the output is read by agents too."""
    rows = [_HEADERS, *(_row(record) for record in records)]
    widths = [max(len(row[index]) for row in rows) for index in range(len(_HEADERS))]
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row, widths, strict=True)]
        typer.echo("  ".join(cells).rstrip())


def _parse_since(since: str | None) -> date | None:
    if since is None:
        return None
    try:
        return datetime.strptime(since, "%Y-%m-%d").date()
    except ValueError:
        typer.echo(f"Error: --since expects YYYY-MM-DD, got {since!r}.", err=True)
        raise typer.Exit(2) from None


@journal_app.callback(invoke_without_command=True)  # type: ignore[untyped-decorator, unused-ignore]
def show_journal(
    last: int = _LAST_OPTION,
    tool: str | None = _TOOL_OPTION,
    since: str | None = _SINCE_OPTION,
    failures: bool = _FAILURES_OPTION,
    mutations: bool = _MUTATIONS_OPTION,
    as_json: bool = _JSON_OPTION,
    path: str | None = _PATH_OPTION,
) -> None:
    """Show recorded MCP tool calls, newest last."""
    from mureo.mcp.journal import journal_path

    target = Path(path) if path is not None else journal_path()
    if not target.exists():
        # Not an error: a workspace where no tool has run yet, or an
        # operator who opted out, has no journal and that is a normal state.
        typer.echo(f"no journal at {target}")
        return

    cutoff = _parse_since(since)
    records, skipped = _read_records(target)
    kept = [
        record
        for record in records
        if _matches(
            record,
            tool=tool,
            since=cutoff,
            failures=failures,
            mutations=mutations,
        )
    ]
    kept = kept[-last:]

    if as_json:
        for record in kept:
            typer.echo(json.dumps(record, ensure_ascii=False))
    elif kept:
        _print_table(kept)
    if skipped:
        typer.echo(f"skipped {skipped} malformed line(s)", err=True)
