"""Size-bounded append-only files (#758, phase 6).

``JOURNAL.jsonl`` gains a line per tool call and
``history/reports/<kind>.jsonl`` a line per report version. Both are
append-only on purpose — a record you can rewrite is not a record — and
until this module neither had a ceiling, so a long-lived workspace paid
for its own history on every read and, eventually, on its disk.

Rotation rather than truncation, for the same reason: the bound is on the
size of ONE file, never on how much of the record is kept. A full file is
renamed out of the way with the UTC instant it was retired at in its name
(``JOURNAL.20260919T013000Z.jsonl``) and the writer starts a fresh one.
Nothing is deleted by mureo, ever — what an operator does with a rotated
file (archive it, ship it, delete it) is their decision to make.

:func:`sibling_files` is what keeps the record whole for readers: it
enumerates the rotated files of a path plus the live file, oldest first,
matching ONLY the names this module writes. A ``JOURNAL.jsonl.bak`` an
operator left beside it is not part of the record and is not returned.

One env var, read in one place (:func:`max_append_bytes`):
``MUREO_JOURNAL_MAX_BYTES``. Anything that is not a positive integer is
refused with a single WARNING and the default is used — this is read on
every append, so a bad value must not flood the log, and a file that
stops rotating is a worse answer than a file that ignores the override.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

logger = logging.getLogger(__name__)

#: Ceiling for one append-only file before it is rotated away. 32 MiB is
#: roughly a hundred thousand journal lines: long enough that an ordinary
#: workspace never rotates, small enough that a tail read of a rotated
#: file stays cheap.
DEFAULT_MAX_BYTES = 32 * 1024 * 1024

#: The only environment override, and the only place it is read.
MAX_BYTES_ENV_VAR = "MUREO_JOURNAL_MAX_BYTES"

#: ``strftime`` form of the instant a file was retired at: UTC, second
#: precision, no separators — so the names sort chronologically as text.
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"

#: The same shape as a pattern, for reading the names back.
_STAMP_PATTERN = r"\d{8}T\d{6}Z"

#: Set once the invalid-override warning has been issued (see the module
#: docstring): this function runs on every append.
_env_warning_issued = False


def max_append_bytes() -> int:
    """The configured ceiling for one append-only file, in bytes."""
    global _env_warning_issued
    raw = os.environ.get(MAX_BYTES_ENV_VAR)
    if raw is None:
        return DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value > 0:
        return value
    if not _env_warning_issued:
        _env_warning_issued = True
        logger.warning(
            "%s must be a positive integer number of bytes; got %r — "
            "using the default of %d",
            MAX_BYTES_ENV_VAR,
            raw,
            DEFAULT_MAX_BYTES,
        )
    return DEFAULT_MAX_BYTES


def rotated_name(path: Path, when: datetime) -> Path:
    """A free name to retire ``path`` under, stamped with ``when``.

    ``JOURNAL.jsonl`` -> ``JOURNAL.<stamp>.jsonl`` in the same directory.
    A name already taken (two rotations inside one second, or a restored
    archive) gets ``-1``, ``-2`` … appended to the stamp, so a rotation
    can never overwrite an earlier one.
    """
    stem, suffix = path.stem, path.suffix
    stamp = when.strftime(STAMP_FORMAT)
    candidate = path.with_name(f"{stem}.{stamp}{suffix}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{stem}.{stamp}-{counter}{suffix}")
        counter += 1
    return candidate


def rotate_if_over(path: Path, *, max_bytes: int, now: datetime) -> Path | None:
    """Retire ``path`` when it has reached ``max_bytes``; else do nothing.

    Returns the name the file was moved to, or ``None`` when it was under
    the ceiling or is not there at all. The move is an ``os.replace``, so
    a reader holding the file open keeps reading what it opened and the
    next append creates a fresh file.

    The caller holds the lock. This is half of a read-modify-write on the
    directory entry, and two writers rotating the same file at once would
    otherwise both decide it is full.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size < max_bytes:
        return None
    target = rotated_name(path, now)
    os.replace(path, target)
    return target


def _rotated_pattern(path: Path) -> re.Pattern[str]:
    """Matches exactly the names :func:`rotated_name` writes for ``path``."""
    return re.compile(
        rf"^{re.escape(path.stem)}\.({_STAMP_PATTERN})(?:-(\d+))?"
        rf"{re.escape(path.suffix)}$"
    )


def sibling_files(path: Path) -> list[Path]:
    """Every file holding part of ``path``'s record, oldest first.

    The rotated files in ``path``'s directory followed by ``path`` itself
    when it exists — which is the order a reader walks them in to see one
    continuous record. Only names this module wrote are included: a
    ``.bak``, a ``.lock`` or another file's rotation is not part of it.
    """
    pattern = _rotated_pattern(path)
    stamped: list[tuple[str, int, Path]] = []
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        match = pattern.match(entry.name)
        if match is not None and entry.is_file():
            stamped.append((match.group(1), int(match.group(2) or 0), entry))
    files = [entry for _, _, entry in sorted(stamped, key=lambda item: item[:2])]
    if path.exists():
        files.append(path)
    return files


__all__ = [
    "DEFAULT_MAX_BYTES",
    "MAX_BYTES_ENV_VAR",
    "STAMP_FORMAT",
    "max_append_bytes",
    "rotate_if_over",
    "rotated_name",
    "sibling_files",
]
