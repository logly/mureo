"""``mureo configure --serve`` headless daemon mode (#241 Phase 2 — Part A).

The auto-start service runs configure HEADLESS: no browser, no auto-stop
timeout (it serves until SIGTERM/SIGINT), and it must not depend on a TTY
or print interactive prompts. These tests pin that:

* the ``--serve`` flag forces ``open_browser=False`` and ``timeout_seconds
  is None`` (no cap) on the way into ``run_configure_wizard``;
* the existing interactive path (no ``--serve``) is unchanged — browser
  opens, the 600s cap is passed through;
* at the wizard level, ``timeout_seconds=None`` blocks until ``request_stop``
  with no deadline (verified by stopping it and asserting prompt return).

The server is mocked (or driven via ``request_stop``) so no real port is
held and no daemon outlives the test.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path


def _app() -> Any:
    from mureo.cli.main import app

    return app


@pytest.fixture
def home_dir(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".mureo").mkdir()
    return home


@pytest.fixture(autouse=True)
def _no_update_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve mode (#244) starts a background update poller; disable it here so
    these serve tests never spawn a real ``pip`` subprocess / network call.
    Interval ``0`` is the documented off-switch."""

    monkeypatch.setenv("MUREO_UPDATE_CHECK_INTERVAL_SECONDS", "0")


@pytest.mark.unit
class TestConfigureServeFlagWiring:
    """``--serve`` maps to the headless contract at the CLI boundary."""

    def test_serve_passes_no_browser_and_no_timeout(self) -> None:
        """``--serve`` → ``open_browser=False`` and ``timeout_seconds=None``."""
        with patch(
            "mureo.cli.configure_cmd.run_configure_wizard", return_value=False
        ) as mock_run:
            result = CliRunner().invoke(_app(), ["configure", "--serve"])
        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["open_browser"] is False
        assert kwargs["timeout_seconds"] is None

    def test_serve_uses_default_port(self) -> None:
        """The daemon binds the fixed default port (7613) by default."""
        from mureo.web.server import DEFAULT_CONFIGURE_PORT

        with patch(
            "mureo.cli.configure_cmd.run_configure_wizard", return_value=False
        ) as mock_run:
            CliRunner().invoke(_app(), ["configure", "--serve"])
        assert mock_run.call_args.kwargs["preferred_port"] == DEFAULT_CONFIGURE_PORT

    def test_serve_honours_explicit_port(self) -> None:
        with patch(
            "mureo.cli.configure_cmd.run_configure_wizard", return_value=False
        ) as mock_run:
            CliRunner().invoke(_app(), ["configure", "--serve", "--port", "9999"])
        assert mock_run.call_args.kwargs["preferred_port"] == 9999


@pytest.mark.unit
class TestConfigureInteractiveUnchanged:
    """The default (no ``--serve``) path keeps the interactive contract."""

    def test_interactive_passes_browser_and_timeout_cap(self) -> None:
        with patch(
            "mureo.cli.configure_cmd.run_configure_wizard", return_value=False
        ) as mock_run:
            result = CliRunner().invoke(_app(), ["configure"])
        assert result.exit_code == 0, result.output
        kwargs = mock_run.call_args.kwargs
        assert kwargs["open_browser"] is True
        assert kwargs["timeout_seconds"] == 600.0

    def test_no_browser_flag_still_works(self) -> None:
        with patch(
            "mureo.cli.configure_cmd.run_configure_wizard", return_value=False
        ) as mock_run:
            CliRunner().invoke(_app(), ["configure", "--no-browser"])
        assert mock_run.call_args.kwargs["open_browser"] is False
        # Still the interactive cap, not None.
        assert mock_run.call_args.kwargs["timeout_seconds"] == 600.0


@pytest.mark.unit
class TestRunConfigureWizardNoTimeoutCap:
    """``timeout_seconds=None`` serves indefinitely until ``request_stop``."""

    def test_none_timeout_blocks_until_stop(self, home_dir: Path) -> None:
        """With no cap, the loop only returns when stopped — proving there
        is no deadline that would end it on its own."""
        captured: dict[str, Any] = {}
        from mureo.web.server import ConfigureWizard, run_configure_wizard

        real_ctor = ConfigureWizard

        def _spy(**kwargs: object) -> ConfigureWizard:
            wiz = real_ctor(**kwargs)  # type: ignore[arg-type]
            captured["wiz"] = wiz
            return wiz

        with (
            patch("mureo.web.server.webbrowser.open"),
            patch("mureo.web.server.ConfigureWizard", side_effect=_spy),
        ):
            thread = threading.Thread(
                target=run_configure_wizard,
                kwargs={
                    "home": home_dir,
                    "open_browser": False,
                    "timeout_seconds": None,
                },
                daemon=True,
            )
            thread.start()
            for _ in range(100):
                if "wiz" in captured:
                    break
                time.sleep(0.05)
            captured["wiz"].wait_until_ready(timeout=5.0)

            # Give it time that would have tripped any small deadline.
            time.sleep(0.5)
            assert thread.is_alive(), "no-cap loop returned without a stop"

            captured["wiz"].request_stop()
            thread.join(timeout=5.0)
        assert not thread.is_alive(), "request_stop did not end the no-cap loop"

    def test_serve_mode_does_not_open_browser(self, home_dir: Path) -> None:
        from mureo.web.server import ConfigureWizard, run_configure_wizard

        captured: dict[str, Any] = {}
        real_ctor = ConfigureWizard

        def _spy(**kwargs: object) -> ConfigureWizard:
            wiz = real_ctor(**kwargs)  # type: ignore[arg-type]
            captured["wiz"] = wiz
            return wiz

        with (
            patch("mureo.web.server.webbrowser.open") as mock_open,
            patch("mureo.web.server.ConfigureWizard", side_effect=_spy),
        ):
            thread = threading.Thread(
                target=run_configure_wizard,
                kwargs={
                    "home": home_dir,
                    "open_browser": False,
                    "timeout_seconds": None,
                },
                daemon=True,
            )
            thread.start()
            for _ in range(100):
                if "wiz" in captured:
                    break
                time.sleep(0.05)
            captured["wiz"].wait_until_ready(timeout=5.0)
            captured["wiz"].request_stop()
            thread.join(timeout=5.0)
        mock_open.assert_not_called()


@pytest.mark.unit
class TestServeModeSingleInstance:
    """In ``--serve`` mode, if our own instance already answers the port,
    exit quietly (the service IS the instance) — do not open a browser."""

    def test_serve_reuse_exits_quietly_without_browser(self, home_dir: Path) -> None:
        from mureo.web.server import run_configure_wizard

        with (
            patch("mureo.web.server.probe_mureo_instance", return_value=True),
            patch("mureo.web.server.webbrowser.open") as mock_open,
            patch("mureo.web.server.ConfigureWizard") as mock_ctor,
        ):
            reused = run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=None,
                preferred_port=7613,
            )
        assert reused is True
        mock_ctor.assert_not_called()
        # Headless reuse: no browser even is attempted.
        mock_open.assert_not_called()
