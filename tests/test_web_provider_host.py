"""Host-aware unit tests for ``install_provider`` / ``remove_provider``.

Pins the ``host: str = "claude-code"`` + ``home: Path | None = None``
parameters added to ``mureo.web.setup_actions.install_provider`` /
``remove_provider`` per planner HANDOFF
``feat-web-config-ui-phase1-provider-host.md`` (Q1-Q5).

Behaviour matrix asserted (RED until the params + Desktop branch exist):

- ``host="claude-code"`` (default, or explicit) → byte-for-byte the
  CURRENT behaviour: ``run_install`` then
  ``add_provider_and_disable_in_mureo`` (all CATALOG entries coexist)
  / ``add_provider_to_claude_settings``; the Desktop writer is NOT
  called and ``claude_desktop_config.json`` is never created.
- ``host="claude-desktop"``:
  - hosted_http (meta-ads-official): ``run_install`` short-circuits
    (empty install_argv) — assert it is NOT a real subprocess; the
    ``{"type":"http","url":...}`` block lands in
    ``claude_desktop_config.json``; siblings + unrelated top-level
    keys preserved; ``add_provider_*`` (Code writers) NOT called.
  - pipx (google-ads-official): ``run_install(spec)`` STILL invoked
    (mocked, returncode 0); the ``{"command":"pipx","args":[...]}``
    block lands in the DESKTOP file, NOT ``settings.json``;
    ``add_provider_and_disable_in_mureo`` NOT called (Q2 decision).
  - non-zero ``run_install`` returncode → ``status="error"
    detail="install_returncode_<n>"``; NO config write performed.
- ``remove_provider(host="claude-desktop")`` is symmetric: pops only
  ``mcpServers[provider_id]``; idempotent (absent / missing file).
- ``~/.mureo/credentials.json`` is NEVER read/written/deleted on any
  path.
- signature: both gain ``host: str = "claude-code"`` and
  ``home: Path | None = None``.

All FS via ``tmp_path``; ``run_install`` / Code config writers mocked
(no real pipx/npm subprocess, no network). ``@pytest.mark.unit``.
"""

from __future__ import annotations

import inspect
import json
import platform
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mureo.providers.installer import InstallResult
from mureo.web.setup_actions import install_provider, remove_provider

_META = "meta-ads-official"  # hosted_http
_GOOGLE = "google-ads-official"  # pipx
_META_BLOCK = {"type": "http", "url": "https://mcp.facebook.com/ads"}


def _desktop_cfg(tmp_path: Path) -> Path:
    return (
        tmp_path
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )


def _ok_install() -> InstallResult:
    return InstallResult(returncode=0, stdout="", stderr="", argv=[])


def _seed_creds(tmp_path: Path) -> tuple[Path, bytes]:
    creds = tmp_path / ".mureo" / "credentials.json"
    creds.parent.mkdir(parents=True, exist_ok=True)
    creds.write_text('{"google_ads": {"developer_token": "X"}}', "utf-8")
    return creds, creds.read_bytes()


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProviderSignatures:
    def test_install_provider_accepts_host_and_home(self) -> None:
        """RED: ``install_provider`` has no ``host`` / ``home`` params yet."""
        params = inspect.signature(install_provider).parameters
        assert "host" in params
        assert "home" in params
        assert params["host"].default == "claude-code"
        assert params["home"].default is None

    def test_remove_provider_accepts_host_and_home(self) -> None:
        params = inspect.signature(remove_provider).parameters
        assert "host" in params
        assert "home" in params
        assert params["host"].default == "claude-code"
        assert params["home"].default is None


