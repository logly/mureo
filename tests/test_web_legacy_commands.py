"""Detection and removal of legacy mureo slash commands.

``mureo.web.legacy_commands`` exposes two helpers used by the
configure UI:

* ``detect_legacy_commands(dir)`` — read-only scan for the closed
  allow-list of mureo's historical ``~/.claude/commands/*.md`` files.
* ``remove_legacy_commands(dir)`` — delete those allow-listed files.

Security invariants:
* Closed allow-list — the loop iterates the allow-list, NOT the
  directory contents. A user-owned ``my-custom.md`` cannot be deleted.
* No subprocess.
* OSError is caught and logged, never propagated.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from mureo.web.legacy_commands import (
    LEGACY_COMMAND_NAMES,
    detect_legacy_commands,
    remove_legacy_commands,
)


@pytest.fixture
def commands_dir(tmp_path: Path) -> Path:
    d = tmp_path / "commands"
    d.mkdir()
    return d


@pytest.mark.unit
class TestAllowListShape:
    def test_is_tuple(self) -> None:
        assert isinstance(LEGACY_COMMAND_NAMES, tuple)

    def test_contains_known_legacy_files(self) -> None:
        for expected in (
            "onboard.md",
            "daily-check.md",
            "rescue.md",
            "search-term-cleanup.md",
            "creative-refresh.md",
            "budget-rebalance.md",
            "competitive-scan.md",
            "goal-review.md",
            "weekly-report.md",
            "sync-state.md",
            "learn.md",
        ):
            assert expected in LEGACY_COMMAND_NAMES

    def test_only_basenames_no_paths(self) -> None:
        for name in LEGACY_COMMAND_NAMES:
            assert "/" not in name
            assert "\\" not in name
            assert ".." not in name
            assert name.endswith(".md")


@pytest.mark.unit
class TestDetectLegacyCommands:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert detect_legacy_commands(tmp_path / "does-not-exist") == []

    def test_path_is_file_not_dir_returns_empty(self, tmp_path: Path) -> None:
        not_a_dir = tmp_path / "file"
        not_a_dir.write_text("x")
        assert detect_legacy_commands(not_a_dir) == []

    def test_empty_dir_returns_empty(self, commands_dir: Path) -> None:
        assert detect_legacy_commands(commands_dir) == []

    def test_finds_single_legacy_file(self, commands_dir: Path) -> None:
        (commands_dir / "onboard.md").write_text("legacy")
        assert detect_legacy_commands(commands_dir) == ["onboard.md"]

    def test_finds_multiple_legacy_files(self, commands_dir: Path) -> None:
        (commands_dir / "onboard.md").write_text("a")
        (commands_dir / "rescue.md").write_text("b")
        (commands_dir / "learn.md").write_text("c")
        found = detect_legacy_commands(commands_dir)
        assert set(found) == {"onboard.md", "rescue.md", "learn.md"}

    def test_ignores_user_owned_md(self, commands_dir: Path) -> None:
        """Non-allow-listed ``.md`` must NOT appear in the detect list."""
        (commands_dir / "my-custom.md").write_text("user-owned")
        (commands_dir / "onboard.md").write_text("legacy")
        found = detect_legacy_commands(commands_dir)
        assert "my-custom.md" not in found
        assert "onboard.md" in found

    def test_ignores_subdirectories_with_matching_name(
        self, commands_dir: Path
    ) -> None:
        """A directory named like a legacy file must NOT count — only
        regular files are detected."""
        (commands_dir / "onboard.md").mkdir()
        assert detect_legacy_commands(commands_dir) == []

    def test_oserror_during_isfile_is_skipped(self, commands_dir: Path) -> None:
        """Permission-denied during ``is_file`` is caught silently."""
        (commands_dir / "onboard.md").write_text("legacy")

        original_is_file = Path.is_file

        def _fake_is_file(self: Path) -> bool:
            if self.name == "onboard.md":
                raise OSError("permission denied")
            return original_is_file(self)

        with patch.object(Path, "is_file", _fake_is_file):
            found = detect_legacy_commands(commands_dir)
        assert "onboard.md" not in found


@pytest.mark.unit
class TestRemoveLegacyCommands:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert remove_legacy_commands(tmp_path / "does-not-exist") == []

    def test_empty_dir_returns_empty(self, commands_dir: Path) -> None:
        assert remove_legacy_commands(commands_dir) == []

    def test_removes_single_file_and_returns_basename(self, commands_dir: Path) -> None:
        target = commands_dir / "onboard.md"
        target.write_text("legacy")
        assert remove_legacy_commands(commands_dir) == ["onboard.md"]
        assert not target.exists()

    def test_removes_multiple_files(self, commands_dir: Path) -> None:
        for name in ("onboard.md", "rescue.md", "learn.md"):
            (commands_dir / name).write_text("x")
        removed = remove_legacy_commands(commands_dir)
        assert set(removed) == {"onboard.md", "rescue.md", "learn.md"}
        for name in removed:
            assert not (commands_dir / name).exists()

    def test_preserves_user_owned_files(self, commands_dir: Path) -> None:
        """The cleanup must NOT touch files outside the allow-list,
        even if they sit alongside legacy ones."""
        user = commands_dir / "my-custom.md"
        user.write_text("user data")
        legacy = commands_dir / "onboard.md"
        legacy.write_text("legacy")
        remove_legacy_commands(commands_dir)
        assert user.exists()
        assert user.read_text() == "user data"
        assert not legacy.exists()

    def test_preserves_files_with_no_md_extension(self, commands_dir: Path) -> None:
        other = commands_dir / "onboard.txt"
        other.write_text("ext mismatch")
        remove_legacy_commands(commands_dir)
        assert other.exists()

    def test_oserror_during_unlink_is_logged_not_raised(
        self, commands_dir: Path
    ) -> None:
        """Permission-denied during unlink is swallowed; remove returns
        an empty list for that file."""
        (commands_dir / "onboard.md").write_text("legacy")

        original_unlink = Path.unlink

        def _fake_unlink(self: Path, *args: object, **kwargs: object) -> None:
            if self.name == "onboard.md":
                raise OSError("readonly")
            original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", _fake_unlink):
            removed = remove_legacy_commands(commands_dir)
        assert "onboard.md" not in removed
        assert (commands_dir / "onboard.md").exists()

    def test_does_not_iterate_directory_contents(self, commands_dir: Path) -> None:
        """Sanity: never call ``iterdir`` on the dir — only allow-list
        names. We assert this by adding lots of decoys that aren't on
        the list and checking they survive."""
        decoys = ["a.md", "b.md", "x.md", "outside_evil.md"]
        for name in decoys:
            target = commands_dir / name
            target.write_text("decoy")
        (commands_dir / "rescue.md").write_text("legacy")
        removed = remove_legacy_commands(commands_dir)
        assert removed == ["rescue.md"]
        for name in decoys:
            target = commands_dir / name
            assert target.exists()


@pytest.mark.unit
class TestNoSubprocess:
    """Belt-and-braces — legacy_commands must NOT spawn a subprocess."""

    def test_no_subprocess_import_in_source(self) -> None:
        from mureo.web import legacy_commands as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "subprocess"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "subprocess"
