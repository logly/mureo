"""Read, durably write and lock STATE.json as a whole document (#917).

The lowest layer of the STATE.json surface: the atomic write (temp file ->
fsync -> rename), the cross-process lock that makes a read -> modify -> write
cycle one critical section, and the server clock every targeted mutator
stamps with. The targeted mutators that own STATE.json's merge semantics live
one layer up (:mod:`mureo.context.campaign_store`,
:mod:`mureo.context.action_log_store`, :mod:`mureo.context.batch_store`,
:mod:`mureo.context.platform_store`, :mod:`mureo.context.report_store`), and
:mod:`mureo.context.state` re-exports all of them as the single import site.

Split out of :mod:`mureo.context.state` verbatim so that a module the codec
does not depend on can take the lock at top level instead of through a
function-local import (#879).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

from mureo.context.action_log_guard import guard_action_log_shrink
from mureo.context.errors import ContextFileError
from mureo.context.models import StateDocument
from mureo.context.platform_guards import warn_on_duplicate_accounts
from mureo.context.state_codec import parse_state, render_state
from mureo.fsutil import file_lock


def _atomic_write(path: Path, content: str) -> None:
    """Atomically and durably write a file (temp file -> fsync -> rename).

    fsync the data before the rename so a crash/power loss just after
    ``os.replace`` cannot leave STATE.json as a zero-length/partial file (which
    would lose campaign history / action_log). Best-effort directory fsync makes
    the rename itself durable on POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        _fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


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


def read_state_file(path: Path, *, strict: bool = True) -> StateDocument:
    """Read a STATE.json file and return a StateDocument.

    Returns a default StateDocument if the file does not exist. Pass
    ``strict=False`` (for :func:`parse_state`) from the read-only Reports view
    to skip a non-object ``action_log`` entry or ``decisions`` record instead
    of failing; every other hand-written shape is kept (#881 / #882).
    """
    if not path.exists():
        return StateDocument()
    try:
        text = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ContextFileError(f"No read permission for STATE.json: {path}") from exc
    try:
        return parse_state(text, strict=strict)
    except json.JSONDecodeError as exc:
        raise ContextFileError(f"Failed to parse JSON in STATE.json: {path}") from exc


def write_state_file(
    path: Path, doc: StateDocument, *, previous: StateDocument | None = None
) -> None:
    """Atomically write a StateDocument to a STATE.json file.

    Also emits the advisory duplicate-account warning (#534) — see
    :func:`mureo.context.platform_guards.warn_on_duplicate_accounts`. The write
    proceeds regardless.

    A write that shortens or rewrites the ``action_log`` on disk leaves a
    timestamped copy of that document behind first (#758 phase 6) — see
    :func:`mureo.context.action_log_guard.guard_action_log_shrink`. Pass
    ``previous`` when the caller has already read the on-disk document
    under the same lock, so the guard costs no second read.
    """
    warn_on_duplicate_accounts(path, doc)
    guard_action_log_shrink(path, doc, previous=previous)
    text = render_state(doc)
    _atomic_write(path, text)


def _state_lock_path(path: Path) -> Path:
    """Sidecar lock file for ``path`` (e.g. ``STATE.json`` -> ``STATE.json.lock``)."""
    return path.with_name(path.name + ".lock")


def _locked_state_mutation(
    path: Path, build: Callable[[StateDocument], StateDocument | None]
) -> StateDocument:
    """Run a read -> ``build`` -> write cycle as one critical section.

    ``build`` returning ``None`` means "nothing to change": the document as
    read is returned and nothing is written (#848).

    ``_atomic_write`` only makes the file *replace* atomic; the surrounding
    read-modify-write is not. Holding the cross-process ``file_lock`` across
    read + write serialises every STATE.json mutator, so two concurrent calls
    (built-in <-> built-in, or built-in <-> plugin dispatch) can no longer
    last-writer-wins away each other's changes — e.g. drop an action_log
    entry (issue #115). ``build(doc)`` returns the new document to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_state_lock_path(path)):
        doc = read_state_file(path)
        new_doc = build(doc)
        if new_doc is None:
            return doc
        write_state_file(path, new_doc, previous=doc)
    return new_doc


def _now_iso() -> str:
    """Current time as a timezone-aware ISO 8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    # The underscores stay (#917 moved these names, it did not rename them):
    # they are the primitives the store modules are built on, not API for
    # callers outside this package, and :mod:`mureo.context.state` keeps
    # re-exporting every one of them under its old name.
    "_atomic_write",
    "_locked_state_mutation",
    "_now_iso",
    "_state_lock_path",
    "read_state_file",
    "write_state_file",
]
