"""Deploy third-party plugin *native slash skills* into the host skill dirs.

Issue #439. Two entry-point groups carry plugin skills, for two different
purposes:

- ``mureo.skills`` — *context* skills discovered and matched at runtime by
  :mod:`mureo.core.skills.discovery`. These are never copied to
  ``~/.claude/skills`` and so never appear as a ``/slash`` command.
- ``mureo.native_skills`` (this module) — skills the plugin wants *deployed*
  next to mureo's own bundle in ``~/.claude/skills`` / ``~/.codex/skills`` so
  they are invocable as ``/<skill>``.

A plugin registers a directory of ``<skill>/SKILL.md`` subdirs (same shape as
``mureo/_data/skills``); this module copies those subdirs into the target.

Safety (mirrors the bundle installer and the discovery walker):

- **Built-in-first**: a plugin skill whose directory name collides with a
  mureo bundle skill is skipped — a plugin can never shadow a core ``/slash``.
- **First-wins between plugins**: the first plugin to contribute a given
  skill name wins; later contributions are skipped with a warning.
- **Fault isolation**: a broken entry point (load error, wrong type, missing
  directory) is warned and skipped; the rest still deploy.
- **Path containment**: each candidate skill dir is resolved and must live
  under the entry-point root; symlink escapes are skipped.
- **Plugin-owned removal allow-list**: :func:`remove_native_skills` only
  removes names the *currently installed* plugins contribute (minus any
  bundle collision), so it never touches the bundle or user-authored skills.
  A skill orphaned by an uninstalled plugin is therefore left in place — the
  same "derive the allow-list from the live source" trade-off the bundle
  remover (:func:`mureo.cli.setup_cmd.remove_skills`) makes.
"""

from __future__ import annotations

import contextlib
import shutil
import warnings
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING

from mureo.cli.setup_cmd import _get_data_path, _replace_dest
from mureo.core.providers.registry import NATIVE_SKILLS_ENTRY_POINT_GROUP

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from typing import Any

    # The injectable entry-points loader: ``entry_points`` itself, or a test
    # double. Called as ``loader(group=...)`` and yields EntryPoint-likes.
    EntryPointLoader = Callable[..., Iterable[Any]]


class NativeSkillDeployWarning(UserWarning):
    """Emitted when a plugin native skill is skipped during deployment.

    Distinct :class:`UserWarning` subclass so a strict deployment can opt
    into ``warnings.filterwarnings("error", category=NativeSkillDeployWarning)``
    (mirrors :class:`mureo.core.skills.discovery.SkillDiscoveryWarning`).
    """


def _warn(message: str) -> None:
    warnings.warn(message, NativeSkillDeployWarning, stacklevel=3)


def _coerce_to_dir(value: object) -> Path | None:
    """Return ``value`` as a resolved existing-directory :class:`Path`, else
    ``None``.

    Only :class:`Path` and ``str`` are accepted (same contract as the
    ``mureo.skills`` discoverer's ``_coerce_to_path``); anything else is
    rejected. The path is resolved so the containment guard has a stable base.
    """
    if isinstance(value, Path):
        root = value
    elif isinstance(value, str):
        root = Path(value)
    else:
        return None
    resolved = root.resolve()
    return resolved if resolved.is_dir() else None


def _is_under(root: Path, candidate: Path) -> bool:
    """True iff ``candidate`` resolves to a path inside ``root``.

    Symlink-aware: the candidate is fully resolved before the check, so a
    link that points outside ``root`` returns ``False``. Mirrors
    :func:`mureo.core.skills.discovery._is_under` (no ``walk_up``).

    ``RuntimeError`` is caught alongside ``OSError``/``ValueError`` because
    CPython's ``Path.resolve`` converts a genuine symlink loop (ELOOP, e.g.
    ``x -> x``) into ``RuntimeError("Symlink loop from ...")`` rather than an
    ``OSError`` — an unresolvable path is treated as not-contained (unsafe).
    """
    try:
        candidate.resolve().relative_to(root)
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def builtin_skill_names() -> set[str]:
    """Return the set of mureo bundle skill directory names.

    These are reserved: a plugin native skill may never overwrite one. A
    missing/broken bundle (rare — corrupt install) yields an empty set so a
    plugin deploy still proceeds rather than crashing.
    """
    try:
        src = _get_data_path("skills")
    except FileNotFoundError:
        return set()
    return {
        child.name
        for child in src.iterdir()
        if child.is_dir() and (child / "SKILL.md").exists()
    }


