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
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.providers.catalog import get_provider
from mureo.providers.installer import InstallResult
from mureo.web.setup_actions import install_provider, remove_provider

_META = "meta-ads-official"  # hosted_http
_GOOGLE = "google-ads-official"  # pipx
_META_BLOCK = {"type": "http", "url": "https://mcp.facebook.com/ads"}


@pytest.fixture(autouse=True)
def _isolate_credentials_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point the credentials.json DEFAULT path at an isolated tmp file.

    ``install_provider`` defaults ``credentials_path=None``, which makes
    ``_credential_env_for`` resolve the real ``~/.mureo/credentials.json``.
    Without this fixture, any test exercising the real config-write path
    for a pipx provider would pick up the developer's actual Google Ads
    credentials and leak them into assertions/output. Explicit
    ``credentials_path=`` arguments are preserved untouched.
    """
    iso = tmp_path / "_iso_credentials.json"
    monkeypatch.setattr(
        "mureo.web.env_var_writer._resolve_credentials_path",
        lambda p: p if p is not None else iso,
    )


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


def _unfreeze(value: Any) -> Any:
    """Recursively convert MappingProxyType/tuple catalog blocks to plain
    dict/list so equality + json round-trips match the on-disk shape."""
    if isinstance(value, Mapping):
        return {k: _unfreeze(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_unfreeze(v) for v in value]
    return value


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

    def test_explicit_code_host_identical_to_default(self, tmp_path: Path) -> None:
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
            patch("mureo.providers.installer.run_install", return_value=bad),
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
        ):
            result = setup_actions.install_provider(_GOOGLE)

        assert result.status == "error"
        assert result.detail == "install_returncode_2"
        mock_disable.assert_not_called()

    def test_unknown_provider_code_host_no_fs_write(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        result = setup_actions.install_provider("not-a-provider")

        assert result.status == "error"
        assert result.detail == "unknown_provider"
        assert not cfg.exists()


# ---------------------------------------------------------------------------
# Credential env injection — the reported "registers but unusable" bug
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallProviderInjectsCredentialEnv:
    def test_install_provider_accepts_credentials_path(self) -> None:
        params = inspect.signature(install_provider).parameters
        assert "credentials_path" in params
        assert params["credentials_path"].default is None

    def test_code_host_injects_google_env_from_credentials(
        self, tmp_path: Path
    ) -> None:
        """The official Google Ads block is registered WITH the env the
        upstream MCP needs, resolved from credentials.json — without this
        it registers but cannot authenticate (the reported bug)."""
        from mureo.web import setup_actions

        creds = tmp_path / ".mureo" / "credentials.json"
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text(
            '{"google_ads": {"developer_token": "DT", "client_id": "CID",'
            ' "client_secret": "CS", "refresh_token": "RT",'
            ' "login_customer_id": "123"}}',
            "utf-8",
        )

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
                _GOOGLE, credentials_path=creds
            )

        assert result.status == "ok"
        _, kwargs = mock_disable.call_args
        assert kwargs["extra_env"] == {
            "GOOGLE_ADS_DEVELOPER_TOKEN": "DT",
            "GOOGLE_ADS_CLIENT_ID": "CID",
            "GOOGLE_ADS_CLIENT_SECRET": "CS",
            "GOOGLE_ADS_REFRESH_TOKEN": "RT",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "123",
        }

    def test_code_host_hosted_meta_no_write_no_disable(
        self, tmp_path: Path
    ) -> None:
        """Meta's hosted MCP can't be wired as a raw http entry on Claude
        Code (no DCR) — the Code path returns ``manual_required`` and
        touches NEITHER the provider config NOR the native-disable env,
        even when a meta_ads section exists in credentials.json."""
        from mureo.web import setup_actions

        creds = tmp_path / ".mureo" / "credentials.json"
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text('{"meta_ads": {"access_token": "T"}}', "utf-8")

        with (
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
            patch(
                "mureo.providers.config_writer.add_provider_to_claude_settings",
                side_effect=AssertionError("no http block on hosted_http/Code"),
            ),
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo",
                side_effect=AssertionError("no native auto-disable on hosted_http"),
            ),
        ):
            result = setup_actions.install_provider(
                _META, credentials_path=creds
            )

        assert result.status == "manual_required"
        assert result.detail == _META

    def test_code_host_missing_credentials_still_registers_bare(
        self, tmp_path: Path
    ) -> None:
        """No credentials.json yet → provider still registers (bare
        block, pre-fix shape); no crash."""
        from mureo.web import setup_actions

        creds = tmp_path / ".mureo" / "credentials.json"

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
                _GOOGLE, credentials_path=creds
            )

        assert result.status == "ok"
        _, kwargs = mock_disable.call_args
        assert not kwargs.get("extra_env")


# ---------------------------------------------------------------------------
# Desktop host — install
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallProviderDesktopHost:
    def test_hosted_http_returns_manual_required_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        """meta-ads-official on Desktop: a remote MCP cannot be wired
        into Claude Desktop via the config file (Desktop rejects the
        native http shape; mcp-remote fails on Meta's no-DCR OAuth
        server). The only working path is the user adding it manually
        via Settings → Connectors. So the result is ``manual_required``
        and the config file is NEVER written/created; a pre-existing
        unrelated server and a top-level key are left byte-identical."""
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
        before = cfg.read_bytes()

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

        assert result.status == "manual_required"
        assert result.detail == _META
        assert cfg.read_bytes() == before

    def test_hosted_http_does_not_call_code_writers(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.config_writer." "add_provider_to_claude_settings"
            ) as mock_add,
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
        ):
            setup_actions.install_provider(_META, host="claude-desktop", home=tmp_path)

        mock_add.assert_not_called()
        mock_disable.assert_not_called()

    def test_hosted_http_does_not_write_settings_json(self, tmp_path: Path) -> None:
        """The Code ``settings.json`` must NOT be created on the Desktop
        path (config goes only to the Desktop file)."""
        from mureo.web import setup_actions

        settings = tmp_path / ".claude" / "settings.json"
        with patch.object(platform, "system", return_value="Darwin"):
            setup_actions.install_provider(_META, host="claude-desktop", home=tmp_path)

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

    def test_pipx_desktop_does_not_call_disable_in_mureo(self, tmp_path: Path) -> None:
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

    def test_pipx_returncode_nonzero_no_config_write(self, tmp_path: Path) -> None:
        """Subprocess first; on non-zero returncode NO config write is
        performed (mirrors Code ordering)."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        bad = InstallResult(returncode=3, stdout="", stderr="x", argv=[])
        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch("mureo.providers.installer.run_install", return_value=bad),
        ):
            result = setup_actions.install_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
            )

        assert result.status == "error"
        assert result.detail == "install_returncode_3"
        assert not cfg.exists()

    def test_pipx_idempotent_re_add_no_rewrite(self, tmp_path: Path) -> None:
        """A pipx provider already present with an identical block →
        ``noop`` / file bytes unchanged (pipx is the only Desktop path
        that writes the config; hosted_http never does)."""
        from mureo.web import setup_actions

        spec = get_provider(_GOOGLE)
        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {_GOOGLE: dict(spec.mcp_server_config)}}),
            encoding="utf-8",
        )
        before = cfg.read_bytes()

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
        ):
            result = setup_actions.install_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
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

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
        ):
            result = setup_actions.install_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
            )

        assert result.status == "error"
        assert cfg.read_bytes() == before

    def test_unknown_provider_desktop_no_fs_write(self, tmp_path: Path) -> None:
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
    def test_removes_only_that_id_preserving_siblings(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        # Use a pipx provider — that is the path that still pops an
        # mcpServers block on Desktop (hosted_http remove instead
        # unsets MUREO_DISABLE_*, covered separately).
        cfg.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        _GOOGLE: {"command": "pipx"},
                        "mureo": {"command": "python"},
                    },
                    "theme": "dark",
                }
            ),
            encoding="utf-8",
        )

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.remove_provider(
                _GOOGLE, host="claude-desktop", home=tmp_path
            )

        assert result.status == "ok"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert _GOOGLE not in payload["mcpServers"]
        assert payload["mcpServers"]["mureo"] == {"command": "python"}
        assert payload["theme"] == "dark"

    def test_absent_provider_is_noop_not_registered(self, tmp_path: Path) -> None:
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

    def test_missing_config_file_is_noop_not_registered(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "noop"
        assert result.detail == "not_registered"
        assert not cfg.exists()

    def test_remove_desktop_does_not_call_code_remover(self, tmp_path: Path) -> None:
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
                "mureo.providers.config_writer." "remove_provider_from_claude_settings"
            ) as mock_code_remove,
        ):
            setup_actions.remove_provider(_META, host="claude-desktop", home=tmp_path)

        mock_code_remove.assert_not_called()

    def test_remove_credentials_json_never_touched(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        creds, before = _seed_creds(tmp_path)
        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {_META: _META_BLOCK}}),
            encoding="utf-8",
        )
        with patch.object(platform, "system", return_value="Darwin"):
            setup_actions.remove_provider(_META, host="claude-desktop", home=tmp_path)

        assert creds.read_bytes() == before

    def test_unknown_provider_desktop_remove_errors(self, tmp_path: Path) -> None:
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
            "mureo.providers.config_writer." "remove_provider_from_claude_settings",
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
    def test_desktop_install_reflected_in_collect_status(self, tmp_path: Path) -> None:
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


