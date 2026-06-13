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

    def test_forces_cooked_mode_before_waiting(self, home_dir: Path) -> None:
        """#227: before blocking on the stop event, the wizard normalises
        the TTY to cooked mode so Ctrl+C delivers SIGINT (its stop signal)
        even if a prior step leaked raw mode — otherwise the operator is
        stranded with a dead terminal."""
        with (
            patch("mureo.web.server.webbrowser.open"),
            patch("mureo.web.server.force_cooked_mode") as mock_cooked,
        ):
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=0.2,
            )
        assert mock_cooked.call_count >= 1

    def test_reasserts_cooked_mode_during_wait(
        self, home_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#227 follow-up: a server-side action (a leaked menu in a
        third-party backend) can re-flip the TTY to raw *while* the main
        thread is already blocked on the stop event — a one-shot pre-wait
        fix cannot recover Ctrl+C then. The wait must re-assert cooked
        mode on every tick so a mid-session leak self-heals."""
        monkeypatch.setattr("mureo.web.server._COOKED_REASSERT_SECONDS", 0.05)
        with (
            patch("mureo.web.server.webbrowser.open"),
            patch("mureo.web.server.force_cooked_mode") as mock_cooked,
        ):
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=0.4,
            )
        # Initial assert plus one per ~0.05s tick over a 0.4s wait; allow
        # generous scheduling slack but require clearly more than one-shot.
        assert mock_cooked.call_count >= 4

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
class TestPreferredPortBind:
    """#241 — fixed default port with graceful EADDRINUSE fallback.

    ``serve(preferred_port=N)`` tries ``N`` first; on ``OSError`` it falls
    back to an ephemeral port and still serves. ``preferred_port=0`` (the
    default) keeps the pre-existing pure-ephemeral behaviour so every
    earlier test fixture is unchanged.
    """

    def test_default_serve_is_pure_ephemeral(self, home_dir: Path) -> None:
        """No preferred port → ephemeral bind, exactly as before."""
        wiz = ConfigureWizard(home=home_dir)
        thread = threading.Thread(target=wiz.serve, daemon=True)
        thread.start()
        try:
            wiz.wait_until_ready(timeout=5.0)
            assert 0 < wiz.port < 65536
        finally:
            wiz.shutdown()
            thread.join(timeout=2.0)

    def test_preferred_port_is_bound_when_free(self, home_dir: Path) -> None:
        """A free preferred port is honoured and reported by ``port``.

        A throwaway socket grabs an OS-assigned free port, releases it,
        and that number is fed as ``preferred_port`` — avoiding a
        hard-coded 7613 that could already be held on the test host.
        """
        import socket

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
        probe.close()

        wiz = ConfigureWizard(home=home_dir)
        thread = threading.Thread(
            target=wiz.serve, kwargs={"preferred_port": free_port}, daemon=True
        )
        thread.start()
        try:
            wiz.wait_until_ready(timeout=5.0)
            assert wiz.port == free_port
        finally:
            wiz.shutdown()
            thread.join(timeout=2.0)

    def test_eaddrinuse_falls_back_to_ephemeral(self, home_dir: Path) -> None:
        """A collision on the preferred port must never crash startup.

        The first ``_ConfigureServer`` construction (preferred port) is
        forced to raise ``OSError(EADDRINUSE)``; the second (ephemeral,
        port 0) succeeds. The server still becomes ready and serves on a
        real ephemeral port.
        """
        import errno

        from mureo.web import server as server_mod

        real_ctor = server_mod._ConfigureServer
        calls: list[int] = []

        def flaky_ctor(address: tuple[str, int], handler: object) -> object:
            calls.append(address[1])
            if len(calls) == 1:
                raise OSError(errno.EADDRINUSE, "address already in use")
            return real_ctor(address, handler)  # type: ignore[arg-type]

        wiz = ConfigureWizard(home=home_dir)
        with patch.object(server_mod, "_ConfigureServer", side_effect=flaky_ctor):
            thread = threading.Thread(
                target=wiz.serve, kwargs={"preferred_port": 59999}, daemon=True
            )
            thread.start()
            try:
                wiz.wait_until_ready(timeout=5.0)
                # First attempt used the preferred port, then fell back to 0.
                assert calls == [59999, 0]
                assert 0 < wiz.port < 65536
            finally:
                wiz.shutdown()
                thread.join(timeout=2.0)


@pytest.mark.unit
class TestStateFilePersistence:
    """#241 — the actually-bound port is persisted to
    ``<home>/.mureo/configure.json`` (0o600) so ``mureo open`` can find
    the live URL after an ephemeral fallback changed the port."""

    def test_state_file_written_under_injected_home(self, home_dir: Path) -> None:
        import json
        import os

        with patch("mureo.web.server.webbrowser.open"):
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=0.3,
            )
        state_path = home_dir / ".mureo" / "configure.json"
        assert state_path.exists(), "state file was not written"
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert set(data.keys()) == {"port", "pid", "url"}
        assert isinstance(data["port"], int) and 0 < data["port"] < 65536
        assert data["pid"] == os.getpid()
        assert data["url"] == f"http://127.0.0.1:{data['port']}/"

    @pytest.mark.skipif(
        not hasattr(__import__("os"), "fchmod"),
        reason="POSIX-only permission bits",
    )
    def test_state_file_is_owner_only(self, home_dir: Path) -> None:
        import stat

        with patch("mureo.web.server.webbrowser.open"):
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=0.3,
            )
        state_path = home_dir / ".mureo" / "configure.json"
        mode = stat.S_IMODE(state_path.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_state_write_failure_does_not_crash(self, home_dir: Path) -> None:
        """A best-effort state write that raises must not break configure."""
        with (
            patch("mureo.web.server.webbrowser.open"),
            patch(
                "mureo.web.server.write_state_file",
                side_effect=OSError("disk full"),
            ),
        ):
            # Must complete cleanly despite the write blowing up.
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=0.3,
            )


@pytest.mark.unit
class TestSingleInstanceReuse:
    """#241 — if the preferred port is already serving *our* instance,
    do NOT start a second server: just open the browser to it and
    return. A foreign occupant (ping fails) proceeds to normal start
    with ephemeral fallback."""

    def test_reuses_existing_instance_without_second_server(
        self, home_dir: Path
    ) -> None:
        """A probe-True preferred port → open browser, no server thread."""
        with (
            patch("mureo.web.server.probe_mureo_instance", return_value=True),
            patch("mureo.web.server.webbrowser.open") as mock_open,
            patch("mureo.web.server.ConfigureWizard") as mock_ctor,
        ):
            run_configure_wizard(
                home=home_dir,
                open_browser=True,
                preferred_port=7613,
                timeout_seconds=0.3,
            )
        # No wizard was constructed and no server spun up — pure reuse.
        mock_ctor.assert_not_called()
        mock_open.assert_called_once()
        url = mock_open.call_args.args[0]
        assert url == "http://127.0.0.1:7613/"

    def test_reuse_respects_no_browser(self, home_dir: Path) -> None:
        with (
            patch("mureo.web.server.probe_mureo_instance", return_value=True),
            patch("mureo.web.server.webbrowser.open") as mock_open,
            patch("mureo.web.server.ConfigureWizard") as mock_ctor,
        ):
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                preferred_port=7613,
                timeout_seconds=0.3,
            )
        mock_ctor.assert_not_called()
        mock_open.assert_not_called()

    def test_foreign_occupant_starts_normally(self, home_dir: Path) -> None:
        """probe-False (foreign / nothing there) → start a server as usual.

        With a real ephemeral fallback the bind never collides, so the
        wizard still becomes ready and the loop completes.
        """
        with (
            patch("mureo.web.server.probe_mureo_instance", return_value=False),
            patch("mureo.web.server.webbrowser.open") as mock_open,
        ):
            run_configure_wizard(
                home=home_dir,
                open_browser=True,
                preferred_port=7613,
                timeout_seconds=0.3,
            )
        # A real server ran and opened its own (possibly fallback) URL.
        mock_open.assert_called_once()
        assert mock_open.call_args.args[0].startswith("http://127.0.0.1:")


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
        # The handler returns "stopping" and the server thread sets the
        # stop event; sampling is_set() immediately races that thread
        # (flaky on CI). stop_event is a threading.Event — wait for it
        # with a bounded timeout instead.
        assert served_wizard.stop_event.wait(
            timeout=5.0
        ), "/api/shutdown did not trigger stop within 5s"


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