def _iter_native_roots(
    loader: EntryPointLoader | None,
) -> Iterator[tuple[str, Path]]:
    """Yield ``(entry_point_name, resolved_root_dir)`` for each valid plugin.

    Fault-isolated: a failure to iterate the group, load an entry point, or
    coerce its value to a directory is warned and skipped — never raised.
    """
    load = loader or entry_points
    try:
        eps: tuple[Any, ...] = tuple(load(group=NATIVE_SKILLS_ENTRY_POINT_GROUP))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 — discovery must not crash
        _warn(f"native-skill entry-point discovery failed: {exc!r}")
        return

    for ep in eps:
        ep_name = getattr(ep, "name", "<unknown>")
        # ``ep.load()`` runs arbitrary plugin import code and ``_coerce_to_dir``
        # calls ``Path.resolve`` (which can raise on a symlink loop), so both
        # are inside the per-plugin fault boundary.
        try:
            loaded = ep.load()
            root = _coerce_to_dir(loaded)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — per-plugin isolation
            _warn(
                f"native-skill entry point {ep_name!r} failed to load: "
                f"{exc!r}; skipped"
            )
            continue
        if root is None:
            _warn(
                f"native-skill entry point {ep_name!r} did not yield an "
                f"existing directory (got {type(loaded).__name__}); skipped"
            )
            continue
        yield ep_name, root


def _tree_is_contained(top: Path, root: Path) -> bool:
    """True iff every entry reachable under ``top`` resolves inside ``root``.

    ``shutil.copytree`` dereferences symlinks by default, so a symlink *inside*
    an otherwise-valid skill dir (e.g. ``reference.md -> ~/.ssh/id_rsa``) would
    copy the link target's **contents** into the deployed skill — a plugin
    could exfiltrate any readable file into ``~/.claude/skills``.

    We must walk exactly the paths ``copytree`` would, which means **following
    symlinked directories** (``copytree`` recurses into them): a symlinked dir
    that lands inside ``root`` can itself hold a symlink escaping ``root``
    (a two-hop escape). ``os.walk(followlinks=False)`` misses that, so this
    walks iteratively, descending into symlinked dirs, guarding against
    symlink loops with a resolved-path visited set, and rejecting the skill the
    moment any child's resolved path escapes ``root``.
    """
    visited: set[Path] = set()
    stack: list[Path] = [top]
    while stack:
        directory = stack.pop()
        try:
            real = directory.resolve()
        except (OSError, RuntimeError):  # RuntimeError = ELOOP (see _is_under)
            return False
        if real in visited:  # symlink loop already validated — stop recursing
            continue
        visited.add(real)
        try:
            children = list(directory.iterdir())
        except OSError:
            return False
        for child in children:
            # ``_is_under`` resolves the full symlink chain, so a link that
            # ultimately escapes ``root`` is rejected here before we descend.
            if not _is_under(root, child):
                return False
            if child.is_dir():  # follows symlinked dirs, mirroring copytree
                stack.append(child)
    return True


def _plugin_skill_dirs(root: Path, ep_name: str) -> list[Path]:
    """Return the immediate child skill dirs (contain ``SKILL.md``) of ``root``.

    Only depth-1 children are considered — one directory per skill, matching
    the bundle layout. Symlinked children that escape ``root`` are skipped.
    Sorted for deterministic first-wins ordering.
    """
    dirs: list[Path] = []
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        _warn(f"cannot list native-skill dir {root!s} ({ep_name!r}): {exc}")
        return dirs
    for child in children:
        if not child.is_dir():
            continue
        if not _is_under(root, child):
            _warn(
                f"native-skill dir {child!s} under {ep_name!r} escapes the "
                f"entry-point root {root!s}; skipped"
            )
            continue
        if (child / "SKILL.md").is_file():
            dirs.append(child)
    return dirs


