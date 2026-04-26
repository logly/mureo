"""Install / remove / clear BYOD data sets.

Pipeline for ``mureo byod import``:
  user CSV -> adapter detect -> adapter normalize -> manifest update.

Manifest write is atomic; partial imports never leave a half-built
``manifest.json``.
"""

from __future__ import annotations

import csv as _csv
import hashlib
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mureo.byod.adapters.google_ads import (
    GoogleAdsAdapter,
    UnsupportedFormatError,
)
from mureo.byod.runtime import (
    SCHEMA_VERSION,
    SUPPORTED_PLATFORMS,
    byod_data_dir,
    read_manifest,
    write_manifest,
)

logger = logging.getLogger(__name__)

_ADAPTERS: dict[str, Any] = {
    "google_ads": GoogleAdsAdapter,
}


class BYODImportError(RuntimeError):
    """Raised when an import fails for any reason."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _empty_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "imported_on": _now_iso(),
        "platforms": {},
    }


def _detect_platform(src: Path) -> str:
    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        header = list(reader.fieldnames or [])

    for platform, adapter_cls in _ADAPTERS.items():
        if adapter_cls.detect(header):
            return platform

    raise UnsupportedFormatError(
        f"{src.name}: could not auto-detect format. "
        f"Supported: {sorted(_ADAPTERS)}. "
        "Pass --google-ads / --meta-ads / --search-console to force."
    )


def import_csv(
    src: Path,
    *,
    platform: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Import a single CSV into ``~/.mureo/byod/<platform>/``."""
    src = Path(src).expanduser().resolve()
    if not src.is_file():
        raise BYODImportError(f"{src}: file not found")

    if platform is None:
        platform = _detect_platform(src)
    if platform not in _ADAPTERS:
        raise BYODImportError(
            f"Unsupported platform {platform!r}. " f"Available: {sorted(_ADAPTERS)}"
        )

    manifest = read_manifest() or _empty_manifest()

    if platform in manifest["platforms"] and not replace:
        raise BYODImportError(
            f"BYOD data for {platform!r} already exists. "
            "Re-run with --replace to overwrite, or "
            f"`mureo byod remove --{platform.replace('_', '-')}` first."
        )

    src_sha = _sha256_file(src)

    existing: dict[str, Any] | None = manifest["platforms"].get(platform)
    if existing and existing.get("source_file_sha256") == src_sha and not replace:
        logger.info(
            "Same source file already imported for %s (sha256=%s); "
            "skipping re-extraction",
            platform,
            src_sha[:12],
        )
        existing["imported_at"] = _now_iso()
        manifest["imported_on"] = _now_iso()
        write_manifest(manifest)
        return existing

    adapter = _ADAPTERS[platform]()
    byod_root = byod_data_dir().resolve()
    byod_root.mkdir(parents=True, exist_ok=True)
    dst_dir = (byod_data_dir() / platform).resolve()

    # Defense-in-depth: refuse to write outside ~/.mureo/byod/.
    if byod_root != dst_dir and byod_root not in dst_dir.parents:
        raise BYODImportError(f"Refusing to write outside BYOD root: {dst_dir}")

    if dst_dir.exists():
        shutil.rmtree(dst_dir)

    result = adapter.normalize(src, dst_dir)

    entry = {
        "files": list(result.files_written),
        "date_range": {
            "start": result.date_range[0],
            "end": result.date_range[1],
        },
        "rows": result.rows,
        "campaigns": result.campaigns,
        "ad_groups": result.ad_groups,
        "source_format": result.source_format,
        "imported_at": _now_iso(),
        "source_file_sha256": src_sha,
        "source_filename": src.name,
    }
    manifest["platforms"][platform] = entry
    manifest["imported_on"] = _now_iso()
    write_manifest(manifest)
    return entry


def remove_platform(platform: str) -> bool:
    """Remove BYOD data for a single platform."""
    if platform not in SUPPORTED_PLATFORMS:
        raise BYODImportError(f"Unknown platform {platform!r}")

    manifest = read_manifest()
    if manifest is None or platform not in manifest["platforms"]:
        return False

    manifest["platforms"].pop(platform, None)
    dst_dir = byod_data_dir() / platform
    if dst_dir.exists():
        shutil.rmtree(dst_dir)

    if manifest["platforms"]:
        manifest["imported_on"] = _now_iso()
        write_manifest(manifest)
    else:
        clear_all()
    return True


def clear_all() -> bool:
    """Remove ``~/.mureo/byod/`` entirely."""
    target = byod_data_dir()
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True
