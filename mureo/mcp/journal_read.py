"""Reading ``JOURNAL.jsonl`` back (#758, phase 4b).

The journal's only reader used to be three private functions inside
``mureo journal`` (:mod:`mureo.cli.journal_cmd`). ``mureo_history_query``
asks the same file the same questions, and a second reader is a second
answer to "does this record match" — so the parse, the date and the
filter live here, and the command imports them.

Two rules the readers here keep:

- **a malformed line is counted, never fatal.** The journal is appended by
  a best-effort writer, so a crash can leave a half-written final line.
  Refusing the file over one bad line would cost the caller the other ten
  thousand;
- **a bounded read is available.** :func:`read_records_tail` returns the
  LAST ``max_lines`` records by seeking from the end, because the journal
  grows one line per tool call. A tool that read the whole file would
  grow with the workspace; the CLI keeps reading it whole, which is the
  right trade for a command an operator ran on purpose.
- **the record is more than one file.** Since #758 phase 6 a full journal
  is rotated away (:mod:`mureo.core.rotation`), so both readers have a
  multi-file form — :func:`read_records_files` and
  :func:`read_records_tail_files` — that walks the files of one record
  oldest first. The tail form spends its line budget newest file first,
  so the bound is on the whole read rather than on each file.

Deliberately dependency-free: ``mureo.cli.main`` imports the command at
startup, and every module this one imports is paid for on every ``mureo``
invocation (#486).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

#: How much of the file one seek-and-read step pulls back. Big enough that
#: a few hundred journal lines come back in one read, small enough that the
#: tail of a huge file is never loaded whole.
TAIL_BLOCK_BYTES = 65536

#: How many TAIL lines of the journal one bounded read may look at,
#: counted across the live file and its rotated siblings. Lives here
#: because BOTH bounded readers use it — ``mureo_history_query`` and
#: ``mureo journal --all`` — and two bounds on the same file would drift
#: into two different answers to "is that everything?".
JOURNAL_SCAN_LINES = 20_000


@dataclass(frozen=True, eq=False)
class JournalTail:
    """The tail of a journal: what parsed, how much was looked at.

    ``scanned_lines`` is part of the answer rather than a log line: a
    bounded read that found nothing has to be distinguishable from an
    exhaustive one that found nothing, or "no such call was ever made"
    gets reported from a window that never reached it.

    ``eq=False`` with ``frozen=True`` for the same reason as
    :class:`mureo.context.history.DailyArchiveRead`: a generated ``__hash__``
    over a list field would raise in whatever set or cache a caller put the
    result in.
    """

    records: list[dict[str, Any]]
    scanned_lines: int
    skipped_lines: int


def read_records(path: Path) -> tuple[list[dict[str, Any]], int]:
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


def read_records_files(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], int]:
    """:func:`read_records` over several files, in the order given.

    Paths that do not exist are skipped: the caller is enumerating what a
    rotation left behind, and a file that was moved or archived away
    between the listing and the read is not an error.
    """
    records: list[dict[str, Any]] = []
    skipped = 0
    for path in paths:
        if not path.exists():
            continue
        found, unparseable = read_records(path)
        records.extend(found)
        skipped += unparseable
    return records, skipped


def record_date(record: dict[str, Any]) -> date | None:
    """The record's UTC date, or ``None`` when its ``ts`` is unusable."""
    try:
        parsed = datetime.fromisoformat(str(record.get("ts", "")))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date()


def record_matches(
    record: dict[str, Any],
    *,
    tool: str | None,
    since: date | None,
    failures: bool,
    mutations: bool,
    until: date | None = None,
    batch_id: str | None = None,
    family: str | None = None,
    outcome: str | None = None,
) -> bool:
    """Whether ``record`` survives every filter that was asked for.

    The four required parameters are the command's, unchanged. The four
    keyword ones default to off, so a caller that does not ask for them
    gets exactly the pre-#758-phase-4b answer.
    """
    if tool is not None and record.get("tool") != tool:
        return False
    if family is not None and record.get("family") != family:
        return False
    if batch_id is not None and record.get("batch_id") != batch_id:
        return False
    if outcome is not None and record.get("outcome") != outcome:
        return False
    if failures and record.get("outcome") == "ok":
        return False
    if mutations and record.get("mutating") is not True:
        return False
    if since is None and until is None:
        return True
    recorded = record_date(record)
    # A record with no usable timestamp cannot be shown to be inside a
    # window, so a dated filter excludes it rather than guessing.
    if recorded is None:
        return False
    if since is not None and recorded < since:
        return False
    return not (until is not None and recorded > until)


