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

import logging
import os

logger = logging.getLogger(__name__)

_OWNER_ONLY = 0o600


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


__all__ = ["secure_chmod", "secure_fchmod"]
