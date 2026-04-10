"""Authentication setup wizard

Interactively configure credentials via mureo auth setup.
Google Ads: Developer Token input -> Browser OAuth -> refresh_token retrieval -> Customer ID selection
Meta Ads: App ID/Secret input -> Browser OAuth -> Long-Lived Token retrieval -> Account ID selection
"""

from __future__ import annotations

import html
import http.server
import json
import logging
import os
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from google_auth_oauthlib.flow import InstalledAppFlow

from mureo.auth import GoogleAdsCredentials, MetaAdsCredentials

logger = logging.getLogger(__name__)

_GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
_SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters"
_GOOGLE_SCOPES = [_GOOGLE_ADS_SCOPE, _SEARCH_CONSOLE_SCOPE]


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
        label_fn = lambda a: f"{a['name']} ({a['id']})"  # noqa: E731

    labels = [label_fn(a) for a in accounts]

    try:
        from simple_term_menu import TerminalMenu

        menu = TerminalMenu(labels, title="Select with ↑↓ and press Enter to confirm:")
        idx = menu.show()
        if idx is None:
            print("Selection cancelled. You can configure it later.")
            return None
        selected = accounts[idx]
        print(f"Selected: {selected['name']} ({selected['id']})")
        return selected["id"]  # type: ignore[no-any-return]
    except ImportError:
        # Fall back to number input if simple-term-menu is not available
        for i, label in enumerate(labels, 1):
            print(f"  {i}. {label}")
        print()
        try:
            choice = int(input("Enter number: ").strip())
            if 1 <= choice <= len(accounts):
                selected = accounts[choice - 1]
                print(f"Selected: {selected['name']} ({selected['id']})")
                return selected["id"]  # type: ignore[no-any-return]
        except (ValueError, IndexError):
            pass
        print("Invalid selection. You can configure it later.")
        return None


_META_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_META_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
_META_OAUTH_SCOPES = (
    "ads_management,ads_read,business_management,"
    "pages_show_list,pages_manage_ads,pages_read_engagement,leads_retrieval"
)

_HTTP_TIMEOUT = 30.0

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
        """Suppress log output to stdout."""
        logger.debug(fmt, *args)


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


async def run_google_oauth(
    client_id: str,
    client_secret: str,
) -> OAuthResult:
    """Run browser OAuth via InstalledAppFlow to obtain a refresh_token.

    Uses InstalledAppFlow from google-auth-oauthlib to handle local server startup,
    browser authentication, callback reception, and token exchange.

    Args:
        client_id: OAuth Client ID
        client_secret: OAuth Client Secret

    Returns:
        OAuthResult（refresh_token, access_token）

    Raises:
        RuntimeError: If OAuth authentication fails.
    """
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=_GOOGLE_SCOPES,
    )

    # Browser OAuth (local server auto-starts and auto-stops)
    # port=0 lets the OS pick an available port automatically, avoiding
    # conflicts with other processes. Google OAuth "installed app" clients
    # accept http://localhost on any port.
    credentials = flow.run_local_server(port=0, prompt="consent")

    if credentials.refresh_token is None:
        raise RuntimeError("Failed to obtain refresh_token")

    return OAuthResult(
        refresh_token=credentials.refresh_token,
        access_token=credentials.token,
    )


# ---------------------------------------------------------------------------
# Account list retrieval
# ---------------------------------------------------------------------------


