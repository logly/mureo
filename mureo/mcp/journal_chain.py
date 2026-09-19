"""The journal's hash chain and its append (#758, phase 6).

``JOURNAL.jsonl`` is append-only by contract, and nothing enforced it. A
line could be edited or removed with a text editor and the file would
still read as the complete record of what an agent did — which is
exactly the claim the journal exists to support.

Each record therefore ends with two keys:

- ``prev`` — the SHA-256 of the previous PHYSICAL line (its bytes,
  without the trailing newline); ``""`` for the first line ever written;
- ``h`` — the SHA-256 of the record itself, serialised exactly as the
  line is but without ``h``. Since ``h`` is written last, that is the
  line minus its own hash — computed by re-serialising, never by string
  surgery, so the two can never drift.

The chain continues **across rotation** (:mod:`mureo.core.rotation`): the
first line of a new file points at the last line of the file that was
retired, so :func:`verify_chain` walks a workspace's journal files as one
sequence.

What this proves, and what it does not
--------------------------------------
Editing a line, removing a line, or splicing one in is detectable
wherever it happens, because every later line names what came before it.
**Truncating the tail is not.** Dropping the last N lines leaves a
shorter chain that is still internally consistent, and detecting that
needs an anchor kept somewhere the same writer cannot reach — which a
local-first tool does not have. :func:`verify_chain` reports what it can
prove and nothing more; ``tests/test_journal_chain.py`` pins the limit so
it cannot quietly be overstated later.

Lines written before phase 6 (``v: 1``) carry neither key. They are
counted as ``unchained`` and are not a break: nothing can be proved about
them, and calling a pre-upgrade workspace tampered-with would be a false
accusation.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from mureo.core.rotation import max_append_bytes, rotate_if_over, sibling_files
from mureo.fsutil import file_lock, lock_path_for, secure_chmod

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

#: The two keys a chained record ends with, in this order.
CHAIN_PREV_KEY = "prev"
CHAIN_HASH_KEY = "h"

#: Why a chain does not hold at some line.
BREAK_PREV_MISMATCH = "prev_mismatch"
BREAK_HASH_MISMATCH = "hash_mismatch"
BREAK_UNPARSEABLE = "unparseable"

#: Internal marker for a pre-phase-6 line: not a break, but not a link.
_UNCHAINED = "unchained"

#: How much of the tail one seek-and-read step pulls back while looking
#: for the last line. Doubled on every further step, so a record larger
#: than one block is still read WHOLE (hashing only the part a single
#: read landed on would invent a hash that matches nothing) without ever
#: reading a whole file to append one line.
TAIL_BLOCK_BYTES = 65536


@dataclass(frozen=True)
class ChainReport:
    """What a walk of one journal's files found.

    ``first_break`` is ``(file, 1-based line number, why)``; the scan
    continues past it so the record counts stay complete, but only the
    first one is reported — everything after a break is a consequence of
    it, not independent evidence.
    """

    files: int
    records: int
    unchained: int
    first_break: tuple[Path, int, str] | None

    @property
    def ok(self) -> bool:
        """Whether the chain holds everywhere it could be checked."""
        return self.first_break is None


def canonical_json(record: dict[str, Any]) -> str:
    """The record serialised exactly as a journal line is."""
    return json.dumps(record, ensure_ascii=False, default=str)


def record_hash(record: dict[str, Any]) -> str:
    """SHA-256 of ``record`` without its own ``h`` key."""
    without_hash = {
        key: value for key, value in record.items() if key != CHAIN_HASH_KEY
    }
    return hashlib.sha256(canonical_json(without_hash).encode("utf-8")).hexdigest()


def last_line(path: Path) -> bytes | None:
    """The final non-empty line of ``path``, newline stripped.

    Read backwards from the end so appending does not cost a full-file
    read, and in growing blocks so a line bigger than one block is still
    returned in full. ``None`` when the file is absent, empty, or holds
    nothing but newlines.
    """
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            step = TAIL_BLOCK_BYTES
            data = b""
            while position > 0:
                read = min(step, position)
                position -= read
                handle.seek(position)
                data = handle.read(read) + data
                trimmed = data.rstrip(b"\n")
                cut = trimmed.rfind(b"\n")
                if cut >= 0:
                    return trimmed[cut + 1 :]
                step *= 2
    except OSError:
        return None
    return data.rstrip(b"\n") or None


def last_line_hash(path: Path) -> str | None:
    """SHA-256 of ``path``'s final non-empty line, or ``None``."""
    line = last_line(path)
    return None if line is None else hashlib.sha256(line).hexdigest()


