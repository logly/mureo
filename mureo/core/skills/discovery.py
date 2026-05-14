"""Entry-points-based skill discovery (Issue #89 P1-08).

Discovers ``SKILL.md`` files from two sources:

1. **Built-in skills**: the in-tree directory at
   ``<mureo package>/_data/skills/``. Resolved relative to
   :data:`mureo.__file__` so it works for both editable installs and
   wheel installs. The built-in path is unconditionally scanned (no
   entry point required); :func:`discover_skills` accepts
   ``include_builtins=False`` for tests that want to isolate
   third-party entry points.
2. **Third-party plugins**: each entry point in the
   ``mureo.skills`` group must ``load()`` to a directory (a
   :class:`Path` or ``str``). The discoverer recursively walks that
   directory looking for ``SKILL.md`` files. This is the documented
   "Option B" convention (see planner HANDOFF feat-skill-matcher.md):
   the entry-point value is a directory path, not a module attribute.

Bounds (DoS guards)
-------------------
- ``_MAX_RECURSION_DEPTH = 4`` — a ``SKILL.md`` more than 4 directory
  levels below the entry-point root is skipped with a warning.
- ``_MAX_SKILLS_PER_ENTRY_POINT = 64`` — once 64 files have been
  accepted from a single entry-point root the scanner stops with a
  warning.
- 64 KiB per file (enforced inside :func:`parse_skill_md`).

Security posture
----------------
1. **Per-plugin fault isolation**: every ``ep.load()`` and every
   per-file parse runs inside a broad try/except so one hostile plugin
   cannot break discovery of the rest. ``# noqa: BLE001`` is required
   on these handlers — broad catching is the intended fault-isolation
   boundary.
2. **Path traversal guard**: every discovered ``SKILL.md`` is
   :meth:`Path.resolve` -d and verified to be a descendant of the
   originating entry-point root. Symlinks that escape the root are
   skipped with a warning. The built-in directory uses the same guard
   with itself as the root.
3. **First-wins on duplicate name**: a later-installed malicious
   plugin cannot silently take over a built-in skill's name. The
   second contribution emits a :class:`SkillDiscoveryWarning`.
4. **Untrusted distribution name**: ``ep.dist.name`` is captured into
   :attr:`SkillEntry.source_distribution` as display data only.

Caching
-------
The result is cached behind a module-level singleton; a second
:func:`discover_skills` call without ``refresh=True`` does NOT
re-iterate ``entry_points``. ``refresh=True`` forces re-iteration.
``clear_skills_cache`` resets the cache for test isolation (mirroring
the registry's ``clear_registry``).

Foundation rule
---------------
Imports from :mod:`mureo.core.providers.registry` (constant only),
:mod:`mureo.core.skills.models`, and
:mod:`mureo.core.skills.parser`. No domain Protocol imports.
"""

from __future__ import annotations

import warnings
from dataclasses import replace
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Final

import mureo
from mureo.core.providers.registry import SKILLS_ENTRY_POINT_GROUP
from mureo.core.skills.parser import SkillParseError, parse_skill_md

if TYPE_CHECKING:
    from mureo.core.skills.models import SkillEntry

_MAX_RECURSION_DEPTH: Final[int] = 4
_MAX_SKILLS_PER_ENTRY_POINT: Final[int] = 64

_BUILTIN_SKILLS_DIR: Final[Path] = (
    Path(mureo.__file__).resolve().parent / "_data" / "skills"
)


class SkillDiscoveryWarning(UserWarning):
    """Emitted when a skill is skipped during discovery.

    Distinct :class:`UserWarning` subclass so security-conscious
    deployments can opt into strict mode via
    ``warnings.filterwarnings("error", category=SkillDiscoveryWarning)``.
    """


_cache: tuple[SkillEntry, ...] | None = None