async def list_accessible_accounts(
    credentials: GoogleAdsCredentials,
) -> list[dict[str, Any]]:
    """Retrieve the list of accessible accounts via Google Ads API.

    Uses the Google Ads SDK directly to enumerate accessible accounts.
    Since GoogleAdsApiClient in mureo-core requires a customer_id,
    direct SDK calls are needed for account discovery during setup.

    Args:
        credentials: Google Ads credentials

    Returns:
        List of account info dicts (id, name).
    """
    from google.ads.googleads.client import GoogleAdsClient
    from google.oauth2.credentials import Credentials as OAuthCredentials

    oauth_creds = OAuthCredentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=credentials.refresh_token,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )

    ga_client = GoogleAdsClient(
        credentials=oauth_creds,
        developer_token=credentials.developer_token,
        login_customer_id=credentials.login_customer_id,
    )

    try:
        customer_service = ga_client.get_service("CustomerService")
        response = customer_service.list_accessible_customers()
    except Exception:
        logger.warning("Failed to retrieve account list", exc_info=True)
        return []

    # Retrieve descriptive_name for each account
    ga_service = ga_client.get_service("GoogleAdsService")
    accounts: list[dict[str, Any]] = []
    for resource_name in response.resource_names:
        customer_id = resource_name.split("/")[-1]
        name = customer_id  # fallback
        try:
            query = "SELECT customer.descriptive_name FROM customer LIMIT 1"
            rows = ga_service.search(customer_id=customer_id, query=query)
            for row in rows:
                name = row.customer.descriptive_name or customer_id
                break
        except Exception:
            logger.debug("Failed to retrieve account name: %s", customer_id)
        accounts.append({"id": customer_id, "name": name})

    return accounts


# ---------------------------------------------------------------------------
# MCP configuration deployment
# ---------------------------------------------------------------------------

_MCP_SERVER_CONFIG = {
    "command": "python",
    "args": ["-m", "mureo.mcp"],
}


def install_mcp_config(scope: str = "global") -> Path | None:
    """Add MCP configuration to the Claude Code settings file.

    Global: Merge into mcpServers in ~/.claude/settings.json
    Project: Merge into .mcp.json in the current directory

    Skips if mureo is already configured.

    Args:
        scope: "global" (~/.claude/settings.json) or "project" (.mcp.json)

    Returns:
        Path to the settings file. None if skipped.
    """
    if scope == "global":
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        # Project-level MCP config goes in .mcp.json
        settings_path = Path.cwd() / ".mcp.json"

    # Load existing settings
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Get or create mcpServers section
    mcp_servers = existing.setdefault("mcpServers", {})

    # Skip if mureo is already configured
    if "mureo" in mcp_servers:
        logger.info("MCP configuration already exists: %s", settings_path)
        return None

    # Add mureo
    mcp_servers["mureo"] = _MCP_SERVER_CONFIG
    existing["mcpServers"] = mcp_servers

    # Create directory and write
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
        from simple_term_menu import TerminalMenu

        options = [
            "Global (~/.claude/settings.json) — Available in all projects",
            "This directory (.mcp.json) — This project only",
            "Skip (configure manually)",
        ]
        menu = TerminalMenu(
            options, title="Where should the MCP configuration be placed?"
        )
        idx = menu.show()
        if idx is None or idx == 2:
            print("MCP configuration skipped.")
            return
        scope = "global" if idx == 0 else "project"
    except ImportError:
        # Fallback: number input
        print("Where should the MCP configuration be placed?")
        print("  1. Global (~/.claude/settings.json) — Available in all projects")
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

# Unique identifier to detect mureo-installed hooks
_MUREO_HOOK_TAG = "[mureo-credential-guard]"

_CREDENTIAL_GUARD_HOOK_READ = {
    "matcher": "Read",
    "hooks": [
        {
            "type": "command",
            "command": (
                f'python3 -c "'
                f"import sys,json; "
                f"d=json.loads(sys.stdin.read()); "
                f"p=d.get('tool_input',{{}}).get('file_path',''); "
                f"sys.exit(1) if 'credentials' in p and '.mureo' in p else sys.exit(0)"
                f'" # {_MUREO_HOOK_TAG}'
            ),
        }
    ],
}

_CREDENTIAL_GUARD_HOOK_BASH = {
    "matcher": "Bash",
    "hooks": [
        {
            "type": "command",
            "command": (
                f'python3 -c "'
                f"import sys,json; "
                f"d=json.loads(sys.stdin.read()); "
                f"c=d.get('tool_input',{{}}).get('command',''); "
                f"sys.exit(1) if '.mureo/credentials' in c or "
                f"('.mureo' in c and 'credentials' in c) else sys.exit(0)"
                f'" # {_MUREO_HOOK_TAG}'
            ),
        }
    ],
}