def _tail_bytes(path: Path, max_lines: int) -> bytes:
    """The smallest run of trailing bytes that holds ``max_lines`` lines.

    Read backwards in blocks until one more newline than asked for has been
    seen: that extra newline is what guarantees the oldest line in the run
    is COMPLETE, so :func:`tail_lines` can drop the partial one the seek
    landed in the middle of.
    """
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        chunks: list[bytes] = []
        newlines = 0
        while position > 0 and newlines <= max_lines:
            step = min(TAIL_BLOCK_BYTES, position)
            position -= step
            handle.seek(position)
            block = handle.read(step)
            newlines += block.count(b"\n")
            chunks.append(block)
    return b"".join(reversed(chunks))


def tail_lines(path: Path, max_lines: int) -> list[str]:
    """The last ``max_lines`` lines of ``path``, oldest first.

    Split on ``\\n`` rather than with ``splitlines()``: the journal is
    written with ``ensure_ascii=False``, so a record can legitimately carry
    a raw U+2028 that ``splitlines()`` would treat as a line break and cut
    a valid record in half. A trailing ``\\r`` is stripped, so a file
    written with CRLF reads the same as one without.

    Raises:
        ValueError: ``max_lines`` is below 1.
    """
    if max_lines < 1:
        raise ValueError(f"max_lines must be at least 1; got {max_lines}")
    data = _tail_bytes(path, max_lines)
    if data.endswith(b"\n"):
        data = data[:-1]
    if not data:
        return []
    # Decoded AFTER the blocks are joined, so the only place a multi-byte
    # character can be cut is the start of the oldest block — which is in
    # the partial line the slice below drops.
    lines = [
        chunk.decode("utf-8", "replace").rstrip("\r") for chunk in data.split(b"\n")
    ]
    return lines[-max_lines:]


def read_records_tail(path: Path, max_lines: int) -> JournalTail:
    """Parse the last ``max_lines`` lines of ``path``, oldest first.

    ``scanned_lines`` counts the non-empty lines that were looked at, so a
    caller can report the bound it actually read under; ``skipped_lines``
    counts the ones that did not parse into an object.
    """
    records: list[dict[str, Any]] = []
    scanned = 0
    skipped = 0
    for raw in tail_lines(path, max_lines):
        line = raw.strip()
        if not line:
            continue
        scanned += 1
        try:
            record = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            skipped += 1
    return JournalTail(records=records, scanned_lines=scanned, skipped_lines=skipped)


def read_records_tail_files(paths: Sequence[Path], max_lines: int) -> JournalTail:
    """The last ``max_lines`` records across ``paths``, oldest first.

    ``paths`` is oldest file first (what
    :func:`~mureo.core.rotation.sibling_files` returns) and is consumed
    in reverse, so the newest file spends the budget first and an older
    one is opened only if lines are left. The bound is on the whole read,
    not on each file: a caller that asked for 20 000 lines gets 20 000,
    however many files they are spread over.

    Raises:
        ValueError: ``max_lines`` is below 1.
    """
    if max_lines < 1:
        raise ValueError(f"max_lines must be at least 1; got {max_lines}")
    remaining = max_lines
    tails: list[JournalTail] = []
    for path in reversed(paths):
        if remaining < 1:
            break
        if not path.exists():
            continue
        tail = read_records_tail(path, remaining)
        tails.append(tail)
        remaining -= tail.scanned_lines
    records: list[dict[str, Any]] = []
    for tail in reversed(tails):
        records.extend(tail.records)
    return JournalTail(
        records=records,
        scanned_lines=sum(tail.scanned_lines for tail in tails),
        skipped_lines=sum(tail.skipped_lines for tail in tails),
    )


__all__ = [
    "JOURNAL_SCAN_LINES",
    "TAIL_BLOCK_BYTES",
    "JournalTail",
    "read_records",
    "read_records_files",
    "read_records_tail",
    "read_records_tail_files",
    "record_date",
    "record_matches",
    "tail_lines",
]
