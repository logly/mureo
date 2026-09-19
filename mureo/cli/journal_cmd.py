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

The parse, the date and the filter themselves live in
:mod:`mureo.mcp.journal_read`, shared with ``mureo_history_query`` (#758
phase 4b) so the CLI and the tool cannot disagree about what matches.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from datetime import date

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

#: Anything that would stop the cell being one line of plain text.
#:
#: Three passes, in order. ANSI escape sequences go WHOLE — dropping only
#: the leading ``\x1b`` would leave ``[31m`` sitting in the operator's
#: table as literal text. Then the remaining C0/C1 control characters,
#: then runs of whitespace. All of it matters for a table built by padding
#: strings: a newline breaks the column alignment of every row after it,
#: and an escape sequence written by a model recolours or repositions the
#: terminal of whoever reads the journal back.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_WHITESPACE = re.compile(r"\s+")

_HEADERS = (
    "ts",
    "outcome",
    "tool",
    "family",
    "ms",
    "batch_id",
    "reason/rationale",
)

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


def _explanation(record: dict[str, Any]) -> str:
    """The one sentence this row is worth showing, by outcome.

    A failure explains ITSELF — that is what the operator scanning the
    table is looking for, and it must not be displaced by the agent's
    rationale for attempting it. A successful call has nothing to explain,
    so the column shows WHY the change was made instead (#758 phase 2).
    Both readings are in ``--json`` in full, under their own keys.

    Flattened to one line of printable text before the caller truncates
    it: this is model-written prose in a column built by padding strings.
    """
    if record.get("outcome") != "ok":
        text = str(record.get("reason") or "")
    else:
        text = str(record.get("rationale") or "")
    return _WHITESPACE.sub(" ", _UNPRINTABLE.sub(" ", _ANSI.sub("", text))).strip()


def _row(record: dict[str, Any]) -> tuple[str, ...]:
    reason = _explanation(record)
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

    # The parse and the filter are shared with ``mureo_history_query``
    # (#758 phase 4b): one file must not have two answers to "does this
    # record match". Imported here, like ``journal_path``, because
    # ``mureo.mcp`` pulls the whole MCP server in at package import (#486).
    from mureo.mcp.journal_read import read_records, record_matches

    target = Path(path) if path is not None else journal_path()
    if not target.exists():
        # Not an error: a workspace where no tool has run yet, or an
        # operator who opted out, has no journal and that is a normal state.
        typer.echo(f"no journal at {target}")
        return

    cutoff = _parse_since(since)
    records, skipped = read_records(target)
    kept = [
        record
        for record in records
        if record_matches(
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
