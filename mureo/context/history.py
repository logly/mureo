"""What STATE.json loses, kept beside it (#758, phase 4a).

STATE.json is a WORKING document: it is read whole, re-rendered and written
back on every mutation, so it has to stay bounded. Two of its sections pay
for that bound with history —

- ``platforms[<p>].daily`` is trimmed to
  :data:`~mureo.context.daily.DAILY_RETENTION_DAYS` days on every write, so
  the day that falls out of the window is gone;
- ``reports[<kind>]`` is overwritten by every
  :func:`~mureo.context.state.set_report`, so the previous version of a
  verdict is gone.

Both are the right rule for the document and the wrong rule for the record.
This module is where the trimmed and the overwritten go: a ``history/``
directory beside STATE.json that only ever grows, is never read by the
dashboard, and is written on the same lock as the write that would otherwise
have dropped the data.

Layout::

    <workspace>/
      STATE.json
      history/
        daily/2026-08.json      # one file per calendar month, ALL platforms
        reports/weekly.jsonl    # append-only, one version per line

One file per MONTH rather than per platform-and-day, because a platform key
can be ``plugin:<dist>:<provider>`` — turning that into a filename is how a
key ends up escaping its directory, and a month is a name mureo mints itself
from a date it has already validated.

Two rules the writers here do not bend:

- **a file that failed to parse is never overwritten.** Re-writing it would
  delete whatever it holds to tidy a parse error, which is the one outcome an
  archive exists to prevent; :class:`~mureo.context.errors.ContextFileError`
  names the file and the caller's write fails with it;
- **a reader is tolerant instead.** Reading is not the moment to lose an
  answer over one bad file, so :func:`read_daily_archive` skips it and says
  which one it skipped — the caller can report "and one file could not be
  read" rather than quietly returning a short series.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

from mureo.context.errors import ContextFileError
from mureo.context.models import DAILY_DATE_KEY_PATTERN
from mureo.fsutil import file_lock, lock_path_for, secure_chmod

if TYPE_CHECKING:
    from pathlib import Path

#: Directory name, relative to the workspace (``STATE.json``'s parent).
HISTORY_DIRNAME = "history"

#: Schema version carried by every archive file and ledger line.
ARCHIVE_VERSION = 1

_DAILY_SUBDIR = "daily"
_REPORTS_SUBDIR = "reports"

_DAILY_DATE_KEY_RE = re.compile(DAILY_DATE_KEY_PATTERN)
_MONTH_FILE_RE = re.compile(r"^(\d{4}-\d{2})\.json$")

#: What a report kind may look like once it has to name a file: an
#: ALLOWLIST, not a list of the tricks anyone thought of. A blocklist has to
#: predict the next separator, drive-letter or encoding trick; this admits
#: the vocabulary mureo ships (:data:`~mureo.core.report_kinds.REPORT_KINDS`)
#: and refuses everything else by default.
_SAFE_KIND_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, eq=False)
class DailyArchiveRead:
    """Archived days for one platform, plus the files that could not be read.

    ``skipped_files`` is part of the answer, not a log line: a caller that
    renders a series has to be able to say "and 1 month could not be read"
    instead of presenting a gap as a fact about the account.

    ``eq=False`` with ``frozen=True``: a frozen dataclass derives
    ``__hash__`` from its fields, and ``days`` is a dict — so the generated
    hash would raise in whatever cache or set a caller put the result in.
    Identity equality and identity hashing are the honest pair for a
    read result.
    """

    days: dict[str, dict[str, Any]]
    skipped_files: tuple[str, ...]


@dataclass(frozen=True, eq=False)
class ReportHistoryRead:
    """Ledger entries for one report kind, newest last.

    ``skipped_lines`` counts lines that did not parse. An append-only ledger
    can be truncated by a crash mid-write, and losing the whole history to
    one unparseable tail line would be worse than reporting the count.
    """

    entries: tuple[dict[str, Any], ...]
    skipped_lines: int


def history_dir(state_path: Path) -> Path:
    """The ``history/`` directory beside ``state_path``."""
    return state_path.parent / HISTORY_DIRNAME


def _now_iso() -> str:
    """Current time as a timezone-aware ISO 8601 UTC string.

    The same clock and format as ``mureo.context.state._now_iso`` — stated
    here rather than imported, because a private name is not a contract.
    """
    return datetime.now(timezone.utc).isoformat()


def _fsync_dir(parent: Path) -> None:
    """Best-effort fsync of ``parent`` so a rename is durable (POSIX-only)."""
    try:
        dir_fd = os.open(str(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as JSON: temp file -> fsync -> rename, owner-only.

    The same durability pattern STATE.json is written with: fsync the data
    before the rename, so a crash just after ``os.replace`` cannot leave a
    month of history as a zero-length file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    # mkstemp creates 0600; the mode survives the rename, so the archive is
    # never world-readable, not even for the width of a write.
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    secure_chmod(path)
    _fsync_dir(path.parent)


def _append_json_line(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON line to ``path``, creating it owner-only.

    No fsync: this is an append-only ledger and the journal makes the same
    trade — a line lost to a power cut is one version of one report, while
    an fsync per append would be paid by every report write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    def _opener(target: str, flags: int) -> int:
        return os.open(target, flags | os.O_APPEND | os.O_CREAT, 0o600)

    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    with open(path, "a", encoding="utf-8", opener=_opener) as handle:
        handle.write(line)
    secure_chmod(path)


def _month_path(state_path: Path, month: str) -> Path:
    """Path of the ``YYYY-MM`` daily archive file."""
    return history_dir(state_path) / _DAILY_SUBDIR / f"{month}.json"


def validate_report_kind_path(kind: Any) -> str:
    """``kind`` if it can name a file, else a refusal.

    Checked before anything touches the filesystem, and callable on its own
    so a caller can refuse a bad kind BEFORE it takes a lock (see
    :func:`~mureo.context.state.set_report`). A report kind arrives from the
    tool layer, where an ``enum`` bounds it — but this module is public, a
    library caller has no such schema, and ``..`` must not be able to walk
    out of ``history/reports/``.

    Raises:
        ValueError: ``kind`` is not a non-empty ``[A-Za-z0-9._-]`` string, or
            contains ``..``.
    """
    if not isinstance(kind, str) or not kind:
        raise ValueError("report kind must be a non-empty string")
    if ".." in kind or not _SAFE_KIND_RE.match(kind):
        raise ValueError(
            f"report kind {kind!r} cannot name a file: use letters, digits, "
            "'.', '_' or '-' only, and no '..'"
        )
    return kind


def _group_by_month(days: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``days`` split into ``{YYYY-MM: {day: bucket}}``.

    A key that is not ``YYYY-MM-DD`` is refused rather than filed somewhere:
    the month is taken from the key and becomes a filename, so a key nobody
    validated is a path nobody validated.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for day, bucket in sorted(days.items()):
        if not isinstance(day, str) or not _DAILY_DATE_KEY_RE.match(day):
            raise ValueError(
                f"daily key {day!r} is not a date: archive keys are YYYY-MM-DD"
            )
        grouped.setdefault(day[:7], {})[day] = bucket
    return grouped


#: Appended to every refusal to write a month file. A refusal that only
#: says a file is unreadable leaves an operator with no move that does not
#: risk the history; this one names the move and what it costs (nothing).
_ARCHIVE_REMEDY = (
    "move {path} aside (e.g. rename it) to resume archiving; nothing in "
    "STATE.json was changed"
)


def _load_month(path: Path, month: str) -> dict[str, Any]:
    """The existing month archive, or an empty one.

    A file that does not parse — or that parses into something other than an
    archive this version can merge — raises: this function's caller is about
    to REPLACE the file, and overwriting it would delete a month of history
    to tidy a parse error. The refusal names the remedy, because the only
    safe move belongs to the operator: mureo will not divert the write to a
    sibling file, which would scatter one month across two names.
    """
    if not path.exists():
        return {"v": ARCHIVE_VERSION, "month": month, "platforms": {}}
    remedy = _ARCHIVE_REMEDY.format(path=path)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContextFileError(
            f"Failed to read the daily history archive {path}: it is not "
            f"readable JSON, and overwriting it would delete the month it "
            f"holds — {remedy}"
        ) from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("platforms"), dict):
        raise ContextFileError(
            f"Daily history archive {path} is not an archive document "
            f"(expected an object with a 'platforms' map) — {remedy}"
        )
    if loaded.get("v") != ARCHIVE_VERSION:
        # A shape this version does not know how to merge. Refused rather
        # than rewritten in the shape it does know: a newer mureo may have
        # written it, and guessing would rewrite a month it cannot read.
        raise ContextFileError(
            f"Daily history archive {path} declares version "
            f"{loaded.get('v')!r}, not {ARCHIVE_VERSION}: this version cannot "
            f"merge into it — {remedy}"
        )
    loaded["month"] = month
    return loaded


def archive_platform_daily(
    state_path: Path,
    platform: str,
    account_id: str,
    days: dict[str, dict[str, Any]],
) -> list[Path]:
    """File ``days`` under ``history/daily/<YYYY-MM>.json``. Returns the files.

    Called with the days a STATE.json write is about to trim away, so it runs
    BEFORE the trimming write and on the same lock (see
    :func:`~mureo.context.state.set_platform_daily`). Merge rules mirror the
    document's: a day this call supplies REPLACES that day's bucket, so
    re-archiving is idempotent; every other day, and every other platform in
    the file, is preserved.

    Buckets are archived exactly as stored, ``fetched_at`` included — the
    archive is a record of what was written, not a second opinion about it.
    ``account_id`` is the writing call's, so a platform key whose account
    changed shows the latest one against the whole month.

    Read-modify-write per month file, so a caller that can race another
    writer must hold the state lock — the STATE.json route does (the archive
    runs inside ``_locked_state_mutation``). Archiving BEFORE the trimming
    write also means a document write that then fails leaves a day in both
    places rather than in neither: the archive over-reports, which is the
    safe direction for a record.

    Raises:
        ValueError: a key is not ``YYYY-MM-DD``.
        ContextFileError: an existing month file could not be read.
    """
    written: list[Path] = []
    for month, month_days in _group_by_month(days).items():
        path = _month_path(state_path, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Its OWN sidecar lock, not STATE.json's: the #710 downstream writer
        # holds the lock of the document IT writes, which is not this
        # workspace's STATE.json, so the state lock would not serialise it.
        # A different lock file also means the state route — already holding
        # STATE.json.lock — cannot deadlock against itself here.
        with file_lock(lock_path_for(path)):
            _merge_month(path, month, platform, account_id, month_days)
        written.append(path)
    return written


def _merge_month(
    path: Path,
    month: str,
    platform: str,
    account_id: str,
    month_days: dict[str, Any],
) -> None:
    """Merge ``month_days`` into one month file. Call under its lock."""
    archive = _load_month(path, month)
    platforms: dict[str, Any] = archive["platforms"]
    block = platforms.get(platform)
    existing = block.get("days") if isinstance(block, dict) else None
    stored = dict(existing) if isinstance(existing, dict) else {}
    stored.update(month_days)
    platforms[platform] = {
        "account_id": account_id,
        "days": dict(sorted(stored.items())),
    }
    _atomic_write_json(path, archive)


def _month_files_in_range(
    state_path: Path, since: date | None, until: date | None
) -> list[Path]:
    """The archive files whose month can hold a day in ``[since, until]``.

    Selected by NAME, so a month outside the window is never opened — a
    workspace can hold years of archives and a question about one week must
    not read all of them.
    """
    directory = history_dir(state_path) / _DAILY_SUBDIR
    if not directory.is_dir():
        return []
    selected = []
    for path in sorted(directory.iterdir()):
        match = _MONTH_FILE_RE.match(path.name)
        if match is None:
            continue
        month = match.group(1)
        if since is not None and month < since.strftime("%Y-%m"):
            continue
        if until is not None and month > until.strftime("%Y-%m"):
            continue
        selected.append(path)
    return selected


def _read_month_days(path: Path, platform: str) -> dict[str, Any] | None:
    """One platform's days out of a month file, or ``None`` if unreadable.

    ``None`` covers every reason the file cannot be trusted: unreadable,
    unparseable, not an archive document, or a ``v`` this version does not
    know — a newer shape must be REPORTED as skipped, never read as though
    its fields meant what they mean today. The caller names it to the user.
    """
    try:
        archive = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(archive, dict) or archive.get("v") != ARCHIVE_VERSION:
        return None
    platforms = archive.get("platforms")
    if not isinstance(platforms, dict):
        return None
    block = platforms.get(platform)
    days = block.get("days") if isinstance(block, dict) else None
    return days if isinstance(days, dict) else {}


def _day_in_range(day: str, since: date | None, until: date | None) -> bool:
    """Whether ``day`` falls inside the (inclusive, optional) bounds."""
    if since is None and until is None:
        return True
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        # A key that cannot be placed on a timeline cannot be said to fall
        # inside a window; it is still returned by an unbounded read.
        return False
    return (since is None or parsed >= since) and (until is None or parsed <= until)


def read_daily_archive(
    state_path: Path,
    platform: str,
    since: date | None = None,
    until: date | None = None,
) -> DailyArchiveRead:
    """Archived days for ``platform`` between ``since`` and ``until``.

    Both bounds are inclusive and either may be omitted. The result is sorted
    by day and holds only days this platform has in the archive — days still
    inside STATE.json's retention window live in the document, not here.

    Tolerant: a month file that does not parse is skipped and its name is
    returned in ``skipped_files`` rather than raising, because one bad file
    must not cost the caller every other month.
    """
    days: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    for path in _month_files_in_range(state_path, since, until):
        stored = _read_month_days(path, platform)
        if stored is None:
            skipped.append(path.name)
            continue
        for day, bucket in stored.items():
            if _day_in_range(day, since, until):
                days[day] = bucket
    return DailyArchiveRead(
        days=dict(sorted(days.items())), skipped_files=tuple(skipped)
    )


def append_report_history(state_path: Path, kind: str, summary: dict[str, Any]) -> Path:
    """Append one version of a report to ``history/reports/<kind>.jsonl``.

    Called by :func:`~mureo.context.state.set_report` for EVERY write,
    including the one that stays in STATE.json — so the ledger on its own is
    the complete series, and a reader never has to join it with the document
    to find the latest version.

    The line records who wrote it: the process ``session_id`` (which joins it
    to the journal's records and to ``action_log`` entries of the same
    session) and the MCP client label when one is known. ``client`` is
    omitted rather than written ``null`` when it is not — a CLI run has no
    client, and an absent key says that more honestly than a null does.

    Appended before the document write it belongs to, so a write that then
    fails leaves a version in the ledger that STATE.json never adopted. That
    is the deliberate direction: a record that over-reports can be
    reconciled, one that silently missed a version cannot.

    A ledger that has reached the size bound is rotated away first (#758
    phase 6, :mod:`mureo.core.rotation`) and this line starts a fresh
    file. The bound is on one file, never on the history:
    :func:`read_report_history` reads the rotated files too.

    Raises:
        ValueError: ``kind`` cannot name a file.
    """
    # Imported here, not at module scope: ``mureo.core.__init__`` reaches
    # ``mureo.context.state``, which imports this module, so a module-level
    # import would close a cycle.
    from mureo.core.actor import client_info, session_id
    from mureo.core.rotation import max_append_bytes, rotate_if_over

    safe_kind = validate_report_kind_path(kind)
    entry: dict[str, Any] = {
        "v": ARCHIVE_VERSION,
        "kind": safe_kind,
        "recorded_at": _now_iso(),
        "session_id": session_id(),
    }
    client = client_info()
    if client is not None:
        entry["client"] = client
    entry["summary"] = summary

    path = history_dir(state_path) / _REPORTS_SUBDIR / f"{safe_kind}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Rotation and the append are one critical section: two writers that
    # both found the file full would otherwise rotate it twice and the
    # second would retire a file holding the first's line alone.
    with file_lock(lock_path_for(path)):
        rotate_if_over(
            path, max_bytes=max_append_bytes(), now=datetime.now(timezone.utc)
        )
        _append_json_line(path, entry)
    return path


def _read_report_lines(
    path: Path, since: date | None
) -> tuple[list[dict[str, Any]], int]:
    """The in-range entries of one ledger file, and its unparseable lines."""
    matched: list[dict[str, Any]] = []
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(entry, dict):
                skipped += 1
            elif _report_entry_in_range(entry, since):
                matched.append(entry)
    return matched, skipped


def _report_entry_in_range(entry: dict[str, Any], since: date | None) -> bool:
    """Whether a ledger entry was recorded on or after ``since``."""
    if since is None:
        return True
    recorded = entry.get("recorded_at")
    if not isinstance(recorded, str):
        return False
    # ``Z`` is the spelling half the world writes, and ``fromisoformat``
    # only learned to read it in 3.11 — mureo still supports 3.10, where an
    # unconverted ``Z`` would drop the entry out of every bounded query.
    normalised = f"{recorded[:-1]}+00:00" if recorded.endswith("Z") else recorded
    try:
        return datetime.fromisoformat(normalised).date() >= since
    except ValueError:
        return False


def read_report_history(
    state_path: Path, kind: str, *, limit: int, since: date | None = None
) -> ReportHistoryRead:
    """The last ``limit`` archived versions of ``kind``, newest last.

    ``since`` (inclusive) filters on ``recorded_at``; an entry whose
    timestamp cannot be read is excluded by a bounded query and kept by an
    unbounded one — a record that cannot be dated cannot be claimed to fall
    in a window.

    A line that does not parse is counted in ``skipped_lines``, never raised:
    an append-only ledger can be truncated mid-line by a crash, and one such
    line must not cost the caller the rest of the history.

    The rotated files of the ledger are read too (#758 phase 6), oldest
    first, so ``limit`` still means "the newest versions" rather than "the
    newest versions of the file that happens to be live".

    Raises:
        ValueError: ``kind`` cannot name a file, or ``limit`` is below 1.
    """
    from mureo.core.rotation import sibling_files

    if limit < 1:
        raise ValueError(f"limit must be at least 1; got {limit}")
    path = (
        history_dir(state_path)
        / _REPORTS_SUBDIR
        / f"{validate_report_kind_path(kind)}.jsonl"
    )
    matched: list[dict[str, Any]] = []
    skipped = 0
    for file in sibling_files(path):
        entries, unparseable = _read_report_lines(file, since)
        matched.extend(entries)
        skipped += unparseable
    return ReportHistoryRead(entries=tuple(matched[-limit:]), skipped_lines=skipped)


__all__ = [
    "ARCHIVE_VERSION",
    "HISTORY_DIRNAME",
    "DailyArchiveRead",
    "ReportHistoryRead",
    "append_report_history",
    "archive_platform_daily",
    "history_dir",
    "read_daily_archive",
    "read_report_history",
    "validate_report_kind_path",
]
