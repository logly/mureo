"""Tests for ``mureo.core.skills.discovery`` (RED phase, Issue #89 P1-08).

These tests pin the entry-points-based skill discovery contract:

- Iterates ``importlib.metadata.entry_points(group="mureo.skills")``.
- Each entry point loads to a ``Path``-like (Option B in the plan); the
  discoverer recursively walks the directory looking for ``SKILL.md``.
- Bounded by max recursion depth 4 and max 64 files per entry point.
- Always also scans the in-tree built-in skills directory.
- Per-entry try/except: a broken plugin emits
  :class:`SkillDiscoveryWarning` and is skipped.
- First-wins on duplicate ``name``.
- Idempotent + cached behind a module-level singleton; ``refresh=True``
  re-iterates.
- Path-traversal guard: symlinks escaping the entry-point root are
  rejected with a warning.

NOTE: these imports are expected to FAIL during the RED phase — the
module ``mureo.core.skills.discovery`` does not exist yet.
"""

from __future__ import annotations

import os
import types
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from mureo.core.providers.registry import SKILLS_ENTRY_POINT_GROUP
from mureo.core.skills.discovery import (  # noqa: E402 — RED-phase import
    SkillDiscoveryWarning,
    discover_skills,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_MIN_FRONTMATTER_TEMPLATE = (
    "---\n" "name: {name}\n" 'description: "Test skill {name}."\n' "---\n" "# {name}\n"
)


def _write_skill_md(dir_path: Path, name: str) -> Path:
    """Create ``dir_path/<name>/SKILL.md`` with a minimal valid frontmatter."""
    sub = dir_path / name
    sub.mkdir(parents=True, exist_ok=True)
    p = sub / "SKILL.md"
    p.write_text(_MIN_FRONTMATTER_TEMPLATE.format(name=name), encoding="utf-8")
    return p


def _make_fake_entry_point(
    *,
    name: str,
    distribution: str | None,
    load_result: object | None = None,
    load_exception: BaseException | None = None,
) -> types.SimpleNamespace:
    """Build a duck-typed ``EntryPoint`` for the discoverer to consume.

    Mirrors the pattern used in
    ``tests/core/providers/test_registry_discovery.py``.
    """

    def _load() -> object:
        if load_exception is not None:
            raise load_exception
        return load_result

    dist: types.SimpleNamespace | None = (
        None if distribution is None else types.SimpleNamespace(name=distribution)
    )

    return types.SimpleNamespace(
        name=name,
        group=SKILLS_ENTRY_POINT_GROUP,
        dist=dist,
        load=_load,
    )


@pytest.fixture(autouse=True)
def _reset_discovery_cache() -> Any:
    """Best-effort reset of the discovery singleton between tests.

    The discovery module exposes ``refresh=True``; we additionally
    attempt to clear any module-level cache attribute the implementer
    may add (mirrors the registry's ``clear_registry`` pattern). The
    ``getattr`` fallback keeps this fixture tolerant of either naming.
    """
    from mureo.core.skills import discovery as _discovery  # noqa: PLC0415

    clear = getattr(_discovery, "clear_skills_cache", None)
    if callable(clear):
        clear()
    yield
    if callable(clear):
        clear()


# ---------------------------------------------------------------------------
# Case 1 — built-in scan finds the in-tree skills (integration)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_builtin_scan_finds_in_tree_skills() -> None:
    """Calling :func:`discover_skills` with NO third-party entry points
    must still surface at least one SKILL.md from the in-tree built-in
    directory (so built-in skills work without an entry point).
    """

    def _no_entry_points(group: str) -> tuple[Any, ...]:
        assert group == SKILLS_ENTRY_POINT_GROUP
        return ()

    with patch(
        "mureo.core.skills.discovery.entry_points",
        side_effect=_no_entry_points,
    ):
        entries = discover_skills(refresh=True)

    assert len(entries) >= 1, "built-in scan must yield at least one skill"
    names = {e.name for e in entries}
    # daily-check is one of the known built-ins.
    assert "daily-check" in names, f"expected daily-check among built-ins; got {names}"


# ---------------------------------------------------------------------------
# Case 2 — entry point → directory scan finds both SKILL.md files
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_entry_point_directory_scan_finds_skills(tmp_path: Path) -> None:
    """A fake entry point whose ``load()`` returns a directory ``Path``
    containing two ``SKILL.md`` files in subdirs: both surface.
    """
    _write_skill_md(tmp_path, "alpha-skill")
    _write_skill_md(tmp_path, "beta-skill")

    ep = _make_fake_entry_point(
        name="ep_a",
        distribution="mureo-fake-plugin",
        load_result=tmp_path,
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (ep,)

    with patch(
        "mureo.core.skills.discovery.entry_points",
        side_effect=_eps,
    ):
        entries = discover_skills(refresh=True)

    names = {e.name for e in entries}
    assert "alpha-skill" in names
    assert "beta-skill" in names
    for e in entries:
        if e.name in {"alpha-skill", "beta-skill"}:
            assert e.source_distribution == "mureo-fake-plugin"


# ---------------------------------------------------------------------------
# Case 3 — entry point returns non-Path → warning, skipped
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_entry_point_non_path_load_warns_and_skips(tmp_path: Path) -> None:
    """An EP whose ``load()`` returns something other than a ``Path | str``
    must emit :class:`SkillDiscoveryWarning` and contribute zero entries
    (but not raise).
    """
    bad_ep = _make_fake_entry_point(
        name="bad_value",
        distribution="mureo-bad-plugin",
        load_result=42,
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (bad_ep,)

    with (
        patch(
            "mureo.core.skills.discovery.entry_points",
            side_effect=_eps,
        ),
        pytest.warns(SkillDiscoveryWarning),
    ):
        entries = discover_skills(refresh=True)

    names = {e.name for e in entries}
    # Only built-ins should remain; the bad EP contributes nothing.
    assert all(not n.startswith("bad_value") for n in names)


# ---------------------------------------------------------------------------
# Case 4 — entry point load() raises → warning, skipped
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_entry_point_load_exception_warns_and_skips() -> None:
    """A broken plugin whose ``ep.load()`` raises emits a warning and is
    skipped. Discovery does not abort.
    """
    broken = _make_fake_entry_point(
        name="broken",
        distribution="mureo-broken-plugin",
        load_exception=ImportError("simulated broken plugin"),
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (broken,)

    with (
        patch(
            "mureo.core.skills.discovery.entry_points",
            side_effect=_eps,
        ),
        pytest.warns(SkillDiscoveryWarning, match="broken"),
    ):
        # Must not raise.
        discover_skills(refresh=True)


# ---------------------------------------------------------------------------
# Case 5 — malformed SKILL.md alongside well-formed siblings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_malformed_skill_md_skipped_well_formed_surfaces(tmp_path: Path) -> None:
    """One malformed ``SKILL.md`` warns and is skipped; its well-formed
    siblings still surface.
    """
    _write_skill_md(tmp_path, "good-skill")

    # Malformed sibling: missing required ``description`` key.
    bad_dir = tmp_path / "bad-skill"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text(
        "---\nname: bad-skill\n---\nbody\n", encoding="utf-8"
    )

    ep = _make_fake_entry_point(
        name="ep_mixed",
        distribution="mureo-mixed-plugin",
        load_result=tmp_path,
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (ep,)

    with (
        patch(
            "mureo.core.skills.discovery.entry_points",
            side_effect=_eps,
        ),
        pytest.warns(SkillDiscoveryWarning),
    ):
        entries = discover_skills(refresh=True)

    names = {e.name for e in entries}
    assert "good-skill" in names
    assert "bad-skill" not in names


# ---------------------------------------------------------------------------
# Case 6 — duplicate skill name: first-wins
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_duplicate_skill_name_first_wins(tmp_path: Path) -> None:
    """Two entry points contribute a skill with the same name; the first
    survives and the second emits :class:`SkillDiscoveryWarning`.
    """
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _write_skill_md(dir_a, "shared-name")
    _write_skill_md(dir_b, "shared-name")

    ep_a = _make_fake_entry_point(
        name="ep_a",
        distribution="dist-a",
        load_result=dir_a,
    )
    ep_b = _make_fake_entry_point(
        name="ep_b",
        distribution="dist-b",
        load_result=dir_b,
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (ep_a, ep_b)

    with (
        patch(
            "mureo.core.skills.discovery.entry_points",
            side_effect=_eps,
        ),
        pytest.warns(SkillDiscoveryWarning, match="(?i)duplicate|shadow"),
    ):
        entries = discover_skills(refresh=True)

    shared = [e for e in entries if e.name == "shared-name"]
    assert len(shared) == 1, "first-wins must keep exactly one entry"
    assert shared[0].source_distribution == "dist-a"


# ---------------------------------------------------------------------------
# Case 7 — idempotent caching: second call does NOT re-iterate
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_skills_is_cached() -> None:
    """A second :func:`discover_skills` call without ``refresh=True``
    must NOT re-call ``entry_points``.
    """
    call_counter = {"n": 0}

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        call_counter["n"] += 1
        return ()

    with patch(
        "mureo.core.skills.discovery.entry_points",
        side_effect=_eps,
    ):
        first = discover_skills(refresh=True)
        second = discover_skills()  # cached
        assert second == first
        assert call_counter["n"] == 1, (
            "entry_points must be iterated exactly once when refresh is "
            f"not requested; got {call_counter['n']}"
        )


# ---------------------------------------------------------------------------
# Case 8 — refresh=True re-iterates
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_skills_refresh_reiterates() -> None:
    """``refresh=True`` must force re-iteration of ``entry_points``."""
    call_counter = {"n": 0}

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        call_counter["n"] += 1
        return ()

    with patch(
        "mureo.core.skills.discovery.entry_points",
        side_effect=_eps,
    ):
        discover_skills(refresh=True)
        discover_skills(refresh=True)
        assert (
            call_counter["n"] >= 2
        ), f"refresh=True must re-iterate; got call_counter={call_counter['n']}"


# ---------------------------------------------------------------------------
# Case 9 — directory recursion bounded at depth 4
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discovery_depth_limit_at_4(tmp_path: Path) -> None:
    """A SKILL.md nested deeper than the configured max depth (4) is NOT
    picked up; the discoverer emits a warning rather than silently
    descending.

    The "depth" is measured relative to the entry-point root. A file at
    ``root/l1/l2/l3/l4/l5/SKILL.md`` (5 levels deep) is too deep; a file
    at ``root/l1/l2/SKILL.md`` is fine.
    """
    too_deep = tmp_path / "l1" / "l2" / "l3" / "l4" / "l5"
    too_deep.mkdir(parents=True)
    (too_deep / "SKILL.md").write_text(
        _MIN_FRONTMATTER_TEMPLATE.format(name="deep-skill"), encoding="utf-8"
    )
    # Shallow sibling that MUST surface.
    _write_skill_md(tmp_path, "shallow-skill")

    ep = _make_fake_entry_point(
        name="ep_deep",
        distribution="dist-deep",
        load_result=tmp_path,
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (ep,)

    with (
        patch(
            "mureo.core.skills.discovery.entry_points",
            side_effect=_eps,
        ),
        pytest.warns(SkillDiscoveryWarning, match="(?i)depth|deep"),
    ):
        entries = discover_skills(refresh=True)

    names = {e.name for e in entries}
    assert "shallow-skill" in names
    assert "deep-skill" not in names


# ---------------------------------------------------------------------------
# Case 10 — file count cap per entry point at 64
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discovery_file_count_cap_at_64(tmp_path: Path) -> None:
    """A directory containing 65 SKILL.md files: only 64 surface, and a
    :class:`SkillDiscoveryWarning` mentioning the cap is emitted.
    """
    for i in range(65):
        _write_skill_md(tmp_path, f"skill-{i:03d}")

    ep = _make_fake_entry_point(
        name="ep_many",
        distribution="dist-many",
        load_result=tmp_path,
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (ep,)

    with (
        patch(
            "mureo.core.skills.discovery.entry_points",
            side_effect=_eps,
        ),
        pytest.warns(SkillDiscoveryWarning, match="(?i)cap|limit|64"),
    ):
        entries = discover_skills(refresh=True)

    from_this_ep = [e for e in entries if e.name.startswith("skill-")]
    assert (
        len(from_this_ep) == 64
    ), f"expected exactly 64 skills under cap; got {len(from_this_ep)}"


# ---------------------------------------------------------------------------
# Case 11 — source_distribution propagated from ep.dist.name
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_source_distribution_propagated_from_ep_dist_name(tmp_path: Path) -> None:
    """The discoverer captures ``ep.dist.name`` into
    ``SkillEntry.source_distribution`` for every skill it picks up from
    that entry point.
    """
    _write_skill_md(tmp_path, "branded-skill")

    ep = _make_fake_entry_point(
        name="ep_branded",
        distribution="branded-pkg",
        load_result=tmp_path,
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (ep,)

    with patch(
        "mureo.core.skills.discovery.entry_points",
        side_effect=_eps,
    ):
        entries = discover_skills(refresh=True)

    branded = [e for e in entries if e.name == "branded-skill"]
    assert len(branded) == 1
    assert branded[0].source_distribution == "branded-pkg"


# ---------------------------------------------------------------------------
# Case 12 — path-traversal guard: symlink escaping ep root is rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_path_traversal_symlink_rejected(tmp_path: Path) -> None:
    """A symlink that points *outside* the entry-point root is rejected
    (parser/discovery emits a warning and does not follow it).

    Scenario: the entry point's directory contains a symlink named
    ``escapee`` pointing at a sibling directory ``../outside/`` that
    contains a SKILL.md. The traversal must NOT be followed.
    """
    ep_root = tmp_path / "ep_root"
    outside = tmp_path / "outside"
    ep_root.mkdir()
    outside.mkdir()

    # SKILL.md outside the ep root — would be a security breach if discovered.
    (outside / "evil").mkdir()
    (outside / "evil" / "SKILL.md").write_text(
        _MIN_FRONTMATTER_TEMPLATE.format(name="evil-skill"), encoding="utf-8"
    )

    # Symlink inside the ep root pointing at the outside dir.
    try:
        os.symlink(outside, ep_root / "escapee", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("OS does not support symlinks in this test environment")

    # And one legitimate sibling so the test can confirm normal scan still works.
    _write_skill_md(ep_root, "legit-skill")

    ep = _make_fake_entry_point(
        name="ep_escape",
        distribution="dist-escape",
        load_result=ep_root,
    )

    def _eps(group: str) -> tuple[Any, ...]:  # noqa: ARG001
        return (ep,)

    with patch(
        "mureo.core.skills.discovery.entry_points",
        side_effect=_eps,
    ):
        entries = discover_skills(refresh=True)

    names = {e.name for e in entries}
    assert "legit-skill" in names
    assert (
        "evil-skill" not in names
    ), "discovery must not follow symlinks that escape the entry-point root"