# ---------------------------------------------------------------------------
# Code host — byte-for-byte back-compat (regression guards)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallProviderCodeHostUnchanged:
    def test_default_host_runs_install_then_disable_in_mureo(
        self, tmp_path: Path
    ) -> None:
        """No ``host`` arg → today's path: ``run_install`` then
        ``add_provider_and_disable_in_mureo`` (every CATALOG provider
        sets ``coexists_with_mureo_platform``). Desktop writer NOT called,
        Desktop config NOT created."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with (
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ) as mock_run,
            patch(
                "mureo.providers.config_writer.add_provider_to_claude_settings"
            ) as mock_add,
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
            patch.object(
                setup_actions, "install_desktop_server_block", create=True
            ) as mock_desktop,
        ):
            result = setup_actions.install_provider(_GOOGLE)

        assert result.status == "ok"
        assert result.detail == _GOOGLE
        mock_run.assert_called_once()
        mock_disable.assert_called_once()
        mock_add.assert_not_called()
        mock_desktop.assert_not_called()
        assert not cfg.exists()

    def test_explicit_code_host_identical_to_default(
        self, tmp_path: Path
    ) -> None:
        """``host="claude-code"`` is identical to the default — Code
        writer invoked exactly as today, no Desktop file created."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with (
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
        ):
            result = setup_actions.install_provider(
                _GOOGLE, host="claude-code", home=tmp_path
            )

        assert result.status == "ok"
        mock_disable.assert_called_once()
        assert not cfg.exists()

    def test_code_host_install_returncode_nonzero_no_write(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        bad = InstallResult(returncode=2, stdout="", stderr="boom", argv=[])
        with (
            patch(
                "mureo.providers.installer.run_install", return_value=bad
            ),
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
        ):
            result = setup_actions.install_provider(_GOOGLE)

        assert result.status == "error"
        assert result.detail == "install_returncode_2"
        mock_disable.assert_not_called()

    def test_unknown_provider_code_host_no_fs_write(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        result = setup_actions.install_provider("not-a-provider")

        assert result.status == "error"
        assert result.detail == "unknown_provider"
        assert not cfg.exists()


# ---------------------------------------------------------------------------
# Desktop host — install
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallProviderDesktopHost:
    def test_hosted_http_writes_http_block_to_desktop_config(
        self, tmp_path: Path
    ) -> None:
        """meta-ads-official on Desktop: no real subprocess; the
        ``{"type":"http","url":...}`` block lands in
        ``claude_desktop_config.json``; a pre-existing unrelated server
        and a top-level key are preserved verbatim."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps(
                {
                    "mcpServers": {"other": {"command": "node"}},
                    "globalShortcut": "Cmd+Shift+Space",
                }
            ),
            encoding="utf-8",
        )

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "subprocess.run",
                side_effect=AssertionError("no subprocess on hosted_http"),
            ),
        ):
            result = setup_actions.install_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "ok"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert payload["mcpServers"][_META] == _META_BLOCK
        assert payload["mcpServers"]["other"] == {"command": "node"}
        assert payload["globalShortcut"] == "Cmd+Shift+Space"

    def test_hosted_http_does_not_call_code_writers(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.config_writer."
                "add_provider_to_claude_settings"
            ) as mock_add,
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
        ):
            setup_actions.install_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        mock_add.assert_not_called()
        mock_disable.assert_not_called()

    def test_hosted_http_does_not_write_settings_json(
        self, tmp_path: Path
    ) -> None:
        """The Code ``settings.json`` must NOT be created on the Desktop
        path (config goes only to the Desktop file)."""
        from mureo.web import setup_actions

        settings = tmp_path / ".claude" / "settings.json"
        with patch.object(platform, "system", return_value="Darwin"):
            setup_actions.install_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert not settings.exists()

    def test_pipx_subprocess_still_runs_then_block_to_desktop(
        self, tmp_path: Path
    ) -> None:
        """google-ads-official on Desktop (Q1): ``run_install(spec)`` is
        STILL invoked (mocked, returncode 0); the
        ``{"command":"pipx","args":[...]}`` block is written to
        ``claude_desktop_config.json`` (NOT settings.json)."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ) as mock_run,
        ):
            result = setup_actions.install_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
            )

        assert result.status == "ok"
        mock_run.assert_called_once()
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert payload["mcpServers"][_GOOGLE]["command"] == "pipx"
        assert payload["mcpServers"][_GOOGLE]["args"][0] == "run"
        assert not (tmp_path / ".claude" / "settings.json").exists()

    def test_pipx_desktop_does_not_call_disable_in_mureo(
        self, tmp_path: Path
    ) -> None:
        """Q2: on Desktop only the provider block is written — the
        Code-only ``add_provider_and_disable_in_mureo`` is NOT called."""
        from mureo.web import setup_actions

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
        ):
            setup_actions.install_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
            )

        mock_disable.assert_not_called()

    def test_pipx_returncode_nonzero_no_config_write(
        self, tmp_path: Path
    ) -> None:
        """Subprocess first; on non-zero returncode NO config write is
        performed (mirrors Code ordering)."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        bad = InstallResult(returncode=3, stdout="", stderr="x", argv=[])
        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.installer.run_install", return_value=bad
            ),
        ):
            result = setup_actions.install_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
            )

        assert result.status == "error"
        assert result.detail == "install_returncode_3"
        assert not cfg.exists()

    def test_idempotent_re_add_no_rewrite(self, tmp_path: Path) -> None:
        """Re-adding an already-present identical block → ``noop`` /
        file bytes unchanged."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {_META: _META_BLOCK}}),
            encoding="utf-8",
        )
        before = cfg.read_bytes()

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.install_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "noop"
        assert cfg.read_bytes() == before

    def test_corrupt_desktop_config_refused_not_overwritten(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("{ not json", encoding="utf-8")
        before = cfg.read_bytes()

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.install_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "error"
        assert cfg.read_bytes() == before

    def test_unknown_provider_desktop_no_fs_write(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.install_provider(
                "not-a-provider", host="claude-desktop", home=tmp_path
            )

        assert result.status == "error"
        assert result.detail == "unknown_provider"
        assert not cfg.exists()

    def test_credentials_json_never_touched(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        creds, before = _seed_creds(tmp_path)
        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
        ):
            setup_actions.install_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
            )

        assert creds.exists()
        assert creds.read_bytes() == before


# ---------------------------------------------------------------------------
# Desktop host — remove (symmetric)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProviderDesktopHost:
    def test_removes_only_that_id_preserving_siblings(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        _META: _META_BLOCK,
                        "mureo": {"command": "python"},
                    },
                    "theme": "dark",
                }
            ),
            encoding="utf-8",
        )

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "ok"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert _META not in payload["mcpServers"]
        assert payload["mcpServers"]["mureo"] == {"command": "python"}
        assert payload["theme"] == "dark"

    def test_absent_provider_is_noop_not_registered(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {"mureo": {"command": "x"}}}),
            encoding="utf-8",
        )
        before = cfg.read_bytes()

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "noop"
        assert result.detail == "not_registered"
        assert cfg.read_bytes() == before

    def test_missing_config_file_is_noop_not_registered(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "noop"
        assert result.detail == "not_registered"
        assert not cfg.exists()

    def test_remove_desktop_does_not_call_code_remover(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {_META: _META_BLOCK}}),
            encoding="utf-8",
        )
        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.config_writer."
                "remove_provider_from_claude_settings"
            ) as mock_code_remove,
        ):
            setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        mock_code_remove.assert_not_called()

    def test_remove_credentials_json_never_touched(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        creds, before = _seed_creds(tmp_path)
        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {_META: _META_BLOCK}}),
            encoding="utf-8",
        )
        with patch.object(platform, "system", return_value="Darwin"):
            setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert creds.read_bytes() == before

    def test_unknown_provider_desktop_remove_errors(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.remove_provider(
                "not-a-provider", host="claude-desktop", home=tmp_path
            )

        assert result.status == "error"
        assert result.detail == "unknown_provider"


@pytest.mark.unit
class TestRemoveProviderCodeHostUnchanged:
    def test_default_host_uses_code_remover(self, tmp_path: Path) -> None:
        """Regression guard: default host still delegates to
        ``remove_provider_from_claude_settings`` exactly as today."""
        from mureo.web import setup_actions

        with patch(
            "mureo.providers.config_writer."
            "remove_provider_from_claude_settings",
            return_value=MagicMock(changed=True),
        ) as mock_code_remove:
            result = setup_actions.remove_provider(_META)

        assert result.status == "ok"
        mock_code_remove.assert_called_once_with(_META)


# ---------------------------------------------------------------------------
# Integration-style (still unit, FS-mocked): writer/detector path agreement
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStatusCollectorPathAgreement:
    def test_desktop_install_reflected_in_collect_status(
        self, tmp_path: Path
    ) -> None:
        """After ``install_provider(host="claude-desktop")``,
        ``collect_status("claude-desktop", home=...)`` reports the
        provider installed — proves the writer and the (unmodified)
        detector resolve the SAME Desktop config path."""
        from mureo.web import setup_actions
        from mureo.web.status_collector import collect_status

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
        ):
            setup_actions.install_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
            )
            snapshot = collect_status("claude-desktop", home=tmp_path)

        assert snapshot.providers_installed.get(_GOOGLE) is True
