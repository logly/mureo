"""HTTP route dispatch for the configure-UI server.

A thin layer over ``http.server.BaseHTTPRequestHandler`` that delegates
each route to one of the small helper modules (status_collector,
setup_actions, env_var_writer, oauth_bridge, legacy_commands). All
POST routes are gated by the Host-header check + CSRF token.

Routes
------
``GET  /``                       → ``app.html``
``GET  /static/<file>``          → bundled ``mureo/_data/web/<file>``
``GET  /api/status``             → status_collector snapshot
``GET  /api/csrf``               → ``{"csrf_token": "..."}``
``GET  /api/about``              → mureo + extension package versions
``GET  /api/updates``            → available mureo/plugin updates (pip)
``POST /api/upgrade``            → upgrade mureo + plugins (server-derived)
``GET  /api/oauth/<p>/status``   → per-provider OAuth flags
``POST /api/locale``             → set session locale (en|ja)
``POST /api/host``               → set Claude application host
``POST /api/setup/basic``        → run mureo_mcp / hook / skills
``POST /api/providers/install``  → install one official MCP
``POST /api/providers/confirm``  → disable native once hosted connector works
``POST /api/providers/hosted-status`` → hosted connectors' Connected state
``POST /api/providers/native-toggle`` → switch a platform native↔official
``POST /api/providers/remove``   → remove one official MCP entry
``GET  /api/advisors``           → list external advisor MCP entries
``POST /api/advisors/add``       → add one external advisor MCP entry
``POST /api/advisors/remove``    → remove one external advisor MCP entry
``POST /api/credentials/env-var``→ write one env var into credentials
``GET  /api/credentials/plugins``→ list plugins declaring per-account fields
``POST /api/credentials/plugins/save`` → save one plugin's credentials
``POST /api/oauth/<p>/start``    → spawn WebAuthWizard, return consent URL
``POST /api/legacy/cleanup``     → delete legacy slash commands
``GET  /api/demo/scenarios``     → list registered demo scenarios
``POST /api/demo/init``          → scaffold a demo workspace
``GET  /api/byod/status``        → per-platform byod/live status
``GET  /api/reports/clients``    → selectable reporting clients (Agency seam)
``GET  /api/reports/summary``    → read-only STATE.json report summary
``POST /api/byod/import``        → import a Sheet bundle XLSX
``POST /api/byod/remove``        → drop one platform's BYOD data
``POST /api/byod/clear``         → wipe all BYOD data
``GET  /api/extensions``         → list registered web extensions
``GET  /api/ext/<n>/<sub>``      → dispatch to extension GET handler
``POST /api/ext/<n>/<sub>``      → dispatch to extension POST handler
``GET  /static/ext/<n>/<file>``  → serve extension-shipped static asset
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any

from mureo.core.providers import default_registry, get_account_oauth_config
from mureo.core.runtime_context import (
    runtime_multi_account_auth,
    runtime_ui_plugin_credential_fields,
)
from mureo.core.secret_store import FilesystemSecretStore, SecretStoreError
from mureo.oauth_authcode import parse_loopback_callback_url
from mureo.web._helpers import (
    compare_csrf,
    host_header_ok,
    parse_json_body,
    read_body,
    send_bytes,
    send_error_json,
    send_json,
)
from mureo.web.about import collect_about_info
from mureo.web.advisors import (
    AdvisorActionError,
    add_advisor,
    list_advisors,
    remove_advisor,
)
from mureo.web.byod_actions import (
    byod_clear,
    byod_import,
    byod_remove,
    byod_status,
)
from mureo.web.creative_gallery import list_creative_runs, resolve_gallery_image
from mureo.web.demo_actions import init_demo, list_demo_scenarios
from mureo.web.env_var_writer import (
    is_allowed_env_var,
    remove_credential_section,
    write_credential_env_var,
)
from mureo.web.extensions import (
    FILENAME_PATTERN,
    NAME_PATTERN,
    SUBPATH_PATTERN,
)
from mureo.web.instance import PING_APP_NAME
from mureo.web.legacy_commands import remove_legacy_commands
from mureo.web.native_picker import pick_directory, pick_file
from mureo.web.plugin_credentials import (
    AccountListingError,
    InvalidFieldValueError,
    OAuthAccountsNotSupportedError,
    OAuthNotAuthenticatedError,
    RequiredFieldMissingError,
    UnknownProviderError,
    list_oauth_accounts,
    list_plugin_credential_fields,
    multi_account_picker_scope,
    save_plugin_credentials,
)
from mureo.web.reports import build_report_summary, list_report_clients
from mureo.web.session import OAUTH_PROVIDERS, SUPPORTED_HOSTS
from mureo.web.setup_actions import (
    clear_all_setup,
    confirm_hosted_provider,
    hosted_provider_status,
    install_auth_hook,
    install_basic_setup,
    install_provider,
    install_workflow_skills,
    remove_auth_hook,
    remove_mureo_mcp,
    remove_provider,
    remove_workflow_skills,
    set_native_preference,
)
from mureo.web.status_collector import collect_status
from mureo.web.upgrade_action import run_upgrade_all
from mureo.web.version_check import get_update_status, request_update_refresh

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator, Mapping
    from pathlib import Path

    from mureo.web.extensions import (
        RouteContribution,
        StaticAsset,
        WebExtensionEntry,
    )
    from mureo.web.server import ConfigureWizard

logger = logging.getLogger(__name__)

# After a successful self-upgrade the configure daemon, when it runs under an
# auto-start supervisor (launchd ``KeepAlive`` / systemd ``Restart=always``),
# exits so the supervisor relaunches it on the NEW code. The grace delay lets
# the HTTP response reach the browser (which then polls ``/api/ping`` and
# reloads); the ``os._exit`` backstop guarantees the process actually
# terminates even if a stray non-daemon thread would otherwise keep it alive.
_RESTART_RESPONSE_GRACE_SECONDS = 1.5
_RESTART_HARD_EXIT_SECONDS = 3.0


def _restart_runner(wizard: ConfigureWizard) -> None:
    """Graceful stop → hard-exit backstop, run on a daemon thread.

    Extracted (not a closure) so it is unit-testable with ``time.sleep`` /
    ``os._exit`` patched. ``request_stop`` is best-effort: even if it raises,
    the ``os._exit`` backstop still fires so the supervisor relaunches us.
    """
    time.sleep(_RESTART_RESPONSE_GRACE_SECONDS)
    with contextlib.suppress(Exception):
        wizard.request_stop()
    time.sleep(_RESTART_HARD_EXIT_SECONDS)
    logger.info("exiting for supervisor-managed restart after self-upgrade")
    os._exit(0)


def _request_service_restart(wizard: ConfigureWizard) -> None:
    """Schedule a graceful exit-to-restart of the supervised daemon.

    Spawns a daemon thread so the caller's request handler returns first
    (the ``/api/upgrade`` response must flush before the server goes down).
    Only call this when running under a supervisor — see
    :func:`mureo.web.service.is_managed_service`.
    """
    threading.Thread(
        target=_restart_runner,
        args=(wizard,),
        name="mureo-service-restart",
        daemon=True,
    ).start()


def _reexec_runner() -> None:
    """Replace the process image with a fresh copy of the same command.

    The restart path for an UNSUPERVISED ``mureo configure`` (no launchd /
    systemd to relaunch a self-exit): ``os.execv`` re-runs the command in
    place, picking up new code and config.

    CRITICAL — this deliberately does NOT call ``wizard.request_stop()``.
    Setting the stop event unblocks the main thread's serve loop
    (``run_configure_wizard``), which then returns and finalizes the
    interpreter — and interpreter shutdown ABANDONS this daemon thread before
    ``os.execv`` can run, so the server would exit with no restart (the exact
    opposite of the intent). By leaving the stop event unset the main thread
    stays blocked and the process stays alive until ``os.execv`` replaces the
    whole image atomically — which releases the close-on-exec listen socket on
    its own; the server's ``allow_reuse_address`` lets the re-exec'd process
    rebind the fixed port. Only the response-flush grace is needed first — no
    stop signal, no second sleep. Extracted (not a closure) so it is
    unit-testable with ``time.sleep`` / ``os.execv`` patched.

    The command is rebuilt as ``<python> -m mureo <original args>`` (works for
    both the ``mureo`` entry point and ``python -m mureo``) rather than
    replaying a console-script shim path that may not be re-executable. NOTE:
    on Windows ``os.execv`` is emulated as spawn-new-process + exit-current
    (new PID, no true in-place replace); the Windows service (which is NOT
    supervisor-managed — see ``_post_restart``) relies on that best-effort
    path.
    """
    time.sleep(_RESTART_RESPONSE_GRACE_SECONDS)
    logger.info("re-exec for interactive (unsupervised) configure restart")
    os.execv(sys.executable, [sys.executable, "-m", "mureo", *sys.argv[1:]])


def _request_interactive_reexec() -> None:
    """Schedule an in-place self-reexec of an unsupervised configure server.

    Spawns a daemon thread so the ``/api/restart`` response flushes before
    the process image is replaced. Only call this when NOT running under a
    supervisor — see :func:`mureo.web.service.is_managed_service`.
    """
    threading.Thread(
        target=_reexec_runner,
        name="mureo-interactive-reexec",
        daemon=True,
    ).start()


# #241 — the installed mureo version reported by ``GET /api/ping``. Read
# once at import from the package's ``__version__`` (no ``importlib.metadata``
# round-trip per request); the ping body carries only this string + the app
# name, nothing environment-specific.
try:
    from mureo import __version__ as mureo_version
except Exception:  # noqa: BLE001 — never let a version lookup break import
    mureo_version = "unknown"


_STATIC_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

# Filenames inside ``mureo/_data/web/`` that may be served by GET /static/<name>.
_STATIC_ALLOWLIST: tuple[str, ...] = (
    "app.html",
    "app.css",
    "app.js",
    "landing.js",
    "wizard.js",
    "auth_wizards.js",
    "dashboard.js",
    "extensions.js",
    "i18n.json",
    "logo.png",
    "logo-dark.png",
)

# Regex on path: /api/oauth/<provider>/status or /start
_OAUTH_PROVIDER_RE = re.compile(
    r"^/api/oauth/(?P<provider>[a-z_]+)/(?P<verb>status|start)$"
)

# #201 — generic plugin authorization-code OAuth. Separate from the
# built-in ``/api/oauth/...`` path so the Google/Meta onboarding flow is
# untouched. ``provider`` is a snake_case registry name.
_PLUGIN_OAUTH_RE = re.compile(
    r"^/api/credentials/plugins/(?P<provider>[a-z0-9_]+)/oauth/(?P<verb>start|status)$"
)

# #336 — post-auth account picker. A GET lists the accounts the provider's
# obtained OAuth token can reach so the dashboard renders a radio picker for
# the declared ``accounts_field`` instead of a free-text input.
_PLUGIN_ACCOUNTS_RE = re.compile(
    r"^/api/credentials/plugins/(?P<provider>[a-z0-9_]+)/accounts$"
)

# #216 — the form key the dashboard's Authenticate card submits carrying
# the operator-registered loopback callback URL. Non-secret, so it is also
# persisted (for re-auth pre-fill). The dashboard input key must match.
_OAUTH_CALLBACK_URL_KEY = "oauth_callback_url"

# Third-party web-extension dispatch (see ``mureo.web.extensions``).
# Path components reuse the bare patterns exported by
# ``mureo.web.extensions`` so the registration-side validation and the
# dispatch-side URL match share a single source of truth — a future
# tweak to ``NAME_PATTERN`` etc. flows through both layers in lockstep.
_EXTENSION_API_RE = re.compile(
    rf"^/api/ext/(?P<name>{NAME_PATTERN})(?P<subpath>{SUBPATH_PATTERN})$"
)
_EXTENSION_STATIC_RE = re.compile(
    rf"^/static/ext/(?P<name>{NAME_PATTERN})/(?P<filename>{FILENAME_PATTERN})$"
)


def _find_extension(
    extensions: tuple[WebExtensionEntry, ...], name: str
) -> WebExtensionEntry | None:
    """Linear scan; the registered set is small (single digits typical)."""
    for entry in extensions:
        if entry.name == name:
            return entry
    return None


def _find_extension_route(
    entry: WebExtensionEntry, method: str, subpath: str
) -> RouteContribution | None:
    for route in entry.routes:
        if route.method == method and route.subpath == subpath:
            return route
    return None


def _iter_extension_assets(entry: WebExtensionEntry) -> Iterator[StaticAsset]:
    """Yield every static asset the extension ships — view assets first,
    then dashboard-card assets, in declaration order."""
    if entry.view is not None:
        yield from entry.view.scripts
        yield from entry.view.styles
    for card in entry.dashboard_cards:
        yield from card.scripts
        yield from card.styles


def _find_extension_static(
    entry: WebExtensionEntry, filename: str
) -> StaticAsset | None:
    for asset in _iter_extension_assets(entry):
        if asset.filename == filename:
            return asset
    return None


def _flatten_query(path: str) -> dict[str, str]:
    """Parse a URL's query string into ``{key: first_value}``.

    Multi-value handlers can still reach the raw query via
    ``request.path`` — this helper is the lightweight default the
    extension API contract documents.
    """
    if "?" not in path:
        return {}
    parsed = urllib.parse.parse_qs(path.split("?", 1)[1], keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}


def _resolve_static_body(wizard: ConfigureWizard, filename: str) -> bytes | None:
    """Load a static file from the bundled ``_data/web`` dir."""
    if filename not in _STATIC_ALLOWLIST:
        return None
    path = wizard.static_dir / filename
    if not path.exists() or not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _static_content_type(filename: str) -> str:
    for suffix, ct in _STATIC_CONTENT_TYPES.items():
        if filename.endswith(suffix):
            return ct
    return "application/octet-stream"


class ConfigureHandler(BaseHTTPRequestHandler):
    """Per-request handler for the configure-UI server."""

    wizard: ConfigureWizard

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def setup(self) -> None:
        """Alias ``server.wizard`` onto the handler before request dispatch.

        ``ConfigureWizard.serve()`` assigns the wizard to the underlying
        ``HTTPServer`` (``server.wizard = self``) but the handler code
        below references ``self.wizard`` directly. Hoisting the alias
        in ``setup()`` — which BaseHTTPRequestHandler invokes before
        ``handle()`` — ensures ``self.wizard`` is bound for the full
        request lifecycle.
        """
        self.wizard = self.server.wizard  # type: ignore[attr-defined]
        super().setup()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        logger.debug(fmt, *args)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/index.html":
            self._serve_app_html()
            return
        # Extension static assets are matched BEFORE the generic
        # ``/static/`` branch so the same prefix can route into both
        # the built-in allowlist and the extension-owned asset set.
        ext_static_match = _EXTENSION_STATIC_RE.match(path)
        if ext_static_match is not None:
            self._serve_extension_static(
                ext_static_match.group("name"),
                ext_static_match.group("filename"),
            )
            return
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
            return
        if path == "/api/status":
            self._serve_status()
            return
        if path == "/api/csrf":
            self._serve_csrf()
            return
        if path == "/api/about":
            # #229 — version/package info for the About tab. Read-only,
            # no secrets, so the Host-header gate alone suffices (same
            # as every other GET JSON endpoint).
            send_json(self, collect_about_info())
            return
        if path == "/api/ping":
            # #241 — single-instance probe. A second `mureo configure`
            # launch hits this to tell our own running server apart from
            # a foreign process that merely grabbed the port. Read-only,
            # exposes only the app name + version (NO secrets, NO paths),
            # so the Host-header gate alone suffices like every other GET.
            send_json(
                self,
                {"app": PING_APP_NAME, "version": mureo_version},
            )
            return
        if path == "/api/updates":
            # #239 — available mureo/plugin updates (pip-derived). Read-
            # only and fault-isolated (never raises), so the Host-header
            # gate alone suffices like every other GET JSON endpoint.
            # Non-blocking: the slow pip check runs in a daemon thread and
            # its result is cached, so this handler never blocks (#244).
            send_json(self, get_update_status())
            return
        if path == "/api/extensions":
            self._serve_extensions_index()
            return
        if path == "/api/demo/scenarios":
            send_json(self, list_demo_scenarios().as_dict())
            return
        if path == "/api/byod/status":
            send_json(self, byod_status().as_dict())
            return
        if path == "/api/reports/clients":
            self._serve_reports_clients()
            return
        if path == "/api/reports/summary":
            self._serve_reports_summary()
            return
        if path == "/api/creative/clients":
            # Same picker source as reports — clients are clients (#409).
            send_json(self, {"clients": list_report_clients()})
            return
        if path == "/api/creative/runs":
            self._serve_creative_runs()
            return
        if path == "/api/creative/image":
            self._serve_creative_image()
            return
        if path == "/api/advisors":
            self._serve_advisors()
            return
        if path == "/api/credentials/plugins":
            # Forward the session locale so plugin-declared
            # ``display_name_i18n`` / ``description_i18n`` entries are
            # resolved against the operator's active locale (#186). The
            # field scope (#207) is home-gated — see _resolve_field_scope.
            plugins = list_plugin_credential_fields(
                locale=self.wizard.session.locale,
                field_scope=self._resolve_field_scope(),
            )
            self._inject_saved_oauth_callback_urls(plugins)
            self._inject_plugin_field_state(plugins)
            send_json(self, {"plugins": plugins})
            return
        match = _OAUTH_PROVIDER_RE.match(path)
        if match is not None and match.group("verb") == "status":
            self._serve_oauth_status(match.group("provider"))
            return
        plugin_oauth_match = _PLUGIN_OAUTH_RE.match(path)
        if plugin_oauth_match is not None and (
            plugin_oauth_match.group("verb") == "status"
        ):
            self._serve_plugin_oauth_status(plugin_oauth_match.group("provider"))
            return
        plugin_accounts_match = _PLUGIN_ACCOUNTS_RE.match(path)
        if plugin_accounts_match is not None:
            self._serve_plugin_oauth_accounts(plugin_accounts_match.group("provider"))
            return
        ext_api_match = _EXTENSION_API_RE.match(path)
        if ext_api_match is not None:
            self._dispatch_extension_get(
                ext_api_match.group("name"),
                ext_api_match.group("subpath"),
            )
            return
        send_error_json(self, 404, "not_found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        body = read_body(self)
        if body is None:
            send_error_json(self, 413, "payload_too_large")
            return
        payload = parse_json_body(body)
        if payload is None:
            send_error_json(self, 400, "invalid_json")
            return
        csrf_supplied = self.headers.get("X-CSRF-Token", "")
        if not compare_csrf(csrf_supplied, self.wizard.session.csrf_token):
            send_error_json(self, 403, "csrf_invalid")
            return

        path = self.path.split("?", 1)[0]
        route = self._POST_ROUTES.get(path)
        if route is not None:
            route(self, payload)
            return
        match = _OAUTH_PROVIDER_RE.match(path)
        if match is not None and match.group("verb") == "start":
            self._post_oauth_start(match.group("provider"), payload)
            return
        plugin_oauth_match = _PLUGIN_OAUTH_RE.match(path)
        if plugin_oauth_match is not None and (
            plugin_oauth_match.group("verb") == "start"
        ):
            self._post_plugin_oauth_start(plugin_oauth_match.group("provider"), payload)
            return
        ext_api_match = _EXTENSION_API_RE.match(path)
        if ext_api_match is not None:
            self._dispatch_extension_post(
                ext_api_match.group("name"),
                ext_api_match.group("subpath"),
                payload,
            )
            return
        send_error_json(self, 404, "not_found")

    # ------------------------------------------------------------------
    # Pre-flight helpers
    # ------------------------------------------------------------------
    def _host_ok(self) -> bool:
        # BaseServer.server_address is a broad union in typeshed; for the
        # TCPServer this handler always runs under, it is the (host, port)
        # tuple, so the port index is safe.
        port = int(self.server.server_address[1])  # type: ignore[index]
        host = self.headers.get("Host", "")
        if host_header_ok(host, port):
            return True
        send_error_json(self, 403, "host_not_allowed")
        return False

    # ------------------------------------------------------------------
    # GET handlers
    # ------------------------------------------------------------------
    def _serve_app_html(self) -> None:
        body = _resolve_static_body(self.wizard, "app.html")
        if body is None:
            send_error_json(self, 500, "missing_app_html")
            return
        send_bytes(self, body, content_type=_static_content_type("app.html"))

    def _serve_static(self, filename: str) -> None:
        body = _resolve_static_body(self.wizard, filename)
        if body is None:
            send_error_json(self, 404, "not_found")
            return
        send_bytes(self, body, content_type=_static_content_type(filename))

    def _serve_status(self) -> None:
        snapshot = collect_status(
            self.wizard.session.host,
            paths=self.wizard.host_paths,
            multi_account_auth=self._multi_account_active(),
        )
        send_json(self, snapshot.as_dict())

    def _serve_csrf(self) -> None:
        send_json(self, {"csrf_token": self.wizard.session.csrf_token})

    def _serve_oauth_status(self, provider: str) -> None:
        if provider not in OAUTH_PROVIDERS:
            send_error_json(self, 404, "unknown_provider")
            return
        send_json(self, self.wizard.session.get_oauth_status(provider))

    # ------------------------------------------------------------------
    # POST handlers (each takes the parsed payload)
    # ------------------------------------------------------------------
    def _post_locale(self, payload: dict[str, Any]) -> None:
        locale = payload.get("locale", "")
        if locale not in {"en", "ja"}:
            send_error_json(self, 400, "invalid_locale")
            return
        self.wizard.session.set_locale(locale)
        send_json(self, {"locale": self.wizard.session.locale})

    def _post_host(self, payload: dict[str, Any]) -> None:
        host = payload.get("host", "")
        if host not in SUPPORTED_HOSTS:
            send_error_json(self, 400, "invalid_host")
            return
        self.wizard.set_host(host)
        send_json(self, {"host": self.wizard.session.host})

    def _resolve_host(self, payload: dict[str, Any]) -> str:
        """Client-authoritative host for host-dependent actions.

        The server's ``session.host`` lives in the ``mureo configure``
        process memory and resets to the ``claude-code`` default if that
        process restarts, while the browser keeps the user's real
        choice. Relying on ``session.host`` alone silently routed a
        Desktop user down the Claude Code verification path. So a valid
        ``host`` in the request payload wins and is written back into
        the session (self-healing a reset/stale session); an absent or
        invalid value falls back to the current session host.
        """
        host: str = payload.get("host", "")
        if host in SUPPORTED_HOSTS:
            self.wizard.set_host(host)
            return host
        session_host: str = self.wizard.session.host
        return session_host

    def _post_setup_basic(self, payload: dict[str, Any]) -> None:
        # Client-authoritative host (see _resolve_host): these host-dependent
        # writes/removals must target the operator's actual host, not a
        # session.host that reset to the claude-code default on a daemon
        # restart. Symmetric with the providers endpoints.
        result = install_basic_setup(
            home=self.wizard.home,
            host=self._resolve_host(payload),
            # #222: a multi-account backend must not get the bare `mureo`
            # entry (per-client `mureo-<slug>` entries are the only correct
            # wiring). Same production gate as the account-picker skip.
            skip_mcp_registration=self._multi_account_active(),
        )
        send_json(self, result)

    def _post_setup_mcp_remove(self, payload: dict[str, Any]) -> None:
        result = remove_mureo_mcp(
            home=self.wizard.home, host=self._resolve_host(payload)
        )
        send_json(self, result.as_dict())

    def _post_setup_hook_remove(self, payload: dict[str, Any]) -> None:
        result = remove_auth_hook(
            home=self.wizard.home, host=self._resolve_host(payload)
        )
        send_json(self, result.as_dict())

    def _post_setup_hook_install(self, payload: dict[str, Any]) -> None:
        # Per-row (re)install so the operator can restore the credential-guard
        # hook without re-running the full basic-setup wizard. Host is
        # client-authoritative (see _resolve_host), symmetric with the remove
        # route. install_auth_hook swallows its own errors into an ``error``
        # ActionResult, so this always sends a 200 envelope.
        result = install_auth_hook(
            home=self.wizard.home, host=self._resolve_host(payload)
        )
        send_json(self, result.as_dict())

    def _post_setup_skills_remove(self, payload: dict[str, Any]) -> None:
        result = remove_workflow_skills(
            home=self.wizard.home, host=self._resolve_host(payload)
        )
        send_json(self, result.as_dict())

    def _post_setup_skills_install(self, payload: dict[str, Any]) -> None:
        # Per-row (re)install of the workflow skills, symmetric with the
        # remove route (see _post_setup_hook_install).
        result = install_workflow_skills(
            home=self.wizard.home, host=self._resolve_host(payload)
        )
        send_json(self, result.as_dict())

    def _post_setup_basic_clear(self, payload: dict[str, Any]) -> None:
        envelope = clear_all_setup(
            home=self.wizard.home, host=self._resolve_host(payload)
        )
        send_json(self, envelope)

    def _post_upgrade(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        """#239 — upgrade mureo + every installed ``mureo-*`` plugin.

        The target list is SERVER-derived (``_discover_all_mureo_packages``
        inside ``run_upgrade_all``) — the request body is deliberately
        NOT read for packages, so a stale/hostile client can never inject
        an arbitrary package or pip flag onto the install command. The
        running server is still on the old code afterwards. When running
        under an auto-start supervisor (``is_managed_service``) the daemon
        EXITS-to-RESTART so the supervisor relaunches it on the new code
        automatically (``restarting=True`` tells the UI to wait + reload);
        an interactive ``mureo configure`` has no supervisor, so it keeps
        the manual "restart" prompt (``restarting=False``).

        On success the on-disk dist metadata now reflects the new version,
        so the cached "update available" result is stale. Invalidate it and
        kick a fresh background check (``importlib.invalidate_caches`` lets
        the still-running process read the just-replaced ``.dist-info``), so
        the About badge / summary stop advertising the just-applied update.
        The re-check's outdated verdict itself comes from a fresh
        ``pip --dry-run`` subprocess (which never sees stale in-process
        metadata); the in-process read only fills the displayed version.
        """
        # Lazy import: ``mureo.web.service`` imports ``mureo.web.server``,
        # which imports this module — a module-level import would cycle.
        from mureo.web.service import is_managed_service

        result = run_upgrade_all()
        restarting = False
        if result.get("status") == "ok":
            importlib.invalidate_caches()
            request_update_refresh()
            restarting = is_managed_service()
        result = {**result, "restarting": restarting}
        # Schedule the restart FIRST (same ordering as ``_post_restart``): the
        # scheduler only SPAWNS a daemon thread that waits out
        # ``_RESTART_RESPONSE_GRACE_SECONDS`` before touching the process, so
        # the response below still flushes long before the server goes down.
        # Scheduling before ``send_json`` also removes the send-then-schedule
        # race that made the route test flaky (the assertion could run before
        # the handler thread reached the scheduling line).
        if restarting:
            _request_service_restart(self.wizard)
        send_json(self, result)

    def _post_restart(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        """Restart the running configure server (About tab button).

        Two modes, resolved server-side from the process environment (never
        the request body):
        - Managed (launchd / systemd ``service install``): exit-to-restart so
          the supervisor relaunches the daemon — the robust path also used by
          the self-upgrade flow.
        - Interactive (plain ``mureo configure`` — and Windows, whose Task
          Scheduler will not relaunch a clean exit): self-reexec in place,
          since no supervisor would bring a self-exit back up.

        Either way the restart is scheduled on a daemon thread AFTER this
        response is flushed, so the browser receives ``mode`` and can poll
        ``/api/ping`` until the server returns, then reload. CSRF + Host gated
        like every other POST; the body is ignored.
        """
        # Lazy import: ``mureo.web.service`` imports ``mureo.web.server``,
        # which imports this module — a module-level import would cycle.
        from mureo.web.service import is_managed_service

        managed = is_managed_service()
        mode = "managed" if managed else "interactive"
        # Schedule the restart FIRST. Both schedulers only SPAWN a daemon thread
        # that waits out a response-flush grace (``_RESTART_RESPONSE_GRACE_SECONDS``)
        # before touching the process, so the response below still flushes long
        # before the server goes down. Spawning first (a fast, non-blocking call)
        # also keeps the threaded route tests deterministic — no send-then-
        # schedule race where the assertion runs before the handler thread
        # reaches the scheduling line.
        if managed:
            _request_service_restart(self.wizard)
        else:
            _request_interactive_reexec()
        send_json(self, {"status": "ok", "mode": mode})

    def _post_check_updates(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        """#246 — force a fresh update check for the About "check now" button.

        Invalidates the cached result and starts a background pip check,
        returning immediately (``status="checking"`` on a cold cache). The
        client then polls ``GET /api/updates`` until the status settles.
        Server-derived, read-only, fault-isolated like ``/api/updates``; the
        body is ignored. CSRF + Host gated like every other POST.
        """
        send_json(self, request_update_refresh())

    def _inject_saved_oauth_callback_urls(self, plugins: list[dict[str, Any]]) -> None:
        """Surface each OAuth provider's saved (non-secret) callback URL so
        the dashboard can pre-fill it on re-auth instead of resetting to the
        well-known default (#216).

        Only the ``oauth_callback_url`` field is copied — never a secret —
        and only for providers that declare an ``oauth`` block. Manual-entry
        providers are left untouched (no key added).
        """
        store = FilesystemSecretStore(path=self.wizard.host_paths.credentials_path)
        for plugin in plugins:
            if not plugin.get("oauth"):
                continue
            saved = store.load(plugin["provider_name"])
            url = saved.get(_OAUTH_CALLBACK_URL_KEY)
            if isinstance(url, str) and url:
                plugin["oauth_callback_url"] = url

    def _inject_plugin_field_state(self, plugins: list[dict[str, Any]]) -> None:
        """Annotate each declared field with its stored state for pre-fill
        after a configure restart (#224).

        Per field: ``configured`` (a truthy value is stored) is always set;
        a **non-secret** field additionally gets ``value`` (the stored value
        verbatim, e.g. ``base_account_id`` / ``oauth_callback_url``). A
        **secret** field NEVER ships its value — only the boolean — so a
        secret never round-trips into the browser. The save side's
        blank-keeps-stored contract is unchanged.
        """
        store = FilesystemSecretStore(path=self.wizard.host_paths.credentials_path)
        for plugin in plugins:
            saved = store.load(plugin["provider_name"])
            for field in plugin.get("fields", []):
                stored = saved.get(field["key"])
                field["configured"] = bool(stored)
                if field["configured"] and not field.get("secret"):
                    field["value"] = str(stored)

    def _multi_account_active(self) -> bool:
        """True ⇔ a multi-account backend is active in production (#198/#222).

        The single ``home is None and runtime_multi_account_auth()`` gate
        shared by the account-picker skip (#198), the status flag, and the
        MCP-registration skip (#222). Resolve the capability ONLY when
        ``home is None`` (production): an injected ``home`` sandboxes the
        wizard, and the process-global factory's store lives outside that
        sandbox (in dev/CI a third-party factory resolves against the
        operator's real ~/.mureo), so consulting it under an injected home
        would let a sandboxed/test wizard inherit real-backend behaviour —
        the #195 escape the credentials-path / field-scope gates guard.
        """
        return self.wizard.home is None and runtime_multi_account_auth()

    def _resolve_field_scope(self) -> Mapping[str, Collection[str]] | None:
        """Resolve the per-provider credential-field scope (#207/#211).

        A multi-account backend may scope which fields the dashboard
        renders / required-validates via the store's
        ``ui_plugin_credential_fields`` capability. Resolve it ONLY in
        production (``home is None``): an injected ``home`` sandboxes the
        wizard, and the process-global factory's store lives outside that
        sandbox (the dev/CI agency factory resolves against the operator's
        real ~/.mureo), so consulting it under an injected home would let a
        sandboxed/test wizard inherit a real backend's scoping — the same
        #195 gate the credentials-path / multi-account resolution use.
        Both the list (#207) and save (#211) sides read this one value so
        they never diverge.

        Multi-account fold-in (#337): when a multi-account backend is active
        it also hides each OAuth provider's post-auth picker field
        (``accounts_field``) — the account is chosen per-client at runtime,
        so a single configure-time ``account_id`` is meaningless. This is
        merged with the backend's own ``ui_plugin_credential_fields`` so the
        agency backend need declare nothing for it (``mureo-pro`` unchanged);
        an explicit backend scope for a provider wins, since it is the more
        specific authority.
        """
        if self.wizard.home is not None:
            return None
        backend = runtime_ui_plugin_credential_fields()
        if not self._multi_account_active():
            return backend
        # Auto-hide picker fields, then let any explicit backend scope
        # override per provider (backend is the more specific authority).
        merged: dict[str, Collection[str]] = dict(multi_account_picker_scope())
        if backend:
            merged.update(backend)
        return merged or None

    def _post_plugin_credentials_save(self, payload: dict[str, Any]) -> None:
        """Persist one plugin provider's per-account credential values.

        Maps :class:`UnknownProviderError` to ``400 unknown_provider``
        and :class:`InvalidFieldValueError` to ``400 invalid_field_value``
        so a stale UI gets a clean envelope instead of a 500.
        """
        provider_name = str(payload.get("provider_name", "")).strip()
        if not provider_name:
            send_error_json(self, 400, "provider_name_required")
            return
        raw_values = payload.get("values", {})
        if not isinstance(raw_values, dict):
            send_error_json(self, 400, "invalid_values")
            return
        store = FilesystemSecretStore(path=self.wizard.host_paths.credentials_path)
        try:
            result = save_plugin_credentials(
                provider_name,
                raw_values,
                secret_store=store,
                field_scope=self._resolve_field_scope(),
            )
        except UnknownProviderError:
            send_error_json(self, 400, "unknown_provider")
            return
        except InvalidFieldValueError:
            send_error_json(self, 400, "invalid_field_value")
            return
        except RequiredFieldMissingError:
            send_error_json(self, 400, "required_field_missing")
            return
        except SecretStoreError:
            # The credentials file is corrupt; the store backed it up and
            # refused to overwrite (rather than dropping other providers).
            # Surface a clean signal instead of a 500 / silent data loss.
            send_error_json(self, 409, "credentials_file_corrupt")
            return
        send_json(
            self,
            {
                "status": "ok",
                "provider_name": provider_name,
                "accepted_keys": sorted(result["accepted_keys"]),
            },
        )

    def _post_providers_install(self, payload: dict[str, Any]) -> None:
        provider_id = str(payload.get("provider_id", "")).strip()
        if not provider_id:
            send_error_json(self, 400, "provider_id_required")
            return
        result = install_provider(
            provider_id,
            home=self.wizard.home,
            host=self.wizard.session.host,
            credentials_path=self.wizard.host_paths.credentials_path,
        )
        send_json(self, result.as_dict())

    def _post_providers_confirm(self, payload: dict[str, Any]) -> None:
        provider_id = str(payload.get("provider_id", "")).strip()
        if not provider_id:
            send_error_json(self, 400, "provider_id_required")
            return
        result = confirm_hosted_provider(
            provider_id,
            home=self.wizard.home,
            host=self._resolve_host(payload),
            affirm=bool(payload.get("affirm", False)),
        )
        send_json(self, result.as_dict())

    def _post_providers_hosted_status(  # noqa: ARG002
        self, payload: dict[str, Any]
    ) -> None:
        send_json(
            self,
            {"hosted_connected": hosted_provider_status(self.wizard.session.host)},
        )

    def _post_providers_native_toggle(self, payload: dict[str, Any]) -> None:
        platform = str(payload.get("platform", "")).strip()
        if not platform:
            send_error_json(self, 400, "platform_required")
            return
        result = set_native_preference(
            platform,
            bool(payload.get("prefer_official", False)),
            home=self.wizard.home,
            host=self._resolve_host(payload),
        )
        send_json(self, result.as_dict())

    def _post_providers_remove(self, payload: dict[str, Any]) -> None:
        provider_id = str(payload.get("provider_id", "")).strip()
        if not provider_id:
            send_error_json(self, 400, "provider_id_required")
            return
        result = remove_provider(
            provider_id, home=self.wizard.home, host=self.wizard.session.host
        )
        send_json(self, result.as_dict())

    # ------------------------------------------------------------------
    # External advisor MCP (Advanced) — list / add / remove
    # ------------------------------------------------------------------
    def _insight_sources_path(self) -> Path:
        """Resolve ``insight_sources.json`` next to the runtime credentials.

        Derived from ``host_paths.credentials_path`` (the home-gated,
        runtime-resolved path — see #195/#196) so an injected/sandboxed
        home never escapes to the operator's real ``~/.mureo``. The
        advisor list is a sibling of ``credentials.json``.
        """
        return self.wizard.host_paths.credentials_path.parent / "insight_sources.json"

    def _serve_advisors(self) -> None:
        """GET ``/api/advisors`` — the configured external advisor MCPs.

        Tolerant read (never 500): a missing/malformed file lists nothing.
        Only name/transport/target are surfaced — never args/env/headers,
        which can carry secrets.
        """
        send_json(self, {"advisors": list_advisors(path=self._insight_sources_path())})

    # ------------------------------------------------------------------
    # Reporting dashboard (read-only, STATE.json-sourced)
    # ------------------------------------------------------------------
    def _serve_reports_clients(self) -> None:
        """GET ``/api/reports/clients`` — selectable reporting clients.

        Read-only, Host-gated like every other GET. One client for the OSS
        single-workspace install; the Agency backend's ``list_clients`` seam
        plugs in inside :func:`mureo.web.reports.list_report_clients`. Never
        raises — the builder degrades to the active workspace.
        """
        send_json(self, {"clients": list_report_clients()})

    def _serve_reports_summary(self) -> None:
        """GET ``/api/reports/summary`` — read-only STATE.json report data.

        Optional ``client`` / ``period`` query params select the client
        (Agency seam) and forward a window hint. Read-only, Host-gated, and
        secret-free; the builder never raises on a missing/empty STATE.json.
        """
        query = _flatten_query(self.path)
        client = query.get("client") or None
        period = query.get("period") or None
        send_json(self, build_report_summary(client=client, period=period))

    def _serve_creative_runs(self) -> None:
        """GET ``/api/creative/runs`` — one client's gallery runs (#409).

        Optional ``client`` selects the client via the same multi-account
        seam the reports tab uses. Read-only, Host-gated, secret-free
        (filenames + a whitelisted manifest summary); the builder never
        raises on a missing gallery directory.
        """
        query = _flatten_query(self.path)
        send_json(self, list_creative_runs(query.get("client") or None))

    def _serve_creative_image(self) -> None:
        """GET ``/api/creative/image`` — one gallery PNG (#409).

        ``resolve_gallery_image`` is the security boundary: every refusal
        (charset, non-PNG, traversal, symlink escape, missing file) comes
        back as ``None`` and maps to a uniform 404 — the route neither
        distinguishes the refusal reason nor touches the filesystem
        outside the gallery tree.
        """
        query = _flatten_query(self.path)
        run_id = query.get("run", "")
        filename = query.get("file", "")
        if not run_id or not filename:
            send_error_json(self, 404, "not_found")
            return
        resolved = resolve_gallery_image(query.get("client") or None, run_id, filename)
        if resolved is None:
            send_error_json(self, 404, "not_found")
            return
        try:
            body = resolved.read_bytes()
        except OSError:
            send_error_json(self, 404, "not_found")
            return
        send_bytes(self, body, content_type="image/png")

    def _post_advisors_add(self, payload: dict[str, Any]) -> None:
        try:
            result = add_advisor(payload, path=self._insight_sources_path())
        except AdvisorActionError as exc:
            send_error_json(self, 400, exc.code)
            return
        except Exception:  # noqa: BLE001
            # A malformed existing file (ConfigWriteError) or any other
            # write fault — never echo the exception (it may carry a path
            # fragment); log it server-side and return a generic envelope.
            logger.exception("advisor add failed")
            send_error_json(self, 400, "write_failed")
            return
        send_json(self, result)

    def _post_advisors_remove(self, payload: dict[str, Any]) -> None:
        try:
            result = remove_advisor(payload, path=self._insight_sources_path())
        except AdvisorActionError as exc:
            send_error_json(self, 400, exc.code)
            return
        except Exception:  # noqa: BLE001
            logger.exception("advisor remove failed")
            send_error_json(self, 400, "write_failed")
            return
        send_json(self, result)

    def _post_env_var(self, payload: dict[str, Any]) -> None:
        name = str(payload.get("name", "")).strip()
        value = str(payload.get("value", ""))
        # Optional section disambiguates env names shared across sections
        # (ADC's GOOGLE_APPLICATION_CREDENTIALS). An unknown/mismatched
        # section makes the writer raise ValueError -> 400, so the closed
        # allow-list is preserved without extra validation here (#102 B2).
        section = str(payload.get("section", "")).strip() or None
        if not is_allowed_env_var(name):
            send_error_json(self, 400, "env_var_not_allowed")
            return
        if not value:
            send_error_json(self, 400, "value_required")
            return
        try:
            write_credential_env_var(
                name,
                value,
                section=section,
                credentials_path=self.wizard.host_paths.credentials_path,
            )
        except ValueError:
            send_error_json(self, 400, "write_failed")
            return
        except Exception:  # noqa: BLE001
            logger.exception("env_var write failed")
            send_error_json(self, 500, "internal_error")
            return
        # Never echo the value.
        send_json(self, {"status": "ok", "name": name})

    def _post_credentials_remove(self, payload: dict[str, Any]) -> None:
        section = str(payload.get("section", "")).strip()
        try:
            removed = remove_credential_section(
                section,
                credentials_path=self.wizard.host_paths.credentials_path,
            )
        except ValueError:
            send_error_json(self, 400, "section_not_allowed")
            return
        except Exception:  # noqa: BLE001
            logger.exception("credentials remove failed")
            send_error_json(self, 500, "internal_error")
            return
        send_json(
            self,
            {
                "status": "ok" if removed else "noop",
                "section": section,
            },
        )

    def _post_legacy_cleanup(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        removed = remove_legacy_commands(self.wizard.host_paths.commands_dir)
        send_json(self, {"removed": removed})

    def _post_demo_init(self, payload: dict[str, Any]) -> None:
        target = str(payload.get("target", "")).strip()
        if not target:
            send_error_json(self, 400, "target_required")
            return
        result = init_demo(
            scenario_name=str(payload.get("scenario_name", "")),
            target=target,
            force=bool(payload.get("force", False)),
            skip_import=bool(payload.get("skip_import", False)),
        )
        send_json(self, result.as_dict())

    def _post_byod_import(self, payload: dict[str, Any]) -> None:
        file_path = str(payload.get("file_path", "")).strip()
        if not file_path:
            send_error_json(self, 400, "file_path_required")
            return
        result = byod_import(
            file_path=file_path,
            replace=bool(payload.get("replace", False)),
        )
        send_json(self, result.as_dict())

    def _post_byod_remove(self, payload: dict[str, Any]) -> None:
        result = byod_remove(
            google_ads=bool(payload.get("google_ads", False)),
            meta_ads=bool(payload.get("meta_ads", False)),
        )
        send_json(self, result.as_dict())

    def _post_byod_clear(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        send_json(self, byod_clear().as_dict())

    def _post_shutdown(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        """Stop the configure server so the terminal is freed.

        The user finished in the browser; ask the CLI loop to return
        instead of blocking until ``--timeout-seconds``. Reply first,
        then signal — the response still flushes because the daemon
        request thread outlives ``serve_forever`` returning.
        """
        # #210: materialize the credentials file at the runtime write
        # path BEFORE replying so the filesystem records "setup completed"
        # even when every platform was skipped (no OAuth ran) — a missing
        # file otherwise reads as "setup never ran" to diagnostic tooling.
        # ``host_paths.credentials_path`` is already the runtime-resolved
        # path (#195/#196) behind the home gate, so this serves both
        # standalone and agency installs and never escapes an injected
        # home. Best-effort: a write failure must not block freeing the
        # terminal. ``ensure_exists`` never touches an existing file.
        with contextlib.suppress(Exception):
            FilesystemSecretStore(
                path=self.wizard.host_paths.credentials_path
            ).ensure_exists()
        send_json(self, {"status": "stopping"})
        self.wizard.request_stop()

    def _post_pick_directory(self, payload: dict[str, Any]) -> None:
        title = str(payload.get("title", "Select a folder"))
        # #228: the macOS prompt is keyed by the SESSION locale — never
        # by anything in the request body (zero-injection design).
        locale = self.wizard.session.locale
        send_json(self, pick_directory(title=title, locale=locale).as_dict())

    def _post_pick_file(self, payload: dict[str, Any]) -> None:
        title = str(payload.get("title", "Select a file"))
        kind = str(payload.get("kind", "xlsx"))
        patterns = ("*.xlsx", "*.xlsm") if kind == "xlsx" else ("*.*",)
        locale = self.wizard.session.locale
        send_json(
            self, pick_file(title=title, patterns=patterns, locale=locale).as_dict()
        )

    def _post_oauth_start(
        self, provider: str, payload: dict[str, Any]
    ) -> None:  # noqa: ARG002
        if provider not in OAUTH_PROVIDERS:
            send_error_json(self, 404, "unknown_provider")
            return
        self.wizard.session.mark_oauth_pending(provider)
        # A multi-account backend (#198) persists only the operator-shared
        # credentials and skips the per-account picker. Same production gate
        # as the status flag / MCP-registration skip — see
        # _multi_account_active for the home-is-None rationale.
        multi_account = self._multi_account_active()
        try:
            result = self.wizard.oauth_bridge.start(
                provider=provider,
                configure_wizard=self.wizard,
                credentials_path=self.wizard.host_paths.credentials_path,
                locale=self.wizard.session.locale,
                multi_account_auth=multi_account,
            )
        except ValueError:
            send_error_json(self, 400, "unknown_provider")
            return
        send_json(self, result.as_dict())

    # ------------------------------------------------------------------
    # Generic plugin OAuth (authorization-code) — #201
    # ------------------------------------------------------------------
    def _post_plugin_oauth_start(self, provider: str, payload: dict[str, Any]) -> None:
        """Begin a plugin's authorization-code consent flow (#201/#216/#217).

        Authenticate-IS-save (#217): an ``account_oauth`` provider's
        ``target_field`` is ``required``, so a prior Save would deadlock
        (no token to save yet). Instead the operator's **current form
        values** arrive in the POST body and the client id/secret are read
        from them by the oauth config's field keys — not loaded from disk.
        Missing either → ``400 client_credentials_missing``.

        The operator-registered loopback callback URL (#216) rides in under
        ``oauth_callback_url``; an invalid/non-loopback value →
        ``400 callback_url_invalid``. The submitted values (restricted to
        the provider's declared field keys, minus the still-empty
        ``target_field``) plus the callback URL become ``persist_values``
        so the bridge's callback writes them atomically with the obtained
        token — nothing is on disk until consent succeeds.
        """
        if provider not in default_registry:
            send_error_json(self, 404, "unknown_provider")
            return
        entry = default_registry.get(provider)
        try:
            oauth_config = get_account_oauth_config(entry.provider_class)
        except (TypeError, ValueError):
            # Malformed plugin declaration — fail clean, not 500.
            send_error_json(self, 400, "invalid_oauth_config")
            return
        if oauth_config is None:
            send_error_json(self, 404, "oauth_not_supported")
            return

        raw_values = payload.get("values", {})
        if not isinstance(raw_values, dict):
            send_error_json(self, 400, "invalid_values")
            return
        # Strip at intake: credential values (ids, secrets, callback URL)
        # never carry meaningful surrounding whitespace, and a stray space
        # would break both the token exchange and the persisted copy.
        values = {
            str(k): str(v).strip() for k, v in raw_values.items() if v is not None
        }

        client_id = values.get(oauth_config.client_id_field, "")
        client_secret = values.get(oauth_config.client_secret_field, "")
        if not client_id or not client_secret:
            send_error_json(self, 400, "client_credentials_missing")
            return

        callback_url = values.get(_OAUTH_CALLBACK_URL_KEY, "")
        try:
            parse_loopback_callback_url(callback_url)
        except ValueError:
            send_error_json(self, 400, "callback_url_invalid")
            return

        # Persist only the provider's declared field keys (an attacker-
        # crafted extra key can't sneak onto disk), minus the still-empty
        # target_field, plus the non-secret callback URL for re-auth.
        declared = {
            f.key
            for f in getattr(entry.provider_class, "account_credential_fields", ())
        }
        persist_values = {
            k: v
            for k, v in values.items()
            if k in declared and k != oauth_config.target_field
        }
        persist_values[_OAUTH_CALLBACK_URL_KEY] = callback_url

        self.wizard.session.mark_oauth_pending(provider, allow_dynamic=True)
        result = self.wizard.oauth_bridge.start_plugin_oauth(
            provider=provider,
            configure_wizard=self.wizard,
            oauth_config=oauth_config,
            client_id=client_id,
            client_secret=client_secret,
            callback_url=callback_url,
            persist_values=persist_values,
            credentials_path=self.wizard.host_paths.credentials_path,
        )
        send_json(self, result.as_dict())

    def _serve_plugin_oauth_status(self, provider: str) -> None:
        """Report a plugin OAuth flow's status (reuses the session store).

        Returns an idle snapshot when the provider is valid but no flow
        has started yet (e.g. the UI polls after a page reload), so the
        poller never sees a 5xx.
        """
        if provider not in default_registry:
            send_error_json(self, 404, "unknown_provider")
            return
        try:
            status = self.wizard.session.get_oauth_status(provider)
        except ValueError:
            status = {"pending": False, "success": False, "error": None}
        send_json(self, status)

    def _serve_plugin_oauth_accounts(self, provider: str) -> None:
        """List the accounts a provider's OAuth token can reach (#336).

        Powers the post-auth account picker. Each failure mode maps to a
        clean 4xx envelope the dashboard can act on, never a 5xx:
        ``unknown_provider`` (404), ``accounts_not_supported`` (404 — the
        provider declares no picker), ``not_authenticated`` (409 — consent
        first), ``account_listing_failed`` (502 — the plugin hook raised,
        detail withheld).
        """
        store = FilesystemSecretStore(path=self.wizard.host_paths.credentials_path)
        try:
            accounts = list_oauth_accounts(provider, secret_store=store)
        except UnknownProviderError:
            send_error_json(self, 404, "unknown_provider")
            return
        except OAuthAccountsNotSupportedError:
            send_error_json(self, 404, "accounts_not_supported")
            return
        except OAuthNotAuthenticatedError:
            send_error_json(self, 409, "not_authenticated")
            return
        except AccountListingError:
            send_error_json(self, 502, "account_listing_failed")
            return
        send_json(self, {"accounts": accounts})

    # ------------------------------------------------------------------
    # Extension dispatch
    # ------------------------------------------------------------------
    def _serve_extensions_index(self) -> None:
        """Return the renderer-facing index of registered extensions.

        Each item carries enough information for ``app.js`` to render a
        tab + lazy-load the view: ``name`` is also the URL segment used
        when calling ``/api/ext/<name>/...`` and ``/static/ext/<name>/...``.
        ``view`` is ``null`` for headless extensions (route-only).
        """
        payload: list[dict[str, Any]] = []
        for entry in self.wizard.extensions:
            item: dict[str, Any] = {
                "name": entry.name,
                "display_name": entry.display_name,
                # Defensive copy — the renderer is free to mutate the
                # returned dict (the JSON serialiser does not), and an
                # extension may share the same mapping object across
                # multiple discovery calls within a process.
                "display_name_i18n": dict(entry.display_name_i18n),
                # #189 — surface overrides. Always present (no-op
                # defaults) so extensions.js never needs an existence
                # check before reading them.
                "hidden_builtin_tabs": list(entry.hidden_builtin_tabs),
                "replaces_landing": entry.replaces_landing,
                # Cards injected into built-in dashboard groups. Always
                # present ([] when none) so extensions.js never needs an
                # existence check before iterating.
                "dashboard_cards": [
                    {
                        "group": card.group,
                        "html_fragment": card.html_fragment,
                        "scripts": [a.filename for a in card.scripts],
                        "styles": [a.filename for a in card.styles],
                    }
                    for card in entry.dashboard_cards
                ],
            }
            if entry.view is None:
                item["view"] = None
            else:
                item["view"] = {
                    "html_fragment": entry.view.html_fragment,
                    "scripts": [a.filename for a in entry.view.scripts],
                    "styles": [a.filename for a in entry.view.styles],
                }
            payload.append(item)
        send_json(self, payload)

    def _serve_extension_static(self, name: str, filename: str) -> None:
        """Serve an extension-shipped static asset by name + filename."""
        entry = _find_extension(self.wizard.extensions, name)
        if entry is None:
            send_error_json(self, 404, "not_found")
            return
        asset = _find_extension_static(entry, filename)
        if asset is None:
            send_error_json(self, 404, "not_found")
            return
        send_bytes(self, asset.body, content_type=asset.content_type)

    def _dispatch_extension_get(self, name: str, subpath: str) -> None:
        self._dispatch_extension(name, "GET", subpath, payload=None)

    def _dispatch_extension_post(
        self, name: str, subpath: str, payload: dict[str, Any]
    ) -> None:
        self._dispatch_extension(name, "POST", subpath, payload=payload)

    def _dispatch_extension(
        self,
        name: str,
        method: str,
        subpath: str,
        *,
        payload: dict[str, Any] | None,
    ) -> None:
        """Common dispatch path for GET + POST extension routes.

        Handler exceptions are caught here so one faulty extension
        cannot tear down the configure server. The error is logged
        with the extension/subpath context and a generic 500 envelope
        is returned to the client — we deliberately do not echo the
        exception ``repr`` because it may carry secrets (path
        fragments, token prefixes, etc.) the extension touched.

        A handler that has already begun writing a response before
        raising puts the 500 envelope in an impossible position (the
        wire would carry two status lines). We attempt the envelope
        once and swallow any follow-up failure, downgrading the report
        to a debug log. The contract documented in
        :mod:`mureo.web.extensions` is "handler must not raise after
        starting to write the response" — this branch is the
        defensive backstop, not a free pass.
        """
        entry = _find_extension(self.wizard.extensions, name)
        if entry is None:
            send_error_json(self, 404, "not_found")
            return
        route = _find_extension_route(entry, method, subpath)
        if route is None:
            send_error_json(self, 404, "not_found")
            return
        if method == "GET":
            handler_payload = _flatten_query(self.path)
        else:
            handler_payload = payload or {}
        try:
            route.handler(self, handler_payload)
        except Exception:  # noqa: BLE001 — per-extension fault isolation
            logger.exception("web extension %r raised in %s %s", name, method, subpath)
            try:
                send_error_json(self, 500, "extension_handler_error")
            except Exception:  # noqa: BLE001
                logger.debug(
                    "web extension %r already wrote a partial response; "
                    "the 500 envelope could not be appended",
                    name,
                )

    # ------------------------------------------------------------------
    # Route table
    # ------------------------------------------------------------------
    _POST_ROUTES: dict[str, Callable[[ConfigureHandler, dict[str, Any]], None]] = {
        "/api/locale": _post_locale,
        "/api/host": _post_host,
        "/api/setup/basic": _post_setup_basic,
        "/api/setup/basic/clear": _post_setup_basic_clear,
        "/api/upgrade": _post_upgrade,
        "/api/restart": _post_restart,
        "/api/updates/refresh": _post_check_updates,
        "/api/setup/mcp/remove": _post_setup_mcp_remove,
        "/api/setup/hook/remove": _post_setup_hook_remove,
        "/api/setup/hook/install": _post_setup_hook_install,
        "/api/setup/skills/remove": _post_setup_skills_remove,
        "/api/setup/skills/install": _post_setup_skills_install,
        "/api/providers/install": _post_providers_install,
        "/api/providers/confirm": _post_providers_confirm,
        "/api/providers/hosted-status": _post_providers_hosted_status,
        "/api/providers/native-toggle": _post_providers_native_toggle,
        "/api/providers/remove": _post_providers_remove,
        "/api/advisors/add": _post_advisors_add,
        "/api/advisors/remove": _post_advisors_remove,
        "/api/credentials/env-var": _post_env_var,
        "/api/credentials/remove": _post_credentials_remove,
        "/api/credentials/plugins/save": _post_plugin_credentials_save,
        "/api/legacy/cleanup": _post_legacy_cleanup,
        "/api/demo/init": _post_demo_init,
        "/api/byod/import": _post_byod_import,
        "/api/byod/remove": _post_byod_remove,
        "/api/byod/clear": _post_byod_clear,
        "/api/shutdown": _post_shutdown,
        "/api/pick/directory": _post_pick_directory,
        "/api/pick/file": _post_pick_file,
    }
