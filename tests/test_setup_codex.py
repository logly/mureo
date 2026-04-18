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
    install_codex_credential_guard,
    install_codex_mcp_config,
    install_codex_prompts,
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
                    "hooks": [
                        {"type": "command", "command": "echo 'existing guard'"}
                    ],
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
        data = json.loads(
            (home / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        flat = json.dumps(data)
        # Two mureo entries (Read + Bash) persist; no duplicates are added.
        assert flat.count("[mureo-credential-guard]") == 2

    def test_corrupt_hooks_json_returns_none_without_clobber(
        self, home: Path
    ) -> None:
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


class TestInstallCodexPrompts:
    """Workflow commands are copied as .md files into ~/.codex/prompts/."""

    def test_copies_markdown_files(self, home: Path) -> None:
        count, dest = install_codex_prompts()
        assert dest == home / ".codex" / "prompts"
        assert dest.exists()
        assert count >= 1
        md_files = list(dest.glob("*.md"))
        assert len(md_files) == count
        # onboard.md is a known bundled command
        assert (dest / "onboard.md").exists()

    def test_overwrites_existing(self, home: Path) -> None:
        dest = home / ".codex" / "prompts"
        dest.mkdir(parents=True)
        (dest / "onboard.md").write_text("stale content", encoding="utf-8")

        install_codex_prompts()

        updated = (dest / "onboard.md").read_text(encoding="utf-8")
        assert "stale content" not in updated


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
