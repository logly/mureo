"""Unit tests for ``mureo.cli.setup_cmd.remove_skills`` — RED phase (TDD).

These tests pin the symmetric ``remove_skills`` counterpart of
``install_skills``. Per CTO decision #2 in the planner HANDOFF
``feat-web-config-ui-phase1-uninstall.md``: removal MUST be
bundle-driven (allow-list from ``_get_data_path("skills")``), NOT
prefix-based. A prefix-based remove would leave non-prefixed bundle
skills (``daily-check``, ``onboard``, etc.) behind on uninstall.

Acceptance criteria pinned here:
- Removes only directories whose names match the install bundle.
- User-installed skills outside the bundle (e.g. ``my-custom/``) survive.
- Idempotent — second call returns ``(0, dest)``.
- Tolerates missing destination directory.
- Symlinked skill dirs are ``unlink``-ed, not ``rmtree``-ed (the link's
  target survives) — mirrors ``_replace_dest`` symlink-aware logic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_skill_dir(parent: Path, name: str, content: str = "skill body") -> Path:
    """Create a directory with a ``SKILL.md`` file inside ``parent``."""
    d = parent / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


# Bundle children present in ``mureo/_data/skills/`` (per AGENTS.md
# architecture overview L116-L119). Pinned here so the test does not
# depend on filesystem inspection at runtime.
_BUNDLE_NAMES = (
    "_mureo-google-ads",
    "_mureo-learning",
    "_mureo-meta-ads",
    "_mureo-shared",
    "_mureo-strategy",
    "budget-rebalance",
    "competitive-scan",
    "creative-refresh",
    "daily-check",
    "goal-review",
    "onboard",
    "rescue",
    "search-term-cleanup",
    "sync-state",
    "weekly-report",
)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveSkillsBasics:
    def test_removes_bundle_children_only(self, tmp_path: Path) -> None:
        """All bundle skill dirs are removed; a user-created custom skill
        ``my-custom/`` survives (CTO decision #2, acceptance criteria
        L128-L130)."""
        from mureo.cli.setup_cmd import install_skills, remove_skills

        target = tmp_path / "skills"
        install_skills(target_dir=target)
        # User-installed custom skill — not in the bundle.
        custom = _make_skill_dir(target, "my-custom", "user-owned")
        assert custom.exists()

        count, dest = remove_skills(target_dir=target)

        assert dest == target
        # Every bundle child is gone.
        for name in _BUNDLE_NAMES:
            assert not (target / name).exists(), f"bundle child {name} survived"
        # User-installed skill still present.
        assert (target / "my-custom" / "SKILL.md").read_text(encoding="utf-8") == (
            "user-owned"
        )
        # count == number of bundle skills actually removed.
        assert count == len(_BUNDLE_NAMES)

    def test_idempotent_when_destination_empty(self, tmp_path: Path) -> None:
        """Calling on an empty target returns ``(0, target)`` without
        error (acceptance criteria L131)."""
        from mureo.cli.setup_cmd import remove_skills

        target = tmp_path / "skills"
        target.mkdir()

        count, dest = remove_skills(target_dir=target)

        assert count == 0
        assert dest == target

    def test_idempotent_second_call(self, tmp_path: Path) -> None:
        """A second remove on an already-removed state returns ``(0, dest)``."""
        from mureo.cli.setup_cmd import install_skills, remove_skills

        target = tmp_path / "skills"
        install_skills(target_dir=target)
        first_count, _ = remove_skills(target_dir=target)
        second_count, _ = remove_skills(target_dir=target)

        assert first_count == len(_BUNDLE_NAMES)
        assert second_count == 0

    def test_dest_dir_absent_is_graceful_noop(self, tmp_path: Path) -> None:
        """A missing destination dir returns ``(0, target)`` without raising
        (acceptance criteria L131 — "tolerates the destination directory
        being absent")."""
        from mureo.cli.setup_cmd import remove_skills

        target = tmp_path / "absent"  # never created
        assert not target.exists()

        count, dest = remove_skills(target_dir=target)

        assert count == 0
        assert dest == target

    def test_default_path_uses_path_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omitting ``target_dir`` resolves to ``~/.claude/skills``."""
        from mureo.cli.setup_cmd import install_skills, remove_skills

        monkeypatch.setattr("mureo.cli.setup_cmd.Path.home", lambda: tmp_path)
        install_skills()

        count, dest = remove_skills()

        assert dest == tmp_path / ".claude" / "skills"
        assert count == len(_BUNDLE_NAMES)


@pytest.mark.unit
class TestRemoveSkillsSafety:
    def test_returns_tuple_of_int_and_path(self, tmp_path: Path) -> None:
        """Return type contract: ``tuple[int, Path]``."""
        from mureo.cli.setup_cmd import remove_skills

        target = tmp_path / "skills"
        target.mkdir()

        result = remove_skills(target_dir=target)

        assert isinstance(result, tuple)
        assert len(result) == 2
        count, dest = result
        assert isinstance(count, int)
        assert isinstance(dest, Path)

    def test_preserves_non_skill_dir_with_matching_name(
        self, tmp_path: Path
    ) -> None:
        """If a bundle-named entry lacks ``SKILL.md`` (a user dir that
        happens to share a bundle name), the implementer must still
        remove it because the allow-list is bundle-membership, not
        SKILL.md presence in the destination. A bundle-named dir is FROM
        the install bundle by definition."""
        from mureo.cli.setup_cmd import remove_skills

        target = tmp_path / "skills"
        target.mkdir()
        # User-created dir whose name matches a bundle skill but has no SKILL.md.
        oddball = target / "onboard"
        oddball.mkdir()
        (oddball / "stray-file.md").write_text("user-added", encoding="utf-8")

        count, _ = remove_skills(target_dir=target)

        # Bundle-named dir is removed (it matched the allow-list).
        assert not oddball.exists()
        assert count == 1

    def test_does_not_remove_unrelated_user_dirs(self, tmp_path: Path) -> None:
        """A user dir not in the bundle (and not even shaped like a skill)
        survives untouched, including its contents."""
        from mureo.cli.setup_cmd import install_skills, remove_skills

        target = tmp_path / "skills"
        install_skills(target_dir=target)
        user_dir = target / "totally-custom"
        user_dir.mkdir()
        (user_dir / "scratch.txt").write_text("important", encoding="utf-8")
        (user_dir / "sub").mkdir()
        (user_dir / "sub" / "nested.txt").write_text(
            "nested-data", encoding="utf-8"
        )

        remove_skills(target_dir=target)

        assert user_dir.exists()
        assert (user_dir / "scratch.txt").read_text(encoding="utf-8") == "important"
        assert (user_dir / "sub" / "nested.txt").read_text(encoding="utf-8") == (
            "nested-data"
        )

    def test_handles_symlinked_bundle_skill(self, tmp_path: Path) -> None:
        """A symlinked bundle skill dir is ``unlink``-ed (not ``rmtree``-ed);
        the link's target survives. Mirrors ``_replace_dest`` (planner
        HANDOFF L276-L279)."""
        from mureo.cli.setup_cmd import remove_skills

        external = tmp_path / "external" / "_mureo-shared"
        external.mkdir(parents=True)
        (external / "SKILL.md").write_text("dev copy", encoding="utf-8")
        (external / "precious.txt").write_text("do not delete", encoding="utf-8")

        target = tmp_path / "skills"
        target.mkdir()
        link = target / "_mureo-shared"
        link.symlink_to(external, target_is_directory=True)

        count, _ = remove_skills(target_dir=target)

        # Symlink itself is gone.
        assert not link.is_symlink()
        assert not link.exists()
        # External target untouched.
        assert external.exists()
        assert (external / "SKILL.md").read_text(encoding="utf-8") == "dev copy"
        assert (external / "precious.txt").read_text(encoding="utf-8") == (
            "do not delete"
        )
        assert count == 1

    def test_no_glob_removal(self, tmp_path: Path) -> None:
        """A user-created skill whose name starts with ``_mureo-`` prefix
        but is NOT a bundle skill (e.g. ``_mureo-custom``) must NOT be
        removed. The remove allow-list is bundle-driven (CTO decision
        #2), not prefix-based."""
        from mureo.cli.setup_cmd import remove_skills

        target = tmp_path / "skills"
        target.mkdir()
        # User-installed skill that shares the ``_mureo-`` prefix.
        user_skill = _make_skill_dir(target, "_mureo-custom", "user content")

        count, _ = remove_skills(target_dir=target)

        assert user_skill.exists(), "_mureo-custom must NOT be removed"
        assert (user_skill / "SKILL.md").read_text(encoding="utf-8") == (
            "user content"
        )
        assert count == 0

    def test_count_matches_actually_removed(self, tmp_path: Path) -> None:
        """When only a subset of bundle skills are present, the returned
        count == number of dirs actually removed (not total bundle size)."""
        from mureo.cli.setup_cmd import remove_skills

        target = tmp_path / "skills"
        # Only two of the bundle skills are present.
        _make_skill_dir(target, "daily-check", "x")
        _make_skill_dir(target, "_mureo-shared", "y")

        count, _ = remove_skills(target_dir=target)

        assert count == 2
        assert not (target / "daily-check").exists()
        assert not (target / "_mureo-shared").exists()


@pytest.mark.unit
class TestRemoveSkillsAllowListSource:
    def test_uses_get_data_path_skills_for_allow_list(
        self, tmp_path: Path
    ) -> None:
        """The remove allow-list is derived from
        ``_get_data_path("skills")`` — verify by patching
        ``_get_data_path`` to return a synthetic bundle dir."""
        from mureo.cli.setup_cmd import remove_skills

        # Synthetic install-bundle source containing only one skill.
        fake_src = tmp_path / "fake_bundle"
        _make_skill_dir(fake_src, "only-one", "bundle-shape")

        target = tmp_path / "skills"
        # Both a "bundle" dir and an unrelated dir are present.
        _make_skill_dir(target, "only-one", "installed-bundle")
        _make_skill_dir(target, "third-party", "user-installed")

        with patch(
            "mureo.cli.setup_cmd._get_data_path", return_value=fake_src
        ):
            count, _ = remove_skills(target_dir=target)

        # Only the bundle member is removed.
        assert not (target / "only-one").exists()
        # Non-bundle dir survives.
        assert (target / "third-party").exists()
        assert (target / "third-party" / "SKILL.md").read_text(encoding="utf-8") == (
            "user-installed"
        )
        assert count == 1

    def test_bundle_dir_missing_skill_md_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """A child in the bundle source dir that lacks ``SKILL.md`` is
        NOT part of the allow-list — symmetric with ``install_skills``
        which only copies ``is_dir() and (SKILL.md).exists()`` children."""
        from mureo.cli.setup_cmd import remove_skills

        fake_src = tmp_path / "fake_bundle"
        _make_skill_dir(fake_src, "real-skill", "good")
        # A bundle-source dir without SKILL.md → not allow-listed.
        (fake_src / "no-skill-md").mkdir()
        (fake_src / "no-skill-md" / "README.md").write_text(
            "no SKILL.md here", encoding="utf-8"
        )

        target = tmp_path / "skills"
        target.mkdir()
        # A user-owned dir whose name happens to match the bundle's
        # non-allow-listed entry.
        no_skill_dir = _make_skill_dir(
            target, "no-skill-md", "user-owned-bundle-name-match"
        )
        bundle_skill = _make_skill_dir(target, "real-skill", "installed")

        with patch(
            "mureo.cli.setup_cmd._get_data_path", return_value=fake_src
        ):
            count, _ = remove_skills(target_dir=target)

        # Only ``real-skill`` is in the allow-list.
        assert not bundle_skill.exists()
        # ``no-skill-md`` lacks SKILL.md in the bundle source → NOT in the
        # allow-list → NOT removed from the destination.
        assert no_skill_dir.exists()
        assert (no_skill_dir / "SKILL.md").read_text(encoding="utf-8") == (
            "user-owned-bundle-name-match"
        )
        assert count == 1

    def test_bundle_source_missing_is_graceful_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ``_get_data_path("skills")`` cannot resolve (rare — broken
        install), the remove function MUST no-op gracefully (planner
        HANDOFF L172 — "bundle dir absent at import resolution →
        graceful skip"). Crucially: the destination dir is left alone."""
        from mureo.cli.setup_cmd import remove_skills

        def _missing(_: str) -> Path:
            raise FileNotFoundError("synthetic missing bundle")

        monkeypatch.setattr("mureo.cli.setup_cmd._get_data_path", _missing)

        target = tmp_path / "skills"
        _make_skill_dir(target, "daily-check", "user-orphan")

        count, dest = remove_skills(target_dir=target)

        assert count == 0
        assert dest == target
        # Leftover skill is NOT removed (no allow-list available).
        assert (target / "daily-check" / "SKILL.md").exists()
