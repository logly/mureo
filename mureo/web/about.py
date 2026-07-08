"""Version/package payload for the configure UI's "About mureo" tab (#229).

Resolves the installed mureo version plus every installed mureo plugin,
discovered along TWO axes that together match what ``mureo upgrade`` /
the update-check consider an installed mureo package (#365):

1. **Entry-point** — any distribution contributing to one of mureo's
   plugin extension groups (providers, skills, runtime-context factories,
   web extensions, policy gates, analytics). Catches a plugin whose
   distribution is NOT named ``mureo-*`` (e.g. a third-party ``acme-ads``
   that registers ``mureo.providers``).
2. **Name-prefix** — every installed ``mureo`` / ``mureo-*`` distribution,
   using the SAME discovery the updater uses
   (:func:`mureo.cli.upgrade_cmd._discover_all_mureo_packages`). Catches a
   plugin that registers only, say, ``mureo.skills`` and would otherwise be
   flagged "update available" yet never listed here (#365).

The two are unioned and deduplicated by PEP 503 canonical name (which is
also the display name, matching the update banner's labelling), so the
"Installed packages" list and the "Update available" banner agree —
whenever both observe the same installed metadata — about what is
installed and how it is named.

Only :mod:`importlib.metadata` (stdlib) is consulted. The payload
carries nothing environment-specific: no secrets, no file paths — only
distribution names and versions.

Fault isolation mirrors :mod:`mureo.web.extensions`: one broken
plugin's metadata (a raising ``dist`` lookup, a corrupted group) — or a
failing name-prefix walk — skips just that item, never the endpoint.
"""

from __future__ import annotations

from importlib.metadata import (
    entry_points,
    packages_distributions,
    version,
)
from typing import Any, Final

from mureo.analytics.registry import ANALYTICS_ENTRY_POINT_GROUP
from mureo.cli.upgrade_cmd import _canonicalise, _discover_all_mureo_packages
from mureo.core.policy import POLICY_GATES_ENTRY_POINT_GROUP
from mureo.core.providers.registry import (
    PROVIDERS_ENTRY_POINT_GROUP,
    SKILLS_ENTRY_POINT_GROUP,
)
from mureo.core.runtime_context import RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP
from mureo.web.extensions import WEB_EXTENSIONS_ENTRY_POINT_GROUP

#: Entry-point groups scanned for contributing distributions. Reuses the
#: group-name constants owned by each consuming module so a future
#: rename flows through here automatically. Covers EVERY mureo extension
#: surface (#365) — a ``mureo.skills`` / ``mureo.policy_gates`` /
#: ``mureo.analytics`` plugin is as "installed" as a provider one.
ABOUT_ENTRY_POINT_GROUPS: Final[tuple[str, ...]] = (
    PROVIDERS_ENTRY_POINT_GROUP,
    SKILLS_ENTRY_POINT_GROUP,
    RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
    WEB_EXTENSIONS_ENTRY_POINT_GROUP,
    POLICY_GATES_ENTRY_POINT_GROUP,
    ANALYTICS_ENTRY_POINT_GROUP,
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
    return _safe_version("mureo")


def _safe_version(name: str) -> str:
    """Installed version of ``name``, or the placeholder when unresolvable.

    Always returns a non-empty ``str`` so the payload's documented
    ``{"name": str, "version": str}`` shape holds. ``version()`` can:
    - raise :class:`PackageNotFoundError` (vanished between the walk and here),
    - raise anything else on a corrupted ``METADATA`` (e.g. a non-UTF-8 decode),
    - return ``None`` when the ``Version`` header is absent (malformed dist-info
      — ``version()`` does NOT raise for this).
    Every one of these degrades to the placeholder rather than dropping the row
    or escaping to a 500 — mirroring axis 1's per-item guard in
    :func:`_resolve_distribution`.
    """
    try:
        resolved = version(name)
    except Exception:  # noqa: BLE001 — never 500 the About tab on bad metadata
        return UNKNOWN_VERSION
    return resolved if isinstance(resolved, str) and resolved else UNKNOWN_VERSION


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
    # Route through _safe_version (not version() directly) so a malformed
    # dist-info — Version header absent, so version() returns None rather than
    # raising — degrades to the placeholder here too, matching the dist-present
    # branch above and never emitting a non-string version.
    return fallback_name, _safe_version(fallback_name)


def collect_about_info() -> dict[str, Any]:
    """Return the ``GET /api/about`` response payload.

    Shape::

        {
          "mureo": {"name": "mureo", "version": "<version|unknown>"},
          "packages": [{"name": str, "version": str}, ...]
        }

    ``packages`` unions the two discovery axes described in the module
    docstring — entry-point contributors across :data:`ABOUT_ENTRY_POINT_GROUPS`
    AND every installed ``mureo`` / ``mureo-*`` distribution the updater sees —
    deduplicated by PEP 503 canonical name and sorted by display name, with
    mureo itself always present. The seeded mureo version wins over any
    discovered duplicate so the headline version and the table row never
    disagree.
    """
    mureo_version = _mureo_version()
    # Canonical distribution name -> {"name": <display>, "version": <ver>}.
    # Keying on the canonical name is what makes this list AGREE with the
    # update checker (#365): the updater discovers packages by canonical
    # name-prefix, so deduping here on the same key guarantees a package the
    # updater flags is listed here exactly once and never keyed differently.
    by_canonical: dict[str, dict[str, str]] = {}

    # Axis 1 — entry-point contributors across every mureo extension group.
    # Runs first so that for a plugin present on both axes, its entry-point
    # ``dist.version`` is the one kept (via ``setdefault``) over axis 2's
    # separate lookup. Display name is canonical on both axes, so ordering no
    # longer affects the label.
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
                name, dist_version = resolved
                canonical = _canonicalise(name)
                # Display the CANONICAL name (not the raw ``dist.name``) so a
                # mixed-case / underscored distribution reads identically to the
                # update-check banner, which always shows the canonical form
                # (#365). Keeps the two surfaces labelled the same, not just
                # scoped the same.
                by_canonical.setdefault(
                    canonical, {"name": canonical, "version": dist_version}
                )

    # Axis 2 — every installed ``mureo`` / ``mureo-*`` distribution, by the
    # SAME name-prefix rule the update checker uses (#365). Closes the gap
    # where a name-prefixed plugin registering none of the scanned groups was
    # flagged "update available" yet never listed here.
    for canonical in _name_prefixed_packages():
        by_canonical.setdefault(
            canonical, {"name": canonical, "version": _safe_version(canonical)}
        )

    # mureo itself: the seeded headline version always wins over any
    # discovered duplicate (name-prefix discovery includes ``mureo``).
    by_canonical["mureo"] = {"name": "mureo", "version": mureo_version}

    return {
        "mureo": {"name": "mureo", "version": mureo_version},
        "packages": sorted(by_canonical.values(), key=lambda pkg: pkg["name"]),
    }


def _name_prefixed_packages() -> list[str]:
    """Canonical names of installed ``mureo`` / ``mureo-*`` distributions.

    Delegates to the updater's own discovery so the two features stay in
    lock-step (#365). A failing walk degrades to an empty list — the About
    endpoint must never 500 on a corrupted metadata index.
    """
    try:
        return _discover_all_mureo_packages()
    except Exception:  # noqa: BLE001 — discovery must never 500 the About tab
        return []


__all__ = [
    "ABOUT_ENTRY_POINT_GROUPS",
    "UNKNOWN_VERSION",
    "collect_about_info",
]
