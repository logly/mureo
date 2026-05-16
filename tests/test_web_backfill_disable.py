"""Backfill MUREO_DISABLE_* when mureo MCP is configured AFTER an
official provider was already registered.

Closes the order-dependency hole: `providers add` only auto-sets
MUREO_DISABLE_<P> when a mureo block already exists. If the user added
the official provider FIRST (no mureo block yet) then configured the
mureo MCP later, native + official both ended up active with no
deterministic precedence. `install_mureo_mcp` now backfills the disable
env for already-registered overlapping providers.

Safety rules pinned here:
- pipx/npm providers (google-ads-official, ga4-official): file-registry
  presence is the signal.
- hosted_http (meta-ads-official): NEVER disabled on mere config
  presence — only when the account-level connector is verified
  Connected (`is_hosted_provider_connected`), mirroring the no-strand
  decision made for `providers confirm`.
- idempotent; never raises; no mureo block ⇒ no-op (never invents one).

``@pytest.mark.unit``; FS via ``tmp_path``.
"""

from __future__ import annotations

import json
import platform
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _claude_json(tmp: Path) -> Path:
    return tmp / ".claude.json"


def _desktop_cfg(tmp: Path) -> Path:
    return (
        tmp
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )


def _seed(path: Path, servers: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


_MUREO = {"command": "python", "args": ["-m", "mureo.mcp"]}
_GA_OFFICIAL = {"type": "stdio", "command": "pipx", "args": ["run", "x"]}


@pytest.mark.unit
class TestBackfillDisable:
    def test_code_backfills_google_when_official_present(
        self, tmp_path: Path
    ) -> None:
        from mureo.web.setup_actions import (
            backfill_disable_for_installed_providers,
        )

        cj = _claude_json(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO), "google-ads-official": _GA_OFFICIAL})

        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=False,
        ):
            backfill_disable_for_installed_providers("claude-code", tmp_path)

        env = json.loads(cj.read_text())["mcpServers"]["mureo"].get("env", {})
        assert env.get("MUREO_DISABLE_GOOGLE_ADS") == "1"
        assert "MUREO_DISABLE_META_ADS" not in env

    def test_meta_is_never_backfilled_even_if_connector_connected(
        self, tmp_path: Path
    ) -> None:
        """Meta (hosted) is intentionally OUT of backfill scope — no
        network probe on the basic-setup path. Even with the connector
        reporting Connected, backfill must NOT touch MUREO_DISABLE_META.
        (Meta switching is the explicit confirm / native-toggle path.)"""
        from mureo.web.setup_actions import (
            backfill_disable_for_installed_providers,
        )

        cj = _claude_json(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO)})

        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=True,
        ) as probe:
            backfill_disable_for_installed_providers("claude-code", tmp_path)

        env = json.loads(cj.read_text())["mcpServers"]["mureo"].get("env", {})
        assert "MUREO_DISABLE_META_ADS" not in env
        # And the network probe is never even called from this path.
        probe.assert_not_called()

    def test_code_meta_not_disabled_when_connector_absent(
        self, tmp_path: Path
    ) -> None:
        from mureo.web.setup_actions import (
            backfill_disable_for_installed_providers,
        )

        cj = _claude_json(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO)})

        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=False,
        ):
            backfill_disable_for_installed_providers("claude-code", tmp_path)

        env = json.loads(cj.read_text())["mcpServers"]["mureo"].get("env", {})
        assert env == {} or "MUREO_DISABLE_META_ADS" not in env

    def test_no_mureo_block_is_noop(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import (
            backfill_disable_for_installed_providers,
        )

        cj = _claude_json(tmp_path)
        _seed(cj, {"google-ads-official": _GA_OFFICIAL})
        before = cj.read_bytes()

        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=False,
        ):
            backfill_disable_for_installed_providers("claude-code", tmp_path)

        assert cj.read_bytes() == before  # never invents a mureo block

    def test_idempotent(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import (
            backfill_disable_for_installed_providers,
        )

        cj = _claude_json(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO), "google-ads-official": _GA_OFFICIAL})

        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=False,
        ):
            backfill_disable_for_installed_providers("claude-code", tmp_path)
            first = cj.read_bytes()
            backfill_disable_for_installed_providers("claude-code", tmp_path)

        assert cj.read_bytes() == first

    def test_never_raises(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import (
            backfill_disable_for_installed_providers,
        )

        # Corrupt registry must not propagate an exception.
        cj = _claude_json(tmp_path)
        cj.parent.mkdir(parents=True, exist_ok=True)
        cj.write_text("{ not json", encoding="utf-8")

        backfill_disable_for_installed_providers("claude-code", tmp_path)

    def test_desktop_backfills_google(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import (
            backfill_disable_for_installed_providers,
        )

        cfg = _desktop_cfg(tmp_path)
        _seed(cfg, {"mureo": dict(_MUREO), "google-ads-official": _GA_OFFICIAL})

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.providers.config_writer.is_hosted_provider_connected",
                return_value=False,
            ),
        ):
            backfill_disable_for_installed_providers(
                "claude-desktop", tmp_path
            )

        env = json.loads(cfg.read_text())["mcpServers"]["mureo"].get("env", {})
        assert env.get("MUREO_DISABLE_GOOGLE_ADS") == "1"


@pytest.mark.unit
def test_install_mureo_mcp_triggers_backfill(tmp_path: Path) -> None:
    """install_mureo_mcp (the path basic-setup and the dashboard both
    use) backfills disable-env after the mureo block is written."""
    from mureo.web import setup_actions

    cj = _claude_json(tmp_path)
    _seed(cj, {"google-ads-official": _GA_OFFICIAL})  # official added FIRST

    def _fake_install_mcp_config(scope: str = "global"):
        # Simulate basic-setup creating the mureo block.
        data = json.loads(cj.read_text())
        data["mcpServers"]["mureo"] = dict(_MUREO)
        cj.write_text(json.dumps(data), encoding="utf-8")
        return cj

    with (
        patch(
            "mureo.auth_setup.install_mcp_config",
            side_effect=_fake_install_mcp_config,
        ),
        patch(
            "mureo.web.setup_actions.mark_part_installed"
        ),
        patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=False,
        ),
    ):
        result = setup_actions.install_mureo_mcp(home=tmp_path)

    assert result.status in {"ok", "noop"}
    env = json.loads(cj.read_text())["mcpServers"]["mureo"].get("env", {})
    assert env.get("MUREO_DISABLE_GOOGLE_ADS") == "1"
