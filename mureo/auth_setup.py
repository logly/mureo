"""Authentication setup wizard

Interactively configure credentials via mureo auth setup.
Google Ads: OAuth client input -> Browser OAuth -> refresh_token retrieval -> Customer ID selection
Meta Ads: App ID/Secret input -> Browser OAuth -> Long-Lived Token retrieval -> Account ID selection
"""

from __future__ import annotations

import contextlib
import html
import http.server
import importlib
import json
import logging
import os
import secrets
import shutil
import subprocess  # noqa: S404 - fixed argv, shell=False (claude mcp add-json)
import sys
import threading
import urllib.parse
import webbrowser

try:
    import termios
except ImportError:  # pragma: no cover - Windows (Unix-only stdlib)
    termios = None  # type: ignore[assignment]
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from mureo import credential_guard
from mureo.auth import GoogleAdsCredentials, MetaAdsCredentials
from mureo.core.atomic_json import atomic_write_json, load_existing_json
from mureo.core.ga4_adc import store_has_managed_ga4, sync_ga4_adc_from_google
from mureo.core.google_scopes import (
    GOOGLE_ADS_SCOPE,
    GOOGLE_SCOPES,
    SEARCH_CONSOLE_SCOPE,
    check_granted_scopes,
    granted_scopes,
)
from mureo.core.runtime_context import runtime_credentials_path

# Private alias so existing call sites and test monkeypatches of
# ``mureo.auth_setup._terminal_fd`` keep working now that the canonical
# implementation lives in :mod:`mureo.core.terminal` (#227 follow-up).
from mureo.core.terminal import terminal_fd as _terminal_fd
from mureo.fsutil import backup_file, file_lock, lock_path_for
from mureo.google_ads.accounts import GoogleAdsAccountListError
from mureo.logging_setup import safe_http_log_line
from mureo.meta_ads._api_version import OAUTH_DIALOG_URL, OAUTH_TOKEN_URL
from mureo.meta_ads.accounts import META_HTTP_TIMEOUT_SECONDS, META_OAUTH_SCOPES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from google_auth_oauthlib.flow import Flow

    # Typed views of the lazily-resolved re-exports below. ``as <same-name>``
    # is the PEP 484 explicit-re-export form mypy --strict requires before a
    # downstream module can import the symbol back out.
    from mureo.google_ads.accounts import (
        list_accessible_accounts as list_accessible_accounts,
    )
    from mureo.meta_ads.accounts import (
        list_meta_ad_accounts as list_meta_ad_accounts,
    )

logger = logging.getLogger(__name__)

# Backward-compat re-exports of the account-discovery helpers that live in
# :mod:`mureo.google_ads.accounts` / :mod:`mureo.meta_ads.accounts`. The
# legacy ``mureo.auth_setup.<name>`` paths (and patch targets) stay stable via
# the PEP 562 ``__getattr__`` below; in-module call sites go through
# :func:`_reexport`. Resolved on first access (#486): those packages load the
# Google Ads SDK, whose eager import printed FutureWarnings in the middle of
# ``mureo setup <agent> --skip-auth``, which never touches Google.
_LAZY_REEXPORTS = {
    "list_accessible_accounts": "mureo.google_ads.accounts",
    "list_meta_ad_accounts": "mureo.meta_ads.accounts",
}


def __getattr__(name: str) -> Any:
    """Resolve the deferred account-listing re-exports on first access."""
    module_name = _LAZY_REEXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_name), name)


def _reexport(name: str) -> Any:
    """Return the *current* binding of a deferred re-export.

    Resolved through this module's attribute lookup, deliberately NOT a
    function-local source import: unpatched, lookup falls through to
    :func:`__getattr__` (lazy, #486); patched, the setattr'd attribute
    shadows it, so ``patch("mureo.auth_setup.list_accessible_accounts")``
    intercepts the wizard. A source import would let the real networked
    function run while the mock reports zero calls
    (``tests/test_public_account_listing.py``).
    """
    return getattr(sys.modules[__name__], name)


# Private aliases of mureo.core.google_scopes for existing importers.
_GOOGLE_ADS_SCOPE = GOOGLE_ADS_SCOPE
_SEARCH_CONSOLE_SCOPE = SEARCH_CONSOLE_SCOPE
_GOOGLE_SCOPES = list(GOOGLE_SCOPES)


def _capture_terminal_state(fd: int | None) -> Any | None:
    """Snapshot the current terminal attributes for later restore.

    ``termios.tcgetattr(fd)``, or ``None`` when stdin is not a TTY (pipe,
    CI, Windows, pytest), which tells ``_restore_terminal_state`` to skip.

    #190: ``TerminalMenu.show()`` flips the terminal into cbreak and can
    leave it there on a non-normal exit, so every ``show()`` is wrapped in
    a ``try/finally`` pairing this with ``_restore_terminal_state``.
    """
    if termios is None or fd is None:
        return None
    try:
        return termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        return None


def _restore_terminal_state(fd: int | None, state: Any | None) -> None:
    """Re-apply a snapshot captured by ``_capture_terminal_state``.

    No-op when ``state`` is ``None``. Best-effort (#190): a ``tcsetattr``
    failure must not crash the surrounding CLI flow. ``TCSADRAIN`` lets
    pending output drain first, so a trailing menu redraw cannot leave
    stray escape codes in the next prompt.
    """
    if state is None or termios is None or fd is None:
        return
    with contextlib.suppress(termios.error, OSError, ValueError, AttributeError):
        termios.tcsetattr(fd, termios.TCSADRAIN, state)


def _account_label(account: dict[str, Any]) -> str:
    """``"Name (id)"``, or the bare id when the account has no name (#746).

    The account listers no longer copy the id into ``name`` for an account
    that has none, so ``name`` can be ``None``. Formatting it blindly would
    print the literal string ``None``, and falling back to the id inside
    the same template would print the id twice.
    """

    account_id = str(account.get("id", ""))
    name = account.get("name")
    return f"{name} ({account_id})" if name else account_id


