"""Tests for the ``mureo install-desktop`` command.

This command is the primary onboarding path for non-engineer users
who want to run mureo from Claude Desktop chat. It must:
  - create the workspace directory if absent
  - generate a wrapper script that ``cd``s into the workspace
    (Claude Desktop ignores the ``cwd`` field in its MCP config, so
    we encode cwd in a shell wrapper instead)
  - merge a ``mureo`` entry into ``claude_desktop_config.json``
    without clobbering other MCP servers
  - back up the existing config before mutation

Each test runs against a fake ``$HOME`` via monkeypatch so we never
touch the user's real Claude Desktop config or ``~/.local/bin``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``$HOME`` and ``Path.home()`` to a temp directory.

    The installer reads several paths off ``Path.home()`` (workspace,
    wrapper directory, Claude Desktop config). Pointing them all at a
    sandbox keeps the user's real environment untouched.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Force macOS path even if tests run on Linux CI
    monkeypatch.setattr("sys.platform", "darwin")
    return tmp_path


def _config_path(home: Path) -> Path:
    return (
        home
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )


def _read_config(home: Path) -> dict:
    cfg = _config_path(home)
    if not cfg.exists():
        return {}
    return json.loads(cfg.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fresh install
# ---------------------------------------------------------------------------


def test_install_creates_workspace(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    result = install_desktop(workspace=fake_home / "mureo")

    assert (fake_home / "mureo").is_dir()
    assert result.workspace == fake_home / "mureo"


def test_install_generates_executable_wrapper(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    result = install_desktop(workspace=fake_home / "mureo")

    wrapper = result.wrapper_path
    assert wrapper.exists()
    assert wrapper.stat().st_mode & 0o111
    body = wrapper.read_text(encoding="utf-8")
    assert body.startswith("#!/bin/bash")
    assert f"cd {fake_home / 'mureo'}" in body
    assert "-m mureo.mcp" in body


def test_wrapper_exports_workspace_local_byod_dir(fake_home: Path) -> None:
    """The wrapper must ``export MUREO_BYOD_DIR=<workspace>/byod`` so
    the MCP process reads/writes BYOD data inside the workspace.
    Without this, demo and real workspaces silently share the global
    ``~/.mureo/byod/`` directory."""
    from mureo.desktop_installer import install_desktop

    result = install_desktop(workspace=fake_home / "mureo")
    body = result.wrapper_path.read_text(encoding="utf-8")
    expected = f"export MUREO_BYOD_DIR={fake_home / 'mureo' / 'byod'}"
    assert expected in body


def test_install_writes_config_with_mureo_entry(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    result = install_desktop(workspace=fake_home / "mureo")

    cfg = _read_config(fake_home)
    assert "mcpServers" in cfg
    assert "mureo" in cfg["mcpServers"]
    assert cfg["mcpServers"]["mureo"]["command"] == str(result.wrapper_path)


def test_install_creates_config_dir_if_missing(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    install_desktop(workspace=fake_home / "mureo")

    cfg_dir = fake_home / "Library" / "Application Support" / "Claude"
    assert cfg_dir.is_dir()


# ---------------------------------------------------------------------------
# Existing config preservation
# ---------------------------------------------------------------------------


def test_install_preserves_other_mcp_servers(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "filesystem": {"command": "/usr/local/bin/mcp-fs"},
                    "github": {"command": "npx", "args": ["@github/mcp"]},
                }
            }
        ),
        encoding="utf-8",
    )

    install_desktop(workspace=fake_home / "mureo")

    cfg = _read_config(fake_home)
    assert "filesystem" in cfg["mcpServers"]
    assert "github" in cfg["mcpServers"]
    assert "mureo" in cfg["mcpServers"]


def test_install_preserves_top_level_preferences(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps({"preferences": {"sidebarMode": "chat"}, "mcpServers": {}}),
        encoding="utf-8",
    )

    install_desktop(workspace=fake_home / "mureo")

    cfg = _read_config(fake_home)
    assert cfg["preferences"]["sidebarMode"] == "chat"


# ---------------------------------------------------------------------------
# Existing mureo entry — confirm vs --force
# ---------------------------------------------------------------------------


def test_install_refuses_overwrite_without_force(fake_home: Path) -> None:
    from mureo.desktop_installer import (
        DesktopInstallExistsError,
        install_desktop,
    )

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps({"mcpServers": {"mureo": {"command": "/old/path"}}}),
        encoding="utf-8",
    )

    with pytest.raises(DesktopInstallExistsError):
        install_desktop(workspace=fake_home / "mureo", force=False)


def test_install_overwrites_with_force(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps({"mcpServers": {"mureo": {"command": "/old/path"}}}),
        encoding="utf-8",
    )

    result = install_desktop(workspace=fake_home / "mureo", force=True)

    cfg = _read_config(fake_home)
    assert cfg["mcpServers"]["mureo"]["command"] == str(result.wrapper_path)
    assert cfg["mcpServers"]["mureo"]["command"] != "/old/path"


def test_install_creates_backup_when_overwriting(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"mcpServers": {"mureo": {"command": "/old/path"}}})
    cfg_path.write_text(original, encoding="utf-8")

    result = install_desktop(workspace=fake_home / "mureo", force=True)

    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.backup_path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def test_dry_run_does_not_create_files(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    result = install_desktop(workspace=fake_home / "mureo", dry_run=True)

    assert not (fake_home / "mureo").exists()
    assert not result.wrapper_path.exists()
    assert not _config_path(fake_home).exists()
    assert result.dry_run is True


# ---------------------------------------------------------------------------
# Platform support
# ---------------------------------------------------------------------------


def test_install_refuses_non_macos(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mureo.desktop_installer import (
        DesktopInstallUnsupportedPlatformError,
        install_desktop,
    )

    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(DesktopInstallUnsupportedPlatformError):
        install_desktop(workspace=fake_home / "mureo")


# ---------------------------------------------------------------------------
# Demo seeding
# ---------------------------------------------------------------------------


def test_install_with_demo_seeds_workspace(fake_home: Path) -> None:
    from mureo import desktop_installer

    with patch.object(desktop_installer, "_run_demo_init") as mock_demo:
        desktop_installer.install_desktop(
            workspace=fake_home / "mureo", with_demo="seasonality-trap"
        )

    mock_demo.assert_called_once_with(
        workspace=(fake_home / "mureo").resolve(), scenario="seasonality-trap"
    )


def test_install_with_demo_sets_byod_env_during_seed(fake_home: Path) -> None:
    """During ``_run_demo_init`` the install process must temporarily
    set ``MUREO_BYOD_DIR=<workspace>/byod`` so the demo's BYOD bundle
    lands inside the workspace — not in the global ``~/.mureo/byod/``.
    Without this, the wrapper points at the workspace but the demo
    seed wrote elsewhere, and the user sees an empty BYOD."""
    import os

    from mureo import desktop_installer

    seen_env: dict[str, str | None] = {"value": "<not-set>"}

    def capture_env(workspace: Path, scenario: str) -> None:
        seen_env["value"] = os.environ.get("MUREO_BYOD_DIR")

    with patch.object(desktop_installer, "_run_demo_init", side_effect=capture_env):
        desktop_installer.install_desktop(
            workspace=fake_home / "mureo", with_demo="seasonality-trap"
        )

    assert seen_env["value"] == str((fake_home / "mureo").resolve() / "byod")


def test_install_restores_byod_env_after_seed(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temporary ``MUREO_BYOD_DIR`` must be reverted after demo
    seed completes — leaking it into the calling process would change
    the install-desktop caller's environment in unexpected ways."""
    from mureo import desktop_installer

    monkeypatch.setenv("MUREO_BYOD_DIR", "/preexisting/path")

    with patch.object(desktop_installer, "_run_demo_init"):
        desktop_installer.install_desktop(
            workspace=fake_home / "mureo", with_demo="seasonality-trap"
        )

    import os

    assert os.environ.get("MUREO_BYOD_DIR") == "/preexisting/path"


