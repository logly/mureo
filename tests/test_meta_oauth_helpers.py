"""Tests for auth_setup Meta OAuth public helpers.

These helpers are the shared building blocks between the interactive
CLI (``setup_meta_ads``) and the web-based wizard. Extracting them so
both paths build the same auth URL and run the same short→long token
exchange prevents drift.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# Module imports under test — some of these don't exist yet.
from mureo.auth_setup import (  # noqa: I001
    build_meta_auth_url,
    exchange_meta_code,
)


class TestBuildMetaAuthUrl:
    def test_returns_facebook_oauth_dialog_url(self) -> None:
        url = build_meta_auth_url(
            app_id="1234567890",
            redirect_uri="http://127.0.0.1:8080/meta-ads/callback",
            state="state-xyz",
        )
        assert url.startswith("https://www.facebook.com/")
        assert "dialog/oauth" in url
        assert "client_id=1234567890" in url
        # redirect_uri appears URL-encoded
        assert (
            "redirect_uri=http%3A%2F%2F127.0.0.1%3A8080%2Fmeta-ads%2Fcallback"
            in url
        )
        assert "state=state-xyz" in url
        assert "response_type=code" in url

    def test_includes_required_scopes(self) -> None:
        url = build_meta_auth_url(
            app_id="app",
            redirect_uri="http://127.0.0.1:1/cb",
            state="s",
        )
        assert "ads_management" in url
        assert "ads_read" in url
        assert "business_management" in url

    def test_rejects_non_localhost_redirect_uri(self) -> None:
        """Same localhost-only guard as the Google flow so a caller
        cannot redirect Facebook's OAuth grant to a remote host."""
        with pytest.raises(ValueError):
            build_meta_auth_url(
                app_id="app",
                redirect_uri="https://evil.example.com/cb",
                state="s",
            )

    def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(ValueError):
            build_meta_auth_url(
                app_id="app",
                redirect_uri="javascript:alert(1)",
                state="s",
            )

    def test_state_required(self) -> None:
        """``state`` is required for the web wizard (CSRF protection)
        — callers must supply it, not rely on a default."""
        with pytest.raises(TypeError):
            build_meta_auth_url(  # type: ignore[call-arg]
                app_id="app",
                redirect_uri="http://127.0.0.1:1/cb",
            )


class TestExchangeMetaCode:
    @pytest.mark.asyncio
    async def test_returns_long_lived_token(self) -> None:
        """Happy path: composes short-token + upgrade-to-long-token in
        one public call, returning a MetaOAuthResult."""
        from mureo.auth_setup import MetaOAuthResult

        with (
            patch(
                "mureo.auth_setup._exchange_code_for_short_token",
                new=AsyncMock(return_value="SHORT_TOKEN"),
            ) as mock_short,
            patch(
                "mureo.auth_setup._exchange_short_for_long_token",
                new=AsyncMock(
                    return_value=MetaOAuthResult(
                        access_token="LONG_TOKEN", expires_in=5184000
                    )
                ),
            ) as mock_long,
        ):
            result = await exchange_meta_code(
                code="AUTH_CODE",
                app_id="app",
                app_secret="secret",
                redirect_uri="http://127.0.0.1:8080/meta-ads/callback",
            )

        assert result.access_token == "LONG_TOKEN"
        assert result.expires_in == 5184000

        mock_short.assert_awaited_once_with(
            code="AUTH_CODE",
            app_id="app",
            app_secret="secret",
            redirect_uri="http://127.0.0.1:8080/meta-ads/callback",
        )
        mock_long.assert_awaited_once_with(
            short_token="SHORT_TOKEN",
            app_id="app",
            app_secret="secret",
        )

    @pytest.mark.asyncio
    async def test_short_token_failure_propagates(self) -> None:
        with patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new=AsyncMock(side_effect=RuntimeError("facebook said no")),
        ):
            with pytest.raises(RuntimeError, match="facebook said no"):
                await exchange_meta_code(
                    code="AUTH_CODE",
                    app_id="app",
                    app_secret="secret",
                    redirect_uri="http://127.0.0.1:1/cb",
                )

    @pytest.mark.asyncio
    async def test_long_upgrade_failure_propagates(self) -> None:
        with (
            patch(
                "mureo.auth_setup._exchange_code_for_short_token",
                new=AsyncMock(return_value="SHORT"),
            ),
            patch(
                "mureo.auth_setup._exchange_short_for_long_token",
                new=AsyncMock(side_effect=RuntimeError("upgrade failed")),
            ),
        ):
            with pytest.raises(RuntimeError, match="upgrade failed"):
                await exchange_meta_code(
                    code="AUTH_CODE",
                    app_id="app",
                    app_secret="secret",
                    redirect_uri="http://127.0.0.1:1/cb",
                )