def _previous_hash(path: Path) -> str:
    """What the next line appended to ``path`` must point at.

    The live file's last line, or — when it was just rotated away, or has
    not been created yet — the last line of the newest rotated file, so
    the chain survives rotation. ``""`` when there is no record at all.
    """
    digest = last_line_hash(path)
    if digest is not None:
        return digest
    for sibling in reversed(sibling_files(path)):
        if sibling == path:
            continue
        digest = last_line_hash(sibling)
        if digest is not None:
            return digest
    return ""


def _append_line(path: Path, line: str) -> None:
    """Append ``line`` to ``path``, creating it owner-only."""

    # Create the file 0600 from the start (no world-readable window
    # between create and a later chmod); chmod stays as belt-and-braces
    # for a pre-existing file with looser perms. Same trick as
    # ``plugin_audit``.
    def _opener(target: str, flags: int) -> int:
        return os.open(target, flags | os.O_APPEND | os.O_CREAT, 0o600)

    with open(path, "a", encoding="utf-8", opener=_opener) as handle:
        handle.write(line)
    secure_chmod(path)


def chain_append(path: Path, record: dict[str, Any]) -> None:
    """Append ``record`` to ``path`` as the next link of the chain.

    Rotation, the read of the previous hash and the append are one
    critical section under ``<path>.lock``: two writers that computed
    ``prev`` from the same line would otherwise both claim to follow it,
    and the chain would report a break that nobody caused.

    ``record`` is not modified — the two chain keys are added to a copy,
    so a caller can keep using what it built.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock_path_for(path)):
        rotate_if_over(
            path, max_bytes=max_append_bytes(), now=datetime.now(timezone.utc)
        )
        chained = {**record, CHAIN_PREV_KEY: _previous_hash(path)}
        chained[CHAIN_HASH_KEY] = record_hash(chained)
        _append_line(path, canonical_json(chained) + "\n")


def _check_line(line: bytes, expected: str) -> str | None:
    """Why ``line`` does not continue the chain, or ``None`` if it does."""
    try:
        record = json.loads(line)
    except ValueError:
        return BREAK_UNPARSEABLE
    if not isinstance(record, dict):
        return BREAK_UNPARSEABLE
    if CHAIN_PREV_KEY not in record or CHAIN_HASH_KEY not in record:
        return _UNCHAINED
    if record[CHAIN_PREV_KEY] != expected:
        return BREAK_PREV_MISMATCH
    if record_hash(record) != record[CHAIN_HASH_KEY]:
        return BREAK_HASH_MISMATCH
    return None


def _scan_file(
    path: Path, expected: str
) -> tuple[int, int, tuple[int, str] | None, str]:
    """Walk one file: records, unchained, first break, trailing hash.

    The returned hash is what the next line — in this file or the next
    one — has to point at, which is how continuity across a rotation is
    checked without re-reading anything.
    """
    records = 0
    unchained = 0
    first: tuple[int, str] | None = None
    number = 0
    with path.open("rb") as handle:
        for raw in handle:
            number += 1
            line = raw.rstrip(b"\n")
            if not line.strip():
                continue
            records += 1
            why = _check_line(line, expected)
            expected = hashlib.sha256(line).hexdigest()
            if why == _UNCHAINED:
                unchained += 1
            elif why is not None and first is None:
                first = (number, why)
    return records, unchained, first, expected


def verify_chain(paths: Iterable[Path]) -> ChainReport:
    """Check the chain over ``paths``, oldest file first.

    Files that do not exist are skipped rather than refused: a caller
    passing :func:`~mureo.core.rotation.sibling_files` of a workspace
    with no journal yet is asking a fair question with an empty answer.
    """
    files = 0
    records = 0
    unchained = 0
    first_break: tuple[Path, int, str] | None = None
    expected = ""
    for path in paths:
        if not path.exists():
            continue
        files += 1
        count, loose, first, expected = _scan_file(path, expected)
        records += count
        unchained += loose
        if first is not None and first_break is None:
            first_break = (path, first[0], first[1])
    return ChainReport(
        files=files, records=records, unchained=unchained, first_break=first_break
    )


__all__ = [
    "BREAK_HASH_MISMATCH",
    "BREAK_PREV_MISMATCH",
    "BREAK_UNPARSEABLE",
    "CHAIN_HASH_KEY",
    "CHAIN_PREV_KEY",
    "TAIL_BLOCK_BYTES",
    "ChainReport",
    "canonical_json",
    "chain_append",
    "last_line",
    "last_line_hash",
    "record_hash",
    "verify_chain",
]