def _select_account(
    accounts: list[dict[str, Any]],
    *,
    label_fn: Any | None = None,
) -> str | None:
    """Select an account using arrow keys in the terminal.

    Uses interactive selection if simple-term-menu is available,
    otherwise falls back to number input.

    Returns:
        The selected account ID, or None.
    """
    if label_fn is None:
        label_fn = _account_label

    labels = [label_fn(a) for a in accounts]

    try:
        # Startup cost (~5 ms CPU): simple_term_menu is deferred to the interactive menu (#863).
        from simple_term_menu import TerminalMenu  # noqa: PLC0415 — startup cost (#863)

        # #190: ``show()`` leaves the terminal in cbreak on a non-normal
        # exit (Esc, exception, KeyboardInterrupt), dropping echo and SIGINT
        # for the rest of the shell session; save and restore explicitly.
        fd = _terminal_fd()
        old_attrs = _capture_terminal_state(fd)
        try:
            menu = TerminalMenu(
                labels, title="Select with ↑↓ and press Enter to confirm:"
            )
            idx = menu.show()
        finally:
            _restore_terminal_state(fd, old_attrs)
        if idx is None:
            print("Selection cancelled. You can configure it later.")
            return None
        selected = accounts[idx]
        print(f"Selected: {_account_label(selected)}")
        return selected["id"]  # type: ignore[no-any-return]
    except (ImportError, NotImplementedError):
        # Plain number input when the arrow-key menu is unusable: not
        # installed (ImportError), or Windows / a non-terminal env such as
        # CI, pipes or an IDE console (NotImplementedError).
        for i, label in enumerate(labels, 1):
            print(f"  {i}. {label}")
        print()
        try:
            choice = int(input("Enter number: ").strip())
            if 1 <= choice <= len(accounts):
                selected = accounts[choice - 1]
                print(f"Selected: {_account_label(selected)}")
                return selected["id"]  # type: ignore[no-any-return]
        except (ValueError, IndexError):
            pass
        print("Invalid selection. You can configure it later.")
        return None


_META_AUTH_URL = OAUTH_DIALOG_URL

# Input function replaceable for testing
input_func = input


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthResult:
    """OAuth authentication result (immutable)."""

    refresh_token: str
    access_token: str
    granted_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetaOAuthResult:
    """Meta Ads OAuth authentication result (immutable)."""

    access_token: str  # Long-Lived Token
    expires_in: int  # Seconds (typically 5184000 = 60 days)


# ---------------------------------------------------------------------------
# Local OAuth callback server (shared by Google/Meta)
# ---------------------------------------------------------------------------


