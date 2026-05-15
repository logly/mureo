"""Browser-based OAuth wizard for per-platform credential setup.

The configure UI (``mureo configure``) spawns this wizard via
``mureo.web.oauth_bridge`` for a single platform at a time. The user
pastes the Google Ads Developer Token / OAuth Client ID / Secret (or
Meta App ID / Secret), clicks "Continue", completes OAuth in the same
browser window, and the wizard saves ``~/.mureo/credentials.json``
without requiring any terminal interaction.

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
import urllib.parse
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
    # Locale chosen in the parent configure UI; threaded through the
    # ``?locale=`` query string on the first GET into this wizard so
    # the inline (English-by-default) HTML can switch to Japanese
    # without growing a full i18n catalog. Allow-list: "en" | "ja".
    locale: str = "en"
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


# Inline bilingual strings — kept here (rather than in the configure
# UI's i18n.json) because this wizard is a stand-alone process spun up
# per platform and must not depend on the configure UI's static assets.
# Add a new key here AND a JA translation when introducing user-facing
# copy. The lookup is a simple per-locale dict; missing keys fall back
# to English. NEVER place a secret or user input in these strings.
_I18N: dict[str, dict[str, str]] = {
    "en": {
        "meta.title": "Meta Ads — mureo setup",
        "meta.heading": "Meta Ads credentials",
        "meta.intro": "Paste the App ID and App Secret from your Meta for Developers app.",
        "meta.app_id_label": "App ID",
        "meta.app_id_hint": 'Find or create your app on <a href="https://developers.facebook.com/apps/" target="_blank" rel="noopener">Meta for Developers → My Apps</a>. The App ID appears on the app\'s dashboard.',
        "meta.app_secret_label": "App Secret",
        "meta.app_secret_hint": "On the app dashboard, open <em>Settings → Basic</em> and click <em>Show</em> next to App Secret. Development Mode is fine — App Review is not required when operating your own ad account.",
        "meta.submit": "Continue to Facebook sign-in",
        "meta.notice": "During sign-in you may see a permission warning for <code>business_management</code>. This is required for ad accounts reached through a Business Portfolio and is safe to accept.",
        "google.title": "Google Ads — mureo setup",
        "google.heading": "Google Ads credentials",
        "google.intro": "Paste the three values below. Links next to each field take you to the page in Google's console where each value is displayed.",
        "google.dev_token_label": "Developer Token",
        "google.dev_token_hint": 'Available in the Google Ads API Center — <a href="https://ads.google.com/aw/apicenter" target="_blank" rel="noopener">ads.google.com/aw/apicenter</a>. Requires an approved Google Ads manager account.',
        "google.client_id_label": "OAuth Client ID",
        "google.client_id_hint": 'Create an OAuth 2.0 client (Application type: Desktop) in <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">Google Cloud Console → APIs &amp; Services → Credentials</a>.',
        "google.client_secret_label": "OAuth Client Secret",
        "google.client_secret_hint": "Shown once when the OAuth client is created. Re-open the client in Cloud Console to copy it again.",
        "google.submit": "Continue to Google sign-in",
        "google.notice": "Nothing leaves your machine. The next page is Google's own sign-in, and the refresh token it returns is written to <code>~/.mureo/credentials.json</code> locally.",
        "google_picker.title": "Google Ads — choose account",
        "google_picker.heading": "Choose a Google Ads account",
        "google_picker.intro": "Pick the account you want mureo to operate on. For a child account reached through a manager (MCC), the manager is used automatically as the login context.",
        "google_picker.submit": "Save selection",
        "google_picker.empty_heading": "No Google Ads accounts found",
        "google_picker.empty_notice": "We could not find any Google Ads accounts reachable by this login. You can continue, but no <code>customer_id</code> will be recorded.",
        "google_picker.continue": "Continue",
        "meta_picker.title": "Meta Ads — choose account",
        "meta_picker.heading": "Choose a Meta ad account",
        "meta_picker.intro": "Pick the ad account you want mureo to operate on.",
        "meta_picker.submit": "Save selection",
        "meta_picker.empty_heading": "No Meta ad accounts found",
        "meta_picker.empty_notice": "We could not find any ad accounts reachable by this login. You can continue, but no <code>account_id</code> will be recorded.",
        "meta_picker.continue": "Continue",
    },
    "ja": {
        "meta.title": "Meta Ads — mureo セットアップ",
        "meta.heading": "Meta Ads 認証情報",
        "meta.intro": "Meta for Developers アプリの App ID と App Secret を貼り付けてください。",
        "meta.app_id_label": "App ID",
        "meta.app_id_hint": '<a href="https://developers.facebook.com/apps/" target="_blank" rel="noopener">Meta for Developers → My Apps</a> でアプリを作成または開いてください。App ID はアプリのダッシュボードに表示されます。',
        "meta.app_secret_label": "App Secret",
        "meta.app_secret_hint": "アプリのダッシュボードで <em>Settings → Basic</em> を開き、App Secret の隣の <em>Show</em> をクリックします。Development Mode のままで OK — 自社の広告アカウントを使う限り App Review は不要です。",
        "meta.submit": "Facebook サインインに進む",
        "meta.notice": "サインイン中に <code>business_management</code> のパーミッション警告が表示されることがあります。Business Portfolio 経由の広告アカウントに必要な権限で、許可しても安全です。",
        "google.title": "Google Ads — mureo セットアップ",
        "google.heading": "Google Ads 認証情報",
        "google.intro": "下記の 3 つの値を貼り付けてください。各項目のリンクをクリックすると、Google 管理画面の該当ページが開きます。",
        "google.dev_token_label": "Developer Token",
        "google.dev_token_hint": 'Google Ads API センター — <a href="https://ads.google.com/aw/apicenter" target="_blank" rel="noopener">ads.google.com/aw/apicenter</a> から取得できます。承認済みの Google Ads マネージャアカウントが必要です。',
        "google.client_id_label": "OAuth Client ID",
        "google.client_id_hint": '<a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">Google Cloud Console → APIs &amp; Services → Credentials</a> で OAuth 2.0 クライアント（種別: Desktop）を作成してください。',
        "google.client_secret_label": "OAuth Client Secret",
        "google.client_secret_hint": "OAuth クライアント作成時に一度だけ表示されます。Cloud Console で再度開いてコピーしてください。",
        "google.submit": "Google サインインに進む",
        "google.notice": "情報はマシンの外に出ません。次は Google 自身のサインインで、返却された refresh token はローカルの <code>~/.mureo/credentials.json</code> に保存されます。",
        "google_picker.title": "Google Ads — アカウント選択",
        "google_picker.heading": "Google Ads アカウントを選択",
        "google_picker.intro": "mureo に操作させたいアカウントを選んでください。MCC 配下の子アカウントを選んだ場合、ログインコンテキストには自動的にマネージャが使われます。",
        "google_picker.submit": "選択を保存",
        "google_picker.empty_heading": "Google Ads アカウントが見つかりません",
        "google_picker.empty_notice": "このログインで到達可能な Google Ads アカウントが見つかりませんでした。続行できますが、<code>customer_id</code> は記録されません。",
        "google_picker.continue": "続行",
        "meta_picker.title": "Meta Ads — アカウント選択",
        "meta_picker.heading": "Meta 広告アカウントを選択",
        "meta_picker.intro": "mureo に操作させたい広告アカウントを選んでください。",
        "meta_picker.submit": "選択を保存",
        "meta_picker.empty_heading": "Meta 広告アカウントが見つかりません",
        "meta_picker.empty_notice": "このログインで到達可能な広告アカウントが見つかりませんでした。続行できますが、<code>account_id</code> は記録されません。",
        "meta_picker.continue": "続行",
    },
}


def _t(locale: str, key: str) -> str:
    """Look up ``key`` in the inline catalog. Falls back to English."""
    catalog = _I18N.get(locale) if locale in _I18N else _I18N["en"]
    if catalog is None:  # defensive — keeps mypy quiet
        catalog = _I18N["en"]
    if key in catalog:
        return catalog[key]
    return _I18N["en"].get(key, key)


def _html_lang(locale: str) -> str:
    """Return a safe ``lang`` attribute value (allow-list)."""
    return "ja" if locale == "ja" else "en"


def render_meta_secrets_form(session: WizardSession) -> str:
    """Form for Meta App ID / Secret."""
    csrf = html.escape(session.csrf_token, quote=True)
    loc = session.locale
    lang = _html_lang(loc)
    return f"""<!doctype html>
