"""Tests for ``mureo setup codex``.

Covers installation of MCP config, credential guard hook, slash-command
prompts, and skills for OpenAI Codex CLI. All filesystem operations are
redirected at ``tmp_path`` via monkeypatched ``Path.home()`` so tests
never touch the operator's real ``~/.codex``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mureo.cli.setup_codex import (  # noqa: I001
    CodexMcpConflictError,
    install_codex_command_skills,
    install_codex_credential_guard,
    install_codex_mcp_config,
    install_codex_skills,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home()`` at ``tmp_path`` for each test."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


class TestInstallCodexMcpConfig:
    """``[mcp_servers.mureo]`` is appended to ~/.codex/config.toml."""

    def test_creates_config_when_file_missing(self, home: Path) -> None:
        result = install_codex_mcp_config()
        assert result is not None
        config = home / ".codex" / "config.toml"
        assert config.exists()
        text = config.read_text(encoding="utf-8")
        assert "[mcp_servers.mureo]" in text
        assert 'command = "python"' in text
        assert '"-m"' in text and '"mureo.mcp"' in text

    def test_preserves_existing_content(self, home: Path) -> None:
        config = home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            '[mcp_servers.other]\ncommand = "other-server"\n',
            encoding="utf-8",
        )

        install_codex_mcp_config()

        text = config.read_text(encoding="utf-8")
        # Existing server survives
        assert "[mcp_servers.other]" in text
        assert 'command = "other-server"' in text
        # mureo appended
        assert "[mcp_servers.mureo]" in text

    def test_idempotent_skip_when_already_present(self, home: Path) -> None:
        install_codex_mcp_config()
        # Second call: detect tag, skip.
        result = install_codex_mcp_config()
        assert result is None
        # File contains exactly one mureo block
        text = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert text.count("[mcp_servers.mureo]") == 1

    def test_untagged_block_raises_conflict(self, home: Path) -> None:
        """An existing [mcp_servers.mureo] without the tag marker is refused
        instead of silently appending a duplicate TOML key."""
        config = home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            '[mcp_servers.mureo]\ncommand = "legacy-mureo"\n',
            encoding="utf-8",
        )

        with pytest.raises(CodexMcpConflictError, match="untagged"):
            install_codex_mcp_config()

        # File untouched.
        assert 'command = "legacy-mureo"' in config.read_text(encoding="utf-8")


class TestInstallCodexCredentialGuard:
    """PreToolUse hook in ~/.codex/hooks.json blocks credential reads."""

    def test_creates_hooks_json_when_missing(self, home: Path) -> None:
        result = install_codex_credential_guard()
        assert result is not None
        hooks_file = home / ".codex" / "hooks.json"
        assert hooks_file.exists()
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        pre = data.get("PreToolUse", [])
        assert len(pre) >= 1
        # At least one entry targets Bash and mentions the mureo guard tag
        matchers = [entry.get("matcher") for entry in pre]
        assert "Bash" in matchers
        flat = json.dumps(data)
        assert "[mureo-credential-guard]" in flat

    def test_preserves_existing_hooks(self, home: Path) -> None:
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        existing = {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "echo 'existing guard'"}],
                }
            ]
        }
        hooks_file.write_text(json.dumps(existing), encoding="utf-8")

        install_codex_credential_guard()

        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        flat = json.dumps(data)
        assert "existing guard" in flat
        assert "[mureo-credential-guard]" in flat

    def test_idempotent_skip_when_already_installed(self, home: Path) -> None:
        install_codex_credential_guard()
        result = install_codex_credential_guard()
        assert result is None
        data = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        flat = json.dumps(data)
        # Two mureo entries (Read + Bash) persist; no duplicates are added.
        assert flat.count("[mureo-credential-guard]") == 2

    def test_corrupt_hooks_json_returns_none_without_clobber(self, home: Path) -> None:
        """A corrupt hooks.json is not silently overwritten."""
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        hooks_file.write_text("{not valid json", encoding="utf-8")

        result = install_codex_credential_guard()
        assert result is None
        # Corrupt content left intact for the operator to inspect.
        assert hooks_file.read_text(encoding="utf-8") == "{not valid json"

    def test_pretooluse_wrong_type_refused(self, home: Path) -> None:
        """PreToolUse must be a list; a dict (or other type) is refused."""
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        hooks_file.write_text(
            json.dumps({"PreToolUse": {"matcher": "Bash"}}),
            encoding="utf-8",
        )

        result = install_codex_credential_guard()
        assert result is None


class TestInstallCodexCommandSkills:
    """Workflow commands are installed as Codex skills at
    ``~/.codex/skills/<command>/SKILL.md``. The older ``~/.codex/prompts/``
    layout stopped being picked up in codex-cli 0.117.0+ (Issue #15941),
    so every bundled command now ships as a skill invokable via ``$cmd``
    or the ``/skills`` picker.
    """

    def test_installs_each_command_as_its_own_skill(self, home: Path) -> None:
        count, dest = install_codex_command_skills()
        assert dest == home / ".codex" / "skills"
        assert dest.exists()
        assert count >= 1
        # Known bundled command landed as a skill directory with SKILL.md
        onboard_skill = dest / "onboard" / "SKILL.md"
        assert onboard_skill.exists()
        daily_check_skill = dest / "daily-check" / "SKILL.md"
        assert daily_check_skill.exists()

    def test_skill_has_yaml_frontmatter(self, home: Path) -> None:
        """Each generated SKILL.md starts with ``---\\nname: ...\\ndescription:
        ...\\n---`` so Codex's skill loader can index it and surface the
        description in the ``/skills`` picker."""
        install_codex_command_skills()
        content = (home / ".codex" / "skills" / "daily-check" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert content.startswith("---\n")
        # Frontmatter block terminates before the command body.
        _, frontmatter, body = content.split("---\n", 2)
        assert "name: daily-check" in frontmatter
        assert "description:" in frontmatter
        # Body preserves the source command's first line.
        assert "daily health check" in body.lower()

    def test_replaces_existing_command_skill(self, home: Path) -> None:
        """Re-running setup clobbers a stale SKILL.md even if the
        directory is already there."""
        target = home / ".codex" / "skills" / "onboard"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("stale content", encoding="utf-8")

        install_codex_command_skills()

        updated = (target / "SKILL.md").read_text(encoding="utf-8")
        assert "stale content" not in updated
        assert updated.startswith("---\n")

    def test_cleans_up_legacy_prompts_dir(self, home: Path) -> None:
        """Prior installs placed the same commands in ``~/.codex/prompts/``.
        Those files are dead on codex-cli 0.117.0+ and must be removed so
        ``/skills`` doesn't show ghost duplicates when the user looks at
        their Codex state."""
        legacy = home / ".codex" / "prompts"
        legacy.mkdir(parents=True)
        (legacy / "onboard.md").write_text("legacy prompt", encoding="utf-8")
        (legacy / "daily-check.md").write_text("legacy prompt", encoding="utf-8")
        # A user-authored prompt that mureo shouldn't delete.
        (legacy / "my-custom.md").write_text("mine", encoding="utf-8")

        install_codex_command_skills()

        assert not (legacy / "onboard.md").exists()
        assert not (legacy / "daily-check.md").exists()
        # User's own prompt untouched.
        assert (legacy / "my-custom.md").exists()
        assert (legacy / "my-custom.md").read_text(encoding="utf-8") == "mine"


class TestInstallCodexSkills:
    """Skill directories are copied into ~/.codex/skills/."""

    def test_copies_skill_directories(self, home: Path) -> None:
        count, dest = install_codex_skills()
        assert dest == home / ".codex" / "skills"
        assert dest.exists()
        assert count >= 1
        # mureo-workflows is a known bundled skill
        assert (dest / "mureo-workflows" / "SKILL.md").exists()

    def test_replaces_existing_skill(self, home: Path) -> None:
        dest = home / ".codex" / "skills" / "mureo-workflows"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("stale", encoding="utf-8")

        install_codex_skills()

        updated = (dest / "SKILL.md").read_text(encoding="utf-8")
        assert updated != "stale"