class _OAuthHTTPServer(http.server.HTTPServer):
    """HTTP server for receiving OAuth callbacks. Stores auth results on the server instance."""

    authorization_code: str | None = None
    error: str | None = None
    expected_state: str | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for OAuth callbacks (shared by Google/Meta)."""

    server: _OAuthHTTPServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # Validate state parameter (CSRF protection)
        if self.server.expected_state is not None:
            received_state = params.get("state", [None])[0]
            if received_state != self.server.expected_state:
                self.server.error = (
                    "State parameter mismatch (CSRF verification failed)"
                )
                self._send_html(
                    "Authentication error: state parameter mismatch.",
                    status=403,
                )
                return

        if "code" in params:
            self.server.authorization_code = params["code"][0]
            self._send_html("Authentication complete. You may close this window.")
        elif "error" in params:
            self.server.error = params["error"][0]
            self._send_html(f"Authentication error: {self.server.error}")
        else:
            self._send_html("Invalid request.", status=400)

    def _send_html(self, message: str, status: int = 200) -> None:
        """Send an HTML response. message is escaped via html.escape()."""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        safe_message = html.escape(message)
        body = f"<html><body><h1>{safe_message}</h1></body></html>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """Suppress log output to stdout.

        #581: the callback's request line carries the OAuth ``?code=``,
        so the query string is scrubbed before it is logged at DEBUG.
        """
        logger.debug("%s", safe_http_log_line(fmt, *args))


class OAuthCallbackServer:
    """HTTP server for receiving OAuth callbacks (shared by Google/Meta)."""

    def __init__(
        self,
        port: int = 0,
        expected_state: str | None = None,
    ) -> None:
        self.server = _OAuthHTTPServer(("localhost", port), _CallbackHandler)
        self.server.expected_state = expected_state

    @property
    def authorization_code(self) -> str | None:
        return self.server.authorization_code

    @property
    def error(self) -> str | None:
        return self.server.error

    def wait_for_callback(self) -> None:
        """Process a single request and stop the server."""
        self.server.handle_request()

    def shutdown(self) -> None:
        """Stop the server."""
        self.server.server_close()


# ---------------------------------------------------------------------------
# OAuth flow execution
# ---------------------------------------------------------------------------


def build_google_client_config(client_id: str, client_secret: str) -> dict[str, Any]:
    """Return the ``client_config`` dict consumed by google-auth-oauthlib.

    Shared by the interactive CLI path (:class:`InstalledAppFlow`) and the
    web wizard path (plain :class:`Flow`) so the two agree on OAuth
    endpoints and redirect-URI shape.
    """
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _validate_local_redirect_uri(redirect_uri: str) -> None:
    """Refuse any redirect_uri that isn't a localhost HTTP callback.

    The web wizard binds its callback server to 127.0.0.1, so any other
    scheme/host is either a misconfiguration (reaches a remote OAuth
    relay) or a prompt-injection attempt to redirect tokens elsewhere.
    """
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise ValueError(
            f"redirect_uri must use http://; got {parsed.scheme!r} in "
            f"{redirect_uri!r}"
        )
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(
            f"redirect_uri host must be 127.0.0.1 or localhost; got "
            f"{parsed.hostname!r} in {redirect_uri!r}"
        )


def build_google_flow(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str | None = None,
) -> Flow:
    """Build the OAuth Flow object appropriate for the caller's transport.

    - ``redirect_uri=None`` -> :class:`InstalledAppFlow` (the existing
      CLI path; spins up its own local HTTP server on ``run_local_server``).
    - otherwise -> plain :class:`Flow` whose callback the caller handles on
      their own HTTP server (the web wizard path). The URI must be localhost
      so a malicious or buggy caller cannot redirect the grant elsewhere.

    Both variants receive the same scopes so a single refresh_token
    drives Google Ads, Search Console and GA4.
    """
    # Lazy import (#486): google-auth-oauthlib pulls google.auth in, and
    # ``mureo setup <agent> --skip-auth`` imports this module without OAuth.
    from google_auth_oauthlib.flow import (  # noqa: PLC0415 — startup cost (#486)
        Flow,
        InstalledAppFlow,
    )

    # Google grants the scopes the user left ticked on the consent screen;
    # without this oauthlib fails the whole exchange when the set differs
    # from the request. The granted set is read back from the credentials.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    config = build_google_client_config(client_id, client_secret)
    if redirect_uri is None:
        return InstalledAppFlow.from_client_config(config, scopes=_GOOGLE_SCOPES)
    _validate_local_redirect_uri(redirect_uri)
    flow = Flow.from_client_config(config, scopes=_GOOGLE_SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def google_auth_url(flow: Flow) -> tuple[str, str]:
    """Return ``(authorization_url, state)`` for a web-wizard Flow.

    ``access_type=offline`` + ``prompt=consent`` guarantee a refresh_token on
    every authorization, even for users who granted the app before; otherwise
    Google silently drops it and the exchange fails. The CLI path
    (``run_google_oauth``) passes ``prompt="consent"`` to
    ``flow.run_local_server``; keep the two paths in sync.
    """
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    return url, state


def exchange_google_code(flow: Flow, code: str) -> OAuthResult:
    """Exchange an authorization ``code`` for refresh/access tokens.

    The ``flow`` argument must be the same instance that produced the
    authorization URL, since it carries PKCE / state.

    Raises:
        RuntimeError: If Google returns no ``refresh_token``: the URL was
            built without ``access_type=offline`` + ``prompt=consent``, or a
            cached grant of an earlier consent is being replayed. Re-run via
            :func:`google_auth_url` (which forces both), or revoke prior
            consent at https://myaccount.google.com/permissions and retry.
            Also when Google reports a grant without the Google Ads scope.
    """
    flow.fetch_token(code=code)
    credentials = flow.credentials
    if credentials.refresh_token is None:
        raise RuntimeError(
            "Google returned no refresh_token. Re-run the OAuth flow "
            "ensuring access_type=offline + prompt=consent, or revoke "
            "prior consent at https://myaccount.google.com/permissions "
            "and retry."
        )
    granted = granted_scopes(credentials)
    check_granted_scopes(granted)
    return OAuthResult(
        refresh_token=credentials.refresh_token,
        access_token=credentials.token,
        granted_scopes=granted,
    )


async def run_google_oauth(
    client_id: str,
    client_secret: str,
) -> OAuthResult:
    """Run browser OAuth via InstalledAppFlow to obtain a refresh_token.

    InstalledAppFlow (google-auth-oauthlib) handles the local server, the
    browser authentication, the callback and the token exchange.

    Raises:
        RuntimeError: If OAuth authentication fails.
    """
    flow = build_google_flow(
        client_id=client_id, client_secret=client_secret, redirect_uri=None
    )

    # port=0: the OS picks a free port (no clash with other processes);
    # Google "installed app" clients accept http://localhost on any port.
    credentials = flow.run_local_server(port=0, prompt="consent")

    if credentials.refresh_token is None:
        raise RuntimeError("Failed to obtain refresh_token")

    granted = granted_scopes(credentials)
    check_granted_scopes(granted)
    return OAuthResult(
        refresh_token=credentials.refresh_token,
        access_token=credentials.token,
        granted_scopes=granted,
    )


# ---------------------------------------------------------------------------
# MCP configuration deployment
# ---------------------------------------------------------------------------

# ``command`` is the ABSOLUTE interpreter (``sys.executable``, the env where
# mureo IS installed), not bare "python": Claude Code spawns MCP servers with
# its own minimal PATH, where "python" is a system Python without mureo and
# the MCP silently fails to start. ``type: "stdio"`` is REQUIRED by Claude
# Code's ``mcp add-json`` schema and the ``~/.claude.json`` user-scope entry.
_MCP_SERVER_CONFIG = {
    "type": "stdio",
    "command": sys.executable,
    "args": ["-m", "mureo.mcp"],
}


def _claude_user_config_path() -> Path:
    """Path of the file ``claude mcp add-json --scope user`` writes to.

    User-scope MCP servers live at the root ``mcpServers`` of
    ``~/.claude.json``, NOT ``~/.claude/settings.json`` (never consulted
    for MCP discovery). Also the target of the no-CLI fallback merge.
    """
    return Path.home() / ".claude.json"


def _register_user_scope_mcp() -> Path:
    """Register the mureo MCP server at Claude Code *user* scope.

    Primary path delegates to ``claude mcp add-json`` so Claude Code
    mutates its own live ``~/.claude.json``, avoiding the lost-write race
    of hand-editing a file the running app rewrites; ``remove`` first lets
    a stale entry self-heal. Only when the ``claude`` binary is absent
    (Claude Code is almost certainly not running) does it merge by hand.

    Raises:
        RuntimeError: the ``claude`` CLI is present but registration
            failed — surfaced loudly rather than silently misconfigured.
    """
    config_json = json.dumps(_MCP_SERVER_CONFIG)
    claude_bin = shutil.which("claude")

    if claude_bin is not None:
        # Best-effort remove first (idempotent self-heal); ignore its rc.
        subprocess.run(  # noqa: S603 - fixed argv, shell=False
            [claude_bin, "mcp", "remove", "mureo", "--scope", "user"],
            check=False,
            capture_output=True,
            text=True,
        )
        completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
            [
                claude_bin,
                "mcp",
                "add-json",
                "mureo",
                config_json,
                "--scope",
                "user",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "claude mcp add-json failed (rc="
                f"{completed.returncode}): {completed.stderr.strip()}"
            )
        path = _claude_user_config_path()
        logger.info("mureo MCP registered (user scope) via claude CLI: %s", path)
        return path

    # No claude binary: the file holds the user's entire Claude Code state,
    # so merge through the atomic, refuse-malformed writer.
    path = _claude_user_config_path()
    existing = load_existing_json(path)  # {} if absent; raises on malformed
    mcp_servers = existing.setdefault("mcpServers", {})
    mcp_servers["mureo"] = _MCP_SERVER_CONFIG
    existing["mcpServers"] = mcp_servers
    atomic_write_json(existing, path)
    logger.info("mureo MCP registered (user scope) via fallback merge: %s", path)
    return path


def install_mcp_config(scope: str = "global") -> Path | None:
    """Register the mureo MCP server with Claude Code.

    ``scope="global"``: Claude Code user scope via ``claude mcp add-json
    --scope user`` (persists to ``~/.claude.json`` root ``mcpServers``).
    ``scope="project"``: merge into ``.mcp.json`` in the current directory.

    Returns the path written to; ``None`` only for the project scope when
    mureo is already present (skip).

    Raises:
        RuntimeError: global scope, ``claude`` CLI present but
            registration failed.
    """
    if scope == "global":
        return _register_user_scope_mcp()

    # Claude Code DOES read .mcp.json (user scope is NOT in settings.json).
    settings_path = Path.cwd() / ".mcp.json"

    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    mcp_servers = existing.setdefault("mcpServers", {})
    if "mureo" in mcp_servers:
        logger.info("MCP configuration already exists: %s", settings_path)
        return None

    mcp_servers["mureo"] = _MCP_SERVER_CONFIG
    existing["mcpServers"] = mcp_servers

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    logger.info("MCP configuration added: %s", settings_path)
    return settings_path


def setup_mcp_config() -> None:
    """Interactively deploy MCP configuration."""
    print("\n=== MCP Configuration ===\n")
    print(
        "MCP configuration is required to use mureo from AI agents (e.g. Claude Code)."
    )
    print()

    try:
        # Startup cost (~5 ms CPU): simple_term_menu is deferred to the interactive menu (#863).
        from simple_term_menu import TerminalMenu  # noqa: PLC0415 — startup cost (#863)

        options = [
            "Global (Claude Code user scope) — Available in all projects",
            "This directory (.mcp.json) — This project only",
            "Skip (configure manually)",
        ]
        # See _select_account for the rationale — same #190 fix.
        fd = _terminal_fd()
        old_attrs = _capture_terminal_state(fd)
        try:
            menu = TerminalMenu(
                options, title="Where should the MCP configuration be placed?"
            )
            idx = menu.show()
        finally:
            _restore_terminal_state(fd, old_attrs)
        if idx is None or idx == 2:
            print("MCP configuration skipped.")
            return
        scope = "global" if idx == 0 else "project"
    except (ImportError, NotImplementedError):
        # Plain number-input fallback: simple-term-menu missing
        # (ImportError), Windows (Unix-only termios →
        # NotImplementedError), or a non-terminal env (CI / pipe /
        # PyCharm → NotImplementedError) — degrade, never crash.
        print("Where should the MCP configuration be placed?")
        print("  1. Global (Claude Code user scope) — Available in all projects")
        print("  2. This directory (.mcp.json) — This project only")
        print("  3. Skip (configure manually)")
        print()
        choice = input_func("Enter number [1]: ").strip() or "1"
        if choice == "3":
            print("MCP configuration skipped.")
            return
        scope = "global" if choice != "2" else "project"

    result = install_mcp_config(scope=scope)
    if result is not None:
        print(f"MCP configuration added: {result}")
    else:
        print("MCP configuration already exists.")


# ---------------------------------------------------------------------------
# Credential guard hook
# ---------------------------------------------------------------------------

# Unique identifier to detect mureo-installed hooks (re-exported for callers
# that predate the shared mureo.credential_guard module).
_MUREO_HOOK_TAG = credential_guard.GUARD_TAG


def install_credential_guard() -> Path | None:
    """Add PreToolUse hooks to block AI agents from reading credentials.

    Safely merges into ~/.claude/settings.json without overwriting existing
    hooks. Tagged entries from an older mureo are replaced in place so
    re-running setup upgrades a stale guard (#393: the old ``sys.exit(1)``
    form never blocked anything); everything else is preserved.

    Returns:
        Path to settings file if hooks were added or upgraded. None if
        skipped (already current or file could not be parsed).
    """
    settings_path = Path.home() / ".claude" / "settings.json"

    # Load existing settings (never overwrite on failure)
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Could not parse %s — skipping credential guard installation",
                settings_path,
            )
            return None

    # Get or create hooks.PreToolUse, refusing unexpected shapes
    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        logger.warning(
            "settings.json 'hooks' is not an object — skipping credential guard",
        )
        return None
    pre_tool_use = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre_tool_use, list):
        logger.warning(
            "settings.json 'hooks.PreToolUse' is not a list — "
            "skipping credential guard",
        )
        return None

    # Drop any previously installed mureo entries (tag-scoped), then append
    # the current templates. Identical content means nothing to do.
    kept = [e for e in pre_tool_use if not credential_guard.is_guard_entry(e)]
    desired = kept + credential_guard.guard_entries()
    if desired == pre_tool_use:
        logger.info("Credential guard already installed: %s", settings_path)
        return None
    hooks["PreToolUse"] = desired

    # Write back (preserve all existing content). Same atomic writer the
    # removal path uses on this file — upgrades now rewrite a populated
    # settings.json, so a crash mid-write must not truncate it.
    atomic_write_json(existing, settings_path)

    logger.info("Credential guard hooks installed: %s", settings_path)
    return settings_path


# ---------------------------------------------------------------------------
# credentials.json saving
# ---------------------------------------------------------------------------


def _merge_google_section(
    existing: dict[str, Any],
    google: GoogleAdsCredentials,
    customer_id: str | None,
) -> None:
    """Merge the ``google_ads`` block into ``existing`` in place."""
    prior_google = existing.get("google_ads")
    prior_google = prior_google if isinstance(prior_google, dict) else {}
    google_data: dict[str, Any] = {
        "client_id": google.client_id,
        "client_secret": google.client_secret,
        "refresh_token": google.refresh_token,
    }
    # developer_token is legacy and optional (#751). Write the key only
    # when there is a value: a new setup omits it entirely, and an
    # operator who re-runs the wizard and skips the (now optional) prompt
    # keeps the harmless token they saved earlier rather than losing it.
    developer_token = google.developer_token or prior_google.get("developer_token")
    if developer_token:
        google_data["developer_token"] = developer_token
    # login_customer_id: authentication context (MCC for child accounts,
    # otherwise the account itself)
    google_data["login_customer_id"] = google.login_customer_id
    # customer_id: the account that operations target. Falls back to
    # login_customer_id when not explicitly specified, and finally to any
    # previously-saved customer_id so a re-auth whose account listing
    # transiently failed does not wipe the operator's prior selection.
    google_data["customer_id"] = (
        customer_id
        or google.customer_id
        or google.login_customer_id
        or prior_google.get("customer_id")
    )
    existing["google_ads"] = google_data


def _merge_meta_section(
    existing: dict[str, Any],
    meta: MetaAdsCredentials,
    account_id: str | None,
) -> None:
    """Merge the ``meta_ads`` block into ``existing`` in place."""
    prior_meta = existing.get("meta_ads")
    prior_meta = prior_meta if isinstance(prior_meta, dict) else {}
    access_token = getattr(meta, "access_token", "")
    meta_data: dict[str, Any] = {"access_token": access_token}
    # ``app_id`` / ``app_secret`` are preserved the same way ``account_id``
    # is: this call replaces the whole section, so a writer that simply has
    # nothing to say about the app pair would otherwise DELETE it. That is
    # what the paste route used to do — it saved a system-user token with no
    # app pair on the belief such a token never expires, and re-pasting a
    # token therefore disarmed an auto-refresh the operator had already
    # configured (#726). An explicit value still wins; "" clears.
    app_id = getattr(meta, "app_id", None)
    if app_id is not None:
        meta_data["app_id"] = app_id
    elif prior_meta.get("app_id"):
        meta_data["app_id"] = prior_meta["app_id"]
    app_secret = getattr(meta, "app_secret", None)
    if app_secret is not None:
        meta_data["app_secret"] = app_secret
    elif prior_meta.get("app_secret"):
        meta_data["app_secret"] = prior_meta["app_secret"]
    # Preserve a previously-saved account_id when this call couldn't resolve
    # one (e.g. the account listing failed): the whole meta_ads section is
    # replaced below, so without this a transient failure would silently drop
    # the operator's prior selection.
    if account_id is not None:
        meta_data["account_id"] = account_id
    elif prior_meta.get("account_id"):
        meta_data["account_id"] = prior_meta["account_id"]
    token_obtained_at = _resolve_token_obtained_at(meta, access_token, prior_meta)
    if token_obtained_at is not None:
        meta_data["token_obtained_at"] = token_obtained_at
    # Graph's "this one is permanent" verdict, resolved first because it
    # decides whether an expiry may be written at all (#740).
    never_expires = _resolve_token_bound_flag(
        meta, access_token, prior_meta, "token_never_expires"
    )
    if never_expires:
        meta_data["token_never_expires"] = True
    # All three describe THIS token, so all three follow the same rule:
    # explicit wins, a prior value survives only while the token is
    # unchanged, and a new token inherits none of them (#726). A token Meta
    # called permanent gets no expiry key beside the flag — a countdown and
    # "never" cannot both be true, and the flag is the one Graph stated.
    fields = ("token_type",) if never_expires else ("token_expires_at", "token_type")
    for field_name in fields:
        value = _resolve_token_bound_field(meta, access_token, prior_meta, field_name)
        if value is not None:
            meta_data[field_name] = value
    existing["meta_ads"] = meta_data


def _resolve_token_obtained_at(
    meta: MetaAdsCredentials,
    access_token: str,
    prior_meta: dict[str, Any],
) -> str | None:
    """When the Meta token was obtained, for the 53-day refresh clock.

    Without a persisted ``token_obtained_at`` the background refresh
    (auth.refresh_meta_token_if_needed) never fires and the long-lived token
    silently expires at ~60 days. Prefer an explicit timestamp on the
    credentials object; keep the prior timestamp when the token is unchanged
    (a metadata-only re-save must not reset the clock); otherwise stamp now.
    Returns ``None`` when there is no token to stamp (empty ``access_token``
    and no explicit timestamp), so no key is written — matching the prior
    behaviour exactly.
    """
    obtained_at = getattr(meta, "token_obtained_at", None)
    if obtained_at:
        return str(obtained_at)
    if not access_token:
        return None
    if access_token == prior_meta.get("access_token"):
        prior_ts = prior_meta.get("token_obtained_at")
        if prior_ts:
            return str(prior_ts)
    return datetime.now(tz=timezone.utc).isoformat()


def _resolve_token_bound_field(
    meta: MetaAdsCredentials,
    access_token: str,
    prior_meta: dict[str, Any],
    field_name: str,
) -> str | None:
    """Carry forward a fact that describes ONE SPECIFIC Meta token.

    Unlike ``token_obtained_at`` there is no "derive it now" fallback: both
    fields this backs are facts only Meta can supply (Graph ``debug_token``
    at paste time, or the ``expires_in`` of an exchange), and inventing one
    would put a countdown — or a token kind — on record that nothing backs.
    So:

    * an explicit value on the credentials object wins;
    * otherwise the prior value survives only while the token is UNCHANGED —
      a metadata-only re-save must not lose it, but a NEW token must never
      inherit the old one's;
    * otherwise no key is written, and every reader falls back to the
      pre-#726 behaviour exactly as before.
    """

    value = getattr(meta, field_name, None)
    if value:
        return str(value)
    if access_token and access_token == prior_meta.get("access_token"):
        prior_value = prior_meta.get(field_name)
        if prior_value:
            return str(prior_value)
    return None


def _resolve_token_bound_flag(
    meta: MetaAdsCredentials,
    access_token: str,
    prior_meta: dict[str, Any],
    field_name: str,
) -> bool:
    """:func:`_resolve_token_bound_field`'s rule, for a boolean verdict.

    Same three cases — explicit value wins, a prior value survives only
    while the token is UNCHANGED, otherwise nothing — but the answer is a
    ``bool`` rather than a string, so ``False`` reads as "not established"
    and the caller writes no key (#740).
    """

    if getattr(meta, field_name, False):
        return True
    if access_token and access_token == prior_meta.get("access_token"):
        return bool(prior_meta.get(field_name))
    return False


def _merge_sections(
    existing: dict[str, Any],
    google: GoogleAdsCredentials | None,
    meta: MetaAdsCredentials | None,
    customer_id: str | None,
    account_id: str | None,
    google_granted_scopes: Sequence[str] | None,
    resolved: Path,
) -> None:
    """Merge every section this save carries into ``existing`` in place."""
    if google is not None:
        _merge_google_section(existing, google, customer_id)
        if google_granted_scopes:
            sync_ga4_adc_from_google(
                existing,
                client_id=google.client_id,
                client_secret=google.client_secret,
                refresh_token=google.refresh_token,
                granted_scopes=google_granted_scopes,
                credentials_path=resolved,
            )
    if meta is not None:
        _merge_meta_section(existing, meta, account_id)


def save_credentials(
    path: Path | None = None,
    google: GoogleAdsCredentials | None = None,
    meta: MetaAdsCredentials | None = None,
    customer_id: str | None = None,
    account_id: str | None = None,
    *,
    google_granted_scopes: Sequence[str] | None = None,
) -> None:
    """Save credentials to credentials.json (merged with existing data).

    ``path=None`` resolves the destination through
    :func:`~mureo.core.runtime_context.runtime_credentials_path` rather
    than hardcoding the legacy default, so a runtime that relocates the
    ``SecretStore`` is honored on write and the wizard stops saving where
    nobody reads (#510). An explicit ``path`` is never redirected.

    Args:
        path: Path to credentials.json. Uses the runtime-resolved
            default path if None.
        google: Google Ads credentials
        meta: Meta Ads credentials
        customer_id: Google Ads account (login_customer_id)
        account_id: Meta Ads ad account ID
        google_granted_scopes: Scopes Google granted to ``google``; with
            GA4 read-only among them the ``ga4`` section is derived too.
    """
    resolved = path if path is not None else runtime_credentials_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    # ``load_existing_json`` RAISES on malformed JSON rather than reading it
    # as {} and erasing every other provider's auth; ``atomic_write_json``
    # (tmp + fsync + os.replace + 0o600) means a crash mid-write cannot brick
    # all providers. The cross-process ``file_lock`` keeps a concurrent Meta
    # auto-refresh (auth._save_meta_token) or another wizard run from
    # last-writer-wins away the section this call is not touching.
    with file_lock(lock_path_for(resolved)):
        existing: dict[str, Any] = load_existing_json(resolved)
        _merge_sections(
            existing,
            google,
            meta,
            customer_id,
            account_id,
            google_granted_scopes,
            resolved,
        )
        # Keep a .bak of the prior good file, then write atomically.
        backup_file(resolved)
        atomic_write_json(existing, resolved)

    logger.info("Credentials saved: %s", resolved)


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------


async def setup_google_ads(
    credentials_path: Path | None = None,
) -> GoogleAdsCredentials:
    """Interactive setup for Google Ads authentication.

    1. Display prerequisite guidance
    2. Developer Token input (optional, legacy)
    3. OAuth Client ID input
    4. OAuth Client Secret input
    5. Browser OAuth -> refresh_token retrieval
    6. Account list retrieval -> Customer ID selection
    7. Save to credentials.json

    Args:
        credentials_path: Path to credentials.json. Uses default path if None.

    Returns:
        GoogleAdsCredentials
    """
    print("\n=== Google Ads Setup ===\n")
    print("Please prepare the following in advance:")
    print(
        "  1. A Google Cloud project with Google Ads API access "
        "(APIs & Services > Google Ads API — sign up there; "
        "no manager account needed)"
    )
    print("  2. OAuth 2.0 Client ID / Client Secret (created in the GCP Console)")
    print("     - Application type: Desktop app")
    print("     (Redirect URI is managed automatically by InstalledAppFlow)")
    print(
        "  3. Developer Token: no longer issued by Google "
        "(optional; press Enter to skip)"
    )
    print()

    # Developer Token input — legacy and optional since 2026-09 (#751).
    developer_token = (
        input_func("Developer Token (optional, press Enter to skip): ").strip() or None
    )

    # OAuth Client ID / Secret input
    client_id = input_func("OAuth Client ID: ").strip()
    client_secret = input_func("OAuth Client Secret: ").strip()

    # Browser OAuth flow
    print(
        "\nA browser window will open. Log in with your Google account and grant access..."
    )
    oauth_result = await run_google_oauth(
        client_id=client_id,
        client_secret=client_secret,
    )
    print("OAuth authentication complete.\n")

    # Retrieve account list with temporary credentials
    temp_creds = GoogleAdsCredentials(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=oauth_result.refresh_token,
    )

    try:
        accounts = await _reexport("list_accessible_accounts")(temp_creds)
    except GoogleAdsAccountListError as exc:
        # The listing failing is no longer disguised as "no accounts"
        # (#746) — but it must not cost the operator the refresh token they
        # just granted either. Say what happened and fall through to the
        # save below with an empty roster.
        print(f"Could not list accessible accounts ({exc}).")
        print("You can manually add the Customer ID to credentials.json later.")
        accounts = []

    selected_id: str | None = None
    login_customer_id: str | None = None

    if accounts:
        print("Accessible accounts:\n")
        selected_id = _select_account(accounts)
        if selected_id is not None:
            # If the selected account was reached via an MCC, use the MCC as
            # login_customer_id. Otherwise use the account itself.
            selected_account = next(
                (a for a in accounts if a["id"] == selected_id), None
            )
            if selected_account and selected_account.get("parent_id"):
                login_customer_id = selected_account["parent_id"]
            else:
                login_customer_id = selected_id
    else:
        print("No accessible accounts found.")
        print("You can manually add the Customer ID to credentials.json later.")

    # Generate final credentials. customer_id is the target account;
    # login_customer_id is the MCC for accounts reached via an MCC, or
    # the account itself for directly accessible accounts.
    final_creds = GoogleAdsCredentials(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=oauth_result.refresh_token,
        login_customer_id=login_customer_id,
        customer_id=selected_id,
    )

    save_credentials(
        path=credentials_path,
        google=final_creds,
        google_granted_scopes=oauth_result.granted_scopes,
    )
    _print_google_setup_done(credentials_path or runtime_credentials_path())

    return final_creds


def _print_google_setup_done(path: Path) -> None:
    """Close the Google setup with where it saved and what GA4 can reuse.

    ``path`` is the one ``save_credentials`` actually wrote to — resolving it
    any other way would print the legacy location while the write went to a
    runtime-relocated store (#510).
    """
    print(f"\nCredentials saved: {path}")
    print("Google Ads setup complete.\n")
    if store_has_managed_ga4(path):
        print(
            "GA4 (ga4-official) can use this authorization: "
            "run `mureo providers add ga4-official`."
        )


# ===========================================================================
# Meta Ads section
# ===========================================================================


# ---------------------------------------------------------------------------
# Meta auth URL generation
# ---------------------------------------------------------------------------


def build_meta_auth_url(
    *,
    app_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    """Build a Facebook OAuth authorization URL.

    Public helper shared between the interactive CLI (which passes
    ``http://localhost:<port>/callback``) and the web wizard (which
    passes ``http://127.0.0.1:<port>/meta-ads/callback``). The
    localhost-only guard rejects any ``redirect_uri`` outside
    ``http://127.0.0.1`` / ``http://localhost`` so a prompt-injected
    caller cannot redirect Facebook's grant to a remote host.

    ``state`` is required (CSRF protection for the callback) — callers
    must generate a ``secrets.token_urlsafe`` value and compare it on
    callback with ``secrets.compare_digest``.
    """
    _validate_local_redirect_uri(redirect_uri)
    params: dict[str, str] = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": META_OAUTH_SCOPES,
        "response_type": "code",
        "state": state,
    }
    return f"{_META_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_meta_code(
    *,
    code: str,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
) -> MetaOAuthResult:
    """Exchange a Meta authorization ``code`` for a Long-Lived Token.

    Composes two upstream API calls:

    1. ``code`` + ``redirect_uri`` + app secret -> short-lived token.
    2. Short-lived token + app secret -> long-lived token (60 days).

    Both steps already live as private helpers in this module; this
    wrapper is the public entry point for callers that have received
    an authorization code on their own OAuth callback handler (web
    wizard).
    """
    short_token = await _exchange_code_for_short_token(
        code=code,
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
    )
    return await _exchange_short_for_long_token(
        short_token=short_token,
        app_id=app_id,
        app_secret=app_secret,
    )


def _generate_meta_auth_url(
    app_id: str,
    port: int,
    state: str | None = None,
) -> str:
    """Generate a Facebook OAuth authorization URL.

    Legacy helper used by the interactive CLI path. Shape preserved
    because existing tests assert that ``state`` is omitted from the
    URL when ``None`` is passed. New code should call
    :func:`build_meta_auth_url` instead, which requires a non-empty
    ``state`` for CSRF protection.
    """
    params: dict[str, str] = {
        "client_id": app_id,
        "redirect_uri": f"http://localhost:{port}/callback",
        "scope": META_OAUTH_SCOPES,
        "response_type": "code",
    }
    if state is not None:
        params["state"] = state
    return f"{_META_AUTH_URL}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------------------
# Meta Token exchange: Code -> Short-Lived Token
# ---------------------------------------------------------------------------


async def _exchange_code_for_short_token(
    *,
    code: str,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
) -> str:
    """Obtain a Short-Lived Token from an authorization code.

    Args:
        code: Authorization code obtained from Facebook authentication
        app_id: Meta (Facebook) app ID
        app_secret: Meta (Facebook) app secret
        redirect_uri: Callback URI

    Returns:
        Short-Lived access token

    Raises:
        RuntimeError: If Short-Lived Token retrieval fails.
    """
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "client_secret": app_secret,
        "code": code,
    }

    try:
        # POST so the client_secret and authorization code sit in the request
        # body, not the URL. Meta's Graph ``/oauth/access_token`` accepts these
        # parameters via POST as well as GET, and httpx logs ``request.url`` at
        # INFO — a GET would leak the secret and code into any INFO-level log.
        async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                OAUTH_TOKEN_URL,
                data=params,
            )
            response.raise_for_status()
            data = response.json()
            return data["access_token"]  # type: ignore[no-any-return]
    except Exception as exc:
        raise RuntimeError(f"Failed to retrieve Short-Lived Token: {exc}") from exc


# ---------------------------------------------------------------------------
# Meta Token exchange: Short-Lived -> Long-Lived Token
# ---------------------------------------------------------------------------


async def _exchange_short_for_long_token(
    *,
    short_token: str,
    app_id: str,
    app_secret: str,
) -> MetaOAuthResult:
    """Convert a Short-Lived Token to a Long-Lived Token (valid for 60 days).

    Args:
        short_token: Short-Lived access token
        app_id: Meta (Facebook) app ID
        app_secret: Meta (Facebook) app secret

    Returns:
        MetaOAuthResult (Long-Lived Token + expiration).

    Raises:
        RuntimeError: If conversion to Long-Lived Token fails.
    """
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }

    try:
        # POST so the client_secret and the short-lived token travel in the
        # request body, not the URL. Meta's Graph ``/oauth/access_token``
        # accepts these parameters via POST as well as GET, and httpx logs
        # ``request.url`` at INFO — a GET would leak the secret and token into
        # any INFO-level log.
        async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                OAUTH_TOKEN_URL,
                data=params,
            )
            response.raise_for_status()
            data = response.json()
            return MetaOAuthResult(
                access_token=data["access_token"],
                expires_in=data.get("expires_in", 5184000),
            )
    except Exception as exc:
        raise RuntimeError(f"Failed to convert to Long-Lived Token: {exc}") from exc


# ---------------------------------------------------------------------------
# Meta Ads OAuth flow
# ---------------------------------------------------------------------------


async def run_meta_oauth(
    app_id: str,
    app_secret: str,
    port: int = 0,
) -> MetaOAuthResult:
    """Execute the Facebook OAuth flow to obtain a Long-Lived Token.

    1. Start local HTTP server (background)
    2. Open Facebook OAuth URL in browser
    3. User authenticates and authorizes via Facebook
    4. Receive authorization code via callback
    5. Convert Code -> Short-Lived Token -> Long-Lived Token

    Args:
        app_id: Meta (Facebook) app ID
        app_secret: Meta (Facebook) app secret
        port: Local server port (0=auto-select)

    Returns:
        MetaOAuthResult (Long-Lived Token + expiration).
    """
    # CSRF protection: generate random state token
    state = secrets.token_urlsafe(32)

    # Use shared OAuthCallbackServer
    callback_server = OAuthCallbackServer(port=port, expected_state=state)
    actual_port = callback_server.server.server_address[1]

    # Generate auth URL
    auth_url = _generate_meta_auth_url(app_id=app_id, port=actual_port, state=state)

    # Wait for callback in background
    server_thread = threading.Thread(
        target=callback_server.wait_for_callback, daemon=True
    )
    server_thread.start()

    # Open auth URL in browser. We deliberately do NOT print the URL —
    # it carries the OAuth ``state`` token (replay guard for the
    # callback round-trip) and the user does not need to see it once
    # the browser has loaded the page. Falling back to a manual paste
    # if `webbrowser.open` fails is handled by the surrounding error
    # path; printing the URL unconditionally is clear-text logging
    # of sensitive data per CodeQL's data-flow analysis.
    print("\nOpening authentication page in browser...")
    webbrowser.open(auth_url)

    # Wait for callback
    server_thread.join(timeout=300)

    if callback_server.error:
        raise RuntimeError(f"Authentication error: {callback_server.error}")

    if callback_server.authorization_code is None:
        raise RuntimeError("Authentication timed out")

    redirect_uri = f"http://localhost:{actual_port}/callback"
    code = callback_server.authorization_code

    # Code -> Short-Lived Token
    print("Obtaining Short-Lived Token...")
    short_token = await _exchange_code_for_short_token(
        code=code,
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
    )

    # Short-Lived -> Long-Lived Token
    print("Converting to Long-Lived Token...")
    result = await _exchange_short_for_long_token(
        short_token=short_token,
        app_id=app_id,
        app_secret=app_secret,
    )

    print(
        f"Authentication successful! Token valid for: {result.expires_in // 86400} days"
    )
    return result


# ---------------------------------------------------------------------------
# Meta Ads setup wizard
# ---------------------------------------------------------------------------


async def setup_meta_ads(
    credentials_path: Path | None = None,
) -> MetaAdsCredentials:
    """Interactive setup for Meta Ads authentication.

    1. Display prerequisite guidance
    2. App ID input
    3. App Secret input
    4. Browser OAuth -> access_token retrieval -> Long-Lived conversion
    5. Ad account list retrieval -> Account ID selection
    6. Save to credentials.json

    Args:
        credentials_path: Path to credentials.json. Uses default path if None.

    Returns:
        MetaAdsCredentials
    """
    # Resolved once, then passed to ``save_credentials`` as an explicit
    # path and echoed to the operator. It must go through the same seam
    # ``save_credentials`` would have used for ``path=None``, or this
    # pre-resolution would silently pin the wizard to the legacy file and
    # bypass a runtime-relocated store (#510).
    resolved_path = (
        credentials_path if credentials_path is not None else runtime_credentials_path()
    )

    # Display guidance
    print("\n=== Meta Ads Setup ===")
    print("")
    print("Prerequisites:")
    print(
        "  1. Create an app at Meta for Developers (https://developers.facebook.com/)"
    )
    print("  2. Obtain App ID and App Secret from the app settings")
    print("  3. Under Products > Facebook Login > Settings,")
    print("     add http://localhost to Valid OAuth Redirect URIs")
    print("")

    # App ID / App Secret input (replaceable via input_func for testing)
    app_id = input_func("App ID: ").strip()
    app_secret = input_func("App Secret: ").strip()

    # OAuth flow execution
    print("\nStarting Facebook authentication...")
    oauth_result = await run_meta_oauth(app_id=app_id, app_secret=app_secret)

    # Retrieve ad account list
    print("\nRetrieving ad account list...")
    accounts = await _reexport("list_meta_ad_accounts")(
        access_token=oauth_result.access_token
    )

    if not accounts:
        raise RuntimeError(
            "No ad accounts found. Please check your access permissions."
        )

    # Account selection
    if len(accounts) == 1:
        selected = accounts[0]
        print(f"\nAd account: {_account_label(selected)}")
    else:
        print("\nPlease select an ad account:\n")

        def _meta_label(a: dict[str, Any]) -> str:
            status = "active" if a.get("account_status") == 1 else "inactive"
            return f"{_account_label(a)} [{status}]"

        selected_id = _select_account(accounts, label_fn=_meta_label)
        if selected_id is not None:
            selected = next(a for a in accounts if a["id"] == selected_id)
        else:
            selected = accounts[0]
            print(f"Default: {_account_label(selected)}")

    account_id: str = selected["id"]

    # Save to credentials.json (using shared save_credentials function).
    # ``account_id`` is carried on the returned object as well as persisted:
    # a caller that trusts the return value must see the same ad account that
    # was written to disk, exactly as setup_google_ads returns its selected
    # customer_id.
    meta_creds = MetaAdsCredentials(
        access_token=oauth_result.access_token,
        app_id=app_id,
        app_secret=app_secret,
        account_id=account_id,
    )

    save_credentials(
        path=resolved_path,
        meta=meta_creds,
        account_id=account_id,
    )

    print(f"\nCredentials saved: {resolved_path}")
    print(f"Account: {_account_label(selected)}")

    return meta_creds