<html lang="{lang}">
<head><meta charset="utf-8"><title>{_t(loc, "meta.title")}</title>{_BASE_STYLE}</head>
<body>
<h1>{_t(loc, "meta.heading")}</h1>
<p>{_t(loc, "meta.intro")}</p>
<form method="post" action="/meta-ads/submit">
  <input type="hidden" name="csrf_token" value="{csrf}">

  <label for="meta_app_id">{_t(loc, "meta.app_id_label")}</label>
  <input id="meta_app_id" name="app_id" type="text" required autocomplete="off">
  <div class="hint">{_t(loc, "meta.app_id_hint")}</div>

  <label for="meta_app_secret">{_t(loc, "meta.app_secret_label")}</label>
  <input id="meta_app_secret" name="app_secret" type="password" required autocomplete="off">
  <div class="hint">{_t(loc, "meta.app_secret_hint")}</div>

  <button type="submit">{_t(loc, "meta.submit")}</button>
</form>
<p class="notice">{_t(loc, "meta.notice")}</p>
</body></html>
"""


def render_google_secrets_form(session: WizardSession) -> str:
    """Form for Developer Token / Client ID / Secret."""
    csrf = html.escape(session.csrf_token, quote=True)
    loc = session.locale
    lang = _html_lang(loc)
    return f"""<!doctype html>
