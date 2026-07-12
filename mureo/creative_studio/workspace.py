"""Output workspace lifecycle for Creative Studio runs.

Each generation run gets its own directory under ``./creative_studio/`` named
by a UTC timestamp plus a short random suffix, holding the generated PNGs and
a provenance ``manifest.json``. Files are written ``0o644`` and directories
``0o755`` so a run is world-readable but not writable.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DIR_MODE = 0o755
_FILE_MODE = 0o644
_CHUNK = 65536


def _new_run_id() -> str:
    """Return a run id: ``<UTC-timestamp>_<6 hex chars>``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{secrets.token_hex(3)}"


def create_run_dir(base: Path | None = None) -> Path:
    """Create and return a fresh run directory under ``base``.

    ``base`` defaults to ``./creative_studio`` (relative to the current
    working directory). The directory name is unique per call; on the
    astronomically unlikely id collision the ``exist_ok=False`` mkdir raises
    rather than reusing an existing run.
    """
    base = base if base is not None else Path.cwd() / "creative_studio"
    base.mkdir(parents=True, exist_ok=True)
    run_dir = base / _new_run_id()
    run_dir.mkdir(exist_ok=False)
    os.chmod(run_dir, _DIR_MODE)
    return run_dir


def write_bytes(path: Path, data: bytes) -> Path:
    """Write ``data`` to ``path`` at ``0o644`` and return ``path``."""
    path.write_bytes(data)
    os.chmod(path, _FILE_MODE)
    return path


def write_manifest(run_dir: Path, data: dict[str, Any]) -> Path:
    """Write ``manifest.json`` (indent 2, UTF-8) into ``run_dir``."""
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(path, _FILE_MODE)
    return path


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "create_run_dir",
    "sha256_of",
    "write_bytes",
    "write_manifest",
]
