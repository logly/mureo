"""Unit tests for ``mureo.cli.settings_remove`` — RED phase (TDD).

These tests pin the symmetric ``remove_*`` counterparts of
``install_mcp_config`` / ``install_credential_guard`` (which live in
``mureo.auth_setup``). Per the planner HANDOFF
``feat-web-config-ui-phase1-uninstall.md`` (CTO decision #1), the new
functions live in a NEW file ``mureo/cli/settings_remove.py`` rather
than growing the already-oversize ``auth_setup.py``.

Coverage targets (acceptance criteria, planner HANDOFF):
- pop only the ``"mureo"`` key from ``mcpServers``; preserve every other entry.
- idempotent on absent / already-removed state.
- atomic write — tempfile + ``os.fsync`` + ``os.replace`` + parent fsync;
  any OSError during write leaves the original file byte-for-byte intact.
- malformed JSON raises ``ConfigWriteError`` rather than silently overwriting.
- remove only credential-guard hooks bearing ``_MUREO_HOOK_TAG``; preserve
  unrelated PreToolUse hooks in their original order.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_MUREO_MCP_BLOCK = {"command": "python", "args": ["-m", "mureo.mcp"]}
_GOOGLE_ADS_BLOCK = {
    "command": "pipx",
    "args": ["run", "google-ads-mcp"],
}
_PET_BLOCK = {"command": "pet", "args": ["run"]}
_MUREO_HOOK_TAG = "[mureo-credential-guard]"


def _write_settings(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _make_mureo_hook_entry(matcher: str = "Read") -> dict[str, Any]:
    """Build a PreToolUse hook entry shaped like the installer writes."""
    return {
        "matcher": matcher,
        "hooks": [
            {
                "type": "command",
                "command": f"python3 -c 'pass' # {_MUREO_HOOK_TAG}",
            }
        ],
    }


def _make_unrelated_hook(name: str, command: str = "echo unrelated") -> dict[str, Any]:
    return {
        "matcher": name,
        "hooks": [{"type": "command", "command": command}],
    }


# ---------------------------------------------------------------------------
# remove_mcp_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveMcpConfig:
    def test_removes_only_mureo_key(self, tmp_path: Path) -> None:
        """Given a settings.json with mureo + google-ads-official + pet,
        the remove pops only the ``mureo`` key. Other entries survive in
        original key order (planner HANDOFF acceptance criteria L120,
        L175)."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {
                "mcpServers": {
                    "mureo": _MUREO_MCP_BLOCK,
                    "google-ads-official": _GOOGLE_ADS_BLOCK,
                    "pet": _PET_BLOCK,
                }
            },
        )

        result = remove_mcp_config(settings_path=settings_path)

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "mureo" not in payload["mcpServers"]
        assert payload["mcpServers"]["google-ads-official"] == _GOOGLE_ADS_BLOCK
        assert payload["mcpServers"]["pet"] == _PET_BLOCK
        # Python 3.10+ preserves dict insertion order — assert it explicitly.
        assert list(payload["mcpServers"].keys()) == ["google-ads-official", "pet"]
        assert result.changed is True

    def test_preserves_unrelated_top_level_keys(self, tmp_path: Path) -> None:
        """Top-level keys other than ``mcpServers`` survive verbatim."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        original = {
            "permissions": {"allow": ["Bash(ls:*)"]},
            "mcpServers": {"mureo": _MUREO_MCP_BLOCK},
            "hooks": {"PreToolUse": []},
        }
        _write_settings(settings_path, original)

        remove_mcp_config(settings_path=settings_path)

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert payload["permissions"] == original["permissions"]
        assert payload["hooks"] == {"PreToolUse": []}

    def test_idempotent_when_mureo_absent(self, tmp_path: Path) -> None:
        """Second call (already removed) returns ``changed=False`` without
        rewriting the file (acceptance criteria L122)."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {"mcpServers": {"google-ads-official": _GOOGLE_ADS_BLOCK}},
        )
        pre_mtime = settings_path.stat().st_mtime_ns
        pre_bytes = settings_path.read_bytes()

        result = remove_mcp_config(settings_path=settings_path)

        assert result.changed is False
        # mtime + content must be byte-for-byte unchanged (no rewrite).
        assert settings_path.stat().st_mtime_ns == pre_mtime
        assert settings_path.read_bytes() == pre_bytes

    def test_no_settings_file_returns_noop(self, tmp_path: Path) -> None:
        """When the settings file is absent, return ``changed=False`` and
        do NOT create the file."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        assert not settings_path.exists()

        result = remove_mcp_config(settings_path=settings_path)

        assert result.changed is False
        assert not settings_path.exists()

    def test_no_mcp_servers_key_returns_noop(self, tmp_path: Path) -> None:
        """``settings.json`` without an ``mcpServers`` key returns
        ``changed=False`` without rewriting."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, {"permissions": {"allow": []}})
        pre_bytes = settings_path.read_bytes()

        result = remove_mcp_config(settings_path=settings_path)

        assert result.changed is False
        assert settings_path.read_bytes() == pre_bytes

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        """Corrupt JSON must NOT be silently overwritten — raise
        ConfigWriteError (acceptance criteria L171, L262-L266)."""
        from mureo.cli.settings_remove import (
            ConfigWriteError,
            remove_mcp_config,
        )

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text("{not valid json", encoding="utf-8")
        pre_bytes = settings_path.read_bytes()

        with pytest.raises(ConfigWriteError) as exc_info:
            remove_mcp_config(settings_path=settings_path)

        assert str(settings_path) in str(exc_info.value)
        # File on disk is unchanged.
        assert settings_path.read_bytes() == pre_bytes

    def test_atomic_write_uses_tempfile_in_same_dir(self, tmp_path: Path) -> None:
        """Verify atomic-write invariant: a same-directory ``.tmp`` file
        is the source of the ``os.replace`` call."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {"mcpServers": {"mureo": _MUREO_MCP_BLOCK, "pet": _PET_BLOCK}},
        )

        captured: dict[str, Any] = {}
        real_replace = os.replace

        def _spy_replace(
            src: str | os.PathLike[str], dst: str | os.PathLike[str]
        ) -> None:
            captured["src"] = os.fspath(src)
            captured["dst"] = os.fspath(dst)
            real_replace(src, dst)

        with patch("mureo.cli.settings_remove.os.replace", side_effect=_spy_replace):
            remove_mcp_config(settings_path=settings_path)

        src = Path(captured["src"])
        dst = Path(captured["dst"])
        assert dst == settings_path
        assert src.parent == settings_path.parent
        assert ".tmp" in src.name

    def test_atomic_write_preserves_original_on_failure(
        self, tmp_path: Path
    ) -> None:
        """If ``os.replace`` raises mid-write, the original file is
        byte-for-byte intact and no ``.tmp`` debris remains. Acceptance
        criteria L154-L156."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        original_payload = {
            "mcpServers": {"mureo": _MUREO_MCP_BLOCK, "pet": _PET_BLOCK}
        }
        _write_settings(settings_path, original_payload)
        pre_bytes = settings_path.read_bytes()

        def _boom(src: Any, dst: Any) -> None:
            raise OSError("simulated atomic replace failure")

        with (
            patch("mureo.cli.settings_remove.os.replace", side_effect=_boom),
            pytest.raises(OSError),
        ):
            remove_mcp_config(settings_path=settings_path)

        assert settings_path.read_bytes() == pre_bytes
        # No leftover .tmp debris.
        leftovers = list(settings_path.parent.glob("*.tmp*"))
        assert leftovers == []

    def test_no_tmp_debris_on_success(self, tmp_path: Path) -> None:
        """A successful remove leaves no ``*.tmp*`` files behind."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {"mcpServers": {"mureo": _MUREO_MCP_BLOCK}},
        )

        remove_mcp_config(settings_path=settings_path)

        leftovers = list(settings_path.parent.glob("*.tmp*"))
        assert leftovers == []

    def test_default_path_uses_path_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omitting ``settings_path`` resolves to
        ``Path.home()/.claude/settings.json``."""
        from mureo.cli.settings_remove import remove_mcp_config

        monkeypatch.setattr(
            "mureo.cli.settings_remove.Path.home", lambda: tmp_path
        )
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {"mcpServers": {"mureo": _MUREO_MCP_BLOCK, "pet": _PET_BLOCK}},
        )

        result = remove_mcp_config()

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "mureo" not in payload["mcpServers"]
        assert "pet" in payload["mcpServers"]
        assert result.changed is True

    def test_tmp_file_is_mode_0600(self, tmp_path: Path) -> None:
        """The same-directory tmp file is 0o600 before the rename so a
        credential-adjacent settings file is never world-readable during
        the write window. POSIX-only — skip on Windows."""
        from mureo.cli.settings_remove import remove_mcp_config

        if os.name != "posix":
            pytest.skip("file-mode check only meaningful on POSIX")

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {"mcpServers": {"mureo": _MUREO_MCP_BLOCK, "pet": _PET_BLOCK}},
        )

        captured: dict[str, Any] = {}
        real_replace = os.replace

        def _spy_replace(
            src: str | os.PathLike[str], dst: str | os.PathLike[str]
        ) -> None:
            captured["mode"] = stat.S_IMODE(os.stat(src).st_mode)
            real_replace(src, dst)

        with patch("mureo.cli.settings_remove.os.replace", side_effect=_spy_replace):
            remove_mcp_config(settings_path=settings_path)

        assert captured["mode"] == 0o600

    def test_mcp_servers_non_dict_returns_noop(self, tmp_path: Path) -> None:
        """When ``mcpServers`` is present but not a dict, treat it as
        absent (no-op). Refusing here would block uninstall on
        already-corrupt configs."""
        from mureo.cli.settings_remove import remove_mcp_config

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, {"mcpServers": ["not", "a", "dict"]})
        pre_bytes = settings_path.read_bytes()

        result = remove_mcp_config(settings_path=settings_path)

        assert result.changed is False
        assert settings_path.read_bytes() == pre_bytes


