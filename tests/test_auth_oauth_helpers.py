"""Tests for auth_setup pure OAuth helpers.

These helpers are the shared building blocks between the interactive
CLI (``setup_google_ads``) and the forthcoming web-based auth wizard.
Extracting them so both paths build the same Flow / auth-URL shape
prevents drift.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Module imports under test — some of these don't exist yet.
from mureo.auth_setup import (  # noqa: I001
    build_google_client_config,
    build_google_flow,
    exchange_google_code,
    google_auth_url,
)


class TestBuildGoogleClientConfig:
    def test_structure_matches_installed_app_spec(self) -> None:
        config = build_google_client_config(
            client_id="cid.apps.googleusercontent.com",
            client_secret="SECRET",
        )
        assert "installed" in config
        inst = config["installed"]
        assert inst["client_id"] == "cid.apps.googleusercontent.com"
        assert inst["client_secret"] == "SECRET"
        assert inst["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"
        assert inst["token_uri"] == "https://oauth2.googleapis.com/token"
        # Redirect URIs must include localhost so the interactive
        # InstalledAppFlow path still works.
        assert "http://localhost" in inst["redirect_uris"]


class TestBuildGoogleFlow:
    def test_no_redirect_uri_returns_installed_app_flow(self) -> None:
        """When redirect_uri is None, the CLI path uses InstalledAppFlow
        (which spins up its own local server)."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = build_google_flow(
            client_id="cid", client_secret="SECRET", redirect_uri=None
        )
        assert isinstance(flow, InstalledAppFlow)

    def test_with_redirect_uri_returns_plain_flow(self) -> None:
        """With a redirect_uri, the web wizard path uses plain Flow so
        the caller handles the callback on its own HTTP server."""
        from google_auth_oauthlib.flow import Flow, InstalledAppFlow

        flow = build_google_flow(
            client_id="cid",
            client_secret="SECRET",
            redirect_uri="http://127.0.0.1:59999/google-ads/callback",
        )
        assert isinstance(flow, Flow)
        assert not isinstance(flow, InstalledAppFlow)
        assert flow.redirect_uri == (
            "http://127.0.0.1:59999/google-ads/callback"
        )

    def test_scopes_cover_google_ads_and_search_console(self) -> None:
        """Scopes must include both Google Ads and Search Console so
        a single refresh_token drives both MCP tool surfaces."""
        flow = build_google_flow(
            client_id="cid",
            client_secret="SECRET",
            redirect_uri="http://127.0.0.1:1/cb",
        )
        url, _state = flow.authorization_url(access_type="offline")
        assert "adwords" in url
        assert "webmasters" in url


class TestGoogleAuthUrl:
    def test_returns_url_and_state(self) -> None:
        flow = build_google_flow(
            client_id="cid",
            client_secret="SECRET",
            redirect_uri="http://127.0.0.1:1/cb",
        )
        url, state = google_auth_url(flow)
        assert url.startswith("https://accounts.google.com/")
        assert isinstance(state, str) and len(state) > 0

    def test_forces_offline_and_consent(self) -> None:
        """``access_type=offline`` + ``prompt=consent`` guarantees that
        Google returns a refresh_token every time, even if the user
        already granted the app before."""
        flow = build_google_flow(
            client_id="cid",
            client_secret="SECRET",
            redirect_uri="http://127.0.0.1:1/cb",
        )
        url, _ = google_auth_url(flow)
        assert "access_type=offline" in url
        assert "prompt=consent" in url


class TestExchangeGoogleCode:
    def test_returns_oauth_result_with_refresh_token(self) -> None:
        """Happy path: Flow's ``fetch_token`` populates credentials,
        and ``exchange_google_code`` returns an ``OAuthResult``."""
        from mureo.auth_setup import OAuthResult

        flow = MagicMock()
        flow.credentials.refresh_token = "REFRESH_123"
        flow.credentials.token = "ACCESS_ABC"

        result = exchange_google_code(flow, code="AUTH_CODE")

        flow.fetch_token.assert_called_once_with(code="AUTH_CODE")
        assert isinstance(result, OAuthResult)
        assert result.refresh_token == "REFRESH_123"
        assert result.access_token == "ACCESS_ABC"

    def test_missing_refresh_token_raises(self) -> None:
        """Google only returns a refresh_token when ``prompt=consent``
        is forced. If it comes back missing the exchange must fail
        loudly so the caller can re-run with the right prompt."""
        flow = MagicMock()
        flow.credentials.refresh_token = None
        flow.credentials.token = "ACCESS_ABC"

        with pytest.raises(RuntimeError, match="refresh_token"):
            exchange_google_code(flow, code="AUTH_CODE")


class TestRunGoogleOauthUsesNewHelpers:
    """Regression lock: after refactor, ``run_google_oauth`` must still
    work (it is monkeypatched by many existing setup tests). The new
    implementation delegates to ``build_google_flow`` internally but
    keeps the same public behavior.
    """

    @pytest.mark.asyncio
    async def test_returns_oauth_result(self) -> None:
        from mureo.auth_setup import OAuthResult, run_google_oauth

        mock_creds = MagicMock()
        mock_creds.refresh_token = "REFRESH"
        mock_creds.token = "ACCESS"

        with patch(
            "mureo.auth_setup.build_google_flow"
        ) as mock_build_flow:
            mock_flow = MagicMock()
            mock_flow.run_local_server.return_value = mock_creds
            mock_build_flow.return_value = mock_flow

            result = await run_google_oauth(
                client_id="cid", client_secret="SECRET"
            )

        assert isinstance(result, OAuthResult)
        assert result.refresh_token == "REFRESH"
        assert result.access_token == "ACCESS"
        # Calls build_google_flow with redirect_uri=None (interactive path).
        mock_build_flow.assert_called_once_with(
            client_id="cid", client_secret="SECRET", redirect_uri=None
        )
