"""Browser-based OAuth wizard for non-technical users.

``mureo auth setup --web`` starts a short-lived localhost HTTP server
and opens the operator's browser to a simple form. The user pastes
the Google Ads Developer Token / OAuth Client ID / Secret, clicks
"Continue", completes Google OAuth in the same browser window, and
the wizard saves ``~/.mureo/credentials.json`` without requiring any
terminal interaction.

Design choices and safety properties:

- **Stdlib only.** ``http.server.HTTPServer`` +
  ``BaseHTTPRequestHandler``. No external Web framework dependency.
- **Random local port.** Bind to ``127.0.0.1:0`` so the OS picks a
  free port; the URL is printed once at startup.
- **Localhost only.** Bind address is always ``127.0.0.1``; the
  shared ``build_google_flow`` helper validates ``redirect_uri`` is
  localhost-only as a second layer.
- **CSRF.** Every form POST carries a hidden ``csrf_token`` input
  that must match the per-session token. Compared with
  ``secrets.compare_digest``.
- **No external resources.** Inline CSS only; no CDN fetches, no JS
  frameworks. Prevents a supply-chain compromise from injecting into
  the wizard page.
- **Server dies on completion.** The ``/done`` page marks the
  wizard complete; callers can check ``wizard.completed`` and shut
  down once they're satisfied.
- **Session is in-memory only.** No persistence beyond the save of
  final credentials. If the process dies before ``/done`` the half-
  entered secrets are lost — desired, not regrettable.

Meta Ads support ships in a follow-up PR (P2-3).
"""

from __future__ import annotations

import contextlib
import html
import http.server
import logging
import secrets as _secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mureo.auth import GoogleAdsCredentials

if TYPE_CHECKING:
    from pathlib import Path
