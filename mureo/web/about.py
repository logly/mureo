"""Version/package payload for the configure UI's "About mureo" tab (#229).

Resolves the installed mureo version plus every distribution that
contributes to mureo's plugin entry-point groups (providers, runtime-
context factories, web extensions). Discovery is entry-point based, so
a freshly installed plugin appears automatically — no per-plugin wiring.

Only :mod:`importlib.metadata` (stdlib) is consulted. The payload
carries nothing environment-specific: no secrets, no file paths — only
distribution names and versions.

Fault isolation mirrors :mod:`mureo.web.extensions`: one broken
plugin's metadata (a raising ``dist`` lookup, a corrupted group) skips
just that item, never the endpoint.
"""

from __future__ import annotations

from importlib.metadata import (
    PackageNotFoundError,
    entry_points,
    packages_distributions,
    version,
)
from typing import Any, Final

from mureo.core.providers.registry import PROVIDERS_ENTRY_POINT_GROUP
from mureo.core.runtime_context import RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP
from mureo.web.extensions import WEB_EXTENSIONS_ENTRY_POINT_GROUP

#: Entry-point groups scanned for contributing distributions. Reuses the
#: group-name constants owned by each consuming module so a future
#: rename flows through here automatically.
ABOUT_ENTRY_POINT_GROUPS: Final[tuple[str, ...]] = (
    PROVIDERS_ENTRY_POINT_GROUP,
    RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
    WEB_EXTENSIONS_ENTRY_POINT_GROUP,
)

#: Placeholder shown when a version cannot be resolved (e.g. a dev tree
#: where the ``mureo`` distribution is not installed).
UNKNOWN_VERSION: Final[str] = "unknown"


def _mureo_version() -> str:
    """Installed mureo distribution version, or the placeholder.

    A dev checkout imported straight off the filesystem has no installed
    distribution — :class:`PackageNotFoundError` then must not break the
    About endpoint.
    """
    try:
        return version("mureo")
    except PackageNotFoundError:
        return UNKNOWN_VERSION


def _resolve_distribution(ep: Any) -> tuple[str, str] | None:
    """Resolve one entry point to its owning ``(name, version)`` pair.

    ``EntryPoint.dist`` may be ``None`` on Python 3.10, so when it is
    absent the owning distribution is recovered by mapping the entry
    point's top-level module through ``packages_distributions()``.
    Returns ``None`` when the owner cannot be determined; attribute
    access is defensive (``getattr``) because the caller isolates faults
    per entry point and adversarial metadata objects may raise.
    """
    dist = getattr(ep, "dist", None)
    if dist is not None:
        name = getattr(dist, "name", None)
        if isinstance(name, str) and name:
            dist_version = getattr(dist, "version", None)
            if not isinstance(dist_version, str) or not dist_version:
                dist_version = UNKNOWN_VERSION
            return name, dist_version
    module = getattr(ep, "module", "") or ""
    top_level = module.split(".", 1)[0]
    if not top_level:
        return None
    candidates = packages_distributions().get(top_level, [])
    if not candidates:
        return None
    fallback_name = candidates[0]
    try:
        return fallback_name, version(fallback_name)
    except PackageNotFoundError:
        return fallback_name, UNKNOWN_VERSION


def collect_about_info() -> dict[str, Any]:
    """Return the ``GET /api/about`` response payload.

    Shape::

        {
          "mureo": {"name": "mureo", "version": "<version|unknown>"},
          "packages": [{"name": str, "version": str}, ...]
        }

    ``packages`` lists every distribution contributing to
    :data:`ABOUT_ENTRY_POINT_GROUPS`, deduplicated by distribution name
    and sorted by name, with mureo itself always present. The seeded
    mureo version wins over any entry-point-derived duplicate so the
    headline version and the table row never disagree.
    """
    mureo_version = _mureo_version()
    by_name: dict[str, str] = {"mureo": mureo_version}
    for group in ABOUT_ENTRY_POINT_GROUPS:
        try:
            group_eps = entry_points(group=group)
        except Exception:  # noqa: BLE001 — per-group fault isolation
            continue
        for ep in group_eps:
            try:
                resolved = _resolve_distribution(ep)
            except Exception:  # noqa: BLE001 — per-entry-point fault isolation
                continue
            if resolved is not None:
                by_name.setdefault(resolved[0], resolved[1])
    return {
        "mureo": {"name": "mureo", "version": mureo_version},
        "packages": [
            {"name": name, "version": by_name[name]} for name in sorted(by_name)
        ],
    }


__all__ = [
    "ABOUT_ENTRY_POINT_GROUPS",
    "UNKNOWN_VERSION",
    "collect_about_info",
]
