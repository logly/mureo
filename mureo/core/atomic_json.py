"""Fail-closed reader + atomic writer for mureo's JSON config files (#500).

Every mureo writer that owns a small JSON document on disk — Claude Code
MCP settings (``~/.claude.json``), ``credentials.json``, the Amazon Ads
tool manifest, ``insight_sources.json`` — needs the same two guarantees:

- **fail closed on a malformed existing file.** :func:`load_existing_json`
  returns ``{}`` *only* when the file is absent and raises
  :class:`ConfigWriteError` when it exists but is not a JSON object, so a
  single corrupt byte can never be "read" as empty and then written back,
  erasing everything the caller did not touch.
- **atomic, owner-only writes.** :func:`atomic_write_json` writes through
  an unpredictable same-directory ``tempfile``, chmods it ``0o600``
  *before* the data lands in it, ``fsync``s, then ``os.replace``s — so a
  crash mid-write cannot corrupt the target, the file is never
  world-readable, and a failure leaves no debris.

These helpers used to live (private) in ``mureo.providers.config_writer``,
which is documented for Claude Code settings only; three unrelated writers
reached into it anyway. They are low-level by design: this module depends
on nothing but the stdlib and :mod:`mureo.fsutil`.

Note: neither function serialises the surrounding read-modify-write. A
caller that must not lose a concurrent writer's section wraps the whole
cycle in :func:`mureo.fsutil.file_lock` (see ``auth.save_amazon_access_token``).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from mureo.fsutil import secure_fchmod

__all__ = ["ConfigWriteError", "atomic_write_json", "load_existing_json"]

logger = logging.getLogger(__name__)


class ConfigWriteError(Exception):
    """Raised when a JSON config file cannot be safely updated.

    Used specifically when an existing file contains malformed JSON — we
    refuse to silently overwrite the file to protect user data.
    """


def load_existing_json(path: Path) -> dict[str, Any]:
    """Load ``path`` as a dict, or return ``{}`` if the file is absent.

    Raises:
        ConfigWriteError: when the existing file is malformed JSON. The
            exception message includes the path so the operator can locate
            and fix the file manually.
    """
    # NOTE: the message wording ("settings") predates this module and is
    # part of the user-visible surface (callers such as the Amazon bridge
    # re-wrap it into their own error text); it is deliberately unchanged.
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigWriteError(
            f"failed to read existing settings at {path}: {exc}"
        ) from exc
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigWriteError(
            f"existing settings file at {path} is malformed JSON "
            f"(refusing to overwrite to protect user data): {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ConfigWriteError(
            f"existing settings at {path} is not a JSON object "
            f"(got {type(loaded).__name__}); refusing to overwrite."
        )
    return loaded


def _fsync_directory(parent: Path) -> None:
    """Best-effort ``fsync`` of ``parent`` so a rename is durable.

    POSIX requires ``fsync`` on the directory to flush a rename to disk.
    Not supported on Windows; ignore ``OSError`` there.
    """
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


def atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    """Serialize ``payload`` and atomically replace ``path``.

    Uses :func:`tempfile.mkstemp` to allocate an unpredictable same-directory
    tmp file, sets its mode to ``0o600`` before writing, ``fsync``s the data
    to disk, then ``os.replace``s it into place. Best-effort ``fsync`` on the
    parent directory after the rename so the directory entry is durable too.
    On failure the tmp file is unlinked so no debris remains. The original
    ``path`` (if any) is untouched until ``os.replace`` succeeds.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    # Allocate an unpredictable tmp file in the same directory as the target
    # so ``os.replace`` is guaranteed to be a rename within the same
    # filesystem (and therefore atomic on POSIX).
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        # Restrict permissions BEFORE writing the data so the file is never
        # readable to other local users during the write/replace window.
        secure_fchmod(tmp_fd)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            tmp_fd = -1  # ownership transferred to ``fh``; do not close twice
            fh.write(serialized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    except (OSError, ValueError):
        # Clean up the tmp file on any FS-level failure so the directory
        # stays tidy. ``ValueError`` covers ``json.dumps`` having serialized
        # something unexpected (defensive — payload is built internally).
        try:
            if tmp_fd != -1:
                os.close(tmp_fd)
        except OSError:
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("failed to remove tmp file %s", tmp_path)
        raise
