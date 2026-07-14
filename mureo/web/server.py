"""Threading HTTP server that owns the configure-UI lifecycle.

``ConfigureWizard.serve()`` binds 127.0.0.1 on an ephemeral port and
serves every route in ``handlers.ConfigureHandler``. ``shutdown()``
also tears down any in-flight OAuth bridges so daemon threads do not
outlive the parent process.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.server
import logging
import signal
import socketserver
import threading
import time
import webbrowser
from importlib import resources
from pathlib import Path

from mureo.core.providers import discover_providers
from mureo.core.runtime_context import runtime_credentials_path
from mureo.core.terminal import force_cooked_mode, terminal_fd
from mureo.web.extensions import (
    ServeContext,
    WebExtensionEntry,
    discover_web_extensions,
    start_serve_lifecycles,
    stop_serve_lifecycles,
)
from mureo.web.handlers import ConfigureHandler
from mureo.web.host_paths import HostPaths, get_host_paths
from mureo.web.instance import probe_mureo_instance, write_state_file
from mureo.web.oauth_bridge import OAuthBridge
from mureo.web.session import ConfigureSession
from mureo.web.version_check import (
    start_periodic_update_check,
    stop_periodic_update_check,
)

logger = logging.getLogger(__name__)

# #241 — fixed default port for `mureo configure`. Chosen high in the
# IANA dynamic/private range (49152-65535-ish neighbourhood) and not
# registered to any common service, so a fresh machine almost always
# finds it free → a stable, bookmarkable ``http://127.0.0.1:7613/``.
# When it IS taken, the bind logic falls back to an ephemeral port (and
# single-instance reuse re-opens an already-running mureo), so the fixed
# value is a convenience default, never a hard requirement. 7613 spells
# "MURO" on a phone keypad (6-8-7-6 ≈ m-u-r-o) — a small mnemonic.
DEFAULT_CONFIGURE_PORT = 7613

# #227: how often the configure wait loop re-asserts cooked mode on the
# controlling TTY. A leaked raw mode mid-session is healed within one
# tick; the tcgetattr/tcsetattr pair costs microseconds, so a 1s cadence
# is imperceptible. Tests shrink this to exercise the loop quickly.
_COOKED_REASSERT_SECONDS = 1.0


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
        self._commands_path_override = commands_path
        self._host_paths: HostPaths = self._build_host_paths()
        self.oauth_bridge = OAuthBridge()
        # Discover third-party extensions once at wizard construction.
        # ``discover_web_extensions`` caches internally, so this call
        # plus every subsequent call within the same process re-uses
        # the same tuple — see :mod:`mureo.web.extensions`.
        self.extensions = discover_web_extensions()
        # #268 — also populate the *provider* registry here. Without it the
        # configure UI's Plugin-credentials section is always empty:
        # ``/api/credentials/plugins`` iterates ``default_registry``, which
        # only the MCP startup path otherwise discovers. Idempotent +
        # cached and fault-isolated — see ``_discover_providers_safely``.
        self._discover_providers_safely()

        self._server: _ConfigureServer | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @staticmethod
    def _discover_providers_safely() -> None:
        """Populate the provider registry, never raising on failure.

        Mirrors ``mcp.tool_provider.collect_plugin_tools``: ``discover``
        already isolates per-plugin faults, so the only way out here is a
        wholesale failure (e.g. the underlying ``entry_points`` call
        raising). Swallow it with a warning rather than aborting
        ``mureo configure`` — an empty Plugin-credentials section degrades
        gracefully; a crashed configure UI does not.

        ``BaseException`` (not just ``Exception``) is caught for parity
        with the MCP path: a plugin whose discovery hook raises
        ``SystemExit`` must not tear down configure startup. Only
        ``KeyboardInterrupt`` is honoured so Ctrl+C still works.
        """
        try:
            discover_providers()
        except KeyboardInterrupt:
            raise
        except BaseException:  # noqa: BLE001 — fault isolation boundary
            logger.warning(
                "provider discovery failed; the configure UI's plugin "
                "credentials section may be empty",
                exc_info=True,
            )

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
        """Switch the Claude host and recompute path resolution.

        No-op when ``host`` is already the session host: ``_resolve_host``
        relays the client's host on every host-carrying POST, and the
        rebuild is not free — the credentials override may resolve a
        runtime-context factory (#406).

        The rebuilt bundle is published in a single assignment AFTER every
        override has been applied. The configure server is threaded, and
        publishing the base bundle first opened a window in which
        concurrent requests read — or wrote — the unresolved host-default
        credentials path instead of the runtime-resolved one (#406).
        """
        if host == self.session.host:
            return
        self.session.set_host(host)
        self._host_paths = self._build_host_paths()

    def mark_oauth_complete(
        self, provider: str, *, success: bool, error: str | None = None
    ) -> None:
        """Update the session OAuth status (called by the bridge watcher)."""
        self.session.mark_oauth_complete(provider, success=success, error=error)

    def _bind_server(self, preferred_port: int) -> _ConfigureServer:
        """Bind ``_ConfigureServer`` with fixed-port + ephemeral fallback.

        ``preferred_port == 0`` is the pure-ephemeral path (existing
        behaviour). A non-zero preferred port is attempted first; on an
        :class:`OSError` (typically ``EADDRINUSE`` — the port is held by
        a foreign process) the bind degrades to an ephemeral port so a
        collision can never crash startup. The returned server is bound
        but not yet serving.
        """
        if preferred_port != 0:
            try:
                return _ConfigureServer(
                    (self._bind_host, preferred_port), ConfigureHandler
                )
            except OSError:
                logger.info(
                    "configure port %d busy; falling back to an ephemeral port",
                    preferred_port,
                )
        return _ConfigureServer((self._bind_host, 0), ConfigureHandler)

    def serve(self, preferred_port: int = 0) -> None:
        """Block and serve until ``shutdown()`` is called.

        ``preferred_port`` defaults to ``0`` (ephemeral) so existing
        callers and test fixtures are unchanged. A non-zero value asks
        for that fixed port with a graceful ephemeral fallback on
        collision — see :meth:`_bind_server`.
        """
        with self._bind_server(preferred_port) as server:
            server.wizard = self
            self._server = server
            self._persist_state()
            self._ready.set()
            try:
                server.serve_forever(poll_interval=0.1)
            finally:
                with self._lock:
                    self._server = None

    def _persist_state(self) -> None:
        """Best-effort: record the actually-bound port for ``mureo open``.

        Writes ``<home>/.mureo/configure.json`` honouring an injected
        ``home`` (tests) and falling back to ``Path.home()`` in
        production. A write failure is swallowed inside
        :func:`write_state_file` — persisting the port must never crash
        ``configure``.
        """
        home = self.home if self.home is not None else Path.home()
        # ``write_state_file`` is already best-effort, but guard the call
        # site too so an unexpected failure (e.g. a patched/raising
        # resolver) can never tear down the serving thread.
        with contextlib.suppress(Exception):
            write_state_file(home, port=self.port, url=self.home_url())

    def wait_until_ready(self, timeout: float = 5.0) -> None:
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError("configure wizard failed to bind within timeout")

    @property
    def stop_event(self) -> threading.Event:
        """Set when the CLI loop should stop serving and exit."""
        return self._stop

    def request_stop(self) -> None:
        """Ask ``run_configure_wizard`` to stop serving and return.

        Called from a SIGINT/SIGTERM handler or the ``/api/shutdown``
        route so the terminal is freed the moment the user finishes (or
        presses Ctrl+C) instead of blocking until ``timeout_seconds``.
        """
        self._stop.set()

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
    def _build_host_paths(self) -> HostPaths:
        """Resolve the FULL paths bundle for the current session host.

        Base resolution plus the commands-path pin plus the credentials
        override are all applied to a local value; the caller publishes
        the result in one assignment. The configure server is threaded,
        and mutating ``self._host_paths`` step-by-step opened a window in
        which concurrent requests observed the unresolved host-default
        credentials path (#406) — with a slow runtime-context factory the
        window spanned most of a dashboard page load.
        """
        paths = get_host_paths(self.session.host, home=self.home)
        if self._commands_path_override is not None:
            paths = dataclasses.replace(
                paths, commands_dir=self._commands_path_override
            )
        return self._with_credentials_override(paths)

    def _with_credentials_override(self, paths: HostPaths) -> HostPaths:
        """Align the configure-UI credentials path with the active
        RuntimeContext when running against the real home (#194).

        Every web write site (OAuth, env-var, provider install, plugin
        credentials, credential removal) and the status read share
        ``host_paths.credentials_path``. Resolving that one value from
        :func:`runtime_credentials_path` makes the whole web layer write
        to — and read from — the same location the MCP runtime reads
        from, so a ``mureo.runtime_context_factory`` that relocates the
        ``SecretStore`` is no longer bypassed on write.

        Gated on ``home is None`` (production). An explicitly-injected
        ``home`` means the caller — tests, or alternate-home tooling —
        wants a self-contained path bundle rooted at that home. The
        process-global runtime-context factory is resolved from entry
        points and its paths live OUTSIDE that sandbox (in dev/CI a
        third-party factory such as ``mureo-agency`` resolves against the
        operator's real ``~/.mureo``), so consulting it here would let a
        configure-UI write escape the injected home and clobber real
        credentials. Production ``mureo configure`` always runs with
        ``home=None`` and so still honors the factory. The factory's path
        is resolved by :func:`runtime_credentials_path`, unit-tested
        directly; this method only decides *whether* to apply it.

        Pure: returns a new bundle instead of mutating ``self._host_paths``
        so the caller can publish the fully-resolved result atomically
        (#406).
        """
        if self.home is not None:
            return paths
        resolved = runtime_credentials_path(paths.credentials_path)
        if resolved == paths.credentials_path:
            return paths
        return dataclasses.replace(paths, credentials_path=resolved)


def run_configure_wizard(
    *,
    home: Path | None = None,
    open_browser: bool = True,
    timeout_seconds: float | None = 600.0,
    commands_path: Path | None = None,
    preferred_port: int = 0,
    bind_host: str = "127.0.0.1",
) -> bool:
    """CLI entry point: spin the wizard, open the browser, wait.

    ``preferred_port`` (#241): when non-zero, the server tries that fixed
    port for a stable, bookmarkable URL. BEFORE starting, if the port is
    already serving *our* instance (verified via the ``/api/ping`` probe)
    we do NOT double-start — we just open the browser at the existing URL
    and return (single-instance reuse). A foreign occupant proceeds to a
    normal start where :meth:`ConfigureWizard.serve` falls back to an
    ephemeral port. ``0`` (the default) keeps pure-ephemeral behaviour.

    ``timeout_seconds`` (#241 Phase 2 — headless serve): the interactive
    default ``600.0`` auto-stops the wait loop after ten minutes. Passing
    ``None`` removes the cap entirely, so the server runs indefinitely
    until SIGTERM/SIGINT (or ``request_stop``) — the mode the auto-start
    service uses. ``None`` is the daemon signal throughout: with it the
    function skips opening a browser even on reuse (the service IS the
    instance) and serves headless.

    Returns ``True`` when it reused an already-running instance (no server
    was started), ``False`` when it started and ran its own server. The
    CLI uses this to print the right "already running" vs "stopped"
    message.
    """
    serve_forever = timeout_seconds is None
    if preferred_port != 0 and probe_mureo_instance(bind_host, preferred_port):
        # Single-instance reuse: a mureo configure server already answers
        # the fixed port. In headless serve mode (``serve_forever``) the
        # service IS the instance — if one already runs, just exit 0
        # quietly without touching a browser. Otherwise re-open it.
        url = f"http://{bind_host}:{preferred_port}/"
        logger.info("mureo configure already running at %s", url)
        if open_browser and not serve_forever:
            with contextlib.suppress(Exception):
                webbrowser.open(url)
        return True

    wizard = ConfigureWizard(home=home, commands_path=commands_path)
    thread = threading.Thread(
        target=wizard.serve, kwargs={"preferred_port": preferred_port}, daemon=True
    )
    thread.start()
    wizard.wait_until_ready()

    url = wizard.home_url()
    logger.info("mureo configure UI ready at %s", url)
    if open_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    # #244: only the always-on service (``serve_forever``) polls for updates
    # in the background. A short-lived interactive launch relies on the lazy
    # check that fires when the UI is opened, so it never spawns a poller.
    #
    # #249: the same guard governs extension lifecycle hooks — only the
    # always-on daemon lets extensions run background jobs. The server is
    # already serving (``wait_until_ready`` returned), so a hook may safely
    # call its own routes. ``started_extensions`` is filled only here and
    # consumed in ``finally`` for the symmetric stop.
    started_extensions: tuple[WebExtensionEntry, ...] = ()
    if serve_forever:
        start_periodic_update_check()
        # Hooks run synchronously here — before the SIGINT/SIGTERM
        # handlers below — and sequentially across extensions, so a
        # well-behaved hook returns promptly and offloads ongoing work to
        # its own thread (see the WebExtension docstring). Faults are
        # isolated inside ``start_serve_lifecycles``.
        serve_ctx = ServeContext(
            stop_event=wizard.stop_event,
            request_stop=wizard.request_stop,
            home=wizard.home if wizard.home is not None else Path.home(),
        )
        started_extensions = start_serve_lifecycles(wizard.extensions, serve_ctx)

    # Stop the moment the user finishes (UI POSTs /api/shutdown ->
    # request_stop), presses Ctrl+C (SIGINT) or the process is asked to
    # terminate (SIGTERM); fall back to timeout_seconds as a hard cap.
    # An explicit signal handler that sets the stop Event is reliable in
    # this multi-threaded process (the HTTP server runs on a daemon
    # thread) where bare KeyboardInterrupt delivery is not. Signal
    # handlers can only be registered from the main thread, so degrade
    # gracefully (e.g. under pytest) to a plain timed wait.
    prev_handlers: list[tuple[int, object]] = []

    def _on_signal(_signum: int, _frame: object) -> None:
        wizard.request_stop()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(ValueError, OSError):
                prev_handlers.append((sig, signal.signal(sig, _on_signal)))
        # #227: a prior step (a leaked arrow-key menu in a third-party
        # backend, or an earlier CLI command) can leave the TTY in raw mode
        # with ISIG off — Ctrl+C then never generates SIGINT, so _on_signal
        # never fires and the operator is stranded with a dead terminal
        # (no echo) for the full timeout. Force cooked mode before blocking
        # so Ctrl+C reliably delivers the stop signal, and RE-assert it on
        # every tick: a configure action handled on the HTTP thread can
        # run plugin code that re-flips the TTY to raw while we are
        # already blocked here, which a one-shot fix cannot recover from.
        # No-op on a non-TTY either way.
        fd = terminal_fd()
        force_cooked_mode(fd)
        # ``timeout_seconds is None`` (headless serve) means no deadline:
        # block until ``request_stop`` (SIGTERM/SIGINT) with no hard cap.
        # ``terminal_fd``/``force_cooked_mode`` are no-ops on a non-TTY, so
        # the daemon never depends on a terminal.
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        while not wizard.stop_event.is_set():
            if deadline is None:
                wait_for = _COOKED_REASSERT_SECONDS
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                wait_for = min(_COOKED_REASSERT_SECONDS, remaining)
            wizard.stop_event.wait(timeout=wait_for)
            force_cooked_mode(fd)
    except KeyboardInterrupt:
        # Belt-and-braces: if a KeyboardInterrupt still surfaces (e.g.
        # the handler could not be installed), treat it as a stop.
        pass
    finally:
        if serve_forever:
            # Reverse of startup: stop extension jobs first, then the
            # update poller. ``stop_serve_lifecycles`` stops only the
            # extensions whose ``on_serve_start`` actually ran.
            stop_serve_lifecycles(started_extensions)
            stop_periodic_update_check()
        for signum, prev in prev_handlers:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signum, prev)  # type: ignore[arg-type]
        wizard.shutdown()
        thread.join(timeout=2.0)
    return False