from mureo.auth_setup import (
    build_google_flow,
    exchange_google_code,
    google_auth_url,
    save_credentials,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def _fresh_csrf_token() -> str:
    return _secrets.token_urlsafe(32)


@dataclass
class WizardSession:
    """In-memory state for a single setup run.

    Not thread-safe — the wizard is single-user by design; only one
    browser tab drives it at a time. Fields start as ``None`` and are
    populated as the user walks through the flow.
    """

    csrf_token: str = field(default_factory=_fresh_csrf_token)
    google_flow: Any = None
    google_developer_token: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_state: str | None = None

    def rotate_csrf(self) -> None:
        """Regenerate the CSRF token after a successful mutating POST.

        Prevents replay — once the submit handler accepts a token, that
        same token cannot be reused by another tab or a Back-button
        resubmission.
        """
        self.csrf_token = _fresh_csrf_token()

    def clear_secrets(self) -> None:
        """Zero secret fields after credentials have been persisted.

        The Flow object still holds a copy internally; we can't reach
        into google-auth, but mureo's own session copies are cleared.
        """
        self.google_developer_token = None
        self.google_client_id = None
        self.google_client_secret = None
        self.google_flow = None
        self.google_oauth_state = None


# ---------------------------------------------------------------------------
# HTML templates (inline, escaped)
# ---------------------------------------------------------------------------


_BASE_STYLE = """<style>
body { font-family: -apple-system, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; color: #222; }
h1 { border-bottom: 1px solid #eee; padding-bottom: 8px; }
form { margin: 24px 0; }
label { display: block; margin: 12px 0 4px; font-weight: 600; }
input[type=text], input[type=password] { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; box-sizing: border-box; }
.hint { color: #666; font-size: 13px; margin-top: 2px; }
.hint a { color: #06c; }
button { margin-top: 16px; padding: 10px 20px; background: #06c; color: white; border: 0; border-radius: 4px; cursor: pointer; font-size: 14px; }
button:hover { background: #05a; }
.notice { background: #f5f9ff; border-left: 4px solid #06c; padding: 12px 16px; margin: 16px 0; font-size: 13px; }
</style>"""


def render_home(session: WizardSession) -> str:  # noqa: ARG001
    """Platform chooser — first page the user sees."""
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>mureo setup</title>{_BASE_STYLE}</head>
<body>
<h1>mureo setup</h1>
<p>Pick the ad platform you want to configure.</p>
<form method="get" action="/google-ads">
  <button type="submit">Configure Google Ads</button>
</form>
<p class="notice">Meta Ads support is coming soon — it will appear here as a second button once the related release ships.</p>
</body></html>
"""


def render_google_secrets_form(session: WizardSession) -> str:
    """Form for Developer Token / Client ID / Secret."""
    csrf = html.escape(session.csrf_token, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Google Ads — mureo setup</title>{_BASE_STYLE}</head>
<body>
<h1>Google Ads credentials</h1>
<p>Paste the three values below. Links next to each field take you to the page in Google's console where each value is displayed.</p>
<form method="post" action="/google-ads/submit">
  <input type="hidden" name="csrf_token" value="{csrf}">

  <label for="developer_token">Developer Token</label>
  <input id="developer_token" name="developer_token" type="text" required autocomplete="off">
  <div class="hint">Available in the Google Ads API Center — <a href="https://ads.google.com/aw/apicenter" target="_blank" rel="noopener">ads.google.com/aw/apicenter</a>. Requires an approved Google Ads manager account.</div>

  <label for="client_id">OAuth Client ID</label>
  <input id="client_id" name="client_id" type="text" required autocomplete="off">
  <div class="hint">Create an OAuth 2.0 client (Application type: Desktop) in <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">Google Cloud Console → APIs &amp; Services → Credentials</a>.</div>

  <label for="client_secret">OAuth Client Secret</label>
  <input id="client_secret" name="client_secret" type="password" required autocomplete="off">
  <div class="hint">Shown once when the OAuth client is created. Re-open the client in Cloud Console to copy it again.</div>

  <button type="submit">Continue to Google sign-in</button>
</form>
<p class="notice">Nothing leaves your machine. The next page is Google's own sign-in, and the refresh token it returns is written to <code>~/.mureo/credentials.json</code> locally.</p>
</body></html>
"""


def render_done() -> str:
    """Shown after Google OAuth + credentials save complete."""
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>mureo setup — done</title>{_BASE_STYLE}</head>
<body>
<h1>Setup complete</h1>
<p>Credentials saved to <code>~/.mureo/credentials.json</code>. You can close this tab.</p>
<p class="notice">Restart Claude Desktop (or your MCP client) to pick up the new configuration.</p>
</body></html>
"""


def render_error(message: str) -> str:
    safe = html.escape(message)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>mureo setup — error</title>{_BASE_STYLE}</head>
<body>
<h1>Something went wrong</h1>
<p>{safe}</p>
<p><a href="/">Back to start</a></p>
</body></html>
"""


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class _WizardServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """ThreadingHTTPServer with a ``wizard`` attribute for handlers."""

    daemon_threads = True
    allow_reuse_address = True
    wizard: WebAuthWizard


class _WizardHandler(http.server.BaseHTTPRequestHandler):
    """Route dispatcher for the wizard HTTP server."""

    server: _WizardServer

    # --- routing ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_html(render_home(self.server.wizard.session))
        elif path == "/google-ads":
            self._send_html(render_google_secrets_form(self.server.wizard.session))
        elif path == "/google-ads/callback":
            self._handle_google_callback(parsed.query)
        elif path == "/done":
            self._send_html(render_done())
            self.server.wizard.mark_completed()
        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/google-ads/submit":
            self._handle_google_submit()
        else:
            self.send_error(404, "Not found")

    # --- route implementations ------------------------------------------

    _MAX_FORM_BYTES = 16 * 1024  # 16 KiB cap; secrets are short.
    _GOOGLE_AUTH_ORIGIN = "https://accounts.google.com/"

    def _handle_google_submit(self) -> None:
        if not self._host_header_ok():
            self.send_error(403, "Host header not allowed (DNS rebinding guard)")
            return

        form = self._read_form()
        if form is None:
            self.send_error(413, "Payload too large")
            return
        if not self._csrf_ok(form.get("csrf_token", "")):
            self.send_error(403, "CSRF token invalid")
            return

        dev_token = form.get("developer_token", "").strip()
        client_id = form.get("client_id", "").strip()
        client_secret = form.get("client_secret", "").strip()
        if not (dev_token and client_id and client_secret):
            self._send_html(render_error("All three fields are required."), status=400)
            return

        redirect_uri = (
            f"http://127.0.0.1:{self.server.server_address[1]}/google-ads/callback"
        )
        try:
            flow = build_google_flow(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
            )
            auth_url, state = google_auth_url(flow)
        except Exception:
            logger.exception("Failed to build Google OAuth URL")
            self._send_html(
                render_error(
                    "Could not start Google OAuth. "
                    "Verify the Client ID / Secret and retry."
                ),
                status=500,
            )
            return

        if not auth_url.startswith(self._GOOGLE_AUTH_ORIGIN):
            # Defensive: build_google_flow should always yield a
            # Google-owned URL, but enforce explicitly so the wizard
            # cannot become an open redirect.
            logger.error("Refusing 302 to non-Google URL: %s", auth_url)
            self._send_html(
                render_error("Unexpected OAuth destination; aborting."),
                status=500,
            )
            return

        sess = self.server.wizard.session
        sess.google_flow = flow
        sess.google_developer_token = dev_token
        sess.google_client_id = client_id
        sess.google_client_secret = client_secret
        sess.google_oauth_state = state
        sess.rotate_csrf()  # Invalidate the token we just consumed.

        self.send_response(302)
        self.send_header("Location", auth_url)
        self.end_headers()

    def _handle_google_callback(self, query: str) -> None:
        if not self._host_header_ok():
            self.send_error(403, "Host header not allowed (DNS rebinding guard)")
            return

        params = urllib.parse.parse_qs(query)
        code = params.get("code", [""])[0]
        returned_state = params.get("state", [""])[0]
        oauth_error = params.get("error", [""])[0]
        sess = self.server.wizard.session

        # Google redirects here with ``error=access_denied`` etc. when
        # the user declines or Google refuses the authorization. Show a
        # friendly message instead of a bare 400.
        if oauth_error:
            self._send_html(
                render_error(
                    f"Google sign-in was cancelled or refused "
                    f"(error: {oauth_error}). Return to / and retry."
                ),
                status=400,
            )
            return

        if not code or sess.google_flow is None:
            self.send_error(
                400,
                "Missing authorization code or no in-progress OAuth flow",
            )
            return

        expected_state = sess.google_oauth_state or ""
        if not expected_state or not _secrets.compare_digest(
            returned_state, expected_state
        ):
            logger.warning("OAuth state mismatch on callback")
            self.send_error(
                403,
                "OAuth state mismatch -- possible CSRF or link reuse",
            )
            return

        try:
            result = exchange_google_code(sess.google_flow, code)
        except Exception:
            logger.exception("Google token exchange failed")
            self._send_html(
                render_error(
                    "Google rejected the authorization. "
                    "Re-open the wizard at / and retry."
                ),
                status=400,
            )
            return

        creds = GoogleAdsCredentials(
            developer_token=sess.google_developer_token or "",
            client_id=sess.google_client_id or "",
            client_secret=sess.google_client_secret or "",
            refresh_token=result.refresh_token,
        )
        save_credentials(path=self.server.wizard.credentials_path, google=creds)
        sess.clear_secrets()  # Zero session state now that it's persisted.

        self.send_response(302)
        self.send_header("Location", "/done")
        self.end_headers()

    # --- helpers ---------------------------------------------------------

    def _host_header_ok(self) -> bool:
        """Defend against DNS-rebinding: the browser's Host must match
        127.0.0.1:<port> or localhost:<port>. A malicious page resolving
        attacker.com to 127.0.0.1 would otherwise POST to the wizard
        with the attacker origin intact."""
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _csrf_ok(self, supplied: str) -> bool:
        expected = self.server.wizard.session.csrf_token
        return bool(supplied) and _secrets.compare_digest(supplied, expected)

    def _read_form(self) -> dict[str, str] | None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > self._MAX_FORM_BYTES:
            return None
        body = self.rfile.read(length) if length else b""
        return {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8")).items()}

    def _send_html(self, body: str, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header(
            "Content-Security-Policy",
            (
                "default-src 'none'; "
                "style-src 'unsafe-inline'; "
                "base-uri 'none'; "
                "frame-ancestors 'none'; "
                "object-src 'none'; "
                "form-action 'self' https://accounts.google.com"
            ),
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        # Client may have closed the tab between headers and body —
        # swallow the resulting broken-pipe so it doesn't spam logs.
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """Route HTTP access logs through the logger (quieter by default)."""
        logger.debug(fmt, *args)


# ---------------------------------------------------------------------------
# WebAuthWizard — public API
# ---------------------------------------------------------------------------


class WebAuthWizard:
    """Browser-driven OAuth wizard."""

    def __init__(
        self,
        *,
        bind_host: str = "127.0.0.1",
        credentials_path: Path | None = None,
    ) -> None:
        self._bind_host = bind_host
        self.credentials_path = credentials_path
        self.session = WizardSession()
        self.completed = False

        self._server: _WizardServer | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("serve() has not been called yet")
        return int(self._server.server_address[1])

    def home_url(self) -> str:
        return f"http://{self._bind_host}:{self.port}/"

    def serve(self) -> None:
        """Block and serve requests until :meth:`shutdown` is called."""
        with _WizardServer((self._bind_host, 0), _WizardHandler) as server:
            server.wizard = self
            self._server = server
            self._ready.set()
            try:
                server.serve_forever(poll_interval=0.1)
            finally:
                with self._lock:
                    self._server = None

    def wait_until_ready(self, timeout: float = 5.0) -> None:
        """Block until the server has bound its socket."""
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError("wizard failed to bind within timeout")

    def shutdown(self) -> None:
        with self._lock:
            server = self._server
        if server is not None:
            server.shutdown()

    def mark_completed(self) -> None:
        self.completed = True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def run_web_wizard(
    *,
    credentials_path: Path | None = None,
    open_browser: bool = True,
    timeout_seconds: float = 600.0,
) -> None:
    """Start the wizard, open the browser, wait for completion."""
    wizard = WebAuthWizard(credentials_path=credentials_path)
    thread = threading.Thread(target=wizard.serve, daemon=True)
    thread.start()
    wizard.wait_until_ready()

    url = wizard.home_url()
    print(f"mureo setup wizard running at {url}")
    print("(the browser should open automatically; if not, copy the URL)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            logger.exception("Could not open browser automatically")

    deadline = time.monotonic() + timeout_seconds
    try:
        while not wizard.completed:
            if time.monotonic() > deadline:
                print("Timed out waiting for setup completion.")
                return
            time.sleep(0.5)
        print("Setup complete.")
    finally:
        wizard.shutdown()
        thread.join(timeout=2.0)