def test_install_unsets_byod_env_after_seed_when_unset_initially(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``MUREO_BYOD_DIR`` was unset before install, it must be unset
    after install — not left as the workspace path that we used for
    the demo seed."""
    import os

    from mureo import desktop_installer

    monkeypatch.delenv("MUREO_BYOD_DIR", raising=False)

    with patch.object(desktop_installer, "_run_demo_init"):
        desktop_installer.install_desktop(
            workspace=fake_home / "mureo", with_demo="seasonality-trap"
        )

    assert "MUREO_BYOD_DIR" not in os.environ


def test_install_rejects_unknown_demo_scenario(fake_home: Path) -> None:
    """A typo'd scenario must abort *before* any filesystem mutation
    so the user is not left with a half-set-up workspace."""
    from mureo.desktop_installer import DesktopInstallError, install_desktop

    with pytest.raises(DesktopInstallError, match="Unknown demo scenario"):
        install_desktop(workspace=fake_home / "mureo", with_demo="not_a_scenario")
    # Nothing should have been written
    assert not (fake_home / "mureo").exists()
    assert not _config_path(fake_home).exists()


def test_install_without_demo_does_not_seed(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    install_desktop(workspace=fake_home / "mureo")

    assert not (fake_home / "mureo" / "STRATEGY.md").exists()
    assert not (fake_home / "mureo" / "STATE.json").exists()


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_install_is_idempotent_with_force(fake_home: Path) -> None:
    from mureo.desktop_installer import install_desktop

    install_desktop(workspace=fake_home / "mureo", force=True)
    result = install_desktop(workspace=fake_home / "mureo", force=True)

    cfg = _read_config(fake_home)
    assert cfg["mcpServers"]["mureo"]["command"] == str(result.wrapper_path)
    assert result.wrapper_path.exists()


# ---------------------------------------------------------------------------
# Malformed config
# ---------------------------------------------------------------------------


def test_install_refuses_malformed_config(fake_home: Path) -> None:
    from mureo.desktop_installer import (
        DesktopConfigCorruptError,
        install_desktop,
    )

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(DesktopConfigCorruptError):
        install_desktop(workspace=fake_home / "mureo")


def test_install_refuses_non_object_top_level(fake_home: Path) -> None:
    """A valid-JSON-but-wrong-shape config (array, string, ...) must
    raise cleanly rather than crash with AttributeError when we try to
    call ``.get('mcpServers')`` on it."""
    from mureo.desktop_installer import (
        DesktopConfigCorruptError,
        install_desktop,
    )

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text('"hello"', encoding="utf-8")

    with pytest.raises(DesktopConfigCorruptError, match="object"):
        install_desktop(workspace=fake_home / "mureo")


def test_install_handles_null_mcp_servers(fake_home: Path) -> None:
    """``{"mcpServers": null}`` is wrong but mild — be permissive and
    treat it as an empty servers map (we'd otherwise crash with
    ``'NoneType' object has no attribute 'get'``)."""
    from mureo.desktop_installer import install_desktop

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"mcpServers": None}), encoding="utf-8")

    install_desktop(workspace=fake_home / "mureo")

    cfg = _read_config(fake_home)
    assert "mureo" in cfg["mcpServers"]


def test_install_refuses_non_object_mcp_servers(fake_home: Path) -> None:
    """``{"mcpServers": "oops"}`` is corrupt enough that we should
    refuse rather than silently overwrite — the user clearly hand-
    edited it and may not want us flattening their work."""
    from mureo.desktop_installer import (
        DesktopConfigCorruptError,
        install_desktop,
    )

    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"mcpServers": "oops"}), encoding="utf-8")

    with pytest.raises(DesktopConfigCorruptError, match="mcpServers"):
        install_desktop(workspace=fake_home / "mureo")


def test_install_refuses_symlinked_config(fake_home: Path) -> None:
    """Refuse to follow a symlinked config — Dropbox/iCloud sync
    setups commonly symlink it, and writing through a symlink can land
    the change in an unexpected location."""
    import os

    from mureo.desktop_installer import (
        DesktopConfigCorruptError,
        install_desktop,
    )

    real_target = fake_home / "real_config.json"
    real_target.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    cfg_path = _config_path(fake_home)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(real_target, cfg_path)

    with pytest.raises(DesktopConfigCorruptError, match="symlink"):
        install_desktop(workspace=fake_home / "mureo")


def test_wrapper_quotes_workspace_with_spaces(fake_home: Path) -> None:
    """A workspace path containing spaces must produce a wrapper that
    runs correctly under bash — verified by checking the cd/exec lines
    use shlex-style single quoting."""
    from mureo.desktop_installer import install_desktop

    workspace = fake_home / "my mureo workspace"
    result = install_desktop(workspace=workspace)
    body = result.wrapper_path.read_text(encoding="utf-8")
    # shlex.quote on a path with spaces produces single-quoted form
    expected_cd = f"cd '{workspace.resolve()}'"
    assert expected_cd in body


def test_install_idempotent_does_not_duplicate_mureo_entry(fake_home: Path) -> None:
    """Re-running with --force must keep exactly one ``mureo`` key,
    not append a duplicate."""
    from mureo.desktop_installer import install_desktop

    install_desktop(workspace=fake_home / "mureo", force=True)
    install_desktop(workspace=fake_home / "mureo", force=True)

    cfg = _read_config(fake_home)
    server_keys = list(cfg["mcpServers"].keys())
    assert server_keys.count("mureo") == 1


# ---------------------------------------------------------------------------
# End-to-end: real materialize + workspace isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_install_with_demo_lands_byod_in_workspace_not_global(
    fake_home: Path,
) -> None:
    """End-to-end: ``--with-demo`` must produce a manifest under
    ``<workspace>/byod/`` and **not** under ``~/.mureo/byod/``.

    All earlier tests mock ``_run_demo_init``, so this is the only
    test that proves the env-var dance actually flows through to the
    real ``materialize`` call. Without this guard a future refactor
    that drops the env-var around the seed would silently regress to
    writing the demo bundle into the global directory.
    """
    from mureo.desktop_installer import install_desktop

    workspace = fake_home / "mureo"
    install_desktop(workspace=workspace, with_demo="seasonality-trap")

    workspace_manifest = workspace / "byod" / "manifest.json"
    global_manifest = fake_home / ".mureo" / "byod" / "manifest.json"
    assert (
        workspace_manifest.exists()
    ), f"Expected demo BYOD manifest at {workspace_manifest}; got nothing"
    assert (
        not global_manifest.exists()
    ), f"Demo bundle leaked into global {global_manifest}"


@pytest.mark.integration
def test_two_workspaces_keep_byod_isolated(fake_home: Path) -> None:
    """The headline guarantee: a demo workspace and a real workspace
    can coexist with independent BYOD directories. Switching between
    them is just ``install-desktop --workspace ... --force``."""
    from mureo.desktop_installer import install_desktop

    demo_ws = fake_home / "mureo-demo"
    real_ws = fake_home / "mureo-real"

    install_desktop(workspace=demo_ws, with_demo="seasonality-trap")
    install_desktop(workspace=real_ws, force=True)

    assert (demo_ws / "byod" / "manifest.json").exists()
    # The real workspace was installed without --with-demo, so its
    # byod/ should be empty (or absent). The wrapper, however, must
    # point at it so future imports land there.
    real_wrapper = (fake_home / ".local" / "bin" / "mureo-mcp-wrapper.sh").read_text()
    assert f"export MUREO_BYOD_DIR={real_ws.resolve() / 'byod'}" in real_wrapper
    # And the demo workspace's byod/ must still be intact after the
    # second install — switching workspaces does not touch siblings.
    assert (demo_ws / "byod" / "manifest.json").exists()
