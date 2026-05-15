"""High-level BYOD actions invoked by the configure-UI byod endpoints.

Wraps the ``mureo byod`` CLI primitives (manifest read, bundle import,
per-platform removal, clear-all) and returns JSON-friendly frozen result
envelopes that the configure UI surfaces directly. Failures degrade to
``status="error"`` envelopes rather than propagating exceptions, so a
click in the configure UI never produces a 500.

The bundle XLSX is referenced by a server-side file *path* (local-first
tool): ``_validate_xlsx_path`` is the security core — it runs before any
filesystem-mutating call and before ``import_bundle``. The validated path
is handed only to ``import_bundle`` (XLSX parse); file contents are never
read or echoed here.

Mirrors the wrapper / frozen-result-envelope pattern of
``mureo.web.setup_actions``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mureo.byod.bundle import BundleImportError, import_bundle
from mureo.byod.installer import BYODImportError, clear_all, remove_platform
from mureo.byod.runtime import SUPPORTED_PLATFORMS, byod_has, read_manifest

logger = logging.getLogger(__name__)

__all__ = [
    "ByodResult",
    "byod_status",
    "byod_import",
    "byod_remove",
    "byod_clear",
]

_ALLOWED_SUFFIXES: frozenset[str] = frozenset({".xlsx", ".xlsm"})


@dataclass(frozen=True)
class ByodResult:
    """JSON-friendly result envelope for every byod action."""

    status: str  # "ok" | "noop" | "error"
    detail: str | None = None
    platforms: tuple[dict[str, Any], ...] | None = None
    summary: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.detail is not None:
            out["detail"] = self.detail
        if self.platforms is not None:
            out["platforms"] = [dict(p) for p in self.platforms]
        if self.summary is not None:
            out["summary"] = self.summary
        return out


def _validate_xlsx_path(path: object) -> str:
    """Resolve and validate a bundle XLSX path before any FS use.

    Raises ``ValueError`` when the path is non-str, empty, not absolute,
    carries NUL/control chars, has a non-allowed extension, contains
    ``..`` traversal, or whose ``realpath`` is not an existing regular
    file (this also defeats a ``.xlsx`` symlink pointing at a non-xlsx
    or out-of-tree target). Returns the resolved path on success.
    """
    if not isinstance(path, str):
        raise ValueError("file_path must be a string")
    if not path.strip():
        raise ValueError("file_path must not be empty")
    if any(ord(c) < 0x20 for c in path):
        raise ValueError("file_path contains control characters")
    if not os.path.isabs(path):
        raise ValueError("file_path must be absolute")
    parts = path.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError("file_path must not contain '..' traversal")
    resolved = os.path.realpath(path)
    _, suffix = os.path.splitext(resolved)
    if suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError("file_path must be a .xlsx or .xlsm file")
    if not os.path.isfile(resolved):
        raise ValueError("file_path is not an existing regular file")
    return resolved


def _safe_byod_has(platform: str) -> bool:
    try:
        return byod_has(platform)
    except Exception:  # noqa: BLE001
        logger.exception("byod_has failed for %s", platform)
        return False


def byod_status() -> ByodResult:
    """Report per-platform BYOD vs Live mode.

    Order follows ``SUPPORTED_PLATFORMS`` (google_ads, meta_ads). A
    manifest read error degrades to an ``error`` envelope. No
    credential material is ever read or surfaced.
    """
    try:
        manifest = read_manifest()
    except Exception as exc:  # noqa: BLE001
        logger.exception("byod_status manifest read failed")
        return ByodResult(status="error", detail=type(exc).__name__)

    active = manifest.get("platforms", {}) if isinstance(manifest, dict) else {}
    rows: list[dict[str, Any]] = []
    for platform in SUPPORTED_PLATFORMS:
        if platform in active and _safe_byod_has(platform):
            info = active[platform]
            row: dict[str, Any] = {"platform": platform, "mode": "byod"}
            if isinstance(info, dict):
                if "rows" in info:
                    row["rows"] = info["rows"]
                if info.get("date_range"):
                    row["date_range"] = info["date_range"]
            rows.append(row)
        else:
            rows.append({"platform": platform, "mode": "live"})
    return ByodResult(status="ok", platforms=tuple(rows))


def byod_import(file_path: str, replace: bool) -> ByodResult:
    """Validate ``file_path`` then import the Sheet bundle.

    Validation runs first; on failure ``import_bundle`` is NOT called.
    ``BundleImportError`` / unexpected errors degrade to an ``error``
    envelope. Raw file bytes are never read or echoed here.
    """
    try:
        resolved = _validate_xlsx_path(file_path)
    except ValueError as exc:
        return ByodResult(status="error", detail=str(exc))

    try:
        results = import_bundle(Path(resolved), replace=replace)
    except BundleImportError as exc:
        logger.warning("byod_import rejected bundle: %s", type(exc).__name__)
        return ByodResult(status="error", detail="BundleImportError")
    except Exception as exc:  # noqa: BLE001
        logger.exception("byod_import unexpected failure")
        return ByodResult(status="error", detail=type(exc).__name__)

    return ByodResult(status="ok", summary=dict(results))


def byod_remove(google_ads: bool, meta_ads: bool) -> ByodResult:
    """Drop one platform's BYOD data.

    Exactly one of ``google_ads`` / ``meta_ads`` must be True else an
    ``error`` envelope is returned and ``remove_platform`` is NOT
    called. A no-op removal is reported as ``noop``.
    """
    selected = [
        name
        for name, flag in (("google_ads", google_ads), ("meta_ads", meta_ads))
        if flag
    ]
    if len(selected) != 1:
        return ByodResult(
            status="error",
            detail="select exactly one of google_ads / meta_ads",
        )
    platform = selected[0]
    try:
        removed = remove_platform(platform)
    except BYODImportError as exc:
        logger.warning("byod_remove rejected: %s", type(exc).__name__)
        return ByodResult(status="error", detail="BYODImportError")
    except Exception as exc:  # noqa: BLE001
        logger.exception("byod_remove unexpected failure")
        return ByodResult(status="error", detail=type(exc).__name__)

    if not removed:
        return ByodResult(status="noop", detail=platform)
    return ByodResult(status="ok", detail=platform)


def byod_clear() -> ByodResult:
    """Wipe all BYOD data at ``~/.mureo/byod/``.

    A no-op clear (nothing on disk) is reported as ``noop``;
    ``OSError`` / unexpected errors degrade to an ``error`` envelope.
    """
    try:
        cleared = clear_all()
    except Exception as exc:  # noqa: BLE001
        logger.exception("byod_clear failed")
        return ByodResult(status="error", detail=type(exc).__name__)

    if not cleared:
        return ByodResult(status="noop")
    return ByodResult(status="ok")
