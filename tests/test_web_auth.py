"""Tests for mureo.cli.web_auth — the browser-based OAuth wizard.

The wizard lets a non-technical user run ``mureo auth setup --web``
and walk through secret-entry + OAuth entirely in their browser, so
they never see a terminal.

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
from http.client import HTTPResponse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Module under test — does not exist yet (RED).
from mureo.cli.web_auth import (  # noqa: I001
    WebAuthWizard,
    WizardSession,
    render_google_secrets_form,
    render_home,
)


# ---------------------------------------------------------------------------
# Pure-view tests (no HTTP server)
# ---------------------------------------------------------------------------


class TestRenderHome:
    def test_shows_google_ads_button(self) -> None:
        session = WizardSession()
        html = render_home(session)
        assert "<!doctype html>" in html.lower()
        assert "Google" in html and "Ads" in html
        assert "/google-ads" in html


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
        assert "console.cloud.google.com" in html
        assert "ads.google.com" in html


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


class TestHomeRoute:
    def test_serves_home_page(self, wizard: Any) -> None:
        resp = _fetch(wizard, "/")
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "mureo" in body.lower()
        assert "/google-ads" in body


class TestGoogleAdsFormRoute:
    def test_serves_form_with_csrf_token(self, wizard: Any) -> None:
        resp = _fetch(wizard, "/google-ads")
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert wizard.session.csrf_token in body


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
            f"http://127.0.0.1:{wizard.port}/google-ads/callback"
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

    def test_valid_code_exchanges_and_saves_credentials(
        self, wizard: Any, tmp_path: Path
    ) -> None:
        fake_flow = MagicMock()
        wizard.session.google_flow = fake_flow
        wizard.session.google_developer_token = "DT-123"
        wizard.session.google_client_id = "CID-abc"
        wizard.session.google_client_secret = "SECRET-xyz"
        wizard.session.google_oauth_state = "state-xyz"

        from mureo.auth_setup import OAuthResult

        with patch(
            "mureo.cli.web_auth.exchange_google_code",
            return_value=OAuthResult(
                refresh_token="REFRESH_TOKEN",
                access_token="ACCESS_TOKEN",
            ),
        ) as mock_exchange:
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

        mock_exchange.assert_called_once_with(fake_flow, "AUTH_CODE")

        import json

        creds_file = tmp_path / ".mureo" / "credentials.json"
        assert creds_file.exists()
        data = json.loads(creds_file.read_text(encoding="utf-8"))
        g = data["google_ads"]
        assert g["developer_token"] == "DT-123"
        assert g["client_id"] == "CID-abc"
        assert g["client_secret"] == "SECRET-xyz"
        assert g["refresh_token"] == "REFRESH_TOKEN"

        # Session secrets must be zeroed after successful save so they
        # don't linger in process memory for the wizard's 10-minute
        # lifetime.
        assert wizard.session.google_developer_token is None
        assert wizard.session.google_client_id is None
        assert wizard.session.google_client_secret is None
        assert wizard.session.google_flow is None

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


class TestSecurityHardening:
    """Regression tests for the P2-2 security review findings."""

    def test_response_has_full_security_headers(self, wizard: Any) -> None:
        resp = _fetch(wizard, "/")
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

    def test_csrf_token_rotates_after_successful_submit(
        self, wizard: Any
    ) -> None:
        """Replay protection: after a successful submit, the token that
        authorized it cannot be reused."""
        original_token = wizard.session.csrf_token

        with (
            patch("mureo.cli.web_auth.build_google_flow", return_value=MagicMock()),
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
                    "csrf_token": original_token,
                    "developer_token": "DT",
                    "client_id": "CID",
                    "client_secret": "SEC",
                }
            ).encode()
            req = urllib.request.Request(
                _url(wizard, "/google-ads/submit"), data=data, method="POST"
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
        resp = _fetch(wizard, "/done")
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "close" in body.lower() or "done" in body.lower()
        assert wizard.completed is True


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
