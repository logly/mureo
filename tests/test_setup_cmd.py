"""Tests for mureo setup commands (install_commands, install_skills)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_install_commands(tmp_path: Path) -> None:
    """install_commands copies all .md files to target directory."""
    from mureo.cli.setup_cmd import install_commands

    count, dest = install_commands(target_dir=tmp_path / "commands")

    assert count == 10
    assert dest == tmp_path / "commands"
    assert (dest / "daily-check.md").exists()
    assert (dest / "onboard.md").exists()
    assert (dest / "rescue.md").exists()


@pytest.mark.unit
def test_install_commands_creates_directory(tmp_path: Path) -> None:
    """install_commands creates target directory if it doesn't exist."""
    from mureo.cli.setup_cmd import install_commands

    target = tmp_path / "deep" / "nested" / "commands"
    count, dest = install_commands(target_dir=target)

    assert count == 10
    assert dest.exists()


@pytest.mark.unit
def test_install_commands_overwrites_existing(tmp_path: Path) -> None:
    """install_commands overwrites existing files (idempotent)."""
    from mureo.cli.setup_cmd import install_commands

    target = tmp_path / "commands"
    target.mkdir()
    (target / "daily-check.md").write_text("old content")

    count, _ = install_commands(target_dir=target)

    assert count == 10
    content = (target / "daily-check.md").read_text()
    assert content != "old content"


@pytest.mark.unit
def test_install_commands_preserves_extra_files(tmp_path: Path) -> None:
    """install_commands does not delete extra files in target directory."""
    from mureo.cli.setup_cmd import install_commands

    target = tmp_path / "commands"
    target.mkdir()
    (target / "my-custom-command.md").write_text("custom")

    install_commands(target_dir=target)

    assert (target / "my-custom-command.md").read_text() == "custom"


@pytest.mark.unit
def test_install_skills(tmp_path: Path) -> None:
    """install_skills copies all skill directories to target."""
    from mureo.cli.setup_cmd import install_skills

    count, dest = install_skills(target_dir=tmp_path / "skills")

    assert count == 6
    assert dest == tmp_path / "skills"
    assert (dest / "mureo-google-ads" / "SKILL.md").exists()
    assert (dest / "mureo-meta-ads" / "SKILL.md").exists()
    assert (dest / "mureo-shared" / "SKILL.md").exists()
    assert (dest / "mureo-strategy" / "SKILL.md").exists()
    assert (dest / "mureo-workflows" / "SKILL.md").exists()
    assert (dest / "mureo-learning" / "SKILL.md").exists()


@pytest.mark.unit
def test_install_skills_creates_directory(tmp_path: Path) -> None:
    """install_skills creates target directory if it doesn't exist."""
    from mureo.cli.setup_cmd import install_skills

    target = tmp_path / "deep" / "nested" / "skills"
    count, dest = install_skills(target_dir=target)

    assert count == 6
    assert dest.exists()


@pytest.mark.unit
def test_install_skills_overwrites_existing(tmp_path: Path) -> None:
    """install_skills replaces existing skill directories (idempotent)."""
    from mureo.cli.setup_cmd import install_skills

    target = tmp_path / "skills"
    target.mkdir()
    old_skill = target / "mureo-shared"
    old_skill.mkdir()
    (old_skill / "SKILL.md").write_text("old content")

    install_skills(target_dir=target)

    content = (target / "mureo-shared" / "SKILL.md").read_text()
    assert content != "old content"


@pytest.mark.unit
def test_install_skills_preserves_extra_skills(tmp_path: Path) -> None:
    """install_skills does not delete extra skill directories."""
    from mureo.cli.setup_cmd import install_skills

    target = tmp_path / "skills"
    target.mkdir()
    custom = target / "my-custom-skill"
    custom.mkdir()
    (custom / "SKILL.md").write_text("custom")

    install_skills(target_dir=target)

    assert (target / "my-custom-skill" / "SKILL.md").read_text() == "custom"


@pytest.mark.unit
def test_install_commands_default_path(tmp_path: Path) -> None:
    """install_commands uses ~/.claude/commands as default."""
    from mureo.cli.setup_cmd import install_commands

    with patch("mureo.cli.setup_cmd.Path.home", return_value=tmp_path):
        count, dest = install_commands()

    assert dest == tmp_path / ".claude" / "commands"
    assert count == 10


@pytest.mark.unit
def test_install_skills_default_path(tmp_path: Path) -> None:
    """install_skills uses ~/.claude/skills as default."""
    from mureo.cli.setup_cmd import install_skills

    with patch("mureo.cli.setup_cmd.Path.home", return_value=tmp_path):
        count, dest = install_skills()

    assert dest == tmp_path / ".claude" / "skills"
    assert count == 6