# ---------------------------------------------------------------------------
# remove_credential_guard
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveCredentialGuard:
    def test_removes_only_tagged_hooks(self, tmp_path: Path) -> None:
        """Given mureo's Read+Bash hooks + 2 unrelated PreToolUse entries,
        only the tagged entries are removed and unrelated entries remain
        in original order (acceptance criteria L123, L181)."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        unrelated_a = _make_unrelated_hook("Edit", "echo a")
        unrelated_b = _make_unrelated_hook("Write", "echo b")
        _write_settings(
            settings_path,
            {
                "hooks": {
                    "PreToolUse": [
                        unrelated_a,
                        _make_mureo_hook_entry("Read"),
                        unrelated_b,
                        _make_mureo_hook_entry("Bash"),
                    ]
                }
            },
        )

        result = remove_credential_guard(settings_path=settings_path)

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        remaining = payload["hooks"]["PreToolUse"]
        # Order preserved: unrelated_a first, unrelated_b second.
        assert remaining == [unrelated_a, unrelated_b]
        assert result.changed is True

    def test_idempotent_when_no_tagged_hooks(self, tmp_path: Path) -> None:
        """Second call (already removed) returns ``changed=False`` without
        rewriting (acceptance criteria L125-L127)."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {
                "hooks": {
                    "PreToolUse": [_make_unrelated_hook("Edit", "echo x")]
                }
            },
        )
        pre_bytes = settings_path.read_bytes()
        pre_mtime = settings_path.stat().st_mtime_ns

        result = remove_credential_guard(settings_path=settings_path)

        assert result.changed is False
        assert settings_path.read_bytes() == pre_bytes
        assert settings_path.stat().st_mtime_ns == pre_mtime

    def test_no_settings_file_returns_noop(self, tmp_path: Path) -> None:
        """When the settings file is absent, return ``changed=False``."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"

        result = remove_credential_guard(settings_path=settings_path)

        assert result.changed is False
        assert not settings_path.exists()

    def test_no_hooks_key_returns_noop(self, tmp_path: Path) -> None:
        """``settings.json`` without a ``hooks`` key returns
        ``changed=False`` (acceptance criteria L172)."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, {"mcpServers": {}})
        pre_bytes = settings_path.read_bytes()

        result = remove_credential_guard(settings_path=settings_path)

        assert result.changed is False
        assert settings_path.read_bytes() == pre_bytes

    def test_no_pre_tool_use_key_returns_noop(self, tmp_path: Path) -> None:
        """``hooks`` without ``PreToolUse`` returns ``changed=False``."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, {"hooks": {"PostToolUse": []}})
        pre_bytes = settings_path.read_bytes()

        result = remove_credential_guard(settings_path=settings_path)

        assert result.changed is False
        assert settings_path.read_bytes() == pre_bytes

    def test_does_not_match_substring_in_matcher_field(
        self, tmp_path: Path
    ) -> None:
        """An unrelated entry whose ``matcher`` field happens to contain
        ``[mureo-credential-guard]`` must NOT be removed — the tag is
        only honored inside ``hooks[].command``. Acceptance criteria /
        risk mitigation (planner HANDOFF L268-L275)."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        # A user-owned hook entry whose matcher (not command) coincidentally
        # contains the tag. This must survive removal.
        decoy = {
            "matcher": _MUREO_HOOK_TAG,
            "hooks": [{"type": "command", "command": "echo not mureo"}],
        }
        _write_settings(
            settings_path,
            {
                "hooks": {
                    "PreToolUse": [decoy, _make_mureo_hook_entry("Read")]
                }
            },
        )

        result = remove_credential_guard(settings_path=settings_path)

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        remaining = payload["hooks"]["PreToolUse"]
        assert decoy in remaining
        assert len(remaining) == 1
        assert result.changed is True

    def test_does_not_match_lookalike_command(self, tmp_path: Path) -> None:
        """An unrelated audit-style hook that merely mentions ``mureo``
        and ``credential`` (without the exact tag) must survive."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        lookalike = _make_unrelated_hook(
            "Bash",
            "echo 'audit mureo credentials access'",
        )
        _write_settings(
            settings_path,
            {"hooks": {"PreToolUse": [lookalike]}},
        )

        result = remove_credential_guard(settings_path=settings_path)

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert payload["hooks"]["PreToolUse"] == [lookalike]
        assert result.changed is False

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        """Corrupt JSON raises ConfigWriteError (acceptance criteria
        L171)."""
        from mureo.cli.settings_remove import (
            ConfigWriteError,
            remove_credential_guard,
        )

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text("{nope", encoding="utf-8")
        pre_bytes = settings_path.read_bytes()

        with pytest.raises(ConfigWriteError) as exc_info:
            remove_credential_guard(settings_path=settings_path)

        assert str(settings_path) in str(exc_info.value)
        assert settings_path.read_bytes() == pre_bytes

    def test_atomic_write_preserves_original_on_failure(
        self, tmp_path: Path
    ) -> None:
        """An OSError mid-replace leaves the original byte-for-byte intact."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {
                "hooks": {
                    "PreToolUse": [
                        _make_unrelated_hook("Edit"),
                        _make_mureo_hook_entry("Read"),
                    ]
                }
            },
        )
        pre_bytes = settings_path.read_bytes()

        def _boom(src: Any, dst: Any) -> None:
            raise OSError("simulated replace failure")

        with (
            patch("mureo.cli.settings_remove.os.replace", side_effect=_boom),
            pytest.raises(OSError),
        ):
            remove_credential_guard(settings_path=settings_path)

        assert settings_path.read_bytes() == pre_bytes
        leftovers = list(settings_path.parent.glob("*.tmp*"))
        assert leftovers == []

    def test_atomic_write_uses_tempfile_in_same_dir(
        self, tmp_path: Path
    ) -> None:
        """Verify atomic-write invariant for the hook remover."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {"hooks": {"PreToolUse": [_make_mureo_hook_entry("Read")]}},
        )

        captured: dict[str, Any] = {}
        real_replace = os.replace

        def _spy_replace(
            src: str | os.PathLike[str], dst: str | os.PathLike[str]
        ) -> None:
            captured["src"] = os.fspath(src)
            captured["dst"] = os.fspath(dst)
            real_replace(src, dst)

        with patch("mureo.cli.settings_remove.os.replace", side_effect=_spy_replace):
            remove_credential_guard(settings_path=settings_path)

        src = Path(captured["src"])
        dst = Path(captured["dst"])
        assert dst == settings_path
        assert src.parent == settings_path.parent
        assert ".tmp" in src.name

    def test_default_path_uses_path_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omitting ``settings_path`` resolves through ``Path.home``."""
        from mureo.cli.settings_remove import remove_credential_guard

        monkeypatch.setattr(
            "mureo.cli.settings_remove.Path.home", lambda: tmp_path
        )
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {"hooks": {"PreToolUse": [_make_mureo_hook_entry("Read")]}},
        )

        result = remove_credential_guard()

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert payload["hooks"]["PreToolUse"] == []
        assert result.changed is True

    def test_preserves_unrelated_top_level_keys(self, tmp_path: Path) -> None:
        """``permissions`` / ``mcpServers`` / anything else survives."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        original = {
            "permissions": {"allow": ["Bash(ls:*)"]},
            "mcpServers": {"mureo": _MUREO_MCP_BLOCK},
            "hooks": {"PreToolUse": [_make_mureo_hook_entry("Read")]},
        }
        _write_settings(settings_path, original)

        remove_credential_guard(settings_path=settings_path)

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert payload["permissions"] == original["permissions"]
        assert payload["mcpServers"]["mureo"] == _MUREO_MCP_BLOCK

    def test_removes_both_read_and_bash_entries(self, tmp_path: Path) -> None:
        """Both Read and Bash mureo hooks are removed in one pass —
        symmetric with ``install_credential_guard`` which appends both."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            {
                "hooks": {
                    "PreToolUse": [
                        _make_mureo_hook_entry("Read"),
                        _make_mureo_hook_entry("Bash"),
                    ]
                }
            },
        )

        result = remove_credential_guard(settings_path=settings_path)

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert payload["hooks"]["PreToolUse"] == []
        assert result.changed is True

    def test_strips_mureo_hook_inside_multi_hook_entry(
        self, tmp_path: Path
    ) -> None:
        """When a PreToolUse entry contains BOTH a tagged mureo hook and
        an unrelated hook in its ``hooks`` array, the tagged one is
        removed while the unrelated one survives within the same entry.
        Defensive: install_credential_guard appends as its own entries,
        but a user may have merged them by hand."""
        from mureo.cli.settings_remove import remove_credential_guard

        settings_path = tmp_path / ".claude" / "settings.json"
        merged_entry = {
            "matcher": "Read",
            "hooks": [
                {"type": "command", "command": "echo user-owned"},
                {
                    "type": "command",
                    "command": f"python3 -c 'pass' # {_MUREO_HOOK_TAG}",
                },
            ],
        }
        _write_settings(
            settings_path,
            {"hooks": {"PreToolUse": [merged_entry]}},
        )

        result = remove_credential_guard(settings_path=settings_path)

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        remaining = payload["hooks"]["PreToolUse"]
        # Tagged inner-hook gone; user-owned one survives. Either the
        # entry survives with only the user hook left, or it's pruned
        # entirely — both are valid as long as the user hook is intact.
        leftover_commands = [
            h["command"]
            for entry in remaining
            for h in entry.get("hooks", [])
        ]
        assert "echo user-owned" in leftover_commands
        assert not any(_MUREO_HOOK_TAG in c for c in leftover_commands)
        assert result.changed is True


# ---------------------------------------------------------------------------
# RemoveResult shape contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveResultShape:
    def test_remove_result_is_frozen(self) -> None:
        """``RemoveResult`` is a frozen dataclass (AGENTS.md L203)."""
        from dataclasses import FrozenInstanceError

        from mureo.cli.settings_remove import RemoveResult

        r = RemoveResult(changed=True)
        with pytest.raises(FrozenInstanceError):
            r.changed = False  # type: ignore[misc]

    def test_remove_result_changed_field(self) -> None:
        """``RemoveResult.changed`` is the only required field."""
        from mureo.cli.settings_remove import RemoveResult

        assert RemoveResult(changed=True).changed is True
        assert RemoveResult(changed=False).changed is False
