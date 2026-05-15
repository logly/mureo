"""Unit tests for the NEW ``mureo.web.desktop_mcp`` thin Desktop-MCP writer.

Pins the module created per planner HANDOFF
``feat-web-config-ui-phase1-desktop-host.md`` (Q1/Q6 decisions):

- ``install_desktop_mcp_block(config_path, command, *, backup=True) -> bool``
    1. ``_load_config(config_path)`` (reuses desktop_installer primitive)
    2. read ``mcpServers``; a non-dict value is corrupt → raise/return error,
       NEVER overwrite the user's file
    3. if ``"mureo"`` already present → return ``False`` (→ ``noop``)
    4. else: ``_backup_config`` if the file exists, deep-copy, set
       ``servers["mureo"]``, merge, ``_atomic_write_config``
- ``remove_desktop_mcp_block(config_path) -> bool`` pops only the ``mureo``
  key from ``mcpServers``, preserving every other entry; idempotent.

Hard guarantees asserted here (RED until the module exists):
- atomic write (no ``*.tmp.*`` debris left behind)
- preserves pre-existing ``mcpServers`` entries + unrelated top-level keys
- refuses corrupt JSON / non-dict ``mcpServers`` (no overwrite)
- refuses a symlinked config (Dropbox/iCloud footgun)
- NEVER touches ``~/.mureo/credentials.json``
- the path is sourced from ``get_host_paths("claude-desktop", home)``

All filesystem I/O is through ``tmp_path``; no real ``~/.claude`` /
``~/.mureo`` / Desktop config is ever written. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from mureo.desktop_installer import DesktopConfigCorruptError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _desktop_config_path(tmp_path: Path) -> Path:
    """A throwaway Claude Desktop config path under the tmp home."""
    return tmp_path / "Library" / "Application Support" / "Claude" / (
        "claude_desktop_config.json"
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _tmp_debris(path: Path) -> list[Path]:
    """Sibling tempfiles left by a non-atomic write would match this glob."""
    if not path.parent.exists():
        return []
    return list(path.parent.glob(path.name + ".tmp.*"))


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDesktopMcpModuleSurface:
    def test_module_exports_install_and_remove(self) -> None:
        """RED: the module does not exist yet → ImportError."""
        from mureo.web import desktop_mcp

        assert hasattr(desktop_mcp, "install_desktop_mcp_block")
        assert hasattr(desktop_mcp, "remove_desktop_mcp_block")

    def test_install_signature_accepts_command_and_backup(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        # Keyword-only ``backup`` per planner HANDOFF L31.
        result = desktop_mcp.install_desktop_mcp_block(
            cfg, "python -m mureo.mcp", backup=True
        )
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# install_desktop_mcp_block
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallDesktopMcpBlock:
    def test_creates_config_with_mureo_block_when_absent(
        self, tmp_path: Path
    ) -> None:
        """No config on disk → creates it with ``mcpServers.mureo``."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        assert not cfg.exists()

        changed = desktop_mcp.install_desktop_mcp_block(
            cfg, "python -m mureo.mcp"
        )

        assert changed is True
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert "mureo" in payload["mcpServers"]

    def test_returns_false_when_mureo_already_present(
        self, tmp_path: Path
    ) -> None:
        """Idempotent: an existing ``mureo`` entry → ``False`` (→ noop),
        file content byte-for-byte unchanged."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(cfg, {"mcpServers": {"mureo": {"command": "old"}}})
        before = cfg.read_bytes()

        changed = desktop_mcp.install_desktop_mcp_block(
            cfg, "python -m mureo.mcp"
        )

        assert changed is False
        assert cfg.read_bytes() == before

    def test_preserves_other_mcp_servers_and_top_level_keys(
        self, tmp_path: Path
    ) -> None:
        """A pre-existing non-mureo server and an unrelated top-level key
        survive the install verbatim (deep equality on non-mureo parts)."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(
            cfg,
            {
                "mcpServers": {
                    "other-server": {"command": "node", "args": ["x.js"]}
                },
                "globalShortcut": "Cmd+Shift+Space",
            },
        )

        desktop_mcp.install_desktop_mcp_block(cfg, "python -m mureo.mcp")

        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert payload["mcpServers"]["other-server"] == {
            "command": "node",
            "args": ["x.js"],
        }
        assert payload["globalShortcut"] == "Cmd+Shift+Space"
        assert "mureo" in payload["mcpServers"]

    def test_write_is_atomic_no_tmp_debris(self, tmp_path: Path) -> None:
        """A successful write leaves no sibling ``*.tmp.*`` files (proves
        the tempfile + ``os.replace`` path is used)."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(cfg, {"mcpServers": {}})

        desktop_mcp.install_desktop_mcp_block(cfg, "python -m mureo.mcp")

        assert _tmp_debris(cfg) == []

    def test_backs_up_existing_config_before_write(
        self, tmp_path: Path
    ) -> None:
        """When the config exists and ``backup=True``, a timestamped
        ``.bak.`` snapshot is created (reuses ``_backup_config``)."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(cfg, {"mcpServers": {"other": {"command": "x"}}})

        desktop_mcp.install_desktop_mcp_block(
            cfg, "python -m mureo.mcp", backup=True
        )

        backups = list(cfg.parent.glob(cfg.name + ".bak.*"))
        assert backups, "expected a timestamped backup snapshot"

    def test_no_backup_when_file_absent(self, tmp_path: Path) -> None:
        """Nothing to back up when the config does not yet exist."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        desktop_mcp.install_desktop_mcp_block(
            cfg, "python -m mureo.mcp", backup=True
        )

        assert list(cfg.parent.glob(cfg.name + ".bak.*")) == []

    def test_invalid_json_is_refused_not_overwritten(
        self, tmp_path: Path
    ) -> None:
        """Corrupt (non-JSON) config → ``DesktopConfigCorruptError``;
        original bytes untouched (no silent overwrite)."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("{ this is not json", encoding="utf-8")
        before = cfg.read_bytes()

        with pytest.raises(DesktopConfigCorruptError):
            desktop_mcp.install_desktop_mcp_block(cfg, "python -m mureo.mcp")

        assert cfg.read_bytes() == before

    def test_non_dict_mcp_servers_is_refused_not_overwritten(
        self, tmp_path: Path
    ) -> None:
        """``mcpServers`` present but not an object → corrupt; refuse and
        leave the file untouched (planner HANDOFF L104-L106)."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(cfg, {"mcpServers": ["not", "a", "dict"]})
        before = cfg.read_bytes()

        with pytest.raises(DesktopConfigCorruptError):
            desktop_mcp.install_desktop_mcp_block(cfg, "python -m mureo.mcp")

        assert cfg.read_bytes() == before

    def test_non_object_top_level_is_refused(self, tmp_path: Path) -> None:
        """A JSON array at the top level → ``DesktopConfigCorruptError``
        (reuses ``_load_config``)."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(cfg, [1, 2, 3])

        with pytest.raises(DesktopConfigCorruptError):
            desktop_mcp.install_desktop_mcp_block(cfg, "python -m mureo.mcp")

    def test_symlinked_config_is_refused(self, tmp_path: Path) -> None:
        """A symlinked config must be refused (reuses
        ``_atomic_write_config``'s symlink guard)."""
        from mureo.web import desktop_mcp

        real = tmp_path / "real_config.json"
        _write_json(real, {"mcpServers": {}})
        cfg = _desktop_config_path(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.symlink_to(real)

        with pytest.raises(DesktopConfigCorruptError):
            desktop_mcp.install_desktop_mcp_block(cfg, "python -m mureo.mcp")

    def test_command_value_is_recorded_in_block(self, tmp_path: Path) -> None:
        """The supplied command string is what lands in the mureo block."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        desktop_mcp.install_desktop_mcp_block(cfg, "/usr/bin/mywrapper.sh")

        payload = json.loads(cfg.read_text(encoding="utf-8"))
        serialized = json.dumps(payload["mcpServers"]["mureo"])
        assert "/usr/bin/mywrapper.sh" in serialized

    def test_never_touches_credentials_json(self, tmp_path: Path) -> None:
        """CTO decision #3: the Desktop MCP writer NEVER reads/writes/
        deletes ``~/.mureo/credentials.json``."""
        from mureo.web import desktop_mcp

        creds = tmp_path / ".mureo" / "credentials.json"
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text('{"google_ads": {"developer_token": "X"}}', "utf-8")
        before = creds.read_bytes()

        cfg = _desktop_config_path(tmp_path)
        desktop_mcp.install_desktop_mcp_block(cfg, "python -m mureo.mcp")

        assert creds.exists()
        assert creds.read_bytes() == before

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """The Desktop config's parent dirs may not exist on first run;
        the writer must create them (reuses ``_atomic_write_config``)."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        assert not cfg.parent.exists()

        desktop_mcp.install_desktop_mcp_block(cfg, "python -m mureo.mcp")

        assert cfg.exists()


# ---------------------------------------------------------------------------
# remove_desktop_mcp_block
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveDesktopMcpBlock:
    def test_removes_only_mureo_preserving_others(
        self, tmp_path: Path
    ) -> None:
        """Drops the ``mureo`` key only; sibling servers + top-level keys
        survive."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(
            cfg,
            {
                "mcpServers": {
                    "mureo": {"command": "python -m mureo.mcp"},
                    "other": {"command": "node"},
                },
                "theme": "dark",
            },
        )

        changed = desktop_mcp.remove_desktop_mcp_block(cfg)

        assert changed is True
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert "mureo" not in payload["mcpServers"]
        assert payload["mcpServers"]["other"] == {"command": "node"}
        assert payload["theme"] == "dark"

    def test_returns_false_when_mureo_absent(self, tmp_path: Path) -> None:
        """Idempotent: nothing to remove → ``False`` (→ noop/not_installed),
        file content unchanged."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(cfg, {"mcpServers": {"other": {"command": "node"}}})
        before = cfg.read_bytes()

        changed = desktop_mcp.remove_desktop_mcp_block(cfg)

        assert changed is False
        assert cfg.read_bytes() == before

    def test_returns_false_when_config_missing(self, tmp_path: Path) -> None:
        """No config file at all → ``False`` (nothing to do); no file
        created."""
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        assert not cfg.exists()

        changed = desktop_mcp.remove_desktop_mcp_block(cfg)

        assert changed is False
        assert not cfg.exists()

    def test_remove_is_atomic_no_tmp_debris(self, tmp_path: Path) -> None:
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(
            cfg,
            {"mcpServers": {"mureo": {"command": "x"}, "other": {"command": "y"}}},
        )

        desktop_mcp.remove_desktop_mcp_block(cfg)

        assert _tmp_debris(cfg) == []

    def test_idempotent_second_call_is_noop(self, tmp_path: Path) -> None:
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        _write_json(cfg, {"mcpServers": {"mureo": {"command": "x"}}})

        first = desktop_mcp.remove_desktop_mcp_block(cfg)
        second = desktop_mcp.remove_desktop_mcp_block(cfg)

        assert first is True
        assert second is False

    def test_corrupt_config_refused_not_overwritten(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import desktop_mcp

        cfg = _desktop_config_path(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("}}} not json", encoding="utf-8")
        before = cfg.read_bytes()

        with pytest.raises(DesktopConfigCorruptError):
            desktop_mcp.remove_desktop_mcp_block(cfg)

        assert cfg.read_bytes() == before

    def test_never_touches_credentials_json(self, tmp_path: Path) -> None:
        from mureo.web import desktop_mcp

        creds = tmp_path / ".mureo" / "credentials.json"
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text('{"meta_ads": {"token": "X"}}', "utf-8")
        before = creds.read_bytes()

        cfg = _desktop_config_path(tmp_path)
        _write_json(cfg, {"mcpServers": {"mureo": {"command": "x"}}})
        desktop_mcp.remove_desktop_mcp_block(cfg)

        assert creds.read_bytes() == before


# ---------------------------------------------------------------------------
# Path resolution: must come from host_paths, NOT _macos_config_path()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPathResolutionViaHostPaths:
    def test_macos_path_matches_host_paths_settings_path(
        self, tmp_path: Path
    ) -> None:
        """On macOS the resolved Desktop config path equals
        ``get_host_paths("claude-desktop", home).settings_path`` — i.e.
        the writer must NOT hardcode ``desktop_installer._macos_config_path``
        (which ignores the tmp ``home``)."""
        from mureo.web import desktop_mcp
        from mureo.web.host_paths import get_host_paths

        expected = get_host_paths("claude-desktop", home=tmp_path).settings_path

        with patch.object(platform, "system", return_value="Darwin"):
            resolved = desktop_mcp.resolve_desktop_config_path(home=tmp_path)

        assert resolved == expected
        # And it lives under the tmp home, never the real ~/Library.
        assert str(tmp_path) in str(resolved)

    def test_non_macos_falls_back_to_claude_settings(
        self, tmp_path: Path
    ) -> None:
        """Off macOS, the path falls back to ``<home>/.claude/settings.json``
        (host_paths fallback) — no unsupported-platform error in the web
        flow (acceptance criteria L23 / L118)."""
        from mureo.web import desktop_mcp

        with patch.object(platform, "system", return_value="Linux"):
            resolved = desktop_mcp.resolve_desktop_config_path(home=tmp_path)

        assert resolved == tmp_path / ".claude" / "settings.json"
