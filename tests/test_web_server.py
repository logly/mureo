"""Lifecycle for ``mureo.web.server.ConfigureWizard``.

The configure-UI server must bind 127.0.0.1 on an ephemeral port, expose
its session / host_paths / static_dir to handlers, allow a clean
``shutdown()``, and run the CLI entry point (``run_configure_wizard``)
to completion when ``open_browser=False`` and ``timeout_seconds`` is
small. ``webbrowser.open`` is mocked to keep the test process headless.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mureo.web.host_paths import HostPaths
from mureo.web.server import ConfigureWizard, run_configure_wizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def home_dir(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".mureo").mkdir()
    return home


@pytest.fixture
def served_wizard(home_dir: Path) -> Iterator[ConfigureWizard]:
    wiz = ConfigureWizard(home=home_dir)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


@pytest.mark.unit
class TestConfigureWizardInit:
    def test_session_is_created(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        assert wiz.session.host == "claude-code"
        assert wiz.session.locale == "en"
        assert wiz.session.csrf_token

    def test_host_paths_is_populated_for_default_host(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        assert isinstance(wiz.host_paths, HostPaths)
        assert wiz.host_paths.host == "claude-code"
        assert wiz.host_paths.commands_dir == home_dir / ".claude" / "commands"

    def test_static_dir_default_resolves(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        assert wiz.static_dir.is_dir()

    def test_static_dir_override_respected(
        self, home_dir: Path, tmp_path: Path
    ) -> None:
        custom = tmp_path / "static"
        custom.mkdir()
        wiz = ConfigureWizard(home=home_dir, static_dir=custom)
        assert wiz.static_dir == custom

    def test_commands_path_override_replaces_default(
        self, home_dir: Path, tmp_path: Path
    ) -> None:
        override = tmp_path / "alt_cmds"
        override.mkdir()
        wiz = ConfigureWizard(home=home_dir, commands_path=override)
        assert wiz.commands_path == override
        assert wiz.host_paths.commands_dir == override


@pytest.mark.unit
class TestConfigureWizardPortAndUrl:
    def test_port_raises_before_serve(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        with pytest.raises(RuntimeError, match="serve"):
            _ = wiz.port

    def test_port_is_set_after_serve(self, served_wizard: ConfigureWizard) -> None:
        assert served_wizard.port > 0
        assert served_wizard.port < 65536

    def test_home_url_uses_loopback(self, served_wizard: ConfigureWizard) -> None:
        url = served_wizard.home_url()
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/")
        assert str(served_wizard.port) in url


@pytest.mark.unit
class TestConfigureWizardSetHost:
    def test_set_host_updates_session(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        wiz.set_host("claude-desktop")
        assert wiz.session.host == "claude-desktop"

    def test_set_host_recomputes_host_paths(self, home_dir: Path) -> None:
        with patch("mureo.web.host_paths.platform.system", return_value="Darwin"):
            wiz = ConfigureWizard(home=home_dir)
            wiz.set_host("claude-desktop")
        expected = (
            home_dir
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
        assert wiz.host_paths.settings_path == expected

    def test_set_host_keeps_commands_override(
        self, home_dir: Path, tmp_path: Path
    ) -> None:
        override = tmp_path / "cmds"
        override.mkdir()
        wiz = ConfigureWizard(home=home_dir, commands_path=override)
        wiz.set_host("claude-desktop")
        assert wiz.host_paths.commands_dir == override

    def test_set_host_ignores_unknown_host(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        before = wiz.session.host
        wiz.set_host("vscode")
        assert wiz.session.host == before


@pytest.mark.unit
class TestConfigureWizardMarkOauthComplete:
    def test_success_updates_session_state(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        wiz.mark_oauth_complete("google", success=True)
        assert wiz.session.get_oauth_status("google")["success"] is True

    def test_failure_captures_error_string(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        wiz.mark_oauth_complete("meta", success=False, error="boom")
        assert wiz.session.get_oauth_status("meta")["error"] == "boom"


@pytest.mark.unit
class TestConfigureWizardServeAndShutdown:
    def test_serve_binds_and_ready_event_fires(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        thread = threading.Thread(target=wiz.serve, daemon=True)
        thread.start()
        try:
            wiz.wait_until_ready(timeout=5.0)
            assert wiz.port > 0
        finally:
            wiz.shutdown()
            thread.join(timeout=2.0)
        assert not thread.is_alive()

    def test_wait_until_ready_timeout_raises(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        with pytest.raises(TimeoutError):
            wiz.wait_until_ready(timeout=0.01)

    def test_shutdown_is_idempotent(self, served_wizard: ConfigureWizard) -> None:
        served_wizard.shutdown()
        served_wizard.shutdown()

    def test_shutdown_cancels_oauth_bridges(
        self, served_wizard: ConfigureWizard
    ) -> None:
        with patch.object(served_wizard.oauth_bridge, "cancel_all") as mock_cancel:
            served_wizard.shutdown()
        mock_cancel.assert_called_once()


@pytest.mark.unit
class TestRunConfigureWizardCli:
    def test_completes_after_timeout(self, home_dir: Path) -> None:
        """The CLI helper must return cleanly when timeout_seconds is
        small. ``webbrowser.open`` is mocked so no browser launches."""
        with patch("mureo.web.server.webbrowser.open") as mock_open:
            start = time.monotonic()
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=0.5,
            )
            elapsed = time.monotonic() - start
        mock_open.assert_not_called()
        assert elapsed < 5.0

    def test_opens_browser_when_requested(self, home_dir: Path) -> None:
        with patch("mureo.web.server.webbrowser.open") as mock_open:
            run_configure_wizard(
                home=home_dir,
                open_browser=True,
                timeout_seconds=0.5,
            )
        mock_open.assert_called_once()
        url = mock_open.call_args.args[0]
        assert url.startswith("http://127.0.0.1:")

    def test_browser_open_failure_is_swallowed(self, home_dir: Path) -> None:
        with patch(
            "mureo.web.server.webbrowser.open",
            side_effect=RuntimeError("no display"),
        ):
            run_configure_wizard(
                home=home_dir,
                open_browser=True,
                timeout_seconds=0.5,
            )

    def test_commands_path_override_propagated(
        self, home_dir: Path, tmp_path: Path
    ) -> None:
        override = tmp_path / "cmds"
        override.mkdir()
        captured: dict[str, ConfigureWizard] = {}
        real_ctor = ConfigureWizard

        def _spy(**kwargs: object) -> ConfigureWizard:
            wiz = real_ctor(**kwargs)  # type: ignore[arg-type]
            captured["wiz"] = wiz
            return wiz

        with (
            patch("mureo.web.server.webbrowser.open"),
            patch("mureo.web.server.ConfigureWizard", side_effect=_spy),
        ):
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=0.3,
                commands_path=override,
            )
        assert captured["wiz"].commands_path == override


@pytest.mark.unit
class TestStopLifecycle:
    """``request_stop`` / ``/api/shutdown`` free the terminal instead of
    blocking until ``--timeout-seconds`` (regression: closing the
    browser left the CLI hung for up to 10 minutes; Ctrl+C unreliable)."""

    def test_request_stop_sets_event(self, home_dir: Path) -> None:
        wiz = ConfigureWizard(home=home_dir)
        assert not wiz.stop_event.is_set()
        wiz.request_stop()
        assert wiz.stop_event.is_set()

    def test_run_configure_wizard_returns_immediately_when_stopped(
        self, home_dir: Path
    ) -> None:
        """With a 60s cap, ``request_stop()`` must end the CLI loop in
        well under a second — not wait out the timeout."""
        captured: dict[str, ConfigureWizard] = {}
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
                    "timeout_seconds": 60.0,
                },
                daemon=True,
            )
            thread.start()
            for _ in range(50):
                if "wiz" in captured:
                    break
                time.sleep(0.05)
            captured["wiz"].wait_until_ready(timeout=5.0)

            start = time.monotonic()
            captured["wiz"].request_stop()
            thread.join(timeout=5.0)
            elapsed = time.monotonic() - start

        assert not thread.is_alive(), "CLI loop did not stop on request_stop"
        assert elapsed < 3.0, f"stop took {elapsed:.2f}s (should be ~instant)"

    def test_api_shutdown_route_triggers_stop(
        self, served_wizard: ConfigureWizard
    ) -> None:
        import json
        import urllib.request

        base = f"http://127.0.0.1:{served_wizard.port}"
        token = served_wizard.session.csrf_token
        req = urllib.request.Request(
            f"{base}/api/shutdown",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "X-CSRF-Token": token},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        assert body == {"status": "stopping"}
        assert served_wizard.stop_event.is_set()


@pytest.mark.unit
class TestResolveStaticDir:
    def test_falls_back_when_resources_raises(self, home_dir: Path) -> None:
        """Force the importlib.resources path to fail and verify the
        fallback path is used."""
        with patch(
            "mureo.web.server.resources.files",
            side_effect=FileNotFoundError("nope"),
        ):
            wiz = ConfigureWizard(home=home_dir)
            assert wiz.static_dir.parts[-2:] == ("_data", "web")


@pytest.mark.unit
class TestSecurityBindLoopbackOnly:
    def test_server_binds_to_loopback_only(
        self, served_wizard: ConfigureWizard
    ) -> None:
        """The server must be bound to 127.0.0.1, never 0.0.0.0 — that
        would expose the configure UI to the LAN."""
        assert served_wizard._bind_host == "127.0.0.1"

    def test_home_url_never_contains_zero_host(
        self, served_wizard: ConfigureWizard
    ) -> None:
        url = served_wizard.home_url()
        assert "0.0.0.0" not in url
        assert url.startswith("http://127.0.0.1:")
