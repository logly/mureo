"""`set_native_preference` — user-driven per-platform switch between
mureo-native and the official MCP, from the Web UI.

Guard (no-strand): switching a platform to "official preferred"
(MUREO_DISABLE_<P>=1) is only allowed when the official path is
actually in effect — pipx/npm provider registered, or (Meta) the
account-level connector verified Connected. Switching BACK to native
(unset) is always allowed. Idempotent; never invents a mureo block.

``@pytest.mark.unit``; FS via ``tmp_path``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_GA_OFFICIAL = {"type": "stdio", "command": "pipx", "args": ["run", "x"]}
_MUREO = {"command": "python", "args": ["-m", "mureo.mcp"]}


def _cj(tmp: Path) -> Path:
    return tmp / ".claude.json"


def _seed(path: Path, servers: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def _env(path: Path) -> dict:
    return json.loads(path.read_text())["mcpServers"]["mureo"].get("env", {})


@pytest.mark.unit
class TestSetNativePreference:
    def test_invalid_platform(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import set_native_preference

        r = set_native_preference("search_console", True, home=tmp_path)
        assert r.status == "error"
        assert r.detail == "invalid_platform"

    def test_prefer_official_blocked_when_provider_absent(
        self, tmp_path: Path
    ) -> None:
        from mureo.web.setup_actions import set_native_preference

        cj = _cj(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO)})  # google-ads-official NOT registered
        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=False,
        ):
            r = set_native_preference("google_ads", True, home=tmp_path)
        assert r.status == "error"
        assert r.detail == "provider_not_installed"
        assert "MUREO_DISABLE_GOOGLE_ADS" not in _env(cj)

    def test_prefer_official_allowed_when_provider_registered(
        self, tmp_path: Path
    ) -> None:
        from mureo.web.setup_actions import set_native_preference

        cj = _cj(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO), "google-ads-official": _GA_OFFICIAL})
        r = set_native_preference("google_ads", True, home=tmp_path)
        assert r.status == "ok"
        assert _env(cj)["MUREO_DISABLE_GOOGLE_ADS"] == "1"

    def test_prefer_official_meta_blocked_until_connector_connected(
        self, tmp_path: Path
    ) -> None:
        from mureo.web.setup_actions import set_native_preference

        cj = _cj(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO)})
        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=False,
        ):
            r = set_native_preference("meta_ads", True, home=tmp_path)
        assert r.status == "error"
        assert r.detail == "connector_not_connected"

    def test_prefer_official_meta_ok_when_connector_connected(
        self, tmp_path: Path
    ) -> None:
        from mureo.web.setup_actions import set_native_preference

        cj = _cj(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO)})
        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=True,
        ):
            r = set_native_preference("meta_ads", True, home=tmp_path)
        assert r.status == "ok"
        assert _env(cj)["MUREO_DISABLE_META_ADS"] == "1"

    def test_switch_back_to_native_always_allowed(
        self, tmp_path: Path
    ) -> None:
        from mureo.web.setup_actions import set_native_preference

        cj = _cj(tmp_path)
        _seed(
            cj,
            {
                "mureo": {
                    **_MUREO,
                    "env": {"MUREO_DISABLE_GOOGLE_ADS": "1"},
                }
            },
        )
        # No official provider present, connector not connected — still
        # allowed to restore native (un-strand path).
        with patch(
            "mureo.providers.config_writer.is_hosted_provider_connected",
            return_value=False,
        ):
            r = set_native_preference("google_ads", False, home=tmp_path)
        assert r.status == "ok"
        assert "MUREO_DISABLE_GOOGLE_ADS" not in _env(cj)

    def test_back_to_native_noop_when_already_native(
        self, tmp_path: Path
    ) -> None:
        from mureo.web.setup_actions import set_native_preference

        cj = _cj(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO)})
        r = set_native_preference("google_ads", False, home=tmp_path)
        assert r.status == "noop"

    def test_prefer_official_no_mureo_block(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import set_native_preference

        cj = _cj(tmp_path)
        _seed(cj, {"google-ads-official": _GA_OFFICIAL})  # no mureo block
        r = set_native_preference("google_ads", True, home=tmp_path)
        assert r.status == "error"
        assert r.detail == "no_mureo_block"

    def test_idempotent_prefer_official(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import set_native_preference

        cj = _cj(tmp_path)
        _seed(cj, {"mureo": dict(_MUREO), "google-ads-official": _GA_OFFICIAL})
        set_native_preference("google_ads", True, home=tmp_path)
        r2 = set_native_preference("google_ads", True, home=tmp_path)
        assert r2.status == "noop"
        assert _env(cj)["MUREO_DISABLE_GOOGLE_ADS"] == "1"


# Handler-route dispatch + 400 coverage lives in
# tests/test_web_handlers.py::TestPostProviders (real HTTP path,
# asserts host/home propagation and the blank-platform 400).