def install_credential_guard() -> Path | None:
    """Add PreToolUse hooks to block AI agents from reading credentials.

    Safely merges into ~/.claude/settings.json without overwriting
    existing hooks. Uses a tag comment to detect previously installed
    mureo hooks and avoid duplicates.

    Returns:
        Path to settings file if hooks were added. None if skipped
        (already installed or file could not be parsed).
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

    # Get or create hooks.PreToolUse
    hooks = existing.setdefault("hooks", {})
    pre_tool_use: list[dict[str, Any]] = hooks.setdefault("PreToolUse", [])

    # Check if mureo hooks are already installed (by tag)
    for entry in pre_tool_use:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            if _MUREO_HOOK_TAG in cmd:
                logger.info("Credential guard already installed: %s", settings_path)
                return None

    # Append mureo hooks (do NOT replace existing hooks)
    pre_tool_use.append(_CREDENTIAL_GUARD_HOOK_READ)
    pre_tool_use.append(_CREDENTIAL_GUARD_HOOK_BASH)

    # Write back (preserve all existing content)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    logger.info("Credential guard hooks installed: %s", settings_path)
    return settings_path


# ---------------------------------------------------------------------------
# credentials.json saving
# ---------------------------------------------------------------------------


def save_credentials(
    path: Path | None = None,
    google: GoogleAdsCredentials | None = None,
    meta: MetaAdsCredentials | None = None,
    customer_id: str | None = None,
    account_id: str | None = None,
) -> None:
    """Save credentials to credentials.json (merged with existing data).

    Args:
        path: Path to credentials.json. Uses default path if None.
        google: Google Ads credentials
        meta: Meta Ads credentials
        customer_id: Google Ads account (login_customer_id)
        account_id: Meta Ads ad account ID
    """
    resolved = path if path is not None else _resolve_default_path()

    # Create directory
    resolved.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data
    existing: dict[str, Any] = {}
    if resolved.exists():
        try:
            existing = json.loads(resolved.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Merge Google Ads credentials
    if google is not None:
        google_data: dict[str, Any] = {
            "developer_token": google.developer_token,
            "client_id": google.client_id,
            "client_secret": google.client_secret,
            "refresh_token": google.refresh_token,
        }
        login_cid = customer_id or google.login_customer_id
        if login_cid is not None:
            google_data["login_customer_id"] = login_cid
        else:
            google_data["login_customer_id"] = None
        existing["google_ads"] = google_data

    # Merge Meta Ads credentials
    if meta is not None:
        meta_data: dict[str, Any] = {
            "access_token": getattr(meta, "access_token", ""),
        }
        app_id = getattr(meta, "app_id", None)
        if app_id is not None:
            meta_data["app_id"] = app_id
        app_secret = getattr(meta, "app_secret", None)
        if app_secret is not None:
            meta_data["app_secret"] = app_secret
        if account_id is not None:
            meta_data["account_id"] = account_id
        existing["meta_ads"] = meta_data

    # Write file
    resolved.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Set permissions (owner read/write only)
    os.chmod(resolved, 0o600)

    logger.info("Credentials saved: %s", resolved)


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------


async def setup_google_ads(
    credentials_path: Path | None = None,
) -> GoogleAdsCredentials:
    """Interactive setup for Google Ads authentication.

    1. Display prerequisite guidance
    2. Developer Token input
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
    print("  1. Google Ads Developer Token (from the Google Ads API Center)")
    print("  2. OAuth 2.0 Client ID / Client Secret (created in the GCP Console)")
    print("     - Application type: Desktop app")
    print("     (Redirect URI is managed automatically by InstalledAppFlow)")
    print()

    # Developer Token input
    developer_token = input_func("Developer Token: ").strip()

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

    accounts = await list_accessible_accounts(temp_creds)

    login_customer_id: str | None = None

    if accounts:
        print("Accessible accounts:\n")
        login_customer_id = _select_account(accounts)
    else:
        print("No accessible accounts found.")
        print("You can manually add the Customer ID to credentials.json later.")

    # Generate final credentials
    final_creds = GoogleAdsCredentials(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=oauth_result.refresh_token,
        login_customer_id=login_customer_id,
    )

    # Save
    save_credentials(
        path=credentials_path,
        google=final_creds,
        customer_id=login_customer_id,
    )

    print(f"\nCredentials saved: {credentials_path or _resolve_default_path()}")
    print("Google Ads setup complete.\n")

    return final_creds