# ---------------------------------------------------------------------------
# hosted_http on Claude Desktop = manual Connectors only
#
# A remote MCP cannot be wired into Claude Desktop via the config file:
# Desktop rejects the native {"type":"http","url":...} shape, and the
# mcp-remote stdio bridge fails on servers without OAuth Dynamic Client
# Registration (Meta's hosted Ads MCP returns
# "InvalidClientMetadataError: Dynamic registration is not available").
# The only working path is the user adding it via Claude Desktop →
# Settings → Connectors → Add custom connector. So hosted_http + Desktop
# returns ``manual_required`` and writes NOTHING. Code host is unchanged
# (native http block); pipx/npm Desktop is unchanged (their stdio block).
# ---------------------------------------------------------------------------


_META_HTTP_BLOCK = {"type": "http", "url": "https://mcp.facebook.com/ads"}


@pytest.mark.unit
class TestHostedHttpDesktopManualRequired:
    def test_hosted_http_desktop_returns_manual_required(self, tmp_path: Path) -> None:
        """meta-ads-official on Desktop: result is ``manual_required``
        (the user must add it via Settings → Connectors); NO subprocess,
        NO config file written or created."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
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

        assert result.status == "manual_required"
        assert result.detail == _META
        assert not cfg.exists()

    def test_hosted_http_desktop_no_mcp_remote_anywhere(self, tmp_path: Path) -> None:
        """Hard guard: the abandoned mcp-remote bridge must NEVER be
        written for a hosted_http provider on Desktop."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with patch.object(platform, "system", return_value="Darwin"):
            setup_actions.install_provider(_META, host="claude-desktop", home=tmp_path)

        assert not cfg.exists()

    def test_code_host_hosted_http_returns_manual_required(
        self, tmp_path: Path
    ) -> None:
        """meta-ads-official on Claude Code: a raw user-scope http entry
        can NEVER connect (Meta has no OAuth Dynamic Client
        Registration — Claude shows "✗ Failed to connect"). So the Code
        path must mirror Desktop: ``manual_required``, NO dead http block
        written, and mureo-native Meta NOT auto-disabled (auto-disabling
        while the official path is unverified strands the user — the
        observed regression). The working path is Claude's account-level
        Connectors, which mureo cannot create programmatically."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with (
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
            patch(
                "mureo.providers.config_writer.add_provider_to_claude_settings",
                side_effect=AssertionError("no http block on hosted_http/Code"),
            ),
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo",
                side_effect=AssertionError("no native auto-disable on hosted_http"),
            ),
        ):
            result = setup_actions.install_provider(
                _META, host="claude-code", home=tmp_path
            )

        assert result.status == "manual_required"
        assert result.detail == _META
        assert not cfg.exists()

    def test_pipx_provider_desktop_block_unchanged(self, tmp_path: Path) -> None:
        """pipx providers on Desktop keep their existing
        ``{"command":"pipx","args":[...]}`` block (the manual-required
        short-circuit is gated on ``hosted_http`` only)."""
        from mureo.web import setup_actions

        expected = _unfreeze(get_provider(_GOOGLE).mcp_server_config)
        cfg = _desktop_cfg(tmp_path)
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

        block = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"][_GOOGLE]
        assert block == expected
        assert block["command"] == "pipx"
        assert "mcp-remote" not in json.dumps(block)

    def test_hosted_http_desktop_skips_subprocess(self, tmp_path: Path) -> None:
        """``run_install`` is NEVER invoked for the hosted provider on
        Desktop (short-circuited before the subprocess branch)."""
        from mureo.web import setup_actions

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch("mureo.providers.installer.run_install") as mock_run,
        ):
            setup_actions.install_provider(_META, host="claude-desktop", home=tmp_path)

        mock_run.assert_not_called()

    def test_remove_hosted_http_desktop_clean_tree_is_noop(
        self, tmp_path: Path
    ) -> None:
        """On Desktop the Meta MCP block is never written by mureo
        (manual Connectors), so removing it on a tree with no
        MUREO_DISABLE_META_ADS env is a noop not_registered. The
        env-unset behaviour when it IS set is covered by
        TestHostedHttpDesktopDisablesMureoTools."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {"mureo": {"command": "python"}}}),
            encoding="utf-8",
        )
        with patch.object(platform, "system", return_value="Darwin"):
            removed = setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert removed.status == "noop"
        assert removed.detail == "not_registered"

    def test_credentials_json_never_touched_install_and_remove(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        creds, before = _seed_creds(tmp_path)
        with patch.object(platform, "system", return_value="Darwin"):
            setup_actions.install_provider(_META, host="claude-desktop", home=tmp_path)
            setup_actions.remove_provider(_META, host="claude-desktop", home=tmp_path)

        assert creds.exists()
        assert creds.read_bytes() == before


# ---------------------------------------------------------------------------
# _desktop_block_for(spec) -> Mapping[str, Any]
#
# hosted_http never reaches this helper (short-circuited to
# manual_required). It returns the catalog block verbatim for the
# stdio-shaped pipx/npm specs that DO write the Desktop config.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHostedHttpDesktopDisablesMureoTools:
    """Official Meta on Desktop: the Meta MCP block is NOT written
    (manual Connectors), and mureo-native Meta is NOT auto-disabled —
    the official path only works once the user completes the manual
    Connectors setup, so disabling native first would strand them with
    zero Meta capability. Consistent with the Code/CLI hosted_http
    behaviour. ``remove`` still unsets a stale MUREO_DISABLE_<P> as a
    migration self-heal for users who installed under the old logic."""

    def _seed_mureo_block(self, tmp_path: Path, extra=None) -> Path:
        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        servers = {"mureo": {"command": "python", "args": ["-m", "mureo.mcp"]}}
        if extra:
            servers.update(extra)
        cfg.write_text(
            json.dumps({"mcpServers": servers, "theme": "dark"}),
            encoding="utf-8",
        )
        return cfg

    def test_install_does_not_disable_native_or_write_block(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        cfg = self._seed_mureo_block(tmp_path, extra={"other": {"command": "node"}})
        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.install_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "manual_required"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        # mureo-native Meta is NOT auto-disabled (the reported regression).
        assert "MUREO_DISABLE_META_ADS" not in payload["mcpServers"]["mureo"].get(
            "env", {}
        )
        # mureo block + other server + top-level key untouched.
        assert payload["mcpServers"]["mureo"]["command"] == "python"
        assert payload["mcpServers"]["mureo"]["args"] == ["-m", "mureo.mcp"]
        assert payload["mcpServers"]["other"] == {"command": "node"}
        assert payload["theme"] == "dark"
        # The Meta MCP block itself is NOT written (manual Connectors).
        assert _META not in payload["mcpServers"]

    def test_install_no_mureo_block_is_noop_still_manual_required(
        self, tmp_path: Path
    ) -> None:
        """No mureo block yet (basic setup skipped): disable-env is a
        best-effort no-op; the result is still manual_required and the
        file is not corrupted."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.install_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert result.status == "manual_required"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert "mureo" not in payload["mcpServers"]

    def test_remove_self_heals_stale_disable_meta_env(
        self, tmp_path: Path
    ) -> None:
        """Migration self-heal: a user who installed Meta-official under
        the OLD logic has MUREO_DISABLE_META_ADS=1 stuck on their mureo
        block (native stranded). ``remove`` must unset it and report
        ``ok`` so native Meta comes back."""
        from mureo.web import setup_actions

        cfg = self._seed_mureo_block(
            tmp_path,
            extra={
                "mureo": {
                    "command": "python",
                    "args": ["-m", "mureo.mcp"],
                    "env": {"MUREO_DISABLE_META_ADS": "1"},
                }
            },
        )
        with patch.object(platform, "system", return_value="Darwin"):
            removed = setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )

        assert removed.status == "ok"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        env = payload["mcpServers"]["mureo"].get("env", {})
        assert "MUREO_DISABLE_META_ADS" not in env
        # mureo block otherwise intact.
        assert payload["mcpServers"]["mureo"]["command"] == "python"

    def test_remove_when_not_set_is_noop(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        self._seed_mureo_block(tmp_path)
        with patch.object(platform, "system", return_value="Darwin"):
            removed = setup_actions.remove_provider(
                _META, host="claude-desktop", home=tmp_path
            )
        assert removed.status == "noop"
        assert removed.detail == "not_registered"

    def test_malformed_env_refused_not_overwritten(self, tmp_path: Path) -> None:
        """A truthy non-dict ``mcpServers.mureo.env`` is a corrupt
        config: set_mureo_disable_env_desktop must raise
        DesktopConfigCorruptError (not a bare ValueError) without
        rewriting the file. Surfaced via the install best-effort log;
        the user still gets manual_required and the file is intact."""
        from mureo.desktop_installer import DesktopConfigCorruptError
        from mureo.web import desktop_mcp, setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {"mureo": {"command": "python", "env": "x"}}}),
            encoding="utf-8",
        )
        before = cfg.read_bytes()

        with pytest.raises(DesktopConfigCorruptError):
            desktop_mcp.set_mureo_disable_env_desktop(cfg, "MUREO_DISABLE_META_ADS")
        assert cfg.read_bytes() == before

        # install still degrades gracefully to manual_required.
        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.install_provider(
                _META, host="claude-desktop", home=tmp_path
            )
        assert result.status == "manual_required"
        assert cfg.read_bytes() == before

    def test_credentials_json_never_touched(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        self._seed_mureo_block(tmp_path)
        creds, before = _seed_creds(tmp_path)
        with patch.object(platform, "system", return_value="Darwin"):
            setup_actions.install_provider(_META, host="claude-desktop", home=tmp_path)
            setup_actions.remove_provider(_META, host="claude-desktop", home=tmp_path)
        assert creds.exists()
        assert creds.read_bytes() == before


@pytest.mark.unit
class TestDesktopBlockForHelper:
    def test_helper_exists(self) -> None:
        from mureo.web import setup_actions

        assert hasattr(setup_actions, "_desktop_block_for")

    def test_pipx_spec_returned_verbatim(self) -> None:
        from mureo.web import setup_actions

        spec = get_provider(_GOOGLE)
        expected = _unfreeze(spec.mcp_server_config)
        block = setup_actions._desktop_block_for(spec)
        assert _unfreeze(block) == expected

    def test_ga4_spec_returned_verbatim(self) -> None:
        from mureo.web import setup_actions

        spec = get_provider("ga4-official")
        expected = _unfreeze(spec.mcp_server_config)
        block = setup_actions._desktop_block_for(spec)
        assert _unfreeze(block) == expected


@pytest.mark.unit
class TestConfirmHostedProvider:
    """`confirm_hosted_provider` disables mureo-native tools ONLY after
    the official hosted connector is verified Connected (closes the
    post-setup coexistence gap without ever stranding the user)."""

    def _seed(self, tmp_path: Path, env=None) -> Path:
        cfg = tmp_path / ".claude.json"
        mureo = {"command": "python", "args": ["-m", "mureo.mcp"]}
        if env is not None:
            mureo["env"] = env
        cfg.write_text(
            json.dumps({"mcpServers": {"mureo": mureo}}), encoding="utf-8"
        )
        return cfg

    def test_unknown_provider_errors(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        r = setup_actions.confirm_hosted_provider("nope")
        assert r.status == "error"
        assert r.detail == "unknown_provider"

    def test_non_hosted_rejected(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        r = setup_actions.confirm_hosted_provider(_GOOGLE)
        assert r.status == "error"
        assert r.detail == "not_hosted"

    def test_not_connected_does_not_disable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.web import setup_actions

        cfg = self._seed(tmp_path)
        monkeypatch.setattr(
            "mureo.providers.config_writer.Path.home", lambda: tmp_path
        )
        monkeypatch.setattr(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            lambda spec: False,
        )
        r = setup_actions.confirm_hosted_provider(_META)
        assert r.status == "not_connected"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert "env" not in payload["mcpServers"]["mureo"]

    def test_connected_disables_native(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.web import setup_actions

        cfg = self._seed(tmp_path)
        monkeypatch.setattr(
            "mureo.providers.config_writer.Path.home", lambda: tmp_path
        )
        monkeypatch.setattr(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            lambda spec: True,
        )
        r = setup_actions.confirm_hosted_provider(_META)
        assert r.status == "ok"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert (
            payload["mcpServers"]["mureo"]["env"]["MUREO_DISABLE_META_ADS"]
            == "1"
        )

    def test_connected_already_disabled_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.web import setup_actions

        self._seed(tmp_path, env={"MUREO_DISABLE_META_ADS": "1"})
        monkeypatch.setattr(
            "mureo.providers.config_writer.Path.home", lambda: tmp_path
        )
        monkeypatch.setattr(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            lambda spec: True,
        )
        r = setup_actions.confirm_hosted_provider(_META)
        assert r.status == "noop"

    def test_connected_no_mureo_block_reports_setup_needed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.web import setup_actions

        monkeypatch.setattr(
            "mureo.providers.config_writer.Path.home", lambda: tmp_path
        )
        monkeypatch.setattr(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            lambda spec: True,
        )
        r = setup_actions.confirm_hosted_provider(_META)
        assert r.status == "error"
        assert r.detail == "no_mureo_block"

    def test_desktop_host_is_manual(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        r = setup_actions.confirm_hosted_provider(
            _META, host="claude-desktop", home=tmp_path
        )
        assert r.status == "manual"
        assert r.detail == _META


@pytest.mark.unit
class TestHostedProviderStatus:
    """`hosted_provider_status` reports the account-level Connector
    Connected state for hosted_http providers (mureo never registers
    them, so the file-parse status always says ✗ — this drives the
    dashboard's ✓ once the user finishes the browser Connector setup)."""

    def test_returns_connected_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.web import setup_actions

        monkeypatch.setattr(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            lambda spec: True,
        )
        assert setup_actions.hosted_provider_status() == {
            "meta-ads-official": True
        }

    def test_returns_connected_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.web import setup_actions

        monkeypatch.setattr(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            lambda spec: False,
        )
        assert setup_actions.hosted_provider_status() == {
            "meta-ads-official": False
        }

    def test_never_raises_returns_empty_on_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.web import setup_actions

        def _boom() -> Any:
            raise RuntimeError("catalog blew up")

        monkeypatch.setattr("mureo.providers.catalog.get_catalog", _boom)
        assert setup_actions.hosted_provider_status() == {}
