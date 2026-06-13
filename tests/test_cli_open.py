"""Tests for ``mureo open`` — #241 stable entry point to the dashboard.

``mureo open`` reads ``~/.mureo/configure.json``, and when the recorded
port still answers the ``/api/ping`` probe it opens the browser at the
recorded URL (or just prints it with ``--url-only``). When the state file
is missing or the server is dead it prints guidance to run
``mureo configure`` and exits non-zero.

The state-file home is injected via the ``MUREO_HOME`` env var so the
real ``~/.mureo`` is never touched; ``probe_mureo_instance`` and
``webbrowser.open`` are mocked so nothing hits the network or a browser.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path


def _runner() -> CliRunner:
    return CliRunner()


def _app() -> Any:
    from mureo.cli.main import app

    return app


def _write_state(home: Path, *, port: int, url: str) -> Path:
    """Write a ``configure.json`` state file under ``<home>/.mureo``."""
    mureo_dir = home / ".mureo"
    mureo_dir.mkdir(parents=True, exist_ok=True)
    state = mureo_dir / "configure.json"
    state.write_text(
        json.dumps({"port": port, "pid": 4321, "url": url}), encoding="utf-8"
    )
    return state


@pytest.mark.unit
class TestMureoOpenLiveServer:
    def test_opens_browser_when_server_is_alive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        _write_state(home, port=7613, url="http://127.0.0.1:7613/")
        monkeypatch.setenv("MUREO_HOME", str(home))
        with (
            patch("mureo.cli.open_cmd.probe_mureo_instance", return_value=True),
            patch("mureo.cli.open_cmd.webbrowser.open") as mock_open,
        ):
            result = _runner().invoke(_app(), ["open"])
        assert result.exit_code == 0, result.output
        mock_open.assert_called_once_with("http://127.0.0.1:7613/")
        assert "http://127.0.0.1:7613/" in result.output

    def test_url_only_prints_without_opening_browser(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        _write_state(home, port=7613, url="http://127.0.0.1:7613/")
        monkeypatch.setenv("MUREO_HOME", str(home))
        with (
            patch("mureo.cli.open_cmd.probe_mureo_instance", return_value=True),
            patch("mureo.cli.open_cmd.webbrowser.open") as mock_open,
        ):
            result = _runner().invoke(_app(), ["open", "--url-only"])
        assert result.exit_code == 0, result.output
        mock_open.assert_not_called()
        assert result.output.strip().endswith("http://127.0.0.1:7613/")


@pytest.mark.unit
class TestMureoOpenNoServer:
    def test_missing_state_file_exits_nonzero_with_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("MUREO_HOME", str(home))
        with (
            patch("mureo.cli.open_cmd.probe_mureo_instance", return_value=False),
            patch("mureo.cli.open_cmd.webbrowser.open") as mock_open,
        ):
            result = _runner().invoke(_app(), ["open"])
        assert result.exit_code != 0
        mock_open.assert_not_called()
        assert "mureo configure" in result.output

    def test_dead_server_exits_nonzero_with_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """State file exists but the port no longer answers — stale."""
        home = tmp_path / "home"
        _write_state(home, port=7613, url="http://127.0.0.1:7613/")
        monkeypatch.setenv("MUREO_HOME", str(home))
        with (
            patch("mureo.cli.open_cmd.probe_mureo_instance", return_value=False),
            patch("mureo.cli.open_cmd.webbrowser.open") as mock_open,
        ):
            result = _runner().invoke(_app(), ["open"])
        assert result.exit_code != 0
        mock_open.assert_not_called()
        assert "mureo configure" in result.output

    def test_browser_open_failure_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A headless host where ``webbrowser.open`` raises must still
        exit 0 (the URL was printed; the operator can copy it)."""
        home = tmp_path / "home"
        _write_state(home, port=7613, url="http://127.0.0.1:7613/")
        monkeypatch.setenv("MUREO_HOME", str(home))
        with (
            patch("mureo.cli.open_cmd.probe_mureo_instance", return_value=True),
            patch(
                "mureo.cli.open_cmd.webbrowser.open",
                side_effect=RuntimeError("no display"),
            ),
        ):
            result = _runner().invoke(_app(), ["open"])
        assert result.exit_code == 0, result.output
