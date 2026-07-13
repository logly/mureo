"""Tests for ``mureo setup codex``.

Covers installation of MCP config, credential guard hook, slash-command
prompts, and skills for OpenAI Codex CLI. All filesystem operations are
redirected at ``tmp_path`` via monkeypatched ``Path.home()`` so tests
never touch the operator's real ``~/.codex``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mureo.cli.setup_codex import (  # noqa: I001
    CodexMcpConflictError,
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
        # command must be the interpreter running mureo (sys.executable), not a
        # bare "python" that may be missing or lack mureo installed.
        assert f"command = {json.dumps(sys.executable)}" in text
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


_STALE_GUARD_CMD = (
    'python3 -c "import sys,json; sys.exit(1)" # [mureo-credential-guard]'
)


class TestInstallCodexCredentialGuard:
    """PreToolUse hook in ~/.codex/hooks.json blocks credential reads.

    Codex reads hooks from the nested ``{"hooks": {"PreToolUse": [...]}}``
    shape (same as Claude's settings.json).  Earlier mureo versions wrote a
    top-level ``PreToolUse`` list that Codex never loads, so the install
    must both target the nested location and migrate its own stale entries
    out of the legacy one (#393).
    """

    def test_creates_hooks_json_when_missing(self, home: Path) -> None:
        result = install_codex_credential_guard()
        assert result is not None
        hooks_file = home / ".codex" / "hooks.json"
        assert hooks_file.exists()
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        # Nested shape only — the legacy top-level list is never created.
        assert "PreToolUse" not in data
        pre = data["hooks"]["PreToolUse"]
        assert len(pre) >= 1
        matchers = [entry.get("matcher") for entry in pre]
        assert "Bash" in matchers
        flat = json.dumps(data)
        assert "[mureo-credential-guard]" in flat
        assert "sys.exit(1)" not in flat
        assert "permissionDecision" in flat

    def test_preserves_existing_hooks(self, home: Path) -> None:
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": "echo 'existing guard'"}
                        ],
                    }
                ]
            }
        }
        hooks_file.write_text(json.dumps(existing), encoding="utf-8")

        install_codex_credential_guard()

        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        flat = json.dumps(data)
        assert "existing guard" in flat
        assert "[mureo-credential-guard]" in flat

    def test_migrates_legacy_top_level_entries(self, home: Path) -> None:
        """Stale tagged entries under the legacy top-level ``PreToolUse``
        move to the nested location; foreign legacy entries stay put."""
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        foreign = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "echo mine"}],
        }
        stale = {
            "matcher": "Read",
            "hooks": [{"type": "command", "command": _STALE_GUARD_CMD}],
        }
        hooks_file.write_text(
            json.dumps({"PreToolUse": [foreign, stale]}), encoding="utf-8"
        )

        result = install_codex_credential_guard()

        assert result is not None
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        # Foreign legacy entry untouched, stale mureo entry migrated out.
        assert data["PreToolUse"] == [foreign]
        flat = json.dumps(data["hooks"]["PreToolUse"])
        assert flat.count("[mureo-credential-guard]") == 2
        assert "sys.exit(1)" not in flat

    def test_migrates_legacy_when_only_tagged(self, home: Path) -> None:
        """A legacy list holding only mureo entries is dropped entirely."""
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        stale = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": _STALE_GUARD_CMD}],
        }
        hooks_file.write_text(json.dumps({"PreToolUse": [stale]}), encoding="utf-8")

        result = install_codex_credential_guard()

        assert result is not None
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        assert "PreToolUse" not in data
        assert json.dumps(data["hooks"]).count("[mureo-credential-guard]") == 2

    def test_upgrades_stale_nested_entries(self, home: Path) -> None:
        """Tagged nested entries from an older mureo are replaced, not kept."""
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        stale = {
            "matcher": "Read",
            "hooks": [{"type": "command", "command": _STALE_GUARD_CMD}],
        }
        hooks_file.write_text(
            json.dumps({"hooks": {"PreToolUse": [stale]}}), encoding="utf-8"
        )

        result = install_codex_credential_guard()

        assert result is not None
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        flat = json.dumps(data)
        assert "sys.exit(1)" not in flat
        assert "permissionDecision" in flat
        assert flat.count("[mureo-credential-guard]") == 2

    def test_installed_guard_blocks_credential_read(self, home: Path) -> None:
        """The installed Codex commands share the blocking templates."""
        from tests.hook_guard_runner import deny_decision, run_guard

        install_codex_credential_guard()
        data = json.loads(
            (home / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        commands = [
            h["command"]
            for entry in data["hooks"]["PreToolUse"]
            for h in entry["hooks"]
        ]
        cred = str(home / ".mureo" / "credentials.json")
        decisions = [
            deny_decision(
                run_guard(cmd, {"file_path": cred, "command": f"cat {cred}"}, home)
            )
            for cmd in commands
        ]
        assert "deny" in decisions

    def test_idempotent_skip_when_already_installed(self, home: Path) -> None:
        install_codex_credential_guard()
        result = install_codex_credential_guard()
        assert result is None
        data = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        flat = json.dumps(data)
        # Two mureo entries (path tools + Bash) persist; no duplicates.
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

    def test_legacy_pretooluse_wrong_type_refused(self, home: Path) -> None:
        """Legacy top-level PreToolUse must be a list; a dict is refused."""
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        hooks_file.write_text(
            json.dumps({"PreToolUse": {"matcher": "Bash"}}),
            encoding="utf-8",
        )

        result = install_codex_credential_guard()
        assert result is None

    def test_nested_pretooluse_wrong_type_refused(self, home: Path) -> None:
        """Nested hooks.PreToolUse must be a list; a dict is refused."""
        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        hooks_file.write_text(
            json.dumps({"hooks": {"PreToolUse": {"matcher": "Bash"}}}),
            encoding="utf-8",
        )

        result = install_codex_credential_guard()
        assert result is None


class TestInstallCodexSkills:
    """Skill directories are copied into ~/.codex/skills/.

    Phase 3 (PR #77) merged slash commands into skills, so the 10
    operational skills (daily-check, budget-rebalance, ...) and the
    foundation skills (_mureo-shared, _mureo-strategy, ...) are all
    installed by this single function.
    """

    def test_copies_skill_directories(self, home: Path) -> None:
        count, dest = install_codex_skills()
        assert dest == home / ".codex" / "skills"
        assert dest.exists()
        assert count >= 1
        # Operational skill (formerly a slash command)
        assert (dest / "daily-check" / "SKILL.md").exists()
        # Foundation skill (referenced as PREREQUISITE by operational ones)
        assert (dest / "_mureo-shared" / "SKILL.md").exists()

    def test_replaces_existing_skill(self, home: Path) -> None:
        dest = home / ".codex" / "skills" / "_mureo-shared"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("stale", encoding="utf-8")

        install_codex_skills()

        updated = (dest / "SKILL.md").read_text(encoding="utf-8")
        assert updated != "stale"

    def test_replaces_symlink_without_touching_target(
        self, home: Path, tmp_path: Path
    ) -> None:
        """A symlink at the destination path is replaced with a real copy.

        A developer running `mureo setup codex` in their working clone
        may have symlinked ``~/.codex/skills/_mureo-shared`` at their
        repo's dev copy. ``shutil.rmtree`` refuses symlinks by design,
        so re-installing crashed with ``OSError``. The fix swaps the
        symlink for an ``unlink()`` and the external target stays safe.
        """
        external_target = tmp_path / "external_dev_skill"
        external_target.mkdir()
        (external_target / "SKILL.md").write_text("dev-link")
        (external_target / "keep.txt").write_text("keep")

        dest_parent = home / ".codex" / "skills"
        dest_parent.mkdir(parents=True)
        link = dest_parent / "_mureo-shared"
        link.symlink_to(external_target, target_is_directory=True)

        install_codex_skills()

        assert not link.is_symlink()
        assert link.is_dir()
        assert (link / "SKILL.md").exists()
        assert external_target.exists()
        assert (external_target / "keep.txt").read_text() == "keep"

    def test_replaces_symlinked_operational_skill(
        self, home: Path, tmp_path: Path
    ) -> None:
        """Symlink replacement works for the operational skills too \u2014
        ``onboard``, ``daily-check`` etc. behave the same as foundation
        skills under ``install_codex_skills``."""
        external = tmp_path / "external_onboard_skill"
        external.mkdir()
        (external / "SKILL.md").write_text("dev onboard body")

        dest_parent = home / ".codex" / "skills"
        dest_parent.mkdir(parents=True)
        link = dest_parent / "onboard"
        link.symlink_to(external, target_is_directory=True)

        install_codex_skills()

        assert not link.is_symlink()
        assert link.is_dir()
        assert (link / "SKILL.md").exists()
        assert external.exists()
        assert (external / "SKILL.md").read_text() == "dev onboard body"


class TestRemoveCredentialGuard:
    """remove_codex_credential_guard — inverse of the install, tag-scoped."""

    def test_removes_only_tagged_entries(self, home: Path) -> None:
        from mureo.cli.setup_codex import (
            remove_codex_credential_guard,
        )

        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        # A user's own unrelated hook must survive.
        hooks_file.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"matcher": "Read", "hooks": [{"command": "echo hi"}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        install_codex_credential_guard()
        removed = remove_codex_credential_guard()
        assert removed == hooks_file
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        remaining = [
            h.get("command", "")
            for e in data["hooks"]["PreToolUse"]
            for h in e.get("hooks", [])
        ]
        assert remaining == ["echo hi"]  # only the user's hook kept
        assert "mureo-credential-guard" not in json.dumps(data)

    def test_removes_legacy_top_level_tagged_entries(self, home: Path) -> None:
        """Entries an older mureo wrote to the legacy top-level list are
        removed too (they carry the same tag)."""
        from mureo.cli.setup_codex import remove_codex_credential_guard

        hooks_file = home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True)
        stale = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": _STALE_GUARD_CMD}],
        }
        hooks_file.write_text(json.dumps({"PreToolUse": [stale]}), encoding="utf-8")

        assert remove_codex_credential_guard() == hooks_file
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        assert "mureo-credential-guard" not in json.dumps(data)

    def test_idempotent_when_absent(self, home: Path) -> None:
        from mureo.cli.setup_codex import remove_codex_credential_guard

        assert remove_codex_credential_guard() is None  # no file

    def test_honours_explicit_hooks_file_path(self, tmp_path: Path) -> None:
        """The home-aware override path is respected (configure-UI flow)."""
        from mureo.cli.setup_codex import remove_codex_credential_guard

        target = tmp_path / "custom" / "hooks.json"
        install_codex_credential_guard(target)
        assert target.exists()
        assert remove_codex_credential_guard(target) == target
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["hooks"]["PreToolUse"] == []