# ===========================================================================
# Meta Ads section
# ===========================================================================


# ---------------------------------------------------------------------------
# Meta auth URL generation
# ---------------------------------------------------------------------------


def _generate_meta_auth_url(
    app_id: str,
    port: int,
    state: str | None = None,
) -> str:
    """Generate a Facebook OAuth authorization URL.

    Args:
        app_id: Meta (Facebook) app ID
        port: Local callback server port number
        state: State parameter for CSRF protection

    Returns:
        Authorization URL string.
    """
    params: dict[str, str] = {
        "client_id": app_id,
        "redirect_uri": f"http://localhost:{port}/callback",
        "scope": _META_OAUTH_SCOPES,
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
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/oauth/access_token",
                params=params,
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
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/oauth/access_token",
                params=params,
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
# Meta ad account list retrieval
# ---------------------------------------------------------------------------


async def list_meta_ad_accounts(access_token: str) -> list[dict[str, Any]]:
    """Retrieve ad account list via Graph API.

    GET https://graph.facebook.com/v21.0/me/adaccounts?
        fields=id,name,account_status&
        access_token={access_token}

    Args:
        access_token: Meta Ads access token

    Returns:
        List of ad account dicts (id, name, account_status).

    Raises:
        RuntimeError: If ad account list retrieval fails.
    """
    params = {
        "fields": "id,name,account_status",
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/me/adaccounts",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])  # type: ignore[no-any-return]
    except Exception as exc:
        raise RuntimeError(f"Failed to retrieve ad account list: {exc}") from exc


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

    # Open auth URL in browser
    print("\nOpening authentication page in browser...")
    print(f"URL: {auth_url}")
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
    resolved_path = (
        credentials_path if credentials_path is not None else _resolve_default_path()
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
    accounts = await list_meta_ad_accounts(access_token=oauth_result.access_token)

    if not accounts:
        raise RuntimeError(
            "No ad accounts found. Please check your access permissions."
        )

    # Account selection
    if len(accounts) == 1:
        selected = accounts[0]
        print(f"\nAd account: {selected['name']} ({selected['id']})")
    else:
        print("\nPlease select an ad account:\n")

        def _meta_label(a: dict[str, Any]) -> str:
            status = "active" if a.get("account_status") == 1 else "inactive"
            return f"{a['name']} ({a['id']}) [{status}]"

        selected_id = _select_account(accounts, label_fn=_meta_label)
        if selected_id is not None:
            selected = next(a for a in accounts if a["id"] == selected_id)
        else:
            selected = accounts[0]
            print(f"Default: {selected['name']} ({selected['id']})")

    account_id: str = selected["id"]

    # Save to credentials.json (using shared save_credentials function)
    meta_creds = MetaAdsCredentials(
        access_token=oauth_result.access_token,
        app_id=app_id,
        app_secret=app_secret,
    )

    save_credentials(
        path=resolved_path,
        meta=meta_creds,
        account_id=account_id,
    )

    print(f"\nCredentials saved: {resolved_path}")
    print(f"Account: {selected['name']} ({account_id})")

    return meta_creds


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_default_path() -> Path:
    """Resolve the default credentials.json path."""
    return Path.home() / ".mureo" / "credentials.json"