def discover_skills(
    *, refresh: bool = False, include_builtins: bool = True
) -> tuple[SkillEntry, ...]:
    """Discover skills from built-in directory + entry-points group.

    Args:
        refresh: When ``True``, re-iterate ``entry_points`` and
            re-scan the built-in directory even if a previous call
            cached a result.
        include_builtins: When ``False``, skip the built-in directory
            scan. Defaults to ``True``. Mostly useful in tests that
            want to isolate behaviour to the third-party entry-points
            path.

    Returns:
        Tuple of :class:`SkillEntry`, first-wins on duplicate ``name``.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache

    accepted: dict[str, SkillEntry] = {}

    if include_builtins and _BUILTIN_SKILLS_DIR.is_dir():
        _scan_root(
            root=_BUILTIN_SKILLS_DIR,
            distribution=None,
            accepted=accepted,
            origin_label="built-in",
        )

    for ep in entry_points(group=SKILLS_ENTRY_POINT_GROUP):
        _scan_entry_point(ep, accepted)

    result = tuple(accepted.values())
    _cache = result
    return result


def clear_skills_cache() -> None:
    """Invalidate the module-level discovery cache.

    Test-isolation helper; mirrors :func:`mureo.core.providers.registry
    .clear_registry`.
    """
    global _cache
    _cache = None


def _scan_entry_point(ep: EntryPoint, accepted: dict[str, SkillEntry]) -> None:
    """Load one entry point and scan the directory it returns.

    Per-plugin fault isolation: ``ep.load()`` may execute arbitrary
    third-party code at import time, so the entire load + structural
    check + scan is wrapped in a broad except. ``# noqa: BLE001`` is
    required: broad catching is the intended fault-isolation boundary,
    not a code smell.
    """
    ep_name = getattr(ep, "name", "<unknown>")
    try:
        loaded = ep.load()
    except Exception as exc:  # noqa: BLE001 — per-plugin fault isolation
        _warn(
            f"failed to load skill entry point {ep_name!r} in group "
            f"{SKILLS_ENTRY_POINT_GROUP!r}: {exc!r}"
        )
        return

    root = _coerce_to_path(loaded)
    if root is None:
        _warn(
            f"skill entry point {ep_name!r} did not yield a directory path "
            f"(got {type(loaded).__name__}); skipped"
        )
        return
    if not root.is_dir():
        _warn(
            f"skill entry point {ep_name!r} pointed to {root!s} which is not "
            f"an existing directory; skipped"
        )
        return

    distribution = _resolve_distribution(ep)
    try:
        _scan_root(
            root=root,
            distribution=distribution,
            accepted=accepted,
            origin_label=f"entry point {ep_name!r}",
        )
    except Exception as exc:  # noqa: BLE001 — per-plugin fault isolation
        _warn(
            f"unexpected error while scanning skill entry point "
            f"{ep_name!r}: {exc!r}"
        )


def _coerce_to_path(value: object) -> Path | None:
    """Return ``value`` as a resolved :class:`Path`, or ``None``.

    Only :class:`Path` and ``str`` are accepted — anything else (ints,
    callables, modules) is rejected with the caller emitting a
    warning. Resolved early so the path-traversal guard has a stable
    base to compare against.
    """
    if isinstance(value, Path):
        return value.resolve()
    if isinstance(value, str):
        return Path(value).resolve()
    return None


def _resolve_distribution(ep: EntryPoint) -> str | None:
    """Defensively extract ``ep.dist.name``; ``None`` when unresolvable."""
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None
    name = getattr(dist, "name", None)
    return name if isinstance(name, str) else None


def _scan_root(
    *,
    root: Path,
    distribution: str | None,
    accepted: dict[str, SkillEntry],
    origin_label: str,
) -> None:
    """Walk ``root`` recursively looking for ``SKILL.md`` files.

    Enforces depth and file-count caps; rejects symlinks that escape
    ``root``; isolates per-file parse failures.
    """
    resolved_root = root.resolve()
    candidates = _collect_skill_md_paths(root=resolved_root, origin_label=origin_label)

    accepted_count = 0
    cap_hit = False
    for candidate in candidates:
        if accepted_count >= _MAX_SKILLS_PER_ENTRY_POINT:
            cap_hit = True
            break
        entry = _parse_candidate(
            candidate=candidate,
            root=resolved_root,
            distribution=distribution,
            origin_label=origin_label,
        )
        if entry is None:
            continue
        if entry.name in accepted:
            existing = accepted[entry.name]
            _warn(
                f"duplicate skill name {entry.name!r}: first-discovered "
                f"from {existing.source_path!s} "
                f"(distribution={existing.source_distribution!r}) wins; "
                f"shadow attempt from {entry.source_path!s} "
                f"(distribution={entry.source_distribution!r}) dropped"
            )
            continue
        accepted[entry.name] = entry
        accepted_count += 1

    if cap_hit:
        _warn(
            f"skill scan under {origin_label} hit the cap of "
            f"{_MAX_SKILLS_PER_ENTRY_POINT} SKILL.md files; remaining "
            f"files in {resolved_root!s} are ignored"
        )


def _collect_skill_md_paths(*, root: Path, origin_label: str) -> list[Path]:
    """Return the sorted list of ``SKILL.md`` paths under ``root``.

    Honours the depth cap and the path-traversal guard. Emits warnings
    for symlink escapes and depth violations; never raises out.
    """
    collected: list[Path] = []
    if not root.is_dir():
        return collected

    # Walk subdirectories depth-first up to the depth cap (the
    # ``stack.pop()`` below is LIFO). We intentionally avoid
    # ``Path.rglob`` because it silently follows symlinks and offers no
    # depth limit.
    stack: list[tuple[Path, int]] = [(root, 0)]
    depth_warned = False
    while stack:
        current, depth = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError as exc:
            _warn(f"cannot list directory {current!s} under {origin_label}: {exc}")
            continue

        for child in children:
            if not _is_under(root, child):
                _warn(
                    f"symlink {child!s} under {origin_label} escapes the "
                    f"entry-point root {root!s}; skipped"
                )
                continue
            if child.is_dir():
                if depth + 1 > _MAX_RECURSION_DEPTH:
                    if not depth_warned:
                        _warn(
                            f"skill scan under {origin_label} reached the "
                            f"maximum recursion depth of "
                            f"{_MAX_RECURSION_DEPTH}; deeper directories "
                            f"(such as {child!s}) are ignored"
                        )
                        depth_warned = True
                    continue
                stack.append((child, depth + 1))
            elif child.is_file() and child.name == "SKILL.md":
                collected.append(child)

    collected.sort()
    return collected


def _is_under(root: Path, candidate: Path) -> bool:
    """Return ``True`` iff ``candidate``'s resolved path is under ``root``.

    Symlink-aware: the candidate is fully resolved before the check so
    a symlink that points outside ``root`` returns ``False``.

    Portability note: this relies on the Python 3.10 / 3.11 behaviour
    of :meth:`pathlib.Path.relative_to` — raising :class:`ValueError`
    when the target is not actually relative to ``root``. Python 3.12+
    added a ``walk_up`` parameter to ``relative_to`` that could (if
    enabled) silently return a ``../...`` path instead of raising; we
    do NOT pass ``walk_up=True``, so current code is unaffected. Keep
    this guarantee in mind when touching this helper on newer Pythons.
    """
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(root)
    except ValueError:
        return False
    return True


def _parse_candidate(
    *,
    candidate: Path,
    root: Path,
    distribution: str | None,
    origin_label: str,
) -> SkillEntry | None:
    """Parse one candidate ``SKILL.md`` and attach ``distribution``.

    Returns ``None`` if the parser failed (a warning is emitted) or if
    the resolved path escapes ``root`` (defence in depth — the
    collector already filters, but symlinks could mutate between
    collection and parse).
    """
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        _warn(
            f"SKILL.md at {candidate!s} resolves outside the "
            f"{origin_label} root {root!s}; skipped"
        )
        return None

    try:
        entry = parse_skill_md(resolved)
    except SkillParseError as exc:
        _warn(
            f"malformed SKILL.md under {origin_label} at {resolved!s}: "
            f"{exc}; skipped"
        )
        return None
    except Exception as exc:  # noqa: BLE001 — per-file fault isolation
        _warn(
            f"unexpected error parsing SKILL.md at {resolved!s} under "
            f"{origin_label}: {exc!r}; skipped"
        )
        return None

    if distribution is None:
        return entry
    return replace(entry, source_distribution=distribution)


def _warn(message: str) -> None:
    """Emit a :class:`SkillDiscoveryWarning` from the discovery loop."""
    warnings.warn(message, SkillDiscoveryWarning, stacklevel=3)


__all__ = [
    "SkillDiscoveryWarning",
    "clear_skills_cache",
    "discover_skills",
]
