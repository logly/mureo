"""Tests for mureo.cli.web_auth — the browser-based OAuth wizard.

The wizard is spawned per-platform by ``mureo.web.oauth_bridge`` on
behalf of the ``mureo configure`` UI: the user walks through secret-
entry + OAuth entirely in their browser, so they never see a terminal.

These tests start the real wizard HTTP server on 127.0.0.1:0 (random
port) in a background thread, make requests via ``urllib.request``,
and assert the route behavior. Google OAuth is mocked so nothing hits
the network.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.cli.web_auth import (  # noqa: I001
    WebAuthWizard,
    WizardSession,
    render_google_account_picker,
    render_google_secrets_form,
    render_meta_account_picker,
    render_meta_secrets_form,
)

if TYPE_CHECKING:
    from http.client import HTTPResponse
    from pathlib import Path

# ---------------------------------------------------------------------------
# Pure-view tests (no HTTP server)
# ---------------------------------------------------------------------------


class TestRenderMetaSecretsForm:
    def test_contains_csrf_hidden_input(self) -> None:
        session = WizardSession(csrf_token="META_TOKEN")
        html = render_meta_secrets_form(session)
        assert 'name="csrf_token"' in html
        assert "META_TOKEN" in html

    def test_has_app_id_and_secret_fields(self) -> None:
        html = render_meta_secrets_form(WizardSession())
        assert 'name="app_id"' in html
        assert 'name="app_secret"' in html
        assert 'type="password"' in html  # app_secret masked

    def test_posts_to_meta_submit(self) -> None:
        html = render_meta_secrets_form(WizardSession())
        assert 'action="/meta-ads/submit"' in html
        assert 'method="post"' in html.lower()

    def test_has_deep_link_to_meta_developers(self) -> None:
        html = render_meta_secrets_form(WizardSession())
        # Assert the full deep-link path (not just the host) so the
        # check is precise and CodeQL's `py/incomplete-url-substring-
        # sanitization` rule does not warn about a host-only substring
        # match that could be satisfied by a phishing host.
        assert "https://developers.facebook.com/apps/" in html


class TestRenderGoogleSecretsForm:
    def test_contains_csrf_hidden_input(self) -> None:
        session = WizardSession(csrf_token="TOKEN_123")
        html = render_google_secrets_form(session)
        assert 'name="csrf_token"' in html
        assert "TOKEN_123" in html

    def test_has_three_required_secret_fields(self) -> None:
        session = WizardSession()
        html = render_google_secrets_form(session)
        for field in ("developer_token", "client_id", "client_secret"):
            assert f'name="{field}"' in html
        # client_secret should be type=password to avoid over-the-shoulder leak.
        assert 'type="password"' in html

    def test_posts_to_submit_endpoint(self) -> None:
        html = render_google_secrets_form(WizardSession())
        assert 'action="/google-ads/submit"' in html
        assert 'method="post"' in html.lower()

    def test_has_external_links_to_secret_origins(self) -> None:
        """Inline help tells the user WHERE to get each secret, so
        they don't have to search Google docs from scratch."""
        html = render_google_secrets_form(WizardSession())
        # Full path (not host-only substring) — precise + CodeQL-clean.
        assert "https://console.cloud.google.com/apis/credentials" in html
        assert "https://ads.google.com/aw/apicenter" in html


# ---------------------------------------------------------------------------
# Integration tests — run a real wizard server on 127.0.0.1:0
# ---------------------------------------------------------------------------


@pytest.fixture
def wizard(tmp_path: Path) -> Any:
    """Launch a real WebAuthWizard server on a random port for each test."""
    creds_path = tmp_path / ".mureo" / "credentials.json"
    wiz = WebAuthWizard(credentials_path=creds_path)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=2.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


