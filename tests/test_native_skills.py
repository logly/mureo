"""Tests for plugin native-slash-skill deployment (Issue #439).

Covers ``mureo.cli.native_skills``: entry-point discovery, built-in-first and
plugin-first-wins collision handling, fault isolation, path containment, and
the plugin-owned removal allow-list.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import pytest

from mureo.cli.native_skills import (
    NativeSkillDeployWarning,
    install_native_skills,
    remove_native_skills,
)

if TYPE_CHECKING:
    from pathlib import Path


class _FakeEntryPoint:
    """Minimal stand-in for ``importlib.metadata.EntryPoint``."""

    def __init__(
        self, name: str, value: object, *, load_error: Exception | None = None
    ):
        self.name = name
        self._value = value
        self._load_error = load_error

    def load(self) -> object:
        if self._load_error is not None:
            raise self._load_error
        return self._value


def _loader(*eps: _FakeEntryPoint):
    """Return a callable compatible with ``entry_points(group=...)``."""

    def _load(*, group: str) -> tuple[_FakeEntryPoint, ...]:
        assert group == "mureo.native_skills"
        return eps

    return _load


def _make_skill(root: Path, name: str, body: str = "# skill\n") -> Path:
    """Create ``root/<name>/SKILL.md`` and return the skill dir."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test {name}\n---\n{body}",
        encoding="utf-8",
    )
    return skill_dir