<html lang="{lang}">
<head><meta charset="utf-8"><title>{_t(loc, "google.title")}</title>{_BASE_STYLE}</head>
<body>
<h1>{_t(loc, "google.heading")}</h1>
<p>{_t(loc, "google.intro")}</p>
<form method="post" action="/google-ads/submit">
  <input type="hidden" name="csrf_token" value="{csrf}">

  <label for="developer_token">{_t(loc, "google.dev_token_label")}</label>
  <input id="developer_token" name="developer_token" type="text" required autocomplete="off">
  <div class="hint">{_t(loc, "google.dev_token_hint")}</div>

  <label for="client_id">{_t(loc, "google.client_id_label")}</label>
  <input id="client_id" name="client_id" type="text" required autocomplete="off">
  <div class="hint">{_t(loc, "google.client_id_hint")}</div>

  <label for="client_secret">{_t(loc, "google.client_secret_label")}</label>
  <input id="client_secret" name="client_secret" type="password" required autocomplete="off">
  <div class="hint">{_t(loc, "google.client_secret_hint")}</div>

  <button type="submit">{_t(loc, "google.submit")}</button>
</form>
<p class="notice">{_t(loc, "google.notice")}</p>
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
    loc = session.locale
    lang = _html_lang(loc)
    if not accounts:
        return f"""<!doctype html>
<html lang="{lang}">
<head><meta charset="utf-8"><title>{_t(loc, "google_picker.title")}</title>{_BASE_STYLE}</head>
<body>
<h1>{_t(loc, "google_picker.empty_heading")}</h1>
<p class="notice">{_t(loc, "google_picker.empty_notice")}</p>
<p><a href="/done">{_t(loc, "google_picker.continue")}</a></p>
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
<html lang="{lang}">
<head><meta charset="utf-8"><title>{_t(loc, "google_picker.title")}</title>{_BASE_STYLE}</head>
<body>
<h1>{_t(loc, "google_picker.heading")}</h1>
<p>{_t(loc, "google_picker.intro")}</p>
<form method="post" action="/google-ads/select-account">
  <input type="hidden" name="csrf_token" value="{csrf}">
  {rows_html}
  <button type="submit">{_t(loc, "google_picker.submit")}</button>
</form>
</body></html>
"""


