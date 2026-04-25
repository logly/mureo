"""BYOD runtime helpers shared by the CLI, the MCP client factory, and tests.

The single source of truth for "is BYOD active for platform X" is the
``manifest.json`` written into ``~/.mureo/byod/`` by ``mureo byod import``.

This module is read-light (one small JSON file) and intentionally has no
external dependencies so it can be imported from
``mureo/mcp/_client_factory.py`` without dragging the heavier installer
or adapter code into the MCP server's startup path.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SUPPORTED_PLATFORMS = ("google_ads", "meta_ads", "search_console")

_USER_DIR_NAME = ".mureo"
_BYOD_SUBDIR = "byod"
_MANIFEST_NAME = "manifest.json"


def byod_data_dir() -> Path:
    """Return ``~/.mureo/byod/`` (does not create it)."""
    return Path.home() / _USER_DIR_NAME / _BYOD_SUBDIR


def manifest_path() -> Path:
    return byod_data_dir() / _MANIFEST_NAME


def read_manifest() -> dict[str, Any] | None:
    """Read manifest.json; return ``None`` on absence, parse error, or
    unknown schema version (caller treats those as 'BYOD inactive').
    """
    p = manifest_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("BYOD manifest unreadable, treating as inactive: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        logger.warning(
            "BYOD manifest schema_version=%r != supported %d; treating as inactive",
            data.get("schema_version"),
            SCHEMA_VERSION,
        )
        return None
    if not isinstance(data.get("platforms"), dict):
        return None
    return data


def write_manifest(data: dict[str, Any]) -> None:
    """Atomically replace ``manifest.json`` with the given dict."""
    p = manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".manifest.", suffix=".json", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=False)
            f.write("\n")
        os.replace(tmp_name, p)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def byod_has(platform: str) -> bool:
    """True if BYOD data is registered for ``platform``."""
    if platform not in SUPPORTED_PLATFORMS:
        return False
    manifest = read_manifest()
    if manifest is None:
        return False
    return platform in manifest["platforms"]


def byod_active_platforms() -> list[str]:
    """Return platforms currently in BYOD mode (in canonical order)."""
    manifest = read_manifest()
    if manifest is None:
        return []
    return [p for p in SUPPORTED_PLATFORMS if p in manifest["platforms"]]


def byod_platform_info(platform: str) -> dict[str, Any] | None:
    """Return per-platform manifest entry, or ``None`` if absent."""
    manifest = read_manifest()
    if manifest is None:
        return None
    info = manifest["platforms"].get(platform)
    if not isinstance(info, dict):
        return None
    return info