def test_no_entry_points_creates_dest_and_returns_zero(tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    count, where = install_native_skills(dest, loader=_loader())
    assert count == 0
    assert where == dest
    assert dest.is_dir()


def test_single_plugin_deploys_all_skill_dirs(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin_skills"
    _make_skill(plugin, "acme-cv-report")
    _make_skill(plugin, "acme-adspot-cleanup")
    dest = tmp_path / "skills"

    count, _ = install_native_skills(
        dest, loader=_loader(_FakeEntryPoint("acme", plugin))
    )

    assert count == 2
    assert (dest / "acme-cv-report" / "SKILL.md").is_file()
    assert (dest / "acme-adspot-cleanup" / "SKILL.md").is_file()


def test_accepts_str_valued_entry_point(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin_skills"
    _make_skill(plugin, "acme-thing")
    dest = tmp_path / "skills"

    # entry point yields a str path (the discoverer coerces it)
    count, _ = install_native_skills(
        dest, loader=_loader(_FakeEntryPoint("acme", str(plugin)))
    )
    assert count == 1
    assert (dest / "acme-thing" / "SKILL.md").is_file()


def test_child_without_skill_md_is_ignored(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin_skills"
    _make_skill(plugin, "acme-real")
    (plugin / "not-a-skill").mkdir()  # no SKILL.md
    dest = tmp_path / "skills"

    count, _ = install_native_skills(
        dest, loader=_loader(_FakeEntryPoint("acme", plugin))
    )
    assert count == 1
    assert not (dest / "not-a-skill").exists()


def test_builtin_name_collision_is_skipped(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin_skills"
    # daily-check is a real bundled skill name; a plugin must not shadow it.
    _make_skill(plugin, "daily-check")
    _make_skill(plugin, "acme-unique")
    dest = tmp_path / "skills"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest, loader=_loader(_FakeEntryPoint("acme", plugin))
        )

    assert count == 1
    assert (dest / "acme-unique").exists()
    assert not (dest / "daily-check").exists()
    assert any(
        isinstance(w.message, NativeSkillDeployWarning)
        and "built-in wins" in str(w.message)
        for w in caught
    )


def test_plugin_vs_plugin_first_wins(tmp_path: Path) -> None:
    plugin_a = tmp_path / "a"
    plugin_b = tmp_path / "b"
    _make_skill(plugin_a, "shared-name", body="# from A\n")
    _make_skill(plugin_b, "shared-name", body="# from B\n")
    dest = tmp_path / "skills"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest,
            loader=_loader(
                _FakeEntryPoint("a", plugin_a),
                _FakeEntryPoint("b", plugin_b),
            ),
        )

    assert count == 1
    # First entry point (A) wins.
    assert "from A" in (dest / "shared-name" / "SKILL.md").read_text()
    assert any(
        isinstance(w.message, NativeSkillDeployWarning)
        and "first-contributed" in str(w.message)
        for w in caught
    )


def test_broken_entry_point_is_isolated(tmp_path: Path) -> None:
    good = tmp_path / "good"
    _make_skill(good, "acme-good")
    dest = tmp_path / "skills"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest,
            loader=_loader(
                _FakeEntryPoint("boom", None, load_error=RuntimeError("kaboom")),
                _FakeEntryPoint("good", good),
            ),
        )

    assert count == 1
    assert (dest / "acme-good").exists()
    assert any(
        isinstance(w.message, NativeSkillDeployWarning) and "boom" in str(w.message)
        for w in caught
    )


def test_non_path_value_is_skipped(tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest, loader=_loader(_FakeEntryPoint("bad", 12345))
        )
    assert count == 0
    assert any(isinstance(w.message, NativeSkillDeployWarning) for w in caught)


def test_missing_directory_value_is_skipped(tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    missing = tmp_path / "does_not_exist"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest, loader=_loader(_FakeEntryPoint("bad", missing))
        )
    assert count == 0
    assert any(isinstance(w.message, NativeSkillDeployWarning) for w in caught)


def test_symlink_escaping_root_is_skipped(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _make_skill(outside, "escapee")  # real skill, but outside the root
    plugin = tmp_path / "plugin_skills"
    plugin.mkdir()
    # A symlinked child that points outside the entry-point root.
    try:
        (plugin / "escapee").symlink_to(outside / "escapee", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    dest = tmp_path / "skills"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest, loader=_loader(_FakeEntryPoint("acme", plugin))
        )

    assert count == 0
    assert not (dest / "escapee").exists()
    assert any(
        isinstance(w.message, NativeSkillDeployWarning) and "escapes" in str(w.message)
        for w in caught
    )


def test_reinstall_replaces_existing(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin_skills"
    _make_skill(plugin, "acme-thing", body="# v1\n")
    dest = tmp_path / "skills"
    install_native_skills(dest, loader=_loader(_FakeEntryPoint("acme", plugin)))
    assert "v1" in (dest / "acme-thing" / "SKILL.md").read_text()

    # Author bumps the skill; a re-deploy must replace, not merge/dup.
    _make_skill(plugin, "acme-thing", body="# v2\n")
    count, _ = install_native_skills(
        dest, loader=_loader(_FakeEntryPoint("acme", plugin))
    )
    assert count == 1
    assert "v2" in (dest / "acme-thing" / "SKILL.md").read_text()


def test_remove_only_touches_plugin_skills(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin_skills"
    _make_skill(plugin, "acme-cv-report")
    dest = tmp_path / "skills"
    # A bundle skill and a user skill also live in dest.
    _make_skill(dest, "daily-check")  # simulates a deployed bundle skill
    _make_skill(dest, "my-personal-skill")  # user-authored

    loader = _loader(_FakeEntryPoint("acme", plugin))
    install_native_skills(dest, loader=loader)
    assert (dest / "acme-cv-report").exists()

    removed, _ = remove_native_skills(dest, loader=loader)

    assert removed == 1
    assert not (dest / "acme-cv-report").exists()
    # Bundle + user skills untouched.
    assert (dest / "daily-check").exists()
    assert (dest / "my-personal-skill").exists()


def test_remove_is_idempotent(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin_skills"
    _make_skill(plugin, "acme-thing")
    dest = tmp_path / "skills"
    loader = _loader(_FakeEntryPoint("acme", plugin))
    install_native_skills(dest, loader=loader)

    assert remove_native_skills(dest, loader=loader)[0] == 1
    assert remove_native_skills(dest, loader=loader)[0] == 0


def test_remove_missing_dest_is_noop(tmp_path: Path) -> None:
    dest = tmp_path / "skills"  # never created
    count, where = remove_native_skills(dest, loader=_loader())
    assert count == 0
    assert where == dest


def test_nested_symlink_escape_does_not_exfiltrate(tmp_path: Path) -> None:
    """A symlink INSIDE a valid skill dir must not copy the link target's
    contents into the deployed skill (copytree deref exfiltration)."""
    secret = tmp_path / "secret.txt"
    secret.write_text("SUPER-SECRET-SSH-KEY", encoding="utf-8")

    plugin = tmp_path / "plugin_skills"
    skill = _make_skill(plugin, "acme-skill")  # legitimate SKILL.md present
    try:
        (skill / "reference.md").symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    dest = tmp_path / "skills"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest, loader=_loader(_FakeEntryPoint("acme", plugin))
        )

    assert count == 0
    assert not (dest / "acme-skill").exists()
    # The secret must NOT have been copied anywhere under dest.
    assert not (dest / "acme-skill" / "reference.md").exists()
    assert any(
        isinstance(w.message, NativeSkillDeployWarning)
        and "escapes the plugin root" in str(w.message)
        for w in caught
    )


def test_two_hop_symlink_dir_escape_does_not_exfiltrate(tmp_path: Path) -> None:
    """A symlinked DIR that lands inside the plugin root but itself contains a
    symlink escaping the root must not leak (copytree follows symlinked dirs)."""
    secret = tmp_path / "secret.txt"
    secret.write_text("SUPER-SECRET-SSH-KEY", encoding="utf-8")

    plugin = tmp_path / "plugin_skills"
    skill = _make_skill(plugin, "acme-skill")
    shared = plugin / "shared"  # sibling dir inside the plugin root
    shared.mkdir()
    try:
        (shared / "escape.txt").symlink_to(secret)  # root-escaping link
        # skill/subdir -> plugin/shared  (lands INSIDE root, so hop 1 "passes")
        (skill / "subdir").symlink_to(shared, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    dest = tmp_path / "skills"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest, loader=_loader(_FakeEntryPoint("acme", plugin))
        )

    assert count == 0
    assert not (dest / "acme-skill").exists()
    # The secret must not have been copied through the two-hop chain.
    assert not (dest / "acme-skill" / "subdir" / "escape.txt").exists()
    assert any(
        isinstance(w.message, NativeSkillDeployWarning)
        and "escapes the plugin root" in str(w.message)
        for w in caught
    )


def test_true_symlink_loop_is_isolated_not_propagated(tmp_path: Path) -> None:
    """A genuine ELOOP symlink (``x -> x``) makes Path.resolve raise
    RuntimeError; it must be isolated to that skill, not abort the whole
    install and strand a healthy sibling from another plugin."""
    evil = tmp_path / "evil_plugin"
    skill = _make_skill(evil, "acme-broken")
    try:
        # Self-referential link = a real OS-level loop (ELOOP), distinct from a
        # link to an ancestor dir which resolves in one hop.
        (skill / "x").symlink_to(skill / "x")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    good = tmp_path / "good_plugin"
    _make_skill(good, "zzz-good")
    dest = tmp_path / "skills"

    # Must not raise (RuntimeError from the containment walk is isolated), and
    # the healthy sibling from the other plugin must still deploy.
    count, _ = install_native_skills(
        dest,
        loader=_loader(
            _FakeEntryPoint("evil", evil),
            _FakeEntryPoint("good", good),
        ),
    )
    assert (dest / "zzz-good" / "SKILL.md").is_file()
    assert not (dest / "acme-broken").exists()
    assert count == 1


def test_intra_plugin_symlink_is_allowed(tmp_path: Path) -> None:
    """A symlink pointing INSIDE the plugin root is fine (not an escape)."""
    plugin = tmp_path / "plugin_skills"
    shared = plugin / "shared.txt"
    plugin.mkdir()
    shared.write_text("shared", encoding="utf-8")
    skill = _make_skill(plugin, "acme-skill")
    try:
        (skill / "ref.md").symlink_to(shared)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    dest = tmp_path / "skills"

    count, _ = install_native_skills(
        dest, loader=_loader(_FakeEntryPoint("acme", plugin))
    )
    assert count == 1
    # copytree dereferenced the intra-plugin link into a real file.
    assert (dest / "acme-skill" / "ref.md").read_text() == "shared"


def test_one_skill_failure_does_not_strand_others(tmp_path: Path) -> None:
    """A per-skill copy failure is isolated; other plugins still deploy."""
    plugin_a = tmp_path / "a"
    plugin_b = tmp_path / "b"
    _make_skill(plugin_a, "aaa-first")
    _make_skill(plugin_b, "zzz-second")
    dest = tmp_path / "skills"
    dest.mkdir()
    # A plain FILE where the first skill's dir would go: _replace_dest's rmtree
    # raises NotADirectoryError. The loop must skip it and still install B.
    (dest / "aaa-first").write_text("i am a file, not a dir", encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _ = install_native_skills(
            dest,
            loader=_loader(
                _FakeEntryPoint("a", plugin_a),
                _FakeEntryPoint("b", plugin_b),
            ),
        )

    assert count == 1
    assert (dest / "zzz-second" / "SKILL.md").is_file()
    assert any(
        isinstance(w.message, NativeSkillDeployWarning)
        and "aaa-first" in str(w.message)
        for w in caught
    )


def test_builtin_skill_names_empty_when_bundle_missing(monkeypatch) -> None:
    import mureo.cli.native_skills as ns

    def _boom(_subdir: str) -> object:
        raise FileNotFoundError("bundle missing")

    monkeypatch.setattr(ns, "_get_data_path", _boom)
    assert ns.builtin_skill_names() == set()
