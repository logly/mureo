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

import asyncio
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
from typing import TYPE_CHECKING, Any, TypeVar

from mureo.auth import GoogleAdsCredentials, MetaAdsCredentials
from mureo.auth_setup import (
    build_google_flow,
    build_meta_auth_url,
    exchange_google_code,
    exchange_meta_code,
    google_auth_url,
    list_accessible_accounts,
    list_meta_ad_accounts,
    save_credentials,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


_T = TypeVar("_T")


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run an async coroutine from inside a sync HTTP handler.

    ``BaseHTTPRequestHandler`` is sync-only, but Meta's token-exchange
    helpers are ``async`` (they use ``httpx.AsyncClient``). Each
    request-handling thread has no running loop, so we spin a fresh
    one and drop it when done.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
    # Held between /google-ads/callback and the user's picker submit.
    google_refresh_token: str | None = None
    google_accessible_accounts: list[dict[str, Any]] | None = None

    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    meta_oauth_state: str | None = None
    # Held between /meta-ads/callback and the user's picker submit.
    meta_access_token: str | None = None
    meta_ad_accounts: list[dict[str, Any]] | None = None

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
        self.google_refresh_token = None
        self.google_accessible_accounts = None
        self.meta_app_id = None
        self.meta_app_secret = None
        self.meta_oauth_state = None
        self.meta_access_token = None
        self.meta_ad_accounts = None


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
button.btn-finish { background: #1f9d55; }
button.btn-finish:hover { background: #176f3c; }
button.btn-secondary { background: white; color: #555; border: 1px solid #bbb; }
button.btn-secondary:hover { background: #f2f2f2; color: #222; }
.notice { background: #f5f9ff; border-left: 4px solid #06c; padding: 12px 16px; margin: 16px 0; font-size: 13px; }
</style>"""


def render_home(session: WizardSession) -> str:  # noqa: ARG001
    """Platform chooser — first page the user sees."""
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>mureo setup</title>{_BASE_STYLE}</head>
<body>
<h1>mureo setup</h1>
<p>Pick the ad platform you want to configure. You can run both in sequence from this wizard.</p>
<form method="get" action="/google-ads" style="display:inline-block; margin-right:12px">
  <button type="submit">Configure Google Ads</button>
</form>
<form method="get" action="/meta-ads" style="display:inline-block">
  <button type="submit">Configure Meta Ads</button>
</form>
</body></html>
"""


def render_meta_secrets_form(session: WizardSession) -> str:
    """Form for Meta App ID / Secret."""
    csrf = html.escape(session.csrf_token, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Meta Ads — mureo setup</title>{_BASE_STYLE}</head>
<body>
<h1>Meta Ads credentials</h1>
<p>Paste the App ID and App Secret from your Meta for Developers app.</p>
<form method="post" action="/meta-ads/submit">
  <input type="hidden" name="csrf_token" value="{csrf}">

  <label for="meta_app_id">App ID</label>
  <input id="meta_app_id" name="app_id" type="text" required autocomplete="off">
  <div class="hint">Find or create your app on <a href="https://developers.facebook.com/apps/" target="_blank" rel="noopener">Meta for Developers → My Apps</a>. The App ID appears on the app's dashboard.</div>

  <label for="meta_app_secret">App Secret</label>
  <input id="meta_app_secret" name="app_secret" type="password" required autocomplete="off">
  <div class="hint">On the app dashboard, open <em>Settings → Basic</em> and click <em>Show</em> next to App Secret. Development Mode is fine — App Review is not required when operating your own ad account.</div>

  <button type="submit">Continue to Facebook sign-in</button>
</form>
<p class="notice">During sign-in you may see a permission warning for <code>business_management</code>. This is required for ad accounts reached through a Business Portfolio and is safe to accept.</p>
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


def render_finish_confirm(return_platform: str) -> str:
    """Yes/No confirmation page before terminating the wizard.

    ``return_platform`` is the platform slug the user came from on
    `/after-platform` so "No" can send them back. Unknown values fall
    back to ``google`` which is harmless for the return path.
    """
    safe_platform = (
        return_platform if return_platform in {"google", "meta"} else "google"
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Finish setup? — mureo</title>{_BASE_STYLE}</head>
<body>
<h1>Finish setup?</h1>
<p>This will close the wizard. You can re-run <code>mureo auth setup --web</code> later if you need to reconfigure.</p>
<form method="get" action="/done" style="display:inline-block; margin-right:12px">
  <button class="btn-finish" type="submit">Yes, finish</button>
</form>
<form method="get" action="/after-platform" style="display:inline-block">
  <input type="hidden" name="platform" value="{html.escape(safe_platform, quote=True)}">
  <button class="btn-secondary" type="submit">No, go back</button>
</form>
</body></html>
"""


def render_done(configured: set[str]) -> str:
    """Terminal page. Message adapts to which platforms are configured.

    ``configured`` is the set of platform slugs ({"google", "meta"}) as
    determined from the on-disk credentials.json.
    """
    if configured == {"google", "meta"}:
        headline = "Google Ads and Meta Ads are configured."
    elif configured == {"google"}:
        headline = "Google Ads is configured."
    elif configured == {"meta"}:
        headline = "Meta Ads is configured."
    else:
        # Defensive — /done shouldn't normally be reached with no
        # platforms, but render a neutral page instead of crashing.
        headline = "Setup complete."
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>mureo setup — done</title>{_BASE_STYLE}</head>
<body>
<h1>Setup complete</h1>
<p>{html.escape(headline)} You can close this tab.</p>
<p class="notice">Credentials saved to <code>~/.mureo/credentials.json</code>. Restart Claude Desktop (or your MCP client) to pick up the new configuration.</p>
</body></html>
"""


def render_google_account_picker(
    session: WizardSession, accounts: list[dict[str, Any]]
) -> str:
    """Radio-group picker for a Google Ads customer_id.

    ``accounts`` is the list returned by ``list_accessible_accounts``:
    dicts with ``id``, ``name``, ``is_manager``, ``parent_id``.
    """
    csrf = html.escape(session.csrf_token, quote=True)
    if not accounts:
        return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Google Ads — choose account</title>{_BASE_STYLE}</head>
<body>
<h1>No Google Ads accounts found</h1>
<p class="notice">We could not find any Google Ads accounts reachable by this login. You can continue, but no <code>customer_id</code> will be recorded.</p>
<p><a href="/after-platform?platform=google&amp;warn=no_accounts">Continue</a></p>
</body></html>
"""
    rows = []
    for idx, acct in enumerate(accounts):
        acct_id = html.escape(str(acct.get("id", "")), quote=True)
        name = html.escape(str(acct.get("name", "")))
        is_manager = bool(acct.get("is_manager"))
        parent_id = acct.get("parent_id")
        badges: list[str] = []
        if is_manager:
            badges.append("MCC")
        if parent_id:
            badges.append(f"child of {html.escape(str(parent_id))}")
        badge_html = (
            f" <span class='hint'>({'; '.join(badges)})</span>" if badges else ""
        )
        checked = " checked" if idx == 0 else ""
        rows.append(
            f"""<label style="display:flex; align-items:baseline; gap:8px; margin:6px 0; font-weight:normal">
  <input type="radio" name="account_id" value="{acct_id}"{checked} required>
  <span><code>{acct_id}</code> — {name}{badge_html}</span>
</label>"""
        )
    rows_html = "\n".join(rows)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Google Ads — choose account</title>{_BASE_STYLE}</head>
<body>
<h1>Choose a Google Ads account</h1>
<p>Pick the account you want mureo to operate on. For a child account reached through a manager (MCC), the manager is used automatically as the login context.</p>
<form method="post" action="/google-ads/select-account">
  <input type="hidden" name="csrf_token" value="{csrf}">
  {rows_html}
  <button type="submit">Save selection</button>
</form>
</body></html>
"""


def render_meta_account_picker(
    session: WizardSession, accounts: list[dict[str, Any]]
) -> str:
    """Radio-group picker for a Meta ad account."""
    csrf = html.escape(session.csrf_token, quote=True)
    if not accounts:
        return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Meta Ads — choose account</title>{_BASE_STYLE}</head>
<body>
<h1>No Meta ad accounts found</h1>
<p class="notice">We could not find any ad accounts reachable by this login. You can continue, but no <code>account_id</code> will be recorded.</p>
<p><a href="/after-platform?platform=meta&amp;warn=no_accounts">Continue</a></p>
</body></html>
"""
    rows = []
    for idx, acct in enumerate(accounts):
        acct_id = html.escape(str(acct.get("id", "")), quote=True)
        name = html.escape(str(acct.get("name", "")))
        checked = " checked" if idx == 0 else ""
        rows.append(
            f"""<label style="display:flex; align-items:baseline; gap:8px; margin:6px 0; font-weight:normal">
  <input type="radio" name="account_id" value="{acct_id}"{checked} required>
  <span><code>{acct_id}</code> — {name}</span>
</label>"""
        )
    rows_html = "\n".join(rows)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Meta Ads — choose account</title>{_BASE_STYLE}</head>
<body>
<h1>Choose a Meta ad account</h1>
<p>Pick the ad account you want mureo to operate on.</p>
<form method="post" action="/meta-ads/select-account">
  <input type="hidden" name="csrf_token" value="{csrf}">
  {rows_html}
  <button type="submit">Save selection</button>
</form>
</body></html>
"""


def render_after_platform(
    configured: set[str],
    just_completed: str,
    warn: str | None = None,
) -> str:
    """Intermediate "what next?" page after one platform finishes."""
    labels = {"google": "Google Ads", "meta": "Meta Ads"}
    just_label = labels.get(just_completed, just_completed)

    warning_block = ""
    if warn == "no_accounts":
        warning_block = (
            '<p class="notice" style="border-left-color:#c90">'
            "Warning: we could not list any accounts for "
            f"{html.escape(just_label)}. Credentials were saved, but no "
            "account_id was recorded. You can re-run setup later to "
            "select one, or continue without it.</p>"
        )

    # "Configure the other platform too" CTA. We offer it for any
    # platform that is BOTH not-yet-configured AND not the one the user
    # just finished (so we don't suggest "Configure Google too" right
    # after a Google submit). ``configured`` is the usable-credentials
    # set; ``just_completed`` is the path the user just came from — it
    # may not appear in ``configured`` when the account list was empty.
    remaining = {"google", "meta"} - configured - {just_completed}
    other_cta = ""
    if remaining:
        other = next(iter(remaining))
        other_label = labels.get(other, other)
        other_path = "/google-ads" if other == "google" else "/meta-ads"
        other_cta = (
            f'<form method="get" action="{other_path}" '
            'style="display:inline-block; margin-right:12px">'
            f'<button type="submit">Configure {html.escape(other_label)} too</button>'
            "</form>"
        )

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{html.escape(just_label)} — configured</title>{_BASE_STYLE}</head>
<body>
<h1>{html.escape(just_label)} is configured</h1>
{warning_block}
<p>What next?</p>
{other_cta}
<form method="get" action="/done/confirm" style="display:inline-block">
  <input type="hidden" name="platform" value="{html.escape(just_completed, quote=True)}">
  <button class="btn-finish" type="submit">Finish setup</button>
</form>
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
        elif path == "/google-ads/select-account":
            self._handle_google_account_pick_page()
        elif path == "/meta-ads":
            self._send_html(render_meta_secrets_form(self.server.wizard.session))
        elif path == "/meta-ads/callback":
            self._handle_meta_callback(parsed.query)
        elif path == "/meta-ads/select-account":
            self._handle_meta_account_pick_page()
        elif path == "/after-platform":
            self._handle_after_platform(parsed.query)
        elif path == "/done/confirm":
            params = urllib.parse.parse_qs(parsed.query)
            platform = params.get("platform", [""])[0]
            self._send_html(render_finish_confirm(platform))
        elif path == "/done":
            configured = self._configured_platforms()
            self._send_html(render_done(configured))
            self.server.wizard.mark_completed()
        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/google-ads/submit":
            self._handle_google_submit()
        elif parsed.path == "/google-ads/select-account":
            self._handle_google_account_submit()
        elif parsed.path == "/meta-ads/submit":
            self._handle_meta_submit()
        elif parsed.path == "/meta-ads/select-account":
            self._handle_meta_account_submit()
        else:
            self.send_error(404, "Not found")

    # --- route implementations ------------------------------------------

    _MAX_FORM_BYTES = 16 * 1024  # 16 KiB cap; secrets are short.
    _GOOGLE_AUTH_ORIGIN = "https://accounts.google.com/"
    _META_AUTH_ORIGIN = "https://www.facebook.com/"

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
            # Use the `localhost` hostname rather than the literal
            # 127.0.0.1. Meta's OAuth treats the two differently — IP
            # literals trigger an "insecure connection" warning screen
            # in the Facebook login dialog, while `localhost` is
            # whitelisted as a dev origin. Google accepts both; we use
            # `localhost` for symmetry with the Meta redirect below and
            # with the legacy terminal flow. The wizard server still
            # binds 127.0.0.1 and the Host-header guard accepts both
            # names.
            f"http://localhost:{self.server.server_address[1]}/google-ads/callback"
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
        # NB: csrf_token is NOT rotated here. This submit is an
        # OAuth-URL build — nothing is persisted to disk yet, and
        # rotating mid-flow causes a cached Back-button re-submission
        # (or a parallel tab on /meta-ads) to fail with 403. The OAuth
        # `state` parameter provides independent replay protection for
        # the callback round-trip. Rotation happens at the commit point
        # (`/google-ads/select-account/submit`) instead.

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

        refresh_token = result.refresh_token
        # Build a probe credential to query the Google Ads API for
        # accessible accounts. This is the gap the terminal flow was
        # already filling and the web flow was silently skipping.
        probe_creds = GoogleAdsCredentials(
            developer_token=sess.google_developer_token or "",
            client_id=sess.google_client_id or "",
            client_secret=sess.google_client_secret or "",
            refresh_token=refresh_token,
        )
        try:
            accounts = _run_async(list_accessible_accounts(probe_creds))
        except Exception as exc:  # noqa: BLE001
            # Log only the exception class — the google-ads SDK
            # sometimes embeds request arguments (which could include
            # the developer_token / client_secret) in exception
            # repr/__str__. Writing a full traceback to stderr via
            # exc_info=True would leak those. Type alone is enough
            # to triage.
            logger.warning(
                "Could not list Google Ads accounts (%s) — proceeding "
                "without customer_id",
                type(exc).__name__,
            )
            accounts = []

        if not accounts:
            # Save what we have and let the user continue; they don't
            # lose the refresh token.
            save_credentials(
                path=self.server.wizard.credentials_path,
                google=probe_creds,
            )
            sess.clear_secrets()
            self.send_response(302)
            self.send_header(
                "Location",
                "/after-platform?platform=google&warn=no_accounts",
            )
            self.end_headers()
            return

        # Park the refresh token + account list until the picker submit.
        sess.google_refresh_token = refresh_token
        sess.google_accessible_accounts = accounts
        sess.google_flow = None  # Flow object no longer needed.
        sess.google_oauth_state = None
        sess.rotate_csrf()  # New form, new token.

        self.send_response(302)
        self.send_header("Location", "/google-ads/select-account")
        self.end_headers()

    # --- Google account picker ------------------------------------------

    def _handle_google_account_pick_page(self) -> None:
        sess = self.server.wizard.session
        if not sess.google_accessible_accounts:
            # Stale link or direct URL guess; bounce home.
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
        self._send_html(
            render_google_account_picker(sess, sess.google_accessible_accounts)
        )

    def _handle_google_account_submit(self) -> None:
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

        sess = self.server.wizard.session
        accounts = sess.google_accessible_accounts or []
        if not accounts or not sess.google_refresh_token:
            self.send_error(400, "No pending Google account selection")
            return

        chosen_id = form.get("account_id", "").strip()
        match = next((a for a in accounts if str(a.get("id")) == chosen_id), None)
        if match is None:
            self._send_html(
                render_error("Selected account is not in the authorized list."),
                status=400,
            )
            return

        parent_id = match.get("parent_id")
        login_cid = str(parent_id) if parent_id else chosen_id
        creds = GoogleAdsCredentials(
            developer_token=sess.google_developer_token or "",
            client_id=sess.google_client_id or "",
            client_secret=sess.google_client_secret or "",
            refresh_token=sess.google_refresh_token,
            login_customer_id=login_cid,
            customer_id=chosen_id,
        )
        save_credentials(
            path=self.server.wizard.credentials_path,
            google=creds,
            customer_id=chosen_id,
        )
        sess.clear_secrets()
        sess.rotate_csrf()

        self.send_response(302)
        self.send_header("Location", "/after-platform?platform=google")
        self.end_headers()

    # --- Meta flow ------------------------------------------------------

    def _handle_meta_submit(self) -> None:
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

        app_id = form.get("app_id", "").strip()
        app_secret = form.get("app_secret", "").strip()
        if not (app_id and app_secret):
            self._send_html(
                render_error("App ID and App Secret are required."), status=400
            )
            return

        redirect_uri = (
            f"http://localhost:{self.server.server_address[1]}/meta-ads/callback"
        )
        state = _secrets.token_urlsafe(32)
        try:
            auth_url = build_meta_auth_url(
                app_id=app_id, redirect_uri=redirect_uri, state=state
            )
        except Exception:
            logger.exception("Failed to build Meta OAuth URL")
            self._send_html(
                render_error(
                    "Could not start Meta OAuth. "
                    "Verify the App ID / Secret and retry."
                ),
                status=500,
            )
            return

        if not auth_url.startswith(self._META_AUTH_ORIGIN):
            logger.error("Refusing 302 to non-Meta URL: %s", auth_url)
            self._send_html(
                render_error("Unexpected OAuth destination; aborting."),
                status=500,
            )
            return

        sess = self.server.wizard.session
        sess.meta_app_id = app_id
        sess.meta_app_secret = app_secret
        sess.meta_oauth_state = state
        # See matching comment in `_handle_google_submit` — csrf is not
        # rotated here so a back/refresh from Facebook's OAuth page
        # doesn't wedge the wizard. The Meta `state` parameter is the
        # replay guard for the callback round-trip.

        self.send_response(302)
        self.send_header("Location", auth_url)
        self.end_headers()

    def _handle_meta_callback(self, query: str) -> None:
        if not self._host_header_ok():
            self.send_error(403, "Host header not allowed (DNS rebinding guard)")
            return

        params = urllib.parse.parse_qs(query)
        code = params.get("code", [""])[0]
        returned_state = params.get("state", [""])[0]
        # Meta uses ``error_reason`` / ``error`` on user denial.
        oauth_error = (
            params.get("error", [""])[0] or params.get("error_reason", [""])[0]
        )
        sess = self.server.wizard.session

        if oauth_error:
            self._send_html(
                render_error(
                    f"Facebook sign-in was cancelled or refused "
                    f"(error: {oauth_error}). Return to / and retry."
                ),
                status=400,
            )
            return

        if not code or sess.meta_app_id is None:
            self.send_error(
                400,
                "Missing authorization code or no in-progress Meta flow",
            )
            return

        expected_state = sess.meta_oauth_state or ""
        if not expected_state or not _secrets.compare_digest(
            returned_state, expected_state
        ):
            logger.warning("Meta OAuth state mismatch on callback")
            self.send_error(
                403,
                "OAuth state mismatch -- possible CSRF or link reuse",
            )
            return

        redirect_uri = (
            f"http://localhost:{self.server.server_address[1]}/meta-ads/callback"
        )
        try:
            result = _run_async(
                exchange_meta_code(
                    code=code,
                    app_id=sess.meta_app_id,
                    app_secret=sess.meta_app_secret or "",
                    redirect_uri=redirect_uri,
                )
            )
        except Exception:
            logger.exception("Meta token exchange failed")
            self._send_html(
                render_error(
                    "Facebook rejected the authorization. "
                    "Re-open the wizard at / and retry."
                ),
                status=400,
            )
            return

        access_token = result.access_token
        try:
            accounts = _run_async(list_meta_ad_accounts(access_token))
        except Exception as exc:  # noqa: BLE001
            # See Google-side comment above: don't emit the traceback
            # because it may contain the access_token in the request
            # URL / exception args.
            logger.warning(
                "Could not list Meta ad accounts (%s) — proceeding "
                "without account_id",
                type(exc).__name__,
            )
            accounts = []

        if not accounts:
            creds = MetaAdsCredentials(
                access_token=access_token,
                app_id=sess.meta_app_id,
                app_secret=sess.meta_app_secret or "",
            )
            save_credentials(
                path=self.server.wizard.credentials_path,
                meta=creds,
            )
            sess.clear_secrets()
            self.send_response(302)
            self.send_header(
                "Location",
                "/after-platform?platform=meta&warn=no_accounts",
            )
            self.end_headers()
            return

        sess.meta_access_token = access_token
        sess.meta_ad_accounts = accounts
        sess.meta_oauth_state = None
        sess.rotate_csrf()

        self.send_response(302)
        self.send_header("Location", "/meta-ads/select-account")
        self.end_headers()

    # --- Meta account picker --------------------------------------------

    def _handle_meta_account_pick_page(self) -> None:
        sess = self.server.wizard.session
        if not sess.meta_ad_accounts:
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
        self._send_html(render_meta_account_picker(sess, sess.meta_ad_accounts))

    def _handle_meta_account_submit(self) -> None:
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

        sess = self.server.wizard.session
        accounts = sess.meta_ad_accounts or []
        if not accounts or not sess.meta_access_token:
            self.send_error(400, "No pending Meta account selection")
            return

        chosen_id = form.get("account_id", "").strip()
        match = next((a for a in accounts if str(a.get("id")) == chosen_id), None)
        if match is None:
            self._send_html(
                render_error("Selected account is not in the authorized list."),
                status=400,
            )
            return

        creds = MetaAdsCredentials(
            access_token=sess.meta_access_token,
            app_id=sess.meta_app_id,
            app_secret=sess.meta_app_secret or "",
            account_id=chosen_id,
        )
        save_credentials(
            path=self.server.wizard.credentials_path,
            meta=creds,
            account_id=chosen_id,
        )
        sess.clear_secrets()
        sess.rotate_csrf()

        self.send_response(302)
        self.send_header("Location", "/after-platform?platform=meta")
        self.end_headers()

    # --- After-platform intermediate ------------------------------------

    def _handle_after_platform(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        platform = params.get("platform", [""])[0]
        warn = params.get("warn", [None])[0]
        configured = self._configured_platforms()
        # Note: do NOT bounce to `/` when ``configured`` is empty. A
        # partial save (refresh_token without customer_id on a
        # no-accounts fallback) leaves credentials.json non-usable but
        # still mid-flow — we need the user to reach the Finish button,
        # not get kicked back to the home screen with no feedback.
        if platform not in {"google", "meta"}:
            # Direct URL guess with no platform hint — pick whichever
            # the user has made any progress on, defaulting to Google.
            platform = (
                "google"
                if "google" in configured
                else ("meta" if "meta" in configured else "google")
            )
        self._send_html(
            render_after_platform(configured, just_completed=platform, warn=warn)
        )

    def _configured_platforms(self) -> set[str]:
        """Inspect credentials.json and report which platforms have
        non-empty credentials. Quiet about missing/unreadable files."""
        import json

        path = self.server.wizard.credentials_path
        if path is None or not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return set()
        configured: set[str] = set()
        g = data.get("google_ads") or {}
        # A platform counts as configured only if the credentials are
        # actually usable — refresh_token alone without customer_id
        # produces API calls that fail, and the wizard must not lie to
        # the user on `/done` by declaring an incomplete setup "complete".
        if g.get("refresh_token") and g.get("customer_id"):
            configured.add("google")
        m = data.get("meta_ads") or {}
        if m.get("access_token") and m.get("account_id"):
            configured.add("meta")
        return configured

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
        try:
            decoded = body.decode("utf-8")
        except UnicodeDecodeError:
            # Malformed body — refuse as oversized/invalid rather than
            # letting the exception bubble to a 500.
            return None
        return {k: v[0] for k, v in urllib.parse.parse_qs(decoded).items()}

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
                # form-action is checked through the entire redirect
                # chain in modern browsers, so the Meta submit
                # (/meta-ads/submit → 302 to facebook.com) needs both
                # self AND www.facebook.com allowed, not just self.
                # Same reasoning for Google.
                "form-action 'self' https://accounts.google.com "
                "https://www.facebook.com"
            ),
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # Browser caching of wizard pages would serve a stale CSRF token
        # on the next visit (the server has since rotated). Always fetch
        # fresh so the hidden csrf_token input matches session state.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
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