def _contributed_skills(
    loader: EntryPointLoader | None,
) -> dict[str, tuple[Path, Path]]:
    """Resolve the plugin-contributed skill name → ``(skill_dir, ep_root)`` map.

    Applies built-in-first (bundle names reserved) and first-wins between
    plugins. The returned mapping is exactly the set of names this module is
    allowed to install and, symmetrically, to remove. ``ep_root`` is kept so
    the installer can verify the skill's subtree is contained (no symlink
    escaping the plugin) before copying.
    """
    reserved = builtin_skill_names()
    contributed: dict[str, tuple[Path, Path]] = {}
    for ep_name, root in _iter_native_roots(loader):
        for skill_dir in _plugin_skill_dirs(root, ep_name):
            name = skill_dir.name
            if name in reserved:
                _warn(
                    f"native skill {name!r} from {ep_name!r} collides with a "
                    f"built-in mureo skill; built-in wins, plugin copy skipped"
                )
                continue
            if name in contributed:
                _warn(
                    f"duplicate native skill {name!r}: first-contributed copy "
                    f"wins; {ep_name!r}'s copy at {skill_dir!s} skipped"
                )
                continue
            contributed[name] = (skill_dir, root)
    return contributed


def install_native_skills(
    target_dir: Path | None = None,
    *,
    loader: EntryPointLoader | None = None,
) -> tuple[int, Path]:
    """Copy plugin ``mureo.native_skills`` dirs into ``target_dir``.

    Each skill's subtree is verified contained (no symlink escaping the plugin
    root) before copying, and every copy is isolated: one skill's failure —
    an escaping symlink, a permission error, a destination collision with a
    plain file — is warned and skipped, leaving the rest to deploy.

    Args:
        target_dir: Destination skills directory. Defaults to
            ``~/.claude/skills``. Callers deploying for Codex pass
            ``~/.codex/skills``.
        loader: Injectable replacement for
            :func:`importlib.metadata.entry_points` (tests).

    Returns:
        ``(number of skill dirs deployed, target directory path)``.
    """
    dest = target_dir or (Path.home() / ".claude" / "skills")
    dest.mkdir(parents=True, exist_ok=True)

    count = 0
    for name, (skill_dir, root) in _contributed_skills(loader).items():
        target = dest / name
        # The whole per-skill body — containment check AND copy — is inside the
        # fault boundary. Broad on purpose: the containment walk can hit a
        # genuine symlink loop and copytree can raise OSError / shutil.Error /
        # RecursionError. Whatever the mode, isolate it to this one skill so a
        # single broken/hostile plugin cannot strand the others.
        try:
            if not _tree_is_contained(skill_dir, root):
                _warn(
                    f"native skill {name!r} at {skill_dir!s} contains a symlink "
                    f"that escapes the plugin root {root!s}; skipped for safety"
                )
                continue
            _replace_dest(target)
            # Subtree verified contained above, so the default deref-symlinks
            # behaviour cannot pull in a file from outside the plugin.
            shutil.copytree(skill_dir, target)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — per-skill fault isolation
            _warn(
                f"failed to deploy native skill {name!r} from {skill_dir!s}: "
                f"{exc!r}; skipped"
            )
            # Clean up a partial target so a failed copy leaves no debris.
            with contextlib.suppress(OSError):
                _replace_dest(target)
            continue
        count += 1
    return count, dest


def remove_native_skills(
    target_dir: Path | None = None,
    *,
    loader: EntryPointLoader | None = None,
) -> tuple[int, Path]:
    """Remove plugin-contributed native skills from ``target_dir``.

    The allow-list is derived from the *currently installed* plugins (minus
    any bundle collision), so the bundle's own skills and user-authored
    skills are never touched. Idempotent: a second call returns ``(0, dest)``.
    A missing destination is a graceful no-op. Symlinks are ``unlink``-ed
    rather than ``rmtree``-d so a dev copy at the link target is preserved.
    Per-skill failures are isolated so one undeletable entry does not strand
    the rest.
    """
    dest = target_dir or (Path.home() / ".claude" / "skills")
    if not dest.exists():
        return 0, dest

    count = 0
    for name in _contributed_skills(loader):
        candidate = dest / name
        try:
            if candidate.is_symlink():
                candidate.unlink()
                count += 1
            elif candidate.exists():
                shutil.rmtree(candidate)
                count += 1
        except OSError as exc:
            _warn(f"failed to remove native skill {name!r} at {candidate!s}: {exc}")
    return count, dest


__all__ = [
    "NativeSkillDeployWarning",
    "builtin_skill_names",
    "install_native_skills",
    "remove_native_skills",
]
