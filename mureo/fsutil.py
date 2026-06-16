"""Cross-platform secure-permission helpers.

``os.fchmod`` is Unix-only; on Windows it does not exist and calling it
raises ``AttributeError``, which crashed every mureo credential /
config write path (``credentials.json`` save, provider-config write,
settings rewrite, plugin audit, OAuth token store).

``secure_fchmod`` / ``secure_chmod`` apply owner-only ``0o600`` on
POSIX and degrade to a best-effort no-op on Windows (or any platform
where the perm op is unavailable). They NEVER raise — a permission
hardening step must not break the write it is protecting.

Windows note: NTFS does not use POSIX mode bits; file confidentiality
there relies on the user profile ACL of ``%USERPROFILE%\\.mureo``, not
on this call. This is documented best-effort behaviour, not a silent
security regression.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

try:  # POSIX advisory whole-file lock
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on Windows only
    _fcntl = None  # type: ignore[assignment]

try:  # Windows byte-range lock
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX only
    _msvcrt = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_OWNER_ONLY = 0o600

#: Windows ``msvcrt.locking`` blocks ~10s then raises; retry a few rounds so a
#: short critical section held just over that ceiling still serialises instead
#: of erroring. POSIX ``flock`` blocks indefinitely and needs no retry.
_WIN_LOCK_RETRIES = 6
_WIN_LOCK_BACKOFF_S = 0.05


def secure_fchmod(fd: int) -> None:
    """``fchmod(fd, 0o600)`` on POSIX; best-effort no-op elsewhere."""
    fchmod = getattr(os, "fchmod", None)
    if fchmod is None:  # Windows: os.fchmod is not defined
        logger.debug("secure_fchmod: os.fchmod unavailable (non-POSIX); skip")
        return
    try:
        fchmod(fd, _OWNER_ONLY)
    except (OSError, NotImplementedError):
        logger.debug("secure_fchmod best-effort skip", exc_info=True)


def secure_chmod(path: str | os.PathLike[str]) -> None:
    """``chmod(path, 0o600)``, never raising (best-effort on Windows)."""
    try:
        os.chmod(path, _OWNER_ONLY)
    except (OSError, NotImplementedError):
        logger.debug("secure_chmod best-effort skip", exc_info=True)


def backup_file(path: Path, *, timestamped: bool = False) -> Path | None:
    """Copy ``path`` to a sibling backup before an in-place overwrite.

    Returns the backup path, or ``None`` when ``path`` does not exist yet
    (a first write has no prior state to preserve). With ``timestamped`` the
    backup is ``<name>.bak.<unix_ns>`` so a history accrues (used for
    ``STRATEGY.md``); without it a single rolling ``<name>.bak`` is kept
    (used for ``credentials.json``). The copy inherits the source mode
    (``0o600`` for credential files) and perms are hardened best-effort.

    A symlinked ``path`` is dereferenced — the backup is a real-file copy of
    the link target, not the link itself. Propagates ``OSError`` from the
    copy so a caller never proceeds to overwrite the original when its backup
    could not be made (fail closed).
    """
    if not path.exists():
        return None
    if timestamped:
        # ``time.time_ns()`` is not guaranteed to be monotonic or unique on
        # every platform (macOS truncates to ~µs), so two writes in the same
        # tick could otherwise collide and silently clobber an earlier
        # backup. Disambiguate with a counter so the history is never lost.
        base = f"{path.name}.bak.{time.time_ns()}"
        backup = path.with_name(base)
        counter = 1
        while backup.exists():
            backup = path.with_name(f"{base}.{counter}")
            counter += 1
    else:
        backup = path.with_name(f"{path.name}.bak")
    shutil.copy2(path, backup)
    secure_chmod(backup)
    return backup


def _acquire_lock(fd: int) -> None:
    """Block until an exclusive lock on ``fd`` is held (POSIX or Windows)."""
    if _fcntl is not None:
        _fcntl.flock(fd, _fcntl.LOCK_EX)
        return
    if _msvcrt is not None:  # pragma: no cover - Windows only
        os.lseek(fd, 0, os.SEEK_SET)
        for attempt in range(_WIN_LOCK_RETRIES):
            try:
                # ``LK_LOCK`` is msvcrt's *blocking* lock (retries internally
                # for ~10s, then raises ``OSError``). There is no ``LK_LCK``.
                _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
                return
            except OSError:
                if attempt == _WIN_LOCK_RETRIES - 1:
                    raise
                time.sleep(_WIN_LOCK_BACKOFF_S)
    else:  # pragma: no cover - exotic platform with neither primitive
        logger.warning("file_lock: no fcntl/msvcrt available; lock is a no-op")


def _release_lock(fd: int) -> None:
    """Release the lock held on ``fd``; best-effort (a failed unlock is freed
    on the ``os.close`` that always follows)."""
    try:
        if _fcntl is not None:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        elif _msvcrt is not None:  # pragma: no cover - Windows only
            os.lseek(fd, 0, os.SEEK_SET)
            _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
    except OSError:
        logger.debug("file_lock release best-effort skip", exc_info=True)


@contextlib.contextmanager
def file_lock(lock_path: str | os.PathLike[str]) -> Iterator[None]:
    """Hold an exclusive, cross-platform advisory lock on ``lock_path``.

    Serialises a read-modify-write critical section across threads AND
    processes — mureo's CLI, the MCP server, and the configure server can each
    touch the same ``STATE.json``, so a thread-only or asyncio-only lock would
    not be enough. POSIX uses ``fcntl.flock(LOCK_EX)``; Windows uses
    ``msvcrt.locking(LK_LCK)`` on a one-byte region.

    The lock is tied to the open file descriptor, so the OS releases it
    automatically if the holder crashes — no stale ``.lock`` file can wedge a
    later run. The sidecar is created ``0o600`` and left in place (an empty
    lock file is cheap and avoids an unlink/recreate race). The lock degrades
    to a no-op only on an exotic platform exposing neither primitive (logged at
    WARNING), never on a supported OS.
    """
    fd = os.open(os.fspath(lock_path), os.O_RDWR | os.O_CREAT, _OWNER_ONLY)
    try:
        _acquire_lock(fd)
        try:
            yield
        finally:
            _release_lock(fd)
    finally:
        os.close(fd)


__all__ = ["backup_file", "file_lock", "secure_chmod", "secure_fchmod"]
