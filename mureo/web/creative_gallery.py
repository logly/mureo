"""Read-only data layer for the Creative Studio gallery tab (#409).

Creative Studio writes generated visuals and composed banners to
``<workspace>/creative_studio/<run_id>/`` next to a provenance
``manifest.json`` (see :mod:`mureo.creative_studio.workspace`). This
module enumerates those runs for the configure dashboard and resolves
gallery image paths for the image route. There is no HTTP here (the
handlers own that) and nothing mutates state — read-only, like
:mod:`mureo.web.reports`, whose multi-account seams it reuses:

- the client picker is :func:`mureo.web.reports.list_report_clients`
  (clients are clients — one picker source for every read-only tab);
- per-client resolution goes through the same defensive
  ``state_store_for_client(slug)`` capability, so a multi-account
  backend scopes the gallery to one client's workspace with no changes
  on its side, and the OSS single-workspace install reads the active
  workspace.

The workspace root is derived defensively from the resolved store — a
``workspace`` attribute when declared (the built-in
``FilesystemStateStore`` has one), else the parent of ``state_path``,
else the gallery is empty. Payloads are secret-free: filenames and a
whitelisted manifest summary only, never absolute paths.

``resolve_gallery_image`` is the security boundary for the image route:
both path components must match a conservative charset, the filename
must be a PNG, and the fully resolved path must stay inside the
workspace's ``creative_studio`` tree (closing ``..``, absolute-path,
and symlink escapes). Anything else resolves to ``None`` — the route
404s without touching the filesystem outside the gallery.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Reuse the reports module's seam resolution so every read-only dashboard
# tab agrees on what "the client's store" means (and tests patch a single
# ``mureo.web.reports.get_runtime_context`` seam for both tabs).
from mureo.web.reports import state_store_for_client

if TYPE_CHECKING:
    from mureo.core.state_store import StateStore

logger = logging.getLogger(__name__)

__all__ = ["list_creative_runs", "resolve_gallery_image"]

#: Directory name Creative Studio writes runs under (see workspace.py).
_GALLERY_DIR = "creative_studio"

#: Newest-first cap so a long-lived workspace cannot bloat the payload.
_RUNS_LIMIT = 30

#: Conservative charset for run ids and filenames. Run ids are
#: ``<UTC-stamp>_<hex>`` and images ``<provider>_<nn>.png``, so anything
#: outside this set is foreign — refused rather than interpreted.
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: Manifest keys surfaced to the UI. Everything else (absolute file
#: paths, byte sizes) stays server-side.
_PROMPT_PREVIEW_CHARS = 200

#: Defensive ceilings — Creative Studio writes a handful of images and a
#: tiny manifest per run; anything past these is foreign or corrupt.
_MAX_IMAGES_PER_RUN = 60
_MAX_MANIFEST_BYTES = 65536


def _workspace_root(store: StateStore) -> Path | None:
    """The store's workspace directory, or ``None`` when undeterminable."""
    workspace = getattr(store, "workspace", None)
    if isinstance(workspace, Path):
        return workspace
    state_path = getattr(store, "state_path", None)
    if isinstance(state_path, Path):
        return state_path.parent
    return None


def _gallery_base(client: str | None) -> Path | None:
    root = _workspace_root(state_store_for_client(client))
    if root is None:
        return None
    return root / _GALLERY_DIR


def _manifest_summary(run_dir: Path) -> dict[str, Any]:
    """A secret-free summary of ``manifest.json`` — tolerant of absence.

    A symlinked or oversized manifest is treated as absent: Creative
    Studio only ever writes a small real file, so anything else under
    that name is foreign and must not be followed (the listing enforces
    the same symlink containment as the image route).
    """
    summary: dict[str, Any] = {
        "prompt": "",
        "provider": "",
        "template": None,
        "created_at": None,
    }
    path = run_dir / "manifest.json"
    try:
        if path.is_symlink() or path.stat().st_size > _MAX_MANIFEST_BYTES:
            return summary
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return summary
    if not isinstance(data, dict):
        return summary
    summary["prompt"] = str(data.get("prompt", ""))[:_PROMPT_PREVIEW_CHARS]
    summary["provider"] = str(data.get("provider", ""))
    template = data.get("template")
    summary["template"] = str(template) if isinstance(template, str) else None
    created = data.get("created_at")
    summary["created_at"] = str(created) if isinstance(created, str) else None
    return summary


def _run_entry(run_dir: Path) -> dict[str, Any]:
    images = sorted(
        entry.name
        for entry in run_dir.iterdir()
        if not entry.is_symlink()  # same containment as the image route
        and entry.is_file()
        and entry.suffix.lower() == ".png"
        and _SAFE_COMPONENT.match(entry.name)
    )[:_MAX_IMAGES_PER_RUN]
    return {"run_id": run_dir.name, "images": images, **_manifest_summary(run_dir)}


def list_creative_runs(
    client: str | None = None, *, limit: int = _RUNS_LIMIT
) -> dict[str, Any]:
    """Enumerate a client's Creative Studio runs, newest first.

    Run ids start with a UTC timestamp, so reverse-lexicographic order is
    chronological. Never raises: an unreadable workspace or a missing
    gallery directory yields ``{"runs": []}``, and a single unreadable run
    directory (a permissions hiccup, a race with a live generation) is
    skipped rather than blanking the whole history.

    The listing enforces the same symlink containment as the image route:
    Creative Studio never writes symlinks, so a symlinked run directory,
    image, or manifest under ``creative_studio/`` is foreign — following
    it would let a planted link enumerate filenames and manifest content
    from outside the workspace.
    """
    runs: list[dict[str, Any]] = []
    base = _gallery_base(client)
    try:
        if base is not None and base.is_dir():
            run_dirs = [
                entry
                for entry in base.iterdir()
                if not entry.is_symlink()
                and entry.is_dir()
                and _SAFE_COMPONENT.match(entry.name)
            ]
            run_dirs.sort(key=lambda entry: entry.name, reverse=True)
            for run_dir in run_dirs[:limit]:
                try:
                    runs.append(_run_entry(run_dir))
                except OSError:
                    logger.warning("skipping unreadable creative run %s", run_dir.name)
    except OSError:
        logger.exception("creative gallery enumeration failed")
        runs = []
    return {"client": client or "", "runs": runs}


def resolve_gallery_image(
    client: str | None, run_id: str, filename: str
) -> Path | None:
    """Resolve one gallery image to a real file, or ``None`` when refused.

    Refusals (all mapped to 404 by the route): a component outside the
    conservative charset, a non-PNG filename, a missing file, or a fully
    resolved path that escapes the workspace's ``creative_studio`` tree
    (``..`` tricks and symlinks both fail the containment check).
    """
    if not _SAFE_COMPONENT.match(run_id) or not _SAFE_COMPONENT.match(filename):
        return None
    # Case-insensitive on purpose — mirrors the listing filter's
    # ``suffix.lower()`` so ``x.PNG`` is served, not orphaned.
    if not filename.lower().endswith(".png"):
        return None
    base = _gallery_base(client)
    if base is None or not base.is_dir():
        return None
    try:
        base_resolved = base.resolve(strict=True)
        candidate = (base / run_id / filename).resolve(strict=True)
    except OSError:
        return None
    if base_resolved not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate
