"""``mureo journal --verify`` — check the journal's hash chain (#758 p6).

Split out of :mod:`mureo.cli.journal_cmd` so the command file stays the
option wiring it has always been. What the chain proves (and the one
thing it does not — a truncated tail) is documented on
:mod:`mureo.mcp.journal_chain`; this module only reports it.

The file listing is counted here rather than taken from the report,
because :class:`~mureo.mcp.journal_chain.ChainReport` is a verdict about
one chain, not a per-file tally — and an operator reading "chain BROKEN
at JOURNAL.jsonl:812" needs to see which files were walked to get there.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.mcp.journal_chain import ChainReport

#: Exit codes, so "is the chain intact" is scriptable without parsing text.
EXIT_OK = 0
EXIT_BROKEN = 1
EXIT_NO_JOURNAL = 2


def _record_count(path: Path) -> int:
    """Non-empty lines in ``path`` — what the chain counts as records."""
    with path.open("rb") as handle:
        return sum(1 for raw in handle if raw.strip())


def _as_dict(report: ChainReport) -> dict[str, Any]:
    """The report as JSON, with the break named rather than positional."""
    first_break = None
    if report.first_break is not None:
        path, line, why = report.first_break
        first_break = {"file": str(path), "line": line, "why": why}
    return {
        "files": report.files,
        "records": report.records,
        "unchained": report.unchained,
        "first_break": first_break,
        "ok": report.ok,
    }


def _print_report(files: list[Path], report: ChainReport) -> None:
    """One line per file, then the verdict."""
    for path in files:
        typer.echo(f"{path.name}: {_record_count(path)} records")
    if report.unchained:
        # Stated, never counted against the file: a line written before
        # the chain existed cannot be checked, and refusing to say so
        # would read as "checked, and fine".
        typer.echo(
            f"{report.unchained} unchained v1 record(s) "
            "(written before the chain existed)"
        )
    if report.first_break is None:
        typer.echo("chain ok")
        return
    path, line, why = report.first_break
    typer.echo(f"chain BROKEN at {path.name}:{line} ({why})")


def verify_command(target: Path, *, as_json: bool) -> int:
    """Verify ``target`` and its rotated siblings; return the exit code.

    Every file of the record is walked as ONE chain, oldest first, so a
    line removed either side of a rotation is caught.
    """
    from mureo.core.rotation import sibling_files
    from mureo.mcp.journal_chain import verify_chain

    files = sibling_files(target)
    if not files:
        typer.echo(f"no journal at {target}")
        return EXIT_NO_JOURNAL
    report = verify_chain(files)
    if as_json:
        typer.echo(json.dumps(_as_dict(report), ensure_ascii=False))
    else:
        _print_report(files, report)
    return EXIT_OK if report.ok else EXIT_BROKEN


__all__ = ["EXIT_BROKEN", "EXIT_NO_JOURNAL", "EXIT_OK", "verify_command"]
