"""Threading HTTP server that owns the configure-UI lifecycle.

``ConfigureWizard.serve()`` binds 127.0.0.1 on an ephemeral port and
serves every route in ``handlers.ConfigureHandler``. ``shutdown()``
also tears down any in-flight OAuth bridges so daemon threads do not
outlive the parent process.
"""

from __future__ import annotations

import contextlib
import http.server
import logging
import socketserver
import threading
import time
import webbrowser
from importlib import resources
from pathlib import Path

from mureo.web.handlers import ConfigureHandler
from mureo.web.host_paths import HostPaths, get_host_paths
from mureo.web.oauth_bridge import OAuthBridge
from mureo.web.session import ConfigureSession

logger = logging.getLogger(__name__)


def _resolve_static_dir() -> Path:
    """Locate the bundled ``mureo/_data/web`` directory.

    Mirrors ``cli.setup_cmd._get_data_path`` — tries ``importlib.resources``
    first (pip install) and falls back to the source-tree layout.
    """
    try:
        ref = resources.files("mureo") / "_data" / "web"
        with resources.as_file(ref) as p:
            if p.exists():
                return Path(p)
    except (TypeError, FileNotFoundError):
        pass
    pkg_root = Path(__file__).parent.parent
    candidate = pkg_root / "_data" / "web"
    return candidate


class _ConfigureServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded HTTP server with a back-reference to the wizard."""

    daemon_threads = True
    allow_reuse_address = True
    wizard: ConfigureWizard


class ConfigureWizard:
    """Configure-UI lifecycle owner."""

    def __init__(
        self,
        *,
        bind_host: str = "127.0.0.1",
        home: Path | None = None,
        static_dir: Path | None = None,
        commands_path: Path | None = None,
    ) -> None:
        self._bind_host = bind_host
        self.home = home
        self.static_dir = (
            static_dir if static_dir is not None else _resolve_static_dir()
        )
        self.session = ConfigureSession()
        self._host_paths: HostPaths = get_host_paths(self.session.host, home=home)
        self._commands_path_override = commands_path
        self._apply_commands_override()
        self.oauth_bridge = OAuthBridge()

        self._server: _ConfigureServer | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------
    @property
    def host_paths(self) -> HostPaths:
        return self._host_paths

    @property
    def commands_path(self) -> Path:
        return self._host_paths.commands_dir

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("serve() has not been called yet")
        return int(self._server.server_address[1])

    def home_url(self) -> str:
        return f"http://{self._bind_host}:{self.port}/"

    def set_host(self, host: str) -> None:
        """Switch the Claude host and recompute path resolution."""
        self.session.set_host(host)
        self._host_paths = get_host_paths(self.session.host, home=self.home)
        self._apply_commands_override()

    def mark_oauth_complete(
        self, provider: str, *, success: bool, error: str | None = None
    ) -> None:
        """Update the session OAuth status (called by the bridge watcher)."""
        self.session.mark_oauth_complete(provider, success=success, error=error)

    def serve(self) -> None:
        """Block and serve until ``shutdown()`` is called."""
        with _ConfigureServer((self._bind_host, 0), ConfigureHandler) as server:
            server.wizard = self
            self._server = server
            self._ready.set()
            try:
                server.serve_forever(poll_interval=0.1)
            finally:
                with self._lock:
                    self._server = None

    def wait_until_ready(self, timeout: float = 5.0) -> None:
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError("configure wizard failed to bind within timeout")

    def shutdown(self) -> None:
        with self._lock:
            server = self._server
        if server is not None:
            with contextlib.suppress(Exception):
                server.shutdown()
        with contextlib.suppress(Exception):
            self.oauth_bridge.cancel_all()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _apply_commands_override(self) -> None:
        """If the caller pinned a commands path, swap it into the bundle."""
        if self._commands_path_override is None:
            return
        self._host_paths = HostPaths(
            host=self._host_paths.host,
            settings_path=self._host_paths.settings_path,
            skills_dir=self._host_paths.skills_dir,
            commands_dir=self._commands_path_override,
            credentials_path=self._host_paths.credentials_path,
            mcp_registry_path=self._host_paths.mcp_registry_path,
        )


def run_configure_wizard(
    *,
    home: Path | None = None,
    open_browser: bool = True,
    timeout_seconds: float = 600.0,
    commands_path: Path | None = None,
) -> None:
    """CLI entry point: spin the wizard, open the browser, wait."""
    wizard = ConfigureWizard(home=home, commands_path=commands_path)
    thread = threading.Thread(target=wizard.serve, daemon=True)
    thread.start()
    wizard.wait_until_ready()

    url = wizard.home_url()
    logger.info("mureo configure UI ready at %s", url)
    if open_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(0.5)
    finally:
        wizard.shutdown()
        thread.join(timeout=2.0)
