"""BYOD removal helpers.

Single-CSV import was removed in B-2 — the only ingest path now is
``mureo byod import <bundle.xlsx>`` (see :mod:`mureo.byod.bundle`).
This module retains the platform-removal helpers used by the CLI:
``remove_platform`` for surgical per-platform delete, ``clear_all``
for the nuclear option.

``BYODImportError`` is re-exported for callers that catch it as a
generic BYOD failure marker (the bundle path raises a sibling
``BundleImportError``, but legacy callers may still rely on this
name).
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone

from mureo.byod.runtime import (
    SUPPORTED_PLATFORMS,
    byod_data_dir,
    read_manifest,
    write_manifest,
)

logger = logging.getLogger(__name__)


class BYODImportError(RuntimeError):
    """Raised when a BYOD operation fails for any reason."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def remove_platform(platform: str) -> bool:
    """Remove BYOD data for a single platform.

    Accepts any platform name currently present in the manifest, even
    if it is no longer in :data:`SUPPORTED_PLATFORMS`. This lets users
    clean up stale entries left over from older mureo versions
    (e.g. ``google_analytics`` / ``search_console`` from the pre-Phase-1
    BYOD pipeline).

    Returns True when something was removed, False when there was
    nothing to remove (no manifest, or platform not present in it).
    """
    manifest = read_manifest()
    if manifest is None or platform not in manifest["platforms"]:
        if platform not in SUPPORTED_PLATFORMS:
            raise BYODImportError(f"Unknown platform {platform!r}")
        return False

    manifest["platforms"].pop(platform, None)
    # Defense in depth: a hand-edited / corrupt manifest could embed
    # a path-traversal payload (e.g. "../etc") in the platform key.
    # Refuse to rmtree anything outside ~/.mureo/byod/.
    root = byod_data_dir().resolve()
    dst_dir = (byod_data_dir() / platform).resolve()
    if dst_dir == root or root not in dst_dir.parents:
        raise BYODImportError(
            f"Refusing to remove out-of-tree path {dst_dir} "
            f"(platform key {platform!r} escapes BYOD root)"
        )
    if dst_dir.exists():
        shutil.rmtree(dst_dir)

    if manifest["platforms"]:
        manifest["imported_on"] = _now_iso()
        write_manifest(manifest)
    else:
        # Last platform removed. Drop the manifest file (so byod_has
        # returns False immediately) but leave any unrelated files the
        # user dropped under ~/.mureo/byod/ in place. The previous
        # `clear_all()` here also wiped those — silently surprising for
        # users who staged backup CSVs or notes alongside the manifest.
        from mureo.byod.runtime import manifest_path

        mp = manifest_path()
        if mp.exists():
            mp.unlink()
    return True


def clear_all() -> bool:
    """Remove ``~/.mureo/byod/`` entirely. Returns True on actual removal."""
    target = byod_data_dir()
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True
