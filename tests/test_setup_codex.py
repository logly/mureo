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
    _yaml_escape,
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

    def test_skips_symlinked_legacy_prompts(self, home: Path, tmp_path: Path) -> None:
        """A symlink at ~/.codex/prompts/<bundled>.md must NOT be removed.

        A user may have symlinked a bundled-name file to their own copy
        kept outside `~/.codex/` (e.g. a dotfiles repo). Silently
        unlinking the symlink surprises the operator and loses the link
        even though the target remains intact. The cleanup should skip
        symlinks and leave the operator's link alone.
        """
        legacy = home / ".codex" / "prompts"
        legacy.mkdir(parents=True)
        # Real target lives outside the legacy dir.
        external = tmp_path / "external_onboard.md"
        external.write_text("user's own onboard", encoding="utf-8")
        symlink_path = legacy / "onboard.md"
        symlink_path.symlink_to(external)

        install_codex_command_skills()

        # Symlink survived — we did not silently unlink it.
        assert symlink_path.is_symlink()
        # External target untouched.
        assert external.exists()
        assert external.read_text(encoding="utf-8") == "user's own onboard"

    def test_skips_broken_symlink_legacy_prompt(
        self, home: Path, tmp_path: Path
    ) -> None:
        """A broken symlink (target missing) at a bundled path must also
        survive. ``Path.is_file()`` returns False for a dangling symlink,
        so it's already skipped by the primary guard — but a regression
        test pins that behavior in case the guard is ever restructured."""
        legacy = home / ".codex" / "prompts"
        legacy.mkdir(parents=True)
        broken_link = legacy / "onboard.md"
        broken_link.symlink_to(tmp_path / "does-not-exist.md")

        install_codex_command_skills()

        # Broken symlink untouched: the operator can still see and repair it.
        assert broken_link.is_symlink()


class TestYamlEscape:
    """``_yaml_escape`` must produce a string safe for a YAML double-quoted
    scalar so the skill description survives Codex's frontmatter parser.

    A double-quoted YAML scalar interprets backslash escapes, so a raw
    tab, CR, or unicode line separator in the description would either
    mangle the value or break the frontmatter block entirely.
    """

    def test_escapes_backslash_and_quote(self) -> None:
        assert _yaml_escape(r"a\b") == r"a\\b"
        assert _yaml_escape('say "hi"') == r"say \"hi\""

    def test_escapes_control_characters(self) -> None:
        """Tabs, CR, LF, and other C0 control chars must be escaped so
        they can't silently inject a newline into the frontmatter and
        truncate the description at an unexpected boundary."""
        assert "\\x09" in _yaml_escape("line\tafter-tab")
        assert "\\x0d" in _yaml_escape("carriage\rreturn")
        assert "\\x0a" in _yaml_escape("with\nnewline")

    def test_escapes_unicode_line_separators(self) -> None:
        """U+2028 (LINE SEPARATOR) and U+2029 (PARAGRAPH SEPARATOR) are
        treated as line terminators by some YAML parsers and would break
        a single-line description, so they must be escaped too."""
        assert "\u2028" not in _yaml_escape("a\u2028b")
        assert "\u2029" not in _yaml_escape("a\u2029b")

    def test_leaves_normal_text_unchanged(self) -> None:
        """Regression guard: escaping should be a no-op on ASCII text
        without quotes or backslashes."""
        assert _yaml_escape("run a daily health check") == "run a daily health check"


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

    def test_replaces_symlink_without_touching_target(
        self, home: Path, tmp_path: Path
    ) -> None:
        """A symlink at the destination path is replaced with a real copy.

        A developer running `mureo setup codex` in their working clone
        may have symlinked ``~/.codex/skills/mureo-workflows`` at their
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
        link = dest_parent / "mureo-workflows"
        link.symlink_to(external_target, target_is_directory=True)

        install_codex_skills()

        assert not link.is_symlink()
        assert link.is_dir()
        assert (link / "SKILL.md").exists()
        assert external_target.exists()
        assert (external_target / "keep.txt").read_text() == "keep"


class TestInstallCodexCommandSkillsSymlink:
    """Regression: install_codex_command_skills must tolerate a symlink
    at the destination for a bundled command skill (e.g. the operator
    symlinked their own dev copy into ``~/.codex/skills/onboard``).
    """

    def test_replaces_symlink_command_skill_without_touching_target(
        self, home: Path, tmp_path: Path
    ) -> None:
        external = tmp_path / "external_onboard_skill"
        external.mkdir()
        (external / "SKILL.md").write_text("dev onboard body")

        dest_parent = home / ".codex" / "skills"
        dest_parent.mkdir(parents=True)
        link = dest_parent / "onboard"
        link.symlink_to(external, target_is_directory=True)

        install_codex_command_skills()

        assert not link.is_symlink()
        assert link.is_dir()
        assert (link / "SKILL.md").exists()
        assert external.exists()
        assert (external / "SKILL.md").read_text() == "dev onboard body"