def _url(wiz: Any, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


def _fetch(wiz: Any, path: str) -> HTTPResponse:
    return urllib.request.urlopen(_url(wiz, path), timeout=2.0)


class TestGoogleAdsFormRoute:
    def test_serves_form_with_csrf_token(self, wizard: Any) -> None:
        resp = _fetch(wizard, "/google-ads")
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert wizard.session.csrf_token in body


class TestLocaleRendering:
    """``?locale=ja`` over the wire renders Japanese inline strings."""

    def test_default_locale_is_english(self) -> None:
        html = render_google_secrets_form(WizardSession())
        assert 'lang="en"' in html
        assert "Google Ads credentials" in html

    def test_japanese_session_renders_japanese_heading(self) -> None:
        session = WizardSession(locale="ja")
        html = render_google_secrets_form(session)
        assert 'lang="ja"' in html
        assert "Google Ads 認証情報" in html

    def test_japanese_meta_form_renders_japanese_heading(self) -> None:
        session = WizardSession(locale="ja")
        html = render_meta_secrets_form(session)
        assert 'lang="ja"' in html
        assert "Meta Ads 認証情報" in html

    def test_query_locale_ja_switches_response(self, wizard: Any) -> None:
        resp = _fetch(wizard, "/google-ads?locale=ja")
        body = resp.read().decode("utf-8")
        assert 'lang="ja"' in body
        assert "Google Ads 認証情報" in body

    def test_query_locale_unknown_falls_back_to_english(self, wizard: Any) -> None:
        resp = _fetch(wizard, "/google-ads?locale=fr")
        body = resp.read().decode("utf-8")
        assert 'lang="en"' in body
        assert "Google Ads credentials" in body

    def test_empty_google_picker_japanese(self) -> None:
        session = WizardSession(locale="ja")
        html = render_google_account_picker(session, [])
        assert "Google Ads アカウントが見つかりません" in html

    def test_empty_meta_picker_japanese(self) -> None:
        session = WizardSession(locale="ja")
        html = render_meta_account_picker(session, [])
        assert "Meta 広告アカウントが見つかりません" in html


class TestGoogleAdsSubmitRoute:
    def test_rejects_missing_csrf(self, wizard: Any) -> None:
        data = urllib.parse.urlencode(
            {
                "developer_token": "DT",
                "client_id": "CID",
                "client_secret": "SECRET",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/submit"), data=data, method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: Any) -> None:
        data = urllib.parse.urlencode(
            {
                "csrf_token": "not-the-real-token",
                "developer_token": "DT",
                "client_id": "CID",
                "client_secret": "SECRET",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/submit"), data=data, method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_valid_submit_redirects_to_google_oauth(self, wizard: Any) -> None:
        """With the correct CSRF, the handler builds a Flow, stashes it
        in the session, and returns a 302 to Google's authorization URL."""
        fake_flow = MagicMock()

        with (
            patch(
                "mureo.cli.web_auth.build_google_flow", return_value=fake_flow
            ) as mock_build,
            patch(
                "mureo.cli.web_auth.google_auth_url",
                return_value=(
                    "https://accounts.google.com/o/oauth2/auth?fake=1",
                    "state-xyz",
                ),
            ),
        ):
            data = urllib.parse.urlencode(
                {
                    "csrf_token": wizard.session.csrf_token,
                    "developer_token": "DT-123",
                    "client_id": "CID-abc",
                    "client_secret": "SECRET-xyz",
                }
            ).encode()
            req = urllib.request.Request(
                _url(wizard, "/google-ads/submit"), data=data, method="POST"
            )
            opener = urllib.request.build_opener(_NoRedirect())
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open(req, timeout=2.0)

            assert exc_info.value.code == 302
            loc = exc_info.value.headers.get("Location", "")
            assert loc.startswith("https://accounts.google.com/o/oauth2/auth")

        assert wizard.session.google_flow is fake_flow
        assert wizard.session.google_developer_token == "DT-123"
        assert wizard.session.google_client_id == "CID-abc"
        assert wizard.session.google_client_secret == "SECRET-xyz"
        mock_build.assert_called_once()
        kwargs = mock_build.call_args.kwargs
        assert kwargs["client_id"] == "CID-abc"
        assert kwargs["client_secret"] == "SECRET-xyz"
        assert kwargs["redirect_uri"] == (
            f"http://localhost:{wizard.port}/google-ads/callback"
        )


class TestGoogleAdsCallbackRoute:
    def test_missing_code_returns_400(self, wizard: Any) -> None:
        wizard.session.google_flow = MagicMock()
        wizard.session.google_developer_token = "DT"
        wizard.session.google_client_id = "CID"
        wizard.session.google_client_secret = "SEC"

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch(wizard, "/google-ads/callback")
        assert exc_info.value.code == 400

    def test_missing_session_flow_returns_400(self, wizard: Any) -> None:
        """Hitting the callback URL without a prior /submit is invalid
        (probably a stale link or direct URL guess)."""
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch(wizard, "/google-ads/callback?code=abc")
        assert exc_info.value.code == 400

    def test_valid_code_redirects_to_account_picker(
        self, wizard: Any, tmp_path: Path
    ) -> None:
        """Successful OAuth exchange now redirects to the account-
        picker page rather than straight to /done. The picker lets the
        user choose which customer_id / login_customer_id to persist."""
        fake_flow = MagicMock()
        wizard.session.google_flow = fake_flow
        wizard.session.google_developer_token = "DT-123"
        wizard.session.google_client_id = "CID-abc"
        wizard.session.google_client_secret = "SECRET-xyz"
        wizard.session.google_oauth_state = "state-xyz"

        from mureo.auth_setup import OAuthResult

        fake_accounts = [
            {
                "id": "1111111111",
                "name": "Direct account",
                "is_manager": False,
                "parent_id": None,
            }
        ]

        async def _fake_list(_creds: Any) -> list[dict[str, Any]]:
            return fake_accounts

        with (
            patch(
                "mureo.cli.web_auth.exchange_google_code",
                return_value=OAuthResult(
                    refresh_token="REFRESH_TOKEN",
                    access_token="ACCESS_TOKEN",
                ),
            ) as mock_exchange,
            patch(
                "mureo.cli.web_auth.list_accessible_accounts",
                side_effect=_fake_list,
            ),
        ):
            opener = urllib.request.build_opener(_NoRedirect())
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open(
                    _url(
                        wizard,
                        "/google-ads/callback?code=AUTH_CODE&state=state-xyz",
                    ),
                    timeout=2.0,
                )
            assert exc_info.value.code == 302
            loc = exc_info.value.headers.get("Location", "")
            assert loc == "/google-ads/select-account"

        mock_exchange.assert_called_once_with(fake_flow, "AUTH_CODE")

        # Session now holds the refresh token + account list awaiting
        # the user's picker choice. Session secrets (dev token etc.)
        # must still be present until the picker submit — otherwise
        # save_credentials would lose the client_id/secret.
        assert wizard.session.google_refresh_token == "REFRESH_TOKEN"
        assert wizard.session.google_accessible_accounts == fake_accounts
        assert wizard.session.google_developer_token == "DT-123"
        assert wizard.session.google_client_id == "CID-abc"
        assert wizard.session.google_client_secret == "SECRET-xyz"

    def test_callback_list_accounts_failure_proceeds_to_done(
        self, wizard: Any, tmp_path: Path
    ) -> None:
        """If the Google Ads API account list call fails or returns
        empty, the wizard still saves the credentials (with null
        customer_id / login_customer_id) and sends the user to /done so
        the spawning configure-UI can collect the completion signal.
        The user doesn't lose the refresh token."""
        wizard.session.google_flow = MagicMock()
        wizard.session.google_developer_token = "DT-123"
        wizard.session.google_client_id = "CID-abc"
        wizard.session.google_client_secret = "SECRET-xyz"
        wizard.session.google_oauth_state = "state-xyz"

        from mureo.auth_setup import OAuthResult

        async def _fake_list(_creds: Any) -> list[dict[str, Any]]:
            raise RuntimeError("API down")

        with (
            patch(
                "mureo.cli.web_auth.exchange_google_code",
                return_value=OAuthResult(
                    refresh_token="REFRESH_TOKEN",
                    access_token="ACCESS_TOKEN",
                ),
            ),
            patch(
                "mureo.cli.web_auth.list_accessible_accounts",
                side_effect=_fake_list,
            ),
        ):
            opener = urllib.request.build_opener(_NoRedirect())
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open(
                    _url(
                        wizard,
                        "/google-ads/callback?code=AUTH_CODE&state=state-xyz",
                    ),
                    timeout=2.0,
                )
            assert exc_info.value.code == 302
            loc = exc_info.value.headers.get("Location", "")
            assert loc == "/done"

        import json

        creds_file = tmp_path / ".mureo" / "credentials.json"
        assert creds_file.exists()
        data = json.loads(creds_file.read_text(encoding="utf-8"))
        g = data["google_ads"]
        assert g["refresh_token"] == "REFRESH_TOKEN"
        assert g["customer_id"] is None
        assert g["login_customer_id"] is None
        # Session cleared on the fallback path (no picker to reach).
        assert wizard.session.google_developer_token is None

    def test_user_declines_shows_friendly_error(self, wizard: Any) -> None:
        """Google redirects back with ``error=access_denied`` when the
        user clicks "Deny". The wizard shows a friendly message, not a
        bare 400 with no guidance."""
        wizard.session.google_flow = MagicMock()
        wizard.session.google_oauth_state = "state-xyz"

        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(
                _url(
                    wizard,
                    "/google-ads/callback?error=access_denied&state=state-xyz",
                ),
                timeout=2.0,
            )
        assert exc_info.value.code == 400
        body = exc_info.value.read().decode("utf-8")
        assert "cancelled" in body.lower() or "refused" in body.lower()
        assert "access_denied" in body

    def test_state_mismatch_returns_403(self, wizard: Any) -> None:
        """OAuth state that doesn't match the stashed value is refused
        — catches a stale-link or CSRF-on-callback attack."""
        wizard.session.google_flow = MagicMock()
        wizard.session.google_developer_token = "DT"
        wizard.session.google_client_id = "CID"
        wizard.session.google_client_secret = "SEC"
        wizard.session.google_oauth_state = "legit-state"

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch(wizard, "/google-ads/callback?code=abc&state=attacker-state")
        assert exc_info.value.code == 403


class TestMetaAdsFormRoute:
    def test_serves_form_with_csrf_token(self, wizard: Any) -> None:
        resp = _fetch(wizard, "/meta-ads")
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert wizard.session.csrf_token in body
        assert 'name="app_id"' in body


class TestMetaAdsSubmitRoute:
    def test_rejects_missing_csrf(self, wizard: Any) -> None:
        data = urllib.parse.urlencode({"app_id": "A", "app_secret": "S"}).encode()
        req = urllib.request.Request(
            _url(wizard, "/meta-ads/submit"), data=data, method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: Any) -> None:
        data = urllib.parse.urlencode(
            {"csrf_token": "no", "app_id": "A", "app_secret": "S"}
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/meta-ads/submit"), data=data, method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_rejects_bad_host_header(self, wizard: Any) -> None:
        data = urllib.parse.urlencode(
            {
                "csrf_token": wizard.session.csrf_token,
                "app_id": "A",
                "app_secret": "S",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/meta-ads/submit"),
            data=data,
            method="POST",
            headers={"Host": "attacker.example.com"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_rejects_oversize_body(self, wizard: Any) -> None:
        huge = b"a" * (20 * 1024)
        req = urllib.request.Request(
            _url(wizard, "/meta-ads/submit"),
            data=huge,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 413

    def test_refuses_non_facebook_redirect_origin(self, wizard: Any) -> None:
        """Even if build_meta_auth_url is somehow subverted to return a
        non-Facebook URL, the handler refuses to emit a 302 to it."""
        with patch(
            "mureo.cli.web_auth.build_meta_auth_url",
            return_value="https://evil.example.com/oauth",
        ):
            data = urllib.parse.urlencode(
                {
                    "csrf_token": wizard.session.csrf_token,
                    "app_id": "A",
                    "app_secret": "S",
                }
            ).encode()
            req = urllib.request.Request(
                _url(wizard, "/meta-ads/submit"), data=data, method="POST"
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=2.0)
            assert exc_info.value.code == 500

    def test_valid_submit_redirects_to_facebook(self, wizard: Any) -> None:
        fake_url = "https://www.facebook.com/v21.0/dialog/oauth?client_id=A"

        with patch(
            "mureo.cli.web_auth.build_meta_auth_url", return_value=fake_url
        ) as mock_build:
            data = urllib.parse.urlencode(
                {
                    "csrf_token": wizard.session.csrf_token,
                    "app_id": "APP-123",
                    "app_secret": "SECRET-abc",
                }
            ).encode()
            req = urllib.request.Request(
                _url(wizard, "/meta-ads/submit"), data=data, method="POST"
            )
            opener = urllib.request.build_opener(_NoRedirect())
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open(req, timeout=2.0)

            assert exc_info.value.code == 302
            loc = exc_info.value.headers.get("Location", "")
            assert loc.startswith("https://www.facebook.com/")

        assert wizard.session.meta_app_id == "APP-123"
        assert wizard.session.meta_app_secret == "SECRET-abc"
        assert wizard.session.meta_oauth_state is not None
        mock_build.assert_called_once()
        kwargs = mock_build.call_args.kwargs
        assert kwargs["app_id"] == "APP-123"
        assert kwargs["redirect_uri"] == (
            f"http://localhost:{wizard.port}/meta-ads/callback"
        )


class TestMetaAdsCallbackRoute:
    def test_rejects_bad_host_header(self, wizard: Any) -> None:
        wizard.session.meta_app_id = "A"
        wizard.session.meta_oauth_state = "s"
        req = urllib.request.Request(
            _url(wizard, "/meta-ads/callback?code=abc&state=s"),
            headers={"Host": "attacker.example.com"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_state_mismatch_returns_403(self, wizard: Any) -> None:
        wizard.session.meta_app_id = "A"
        wizard.session.meta_app_secret = "S"
        wizard.session.meta_oauth_state = "legit"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch(wizard, "/meta-ads/callback?code=abc&state=attacker")
        assert exc_info.value.code == 403

    def test_user_decline_shows_friendly_error(self, wizard: Any) -> None:
        wizard.session.meta_app_id = "A"
        wizard.session.meta_oauth_state = "s"
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(
                _url(
                    wizard,
                    "/meta-ads/callback?error=access_denied&state=s",
                ),
                timeout=2.0,
            )
        assert exc_info.value.code == 400
        body = exc_info.value.read().decode("utf-8")
        assert "cancelled" in body.lower() or "refused" in body.lower()

    def test_valid_code_redirects_to_account_picker(
        self, wizard: Any, tmp_path: Path
    ) -> None:
        """Successful Meta OAuth now redirects to the ad-account picker
        so the user can select which account to operate on."""
        wizard.session.meta_app_id = "APP-123"
        wizard.session.meta_app_secret = "SECRET-abc"
        wizard.session.meta_oauth_state = "state-xyz"

        from mureo.auth_setup import MetaOAuthResult

        async def _fake_exchange(**_kwargs: Any) -> MetaOAuthResult:
            return MetaOAuthResult(access_token="LONG_LIVED_TOKEN", expires_in=5184000)

        fake_accounts = [
            {
                "id": "act_111",
                "name": "My Ad Account",
                "account_status": 1,
            }
        ]

        async def _fake_list(_token: str) -> list[dict[str, Any]]:
            return fake_accounts

        with (
            patch(
                "mureo.cli.web_auth.exchange_meta_code",
                side_effect=_fake_exchange,
            ) as mock_exchange,
            patch(
                "mureo.cli.web_auth.list_meta_ad_accounts",
                side_effect=_fake_list,
            ),
        ):
            opener = urllib.request.build_opener(_NoRedirect())
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open(
                    _url(
                        wizard,
                        "/meta-ads/callback?code=AUTH_CODE&state=state-xyz",
                    ),
                    timeout=2.0,
                )
            assert exc_info.value.code == 302
            loc = exc_info.value.headers.get("Location", "")
            assert loc == "/meta-ads/select-account"

        mock_exchange.assert_called_once()
        call_kwargs = mock_exchange.call_args.kwargs
        assert call_kwargs["code"] == "AUTH_CODE"
        assert call_kwargs["app_id"] == "APP-123"
        assert call_kwargs["app_secret"] == "SECRET-abc"

        # Token and account list parked in the session for the picker.
        assert wizard.session.meta_access_token == "LONG_LIVED_TOKEN"
        assert wizard.session.meta_ad_accounts == fake_accounts
        # App id/secret still present — needed at save time.
        assert wizard.session.meta_app_id == "APP-123"
        assert wizard.session.meta_app_secret == "SECRET-abc"

    def test_callback_list_accounts_failure_proceeds_to_done(
        self, wizard: Any, tmp_path: Path
    ) -> None:
        wizard.session.meta_app_id = "APP-123"
        wizard.session.meta_app_secret = "SECRET-abc"
        wizard.session.meta_oauth_state = "state-xyz"

        from mureo.auth_setup import MetaOAuthResult

        async def _fake_exchange(**_kwargs: Any) -> MetaOAuthResult:
            return MetaOAuthResult(access_token="LONG_LIVED_TOKEN", expires_in=5184000)

        async def _fake_list(_token: str) -> list[dict[str, Any]]:
            raise RuntimeError("Graph API down")

        with (
            patch(
                "mureo.cli.web_auth.exchange_meta_code",
                side_effect=_fake_exchange,
            ),
            patch(
                "mureo.cli.web_auth.list_meta_ad_accounts",
                side_effect=_fake_list,
            ),
        ):
            opener = urllib.request.build_opener(_NoRedirect())
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open(
                    _url(
                        wizard,
                        "/meta-ads/callback?code=AUTH_CODE&state=state-xyz",
                    ),
                    timeout=2.0,
                )
            assert exc_info.value.code == 302
            loc = exc_info.value.headers.get("Location", "")
            assert loc == "/done"

        import json

        creds_file = tmp_path / ".mureo" / "credentials.json"
        assert creds_file.exists()
        data = json.loads(creds_file.read_text(encoding="utf-8"))
        m = data["meta_ads"]
        assert m["access_token"] == "LONG_LIVED_TOKEN"
        # account_id absent or explicitly null when listing failed.
        assert m.get("account_id") is None
        assert wizard.session.meta_app_id is None


class TestSecurityHardening:
    """Regression tests for the P2-2 security review findings."""

    def test_response_has_full_security_headers(self, wizard: Any) -> None:
        resp = _fetch(wizard, "/google-ads")
        csp = resp.headers["Content-Security-Policy"]
        for directive in (
            "default-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "form-action 'self' https://accounts.google.com",
        ):
            assert directive in csp
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_dns_rebinding_host_refused(self, wizard: Any) -> None:
        """A submit with a spoofed Host header (DNS rebind scenario)
        is rejected, not processed."""
        data = urllib.parse.urlencode(
            {
                "csrf_token": wizard.session.csrf_token,
                "developer_token": "DT",
                "client_id": "CID",
                "client_secret": "SEC",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/submit"),
            data=data,
            method="POST",
            headers={"Host": "attacker.example.com"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_csrf_token_rotates_after_picker_submit(self, wizard: Any) -> None:
        """Replay protection at the commit point. The OAuth-init
        ``/google-ads/submit`` intentionally does NOT rotate (it's not
        a persist step, and rotating there breaks Back-button re-submits
        and parallel tabs — see the 403 hotfix), but the account-picker
        submit is the real persist point and must invalidate its token.
        """
        wizard.session.google_accessible_accounts = [
            {
                "id": "1111111111",
                "name": "Direct account",
                "is_manager": False,
                "parent_id": None,
            }
        ]
        wizard.session.google_refresh_token = "RT"
        wizard.session.google_developer_token = "DT"
        wizard.session.google_client_id = "CID"
        wizard.session.google_client_secret = "SEC"
        original_token = wizard.session.csrf_token

        data = urllib.parse.urlencode(
            {
                "csrf_token": original_token,
                "account_id": "1111111111",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/select-account"),
            data=data,
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError):
            opener.open(req, timeout=2.0)

        assert wizard.session.csrf_token != original_token

    def test_oversize_post_body_rejected(self, wizard: Any) -> None:
        """Cap on POST Content-Length prevents local DoS / OOM."""
        huge = b"a" * (20 * 1024)  # 20 KB > 16 KB cap
        req = urllib.request.Request(
            _url(wizard, "/google-ads/submit"),
            data=huge,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 413


class TestDoneRoute:
    def test_done_page_marks_completion(self, wizard: Any) -> None:
        """`/done` renders the terminal page and flips wizard.completed,
        which is the binding contract the OAuthBridge watcher polls on."""
        resp = _fetch(wizard, "/done")
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "close" in body.lower() or "done" in body.lower()
        assert wizard.completed is True


class TestRenderGoogleAccountPicker:
    def test_renders_accounts_and_csrf(self) -> None:
        session = WizardSession(csrf_token="PICKER_TOK")
        accounts = [
            {
                "id": "1111111111",
                "name": "Direct account",
                "is_manager": False,
                "parent_id": None,
            },
            {
                "id": "2222222222",
                "name": "Child of MCC",
                "is_manager": False,
                "parent_id": "9999999999",
            },
        ]
        html = render_google_account_picker(session, accounts)
        assert "PICKER_TOK" in html
        assert 'action="/google-ads/select-account"' in html
        assert 'method="post"' in html.lower()
        assert "1111111111" in html
        assert "2222222222" in html
        assert "Direct account" in html
        assert "Child of MCC" in html

    def test_escapes_account_names(self) -> None:
        session = WizardSession()
        accounts = [
            {
                "id": "1111111111",
                "name": "<script>alert(1)</script>",
                "is_manager": False,
                "parent_id": None,
            }
        ]
        html = render_google_account_picker(session, accounts)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderMetaAccountPicker:
    def test_renders_accounts_and_csrf(self) -> None:
        session = WizardSession(csrf_token="META_PICKER_TOK")
        accounts = [
            {"id": "act_111", "name": "Primary", "account_status": 1},
            {"id": "act_222", "name": "Secondary", "account_status": 1},
        ]
        html = render_meta_account_picker(session, accounts)
        assert "META_PICKER_TOK" in html
        assert 'action="/meta-ads/select-account"' in html
        assert "act_111" in html
        assert "Primary" in html


class TestGoogleAccountPickerRoute:
    def test_renders_accounts_from_session(self, wizard: Any) -> None:
        wizard.session.google_accessible_accounts = [
            {
                "id": "1234567890",
                "name": "Demo account",
                "is_manager": False,
                "parent_id": None,
            }
        ]
        resp = _fetch(wizard, "/google-ads/select-account")
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "1234567890" in body
        assert "Demo account" in body
        assert wizard.session.csrf_token in body

    def test_redirects_when_no_session(self, wizard: Any) -> None:
        """Direct hit on /google-ads/select-account without any pending
        account list in the session sends the user home (stale link)."""
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(_url(wizard, "/google-ads/select-account"), timeout=2.0)
        # 302 to / OR 400. Accept either — the point is no crash, no
        # leaked partial state.
        assert exc_info.value.code in (302, 400)


class TestGoogleAccountSubmitRoute:
    def _prime_session(self, wizard: Any) -> None:
        wizard.session.google_developer_token = "DT-123"
        wizard.session.google_client_id = "CID-abc"
        wizard.session.google_client_secret = "SECRET-xyz"
        wizard.session.google_refresh_token = "REFRESH_TOKEN"
        wizard.session.google_accessible_accounts = [
            {
                "id": "1111111111",
                "name": "Direct",
                "is_manager": False,
                "parent_id": None,
            },
            {
                "id": "2222222222",
                "name": "Child",
                "is_manager": False,
                "parent_id": "9999999999",
            },
        ]

    def test_rejects_missing_csrf(self, wizard: Any) -> None:
        self._prime_session(wizard)
        data = urllib.parse.urlencode({"account_id": "1111111111"}).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/select-account"),
            data=data,
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_rejects_bad_host_header(self, wizard: Any) -> None:
        self._prime_session(wizard)
        data = urllib.parse.urlencode(
            {
                "csrf_token": wizard.session.csrf_token,
                "account_id": "1111111111",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/select-account"),
            data=data,
            method="POST",
            headers={"Host": "attacker.example.com"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_saves_customer_id_and_login_customer_id_for_direct_account(
        self, wizard: Any, tmp_path: Path
    ) -> None:
        """For a non-MCC account, customer_id and login_customer_id are
        the same value."""
        self._prime_session(wizard)
        data = urllib.parse.urlencode(
            {
                "csrf_token": wizard.session.csrf_token,
                "account_id": "1111111111",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/select-account"),
            data=data,
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(req, timeout=2.0)
        assert exc_info.value.code == 302
        loc = exc_info.value.headers.get("Location", "")
        assert loc == "/done"

        import json

        data_json = json.loads(
            (tmp_path / ".mureo" / "credentials.json").read_text(encoding="utf-8")
        )
        g = data_json["google_ads"]
        assert g["customer_id"] == "1111111111"
        assert g["login_customer_id"] == "1111111111"
        assert g["refresh_token"] == "REFRESH_TOKEN"
        assert g["developer_token"] == "DT-123"

        # Session now zeroed.
        assert wizard.session.google_developer_token is None
        assert wizard.session.google_client_id is None
        assert wizard.session.google_client_secret is None
        assert wizard.session.google_refresh_token is None
        assert wizard.session.google_accessible_accounts is None

    def test_mcc_account_uses_parent_as_login_customer_id(
        self, wizard: Any, tmp_path: Path
    ) -> None:
        """Picking a child-of-MCC: customer_id is the child, and
        login_customer_id is the parent MCC."""
        self._prime_session(wizard)
        data = urllib.parse.urlencode(
            {
                "csrf_token": wizard.session.csrf_token,
                "account_id": "2222222222",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/select-account"),
            data=data,
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError):
            opener.open(req, timeout=2.0)

        import json

        data_json = json.loads(
            (tmp_path / ".mureo" / "credentials.json").read_text(encoding="utf-8")
        )
        g = data_json["google_ads"]
        assert g["customer_id"] == "2222222222"
        assert g["login_customer_id"] == "9999999999"

    def test_rejects_account_id_not_in_session_list(self, wizard: Any) -> None:
        """A submitted account_id must be in the session's allowed list
        — otherwise a malicious tab could try to write arbitrary values."""
        self._prime_session(wizard)
        data = urllib.parse.urlencode(
            {
                "csrf_token": wizard.session.csrf_token,
                "account_id": "3333333333",  # not in session list
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/google-ads/select-account"),
            data=data,
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 400


class TestMetaAccountPickerRoute:
    def test_renders_accounts_from_session(self, wizard: Any) -> None:
        wizard.session.meta_ad_accounts = [
            {"id": "act_111", "name": "Primary", "account_status": 1},
        ]
        resp = _fetch(wizard, "/meta-ads/select-account")
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "act_111" in body
        assert "Primary" in body


class TestMetaAccountSubmitRoute:
    def _prime_session(self, wizard: Any) -> None:
        wizard.session.meta_app_id = "APP-123"
        wizard.session.meta_app_secret = "SECRET-abc"
        wizard.session.meta_access_token = "LONG_LIVED_TOKEN"
        wizard.session.meta_ad_accounts = [
            {"id": "act_111", "name": "Primary", "account_status": 1},
            {"id": "act_222", "name": "Secondary", "account_status": 1},
        ]

    def test_rejects_missing_csrf(self, wizard: Any) -> None:
        self._prime_session(wizard)
        data = urllib.parse.urlencode({"account_id": "act_111"}).encode()
        req = urllib.request.Request(
            _url(wizard, "/meta-ads/select-account"),
            data=data,
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 403

    def test_saves_selected_account_id(self, wizard: Any, tmp_path: Path) -> None:
        self._prime_session(wizard)
        data = urllib.parse.urlencode(
            {
                "csrf_token": wizard.session.csrf_token,
                "account_id": "act_222",
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/meta-ads/select-account"),
            data=data,
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(req, timeout=2.0)
        assert exc_info.value.code == 302
        loc = exc_info.value.headers.get("Location", "")
        assert loc == "/done"

        import json

        data_json = json.loads(
            (tmp_path / ".mureo" / "credentials.json").read_text(encoding="utf-8")
        )
        m = data_json["meta_ads"]
        assert m["access_token"] == "LONG_LIVED_TOKEN"
        assert m["account_id"] == "act_222"

        # Session secrets zeroed.
        assert wizard.session.meta_app_id is None
        assert wizard.session.meta_app_secret is None
        assert wizard.session.meta_access_token is None
        assert wizard.session.meta_ad_accounts is None

    def test_rejects_account_not_in_session_list(self, wizard: Any) -> None:
        self._prime_session(wizard)
        data = urllib.parse.urlencode(
            {
                "csrf_token": wizard.session.csrf_token,
                "account_id": "act_999",  # not in list
            }
        ).encode()
        req = urllib.request.Request(
            _url(wizard, "/meta-ads/select-account"),
            data=data,
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 400


class TestUnknownRoute:
    def test_returns_404(self, wizard: Any) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch(wizard, "/unknown-path")
        assert exc_info.value.code == 404


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Opener that surfaces 302 redirects as HTTPError so tests can
    assert on Location header directly."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None