def render_meta_account_picker(
    session: WizardSession, accounts: list[dict[str, Any]]
) -> str:
    """Radio-group picker for a Meta ad account."""
    csrf = html.escape(session.csrf_token, quote=True)
    loc = session.locale
    lang = _html_lang(loc)
    if not accounts:
        return f"""<!doctype html>
<html lang="{lang}">
<head><meta charset="utf-8"><title>{_t(loc, "meta_picker.title")}</title>{_BASE_STYLE}</head>
<body>
<h1>{_t(loc, "meta_picker.empty_heading")}</h1>
<p class="notice">{_t(loc, "meta_picker.empty_notice")}</p>
<p><a href="/done">{_t(loc, "meta_picker.continue")}</a></p>
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
<html lang="{lang}">
<head><meta charset="utf-8"><title>{_t(loc, "meta_picker.title")}</title>{_BASE_STYLE}</head>
<body>
<h1>{_t(loc, "meta_picker.heading")}</h1>
<p>{_t(loc, "meta_picker.intro")}</p>
<form method="post" action="/meta-ads/select-account">
  <input type="hidden" name="csrf_token" value="{csrf}">
  {rows_html}
  <button type="submit">{_t(loc, "meta_picker.submit")}</button>
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


# Terminal page served at /done — marks the wizard complete and tells
# the user the tab can be closed. The configure-UI's OAuthBridge watcher
# polls ``wizard.completed`` to learn when this page was reached.
_DONE_PAGE = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>mureo setup — done</title>{_BASE_STYLE}</head>
<body>
<h1>Setup complete</h1>
<p>Credentials saved. You can close this tab and return to mureo configure.</p>
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
        # The configure UI threads its operator's locale through the
        # first GET into this wizard via ``?locale=ja``. Persist it on
        # the session so subsequent GETs (callback, picker) re-use it.
        # Allow-list defends against echoing arbitrary attacker input.
        self._absorb_locale_from_query(parsed.query)
        if path == "/google-ads":
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
        elif path == "/done":
            self.server.wizard.mark_completed()
            self._send_html(_DONE_PAGE)
        else:
            self.send_error(404, "Not found")

    def _absorb_locale_from_query(self, query: str) -> None:
        """If ``?locale=en|ja`` is present, persist it on the session."""
        if not query:
            return
        params = urllib.parse.parse_qs(query, keep_blank_values=False)
        candidates = params.get("locale", [])
        if not candidates:
            return
        chosen = candidates[0]
        if chosen in {"en", "ja"}:
            self.server.wizard.session.locale = chosen

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

    def _validate_oauth_url(
        self, url: str, allowed_origin: str, label: str
    ) -> str | None:
        """Return ``url`` with CR/LF stripped if it is rooted at
        ``allowed_origin``. Otherwise render an error page and return
        ``None`` so the caller can short-circuit *before* mutating any
        session state — keeping a rejected redirect from leaving the
        wizard with half-populated auth material.

        Stripping CR/LF defends the eventual ``Location`` header from
        HTTP response-splitting injection. The rejection log line uses
        only the static ``label`` argument and never echoes any value
        derived from ``url`` — the URL carries the OAuth ``state``
        token and (per CodeQL's taint analysis) any string transitively
        derived from it is treated as sensitive.
        """
        sanitized = url.replace("\r", "").replace("\n", "")
        if sanitized.startswith(allowed_origin):
            return sanitized
        logger.error("Refusing 302 for %s OAuth — URL origin mismatch", label)
        self._send_html(
            render_error("Unexpected OAuth destination; aborting."),
            status=500,
        )
        return None

    def _send_oauth_redirect(self, sanitized_url: str) -> None:
        """Send a 302 to ``sanitized_url``. Caller MUST have run the URL
        through :meth:`_validate_oauth_url` first; this method does not
        re-validate."""
        self.send_response(302)
        self.send_header("Location", sanitized_url)
        self.end_headers()

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

        # Defensive: google_auth_url should always yield a Google-owned
        # URL, but enforce explicitly so the wizard cannot become an
        # open redirect, and strip any CR/LF that would enable HTTP
        # response-splitting via the Location header. Validate BEFORE
        # mutating the session so a rejection cannot leave half-written
        # auth material behind.
        sanitized_url = self._validate_oauth_url(
            auth_url, self._GOOGLE_AUTH_ORIGIN, "Google"
        )
        if sanitized_url is None:
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

        self._send_oauth_redirect(sanitized_url)

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
            self.send_header("Location", "/done")
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
            # Stale link or direct URL guess; bounce to the Google form.
            self.send_response(302)
            self.send_header("Location", "/google-ads")
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
        self.send_header("Location", "/done")
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

        # Validate BEFORE mutating session — a rejected redirect must
        # not leave half-populated auth material behind.
        sanitized_url = self._validate_oauth_url(
            auth_url, self._META_AUTH_ORIGIN, "Meta"
        )
        if sanitized_url is None:
            return

        sess = self.server.wizard.session
        sess.meta_app_id = app_id
        sess.meta_app_secret = app_secret
        sess.meta_oauth_state = state
        # See matching comment in `_handle_google_submit` — csrf is not
        # rotated here so a back/refresh from Facebook's OAuth page
        # doesn't wedge the wizard. The Meta `state` parameter is the
        # replay guard for the callback round-trip.

        self._send_oauth_redirect(sanitized_url)

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
            self.send_header("Location", "/done")
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
            self.send_header("Location", "/meta-ads")
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
