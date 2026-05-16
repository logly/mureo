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
``GET  /api/oauth/<p>/status``   → per-provider OAuth flags
``POST /api/locale``             → set session locale (en|ja)
``POST /api/host``               → set Claude application host
``POST /api/setup/basic``        → run mureo_mcp / hook / skills
``POST /api/providers/install``  → install one official MCP
``POST /api/providers/remove``   → remove one official MCP entry
``POST /api/credentials/env-var``→ write one env var into credentials
``POST /api/oauth/<p>/start``    → spawn WebAuthWizard, return consent URL
``POST /api/legacy/cleanup``     → delete legacy slash commands
``GET  /api/demo/scenarios``     → list registered demo scenarios
``POST /api/demo/init``          → scaffold a demo workspace
``GET  /api/byod/status``        → per-platform byod/live status
``POST /api/byod/import``        → import a Sheet bundle XLSX
``POST /api/byod/remove``        → drop one platform's BYOD data
``POST /api/byod/clear``         → wipe all BYOD data
"""

from __future__ import annotations

import logging
import re
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any

from mureo.web._helpers import (
    compare_csrf,
    host_header_ok,
    parse_json_body,
    read_body,
    send_bytes,
    send_error_json,
    send_json,
)
from mureo.web.byod_actions import (
    byod_clear,
    byod_import,
    byod_remove,
    byod_status,
)
from mureo.web.demo_actions import init_demo, list_demo_scenarios
from mureo.web.env_var_writer import (
    is_allowed_env_var,
    remove_credential_section,
    write_credential_env_var,
)
from mureo.web.legacy_commands import remove_legacy_commands
from mureo.web.native_picker import pick_directory, pick_file
from mureo.web.session import OAUTH_PROVIDERS, SUPPORTED_HOSTS
from mureo.web.setup_actions import (
    clear_all_setup,
    install_basic_setup,
    install_provider,
    remove_auth_hook,
    remove_mureo_mcp,
    remove_provider,
    remove_workflow_skills,
)
from mureo.web.status_collector import collect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    from mureo.web.server import ConfigureWizard

logger = logging.getLogger(__name__)


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
    "i18n.json",
)

# Regex on path: /api/oauth/<provider>/status or /start
_OAUTH_PROVIDER_RE = re.compile(
    r"^/api/oauth/(?P<provider>[a-z_]+)/(?P<verb>status|start)$"
)


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
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
            return
        if path == "/api/status":
            self._serve_status()
            return
        if path == "/api/csrf":
            self._serve_csrf()
            return
        if path == "/api/demo/scenarios":
            send_json(self, list_demo_scenarios().as_dict())
            return
        if path == "/api/byod/status":
            send_json(self, byod_status().as_dict())
            return
        match = _OAUTH_PROVIDER_RE.match(path)
        if match is not None and match.group("verb") == "status":
            self._serve_oauth_status(match.group("provider"))
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

        route = self._POST_ROUTES.get(self.path.split("?", 1)[0])
        if route is not None:
            route(self, payload)
            return
        match = _OAUTH_PROVIDER_RE.match(self.path.split("?", 1)[0])
        if match is not None and match.group("verb") == "start":
            self._post_oauth_start(match.group("provider"), payload)
            return
        send_error_json(self, 404, "not_found")

    # ------------------------------------------------------------------
    # Pre-flight helpers
    # ------------------------------------------------------------------
    def _host_ok(self) -> bool:
        port = int(self.server.server_address[1])
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
            self.wizard.session.host, paths=self.wizard.host_paths
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

    def _post_setup_basic(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        result = install_basic_setup(
            home=self.wizard.home, host=self.wizard.session.host
        )
        send_json(self, result)

    def _post_setup_mcp_remove(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        result = remove_mureo_mcp(home=self.wizard.home, host=self.wizard.session.host)
        send_json(self, result.as_dict())

    def _post_setup_hook_remove(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        result = remove_auth_hook(home=self.wizard.home, host=self.wizard.session.host)
        send_json(self, result.as_dict())

    def _post_setup_skills_remove(
        self, payload: dict[str, Any]
    ) -> None:  # noqa: ARG002
        result = remove_workflow_skills(
            home=self.wizard.home, host=self.wizard.session.host
        )
        send_json(self, result.as_dict())

    def _post_setup_basic_clear(self, payload: dict[str, Any]) -> None:  # noqa: ARG002
        envelope = clear_all_setup(home=self.wizard.home, host=self.wizard.session.host)
        send_json(self, envelope)

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

    def _post_providers_remove(self, payload: dict[str, Any]) -> None:
        provider_id = str(payload.get("provider_id", "")).strip()
        if not provider_id:
            send_error_json(self, 400, "provider_id_required")
            return
        result = remove_provider(
            provider_id, home=self.wizard.home, host=self.wizard.session.host
        )
        send_json(self, result.as_dict())

    def _post_env_var(self, payload: dict[str, Any]) -> None:
        name = str(payload.get("name", "")).strip()
        value = str(payload.get("value", ""))
        if not is_allowed_env_var(name):
            send_error_json(self, 400, "env_var_not_allowed")
            return
        if not value:
            send_error_json(self, 400, "value_required")
            return
        try:
            write_credential_env_var(
                name, value, credentials_path=self.wizard.host_paths.credentials_path
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

    def _post_pick_directory(self, payload: dict[str, Any]) -> None:
        title = str(payload.get("title", "Select a folder"))
        send_json(self, pick_directory(title=title).as_dict())

    def _post_pick_file(self, payload: dict[str, Any]) -> None:
        title = str(payload.get("title", "Select a file"))
        kind = str(payload.get("kind", "xlsx"))
        patterns = ("*.xlsx", "*.xlsm") if kind == "xlsx" else ("*.*",)
        send_json(self, pick_file(title=title, patterns=patterns).as_dict())

    def _post_oauth_start(
        self, provider: str, payload: dict[str, Any]
    ) -> None:  # noqa: ARG002
        if provider not in OAUTH_PROVIDERS:
            send_error_json(self, 404, "unknown_provider")
            return
        self.wizard.session.mark_oauth_pending(provider)
        try:
            result = self.wizard.oauth_bridge.start(
                provider=provider,
                configure_wizard=self.wizard,
                credentials_path=self.wizard.host_paths.credentials_path,
                locale=self.wizard.session.locale,
            )
        except ValueError:
            send_error_json(self, 400, "unknown_provider")
            return
        send_json(self, result.as_dict())

    # ------------------------------------------------------------------
    # Route table
    # ------------------------------------------------------------------
    _POST_ROUTES: dict[str, Callable[[ConfigureHandler, dict[str, Any]], None]] = {
        "/api/locale": _post_locale,
        "/api/host": _post_host,
        "/api/setup/basic": _post_setup_basic,
        "/api/setup/basic/clear": _post_setup_basic_clear,
        "/api/setup/mcp/remove": _post_setup_mcp_remove,
        "/api/setup/hook/remove": _post_setup_hook_remove,
        "/api/setup/skills/remove": _post_setup_skills_remove,
        "/api/providers/install": _post_providers_install,
        "/api/providers/remove": _post_providers_remove,
        "/api/credentials/env-var": _post_env_var,
        "/api/credentials/remove": _post_credentials_remove,
        "/api/legacy/cleanup": _post_legacy_cleanup,
        "/api/demo/init": _post_demo_init,
        "/api/byod/import": _post_byod_import,
        "/api/byod/remove": _post_byod_remove,
        "/api/byod/clear": _post_byod_clear,
        "/api/pick/directory": _post_pick_directory,
        "/api/pick/file": _post_pick_file,
    }
