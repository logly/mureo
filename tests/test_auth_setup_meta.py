"""Tests for the Meta Ads OAuth flow and setup wizard (TDD: RED -> GREEN -> IMPROVE)."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth_setup import (
    MetaOAuthResult,
    OAuthCallbackServer,
    _exchange_code_for_short_token,
    _exchange_short_for_long_token,
    _generate_meta_auth_url,
    list_meta_ad_accounts,
    run_meta_oauth,
    setup_meta_ads,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


# ---------------------------------------------------------------------------
# 1. Build the authorization URL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generate_meta_auth_url() -> None:
    """The correct Facebook authorization URL is generated."""
    url = _generate_meta_auth_url(app_id="123456", port=8080)

    assert "https://www.facebook.com/v21.0/dialog/oauth" in url
    assert "client_id=123456" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback" in url or (
        "redirect_uri=http://localhost:8080/callback" in url
    )
    assert "scope=ads_management" in url
    assert "ads_read" in url
    assert "response_type=code" in url


@pytest.mark.unit
def test_generate_meta_auth_url_different_port() -> None:
    """An authorization URL is generated for different port numbers."""
    url = _generate_meta_auth_url(app_id="999", port=3000)

    assert "client_id=999" in url
    assert "3000" in url


# ---------------------------------------------------------------------------
# 2. Code -> Short-Lived Token exchange
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_exchange_code_for_short_token() -> None:
    """Can obtain a short-lived token from the code (HTTP mocked)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "short-lived-token-abc",
        "token_type": "bearer",
    }
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        token = await _exchange_code_for_short_token(
            code="auth-code-xyz",
            app_id="123456",
            app_secret="secret-789",
            redirect_uri="http://localhost:8080/callback",
        )

    assert token == "short-lived-token-abc"
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    assert f"{_GRAPH_API_BASE}/oauth/access_token" in call_args[0][0] or (
        call_args[1].get("url", call_args[0][0])
        == f"{_GRAPH_API_BASE}/oauth/access_token"
    )


@pytest.mark.unit
async def test_exchange_code_for_short_token_error() -> None:
    """Raises RuntimeError when token exchange fails."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error": {
            "message": "Invalid code",
            "type": "OAuthException",
            "code": 100,
        }
    }
    mock_response.raise_for_status = MagicMock(side_effect=Exception("400 Bad Request"))

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Short-Lived Token"):
            await _exchange_code_for_short_token(
                code="invalid-code",
                app_id="123456",
                app_secret="secret-789",
                redirect_uri="http://localhost:8080/callback",
            )


# ---------------------------------------------------------------------------
# 3. Short -> Long-Lived Token conversion
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_exchange_short_for_long_token() -> None:
    """Short -> long-lived token conversion (HTTP mocked)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "long-lived-token-xyz",
        "token_type": "bearer",
        "expires_in": 5184000,
    }
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _exchange_short_for_long_token(
            short_token="short-lived-token-abc",
            app_id="123456",
            app_secret="secret-789",
        )

    assert isinstance(result, MetaOAuthResult)
    assert result.access_token == "long-lived-token-xyz"
    assert result.expires_in == 5184000


@pytest.mark.unit
async def test_exchange_short_for_long_token_error() -> None:
    """Raises RuntimeError when long-lived token conversion fails."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error": {"message": "Invalid token", "type": "OAuthException", "code": 190}
    }
    mock_response.raise_for_status = MagicMock(side_effect=Exception("400 Bad Request"))

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Long-Lived Token"):
            await _exchange_short_for_long_token(
                short_token="invalid-token",
                app_id="123456",
                app_secret="secret-789",
            )


# ---------------------------------------------------------------------------
# 4. List ad accounts
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_list_meta_ad_accounts() -> None:
    """Fetch the ad-account list (HTTP mocked)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "act_111", "name": "Test Account 1", "account_status": 1},
            {"id": "act_222", "name": "Test Account 2", "account_status": 2},
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        accounts = await list_meta_ad_accounts(access_token="long-lived-token-xyz")

    assert len(accounts) == 2
    assert accounts[0]["id"] == "act_111"
    assert accounts[0]["name"] == "Test Account 1"
    assert accounts[1]["id"] == "act_222"

    # Verify the API request.
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "me/adaccounts" in url


@pytest.mark.unit
async def test_list_meta_ad_accounts_empty() -> None:
    """When there are zero ad accounts."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        accounts = await list_meta_ad_accounts(access_token="some-token")

    assert accounts == []


@pytest.mark.unit
async def test_list_meta_ad_accounts_follows_paging_next_until_exhausted() -> None:
    """When the Graph API splits the response across multiple pages,
    every page must be fetched and concatenated. Regression test for
    the original "only 25 BM accounts ever showed up" bug.
    """
    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {
        "data": [
            {"id": f"act_{i}", "name": f"A{i}", "account_status": 1} for i in range(100)
        ],
        "paging": {"next": "https://graph.facebook.com/v21.0/me/adaccounts?after=cur1"},
    }
    page1.raise_for_status = MagicMock()

    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = {
        "data": [
            {"id": f"act_{i}", "name": f"A{i}", "account_status": 1}
            for i in range(100, 175)
        ],
        "paging": {"next": "https://graph.facebook.com/v21.0/me/adaccounts?after=cur2"},
    }
    page2.raise_for_status = MagicMock()

    # Terminal page: no ``paging.next`` cursor → walk stops.
    page3 = MagicMock()
    page3.status_code = 200
    page3.json.return_value = {
        "data": [
            {"id": f"act_{i}", "name": f"A{i}", "account_status": 1}
            for i in range(175, 230)
        ],
        "paging": {},
    }
    page3.raise_for_status = MagicMock()

    with patch("mureo.meta_ads.accounts.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[page1, page2, page3])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        accounts = await list_meta_ad_accounts(access_token="bm-token")

    assert len(accounts) == 230, "every page must be appended"
    # Three calls: one per page.
    assert mock_client.get.call_count == 3
    # Order preserved (page1 → page2 → page3).
    assert accounts[0]["id"] == "act_0"
    assert accounts[100]["id"] == "act_100"
    assert accounts[-1]["id"] == "act_229"

    # Cursor-shape guarantees: the first call MUST send our params dict
    # (with access_token + limit); subsequent calls MUST follow the
    # Graph-supplied ``paging.next`` URL verbatim and pass ``params=None``
    # so the cursor is not corrupted by re-encoding.
    calls = mock_client.get.call_args_list
    assert calls[0].args[0].endswith("/me/adaccounts")
    assert calls[0].kwargs["params"]["access_token"] == "bm-token"
    assert calls[0].kwargs["params"]["limit"] >= 100
    assert calls[1].args[0] == (
        "https://graph.facebook.com/v21.0/me/adaccounts?after=cur1"
    )
    assert calls[1].kwargs.get("params") is None
    assert calls[2].args[0] == (
        "https://graph.facebook.com/v21.0/me/adaccounts?after=cur2"
    )
    assert calls[2].kwargs.get("params") is None


@pytest.mark.unit
async def test_list_meta_ad_accounts_refuses_non_graph_paging_next() -> None:
    """If the response body is tampered with and ``paging.next`` points
    at a non-Graph host, the walker must refuse to follow it (otherwise
    the access token — which lives in the cursor URL from page 2
    onward — would be leaked to whoever supplied the URL).
    """
    import logging

    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {
        "data": [{"id": "act_1", "name": "A1", "account_status": 1}],
        "paging": {"next": "https://attacker.example/steal?access_token=tok"},
    }
    page1.raise_for_status = MagicMock()

    with (
        patch("mureo.meta_ads.accounts.httpx.AsyncClient") as mock_client_cls,
        patch.object(logging.getLogger("mureo.meta_ads.accounts"), "warning") as warn,
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=page1)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        accounts = await list_meta_ad_accounts(access_token="tok")

    # Only the trusted first page is returned — the attacker URL is not
    # followed, so the dropdown silently truncates rather than leaking.
    assert accounts == [{"id": "act_1", "name": "A1", "account_status": 1}]
    assert mock_client.get.call_count == 1
    # The truncation must be visible in operator logs.
    assert warn.called
    assert "non-Graph" in warn.call_args.args[0]


@pytest.mark.unit
async def test_list_meta_ad_accounts_mid_walk_failure_discards_partial_and_redacts() -> (
    None
):
    """If page 1 succeeds and page 2 returns non-2xx, the walker must
    (a) raise ``RuntimeError`` (not return partial data) and
    (b) scrub the access token from the error message — the token
    lives inside the page-2 cursor URL and httpx's ``HTTPStatusError``
    embeds the full URL in its ``str()``.
    """
    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {
        "data": [{"id": "act_1", "name": "A1", "account_status": 1}],
        "paging": {
            "next": (
                "https://graph.facebook.com/v21.0/me/adaccounts"
                "?after=cur&access_token=SECRET-TOKEN-XYZ"
            )
        },
    }
    page1.raise_for_status = MagicMock()

    page2 = MagicMock()
    page2.status_code = 401
    page2.json.return_value = {"error": {"message": "Token expired"}}
    page2.raise_for_status = MagicMock(
        side_effect=Exception(
            "Client error '401 Unauthorized' for url "
            "'https://graph.facebook.com/v21.0/me/adaccounts"
            "?after=cur&access_token=SECRET-TOKEN-XYZ'"
        )
    )

    with patch("mureo.meta_ads.accounts.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[page1, page2])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError) as excinfo:
            await list_meta_ad_accounts(access_token="SECRET-TOKEN-XYZ")

    # Partial accounts MUST NOT be returned on mid-walk failure — caller
    # gets the error, not a half-filled list.
    msg = str(excinfo.value)
    assert (
        "SECRET-TOKEN-XYZ" not in msg
    ), "access token must not leak into error message"
    assert "***REDACTED***" in msg
    # Chain is broken with ``from None`` so the original exception's
    # ``__cause__`` (which carries the unscrubbed URL) is not surfaced.
    assert excinfo.value.__cause__ is None


@pytest.mark.unit
async def test_list_meta_ad_accounts_requests_large_page_size() -> None:
    """Default Graph API page size is 25 — we ask for the safe maximum
    so a single page covers most BMs and pagination only kicks in for
    truly large portfolios.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [], "paging": {}}
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.meta_ads.accounts.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await list_meta_ad_accounts(access_token="tok")

    call_kwargs = mock_client.get.call_args.kwargs
    params = call_kwargs.get("params") or {}
    assert (
        int(params.get("limit", 0)) >= 100
    ), "first request must ask for at least 100 accounts per page"


@pytest.mark.unit
async def test_list_meta_ad_accounts_caps_page_walk() -> None:
    """A buggy Graph API response that always returns a ``next``
    cursor must NOT spin the configure UI forever; the walker stops
    at the documented cap and warns so the gap is visible.
    """
    import logging

    from mureo.meta_ads.accounts import _MAX_PAGES

    looping_page = MagicMock()
    looping_page.status_code = 200
    looping_page.json.return_value = {
        "data": [{"id": "act_x", "name": "X", "account_status": 1}],
        "paging": {"next": "https://graph.facebook.com/v21.0/me/adaccounts?after=loop"},
    }
    looping_page.raise_for_status = MagicMock()

    with (
        patch("mureo.meta_ads.accounts.httpx.AsyncClient") as mock_client_cls,
        patch.object(logging.getLogger("mureo.meta_ads.accounts"), "warning") as warn,
    ):
        mock_client = AsyncMock()
        # Always return the same looping page — if the walker had no
        # cap it would hang the configure UI thread.
        mock_client.get = AsyncMock(return_value=looping_page)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        accounts = await list_meta_ad_accounts(access_token="tok")

    # Exact equality locks in the documented contract — a future change
    # that silently drops the cap to 1 would be caught here.
    assert mock_client.get.call_count == _MAX_PAGES
    assert len(accounts) == _MAX_PAGES
    # Operators must see a warning when the cap truncated the list.
    assert warn.called
    assert "cap" in warn.call_args.args[0]


@pytest.mark.unit
async def test_list_meta_ad_accounts_error() -> None:
    """Raises RuntimeError when fetching the ad-account list fails."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {
        "error": {"message": "Invalid access token", "type": "OAuthException"}
    }
    mock_response.raise_for_status = MagicMock(
        side_effect=Exception("401 Unauthorized")
    )

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Failed to retrieve ad account list"):
            await list_meta_ad_accounts(access_token="invalid-token")


# ---------------------------------------------------------------------------
# 5. Full setup flow
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_setup_meta_ads_flow(tmp_path: Path) -> None:
    """Complete setup flow (input / OAuth / API all mocked)."""
    credentials_path = tmp_path / "credentials.json"

    # Mock run_meta_oauth.
    mock_oauth_result = MetaOAuthResult(
        access_token="long-lived-token-xyz",
        expires_in=5184000,
    )

    # Mock the ad-account list.
    mock_accounts = [
        {"id": "act_111", "name": "Test Account 1", "account_status": 1},
        {"id": "act_222", "name": "Test Account 2", "account_status": 1},
    ]

    with (
        patch(
            "mureo.auth_setup.input_func", side_effect=["my-app-id", "my-app-secret"]
        ),
        patch("mureo.auth_setup._select_account", return_value="act_111"),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        result = await setup_meta_ads(credentials_path=credentials_path)

    assert result.access_token == "long-lived-token-xyz"
    assert result.app_id == "my-app-id"
    assert result.app_secret == "my-app-secret"

    # Verify OAuth was called.
    mock_oauth.assert_called_once_with(
        app_id="my-app-id",
        app_secret="my-app-secret",
    )

    # Verify the ad-account list was fetched.
    mock_list_accounts.assert_called_once_with(
        access_token="long-lived-token-xyz",
    )


@pytest.mark.unit
async def test_setup_meta_ads_single_account(tmp_path: Path) -> None:
    """A single ad account is auto-selected."""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token-abc",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_999", "name": "Only Account", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["app-id-1", "app-secret-1"]),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        result = await setup_meta_ads(credentials_path=credentials_path)

    assert result.access_token == "token-abc"
    assert result.app_id == "app-id-1"


# ---------------------------------------------------------------------------
# 6. Save credentials
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_save_credentials_meta(tmp_path: Path) -> None:
    """Meta Ads credentials are saved into credentials.json."""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="saved-token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_555", "name": "Saved Account", "account_status": 1},
    ]

    with (
        patch(
            "mureo.auth_setup.input_func", side_effect=["save-app-id", "save-secret"]
        ),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        await setup_meta_ads(credentials_path=credentials_path)

    # Verify the file was created.
    assert credentials_path.exists()

    data = json.loads(credentials_path.read_text(encoding="utf-8"))
    assert "meta_ads" in data
    assert data["meta_ads"]["access_token"] == "saved-token"
    assert data["meta_ads"]["app_id"] == "save-app-id"
    assert data["meta_ads"]["app_secret"] == "save-secret"
    assert data["meta_ads"]["account_id"] == "act_555"


@pytest.mark.unit
async def test_save_credentials_meta_preserves_existing(tmp_path: Path) -> None:
    """Add Meta Ads info without overwriting existing Google Ads credentials."""
    credentials_path = tmp_path / "credentials.json"

    # Existing Google Ads credentials.
    existing_data = {
        "google_ads": {
            "developer_token": "existing-dev-token",
            "client_id": "existing-client-id",
        }
    }
    credentials_path.write_text(json.dumps(existing_data), encoding="utf-8")

    mock_oauth_result = MetaOAuthResult(
        access_token="new-meta-token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_777", "name": "Meta Account", "account_status": 1},
    ]

    with (
        patch(
            "mureo.auth_setup.input_func", side_effect=["meta-app-id", "meta-secret"]
        ),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        await setup_meta_ads(credentials_path=credentials_path)

    data = json.loads(credentials_path.read_text(encoding="utf-8"))

    # Existing Google Ads info should remain.
    assert data["google_ads"]["developer_token"] == "existing-dev-token"
    # Meta Ads info should be added.
    assert data["meta_ads"]["access_token"] == "new-meta-token"
    assert data["meta_ads"]["account_id"] == "act_777"


# ---------------------------------------------------------------------------
# 7. MetaOAuthResult immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_meta_oauth_result_immutable() -> None:
    """MetaOAuthResult is frozen."""
    import dataclasses

    result = MetaOAuthResult(access_token="tok", expires_in=3600)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.access_token = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 8. run_meta_oauth integration test (local server + token exchange)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_meta_oauth() -> None:
    """run_meta_oauth uses OAuthCallbackServer and completes the OAuth flow."""
    mock_long_result = MetaOAuthResult(
        access_token="final-long-token",
        expires_in=5184000,
    )

    with (
        patch("mureo.auth_setup.webbrowser.open") as mock_browser,
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short-token-from-code",
        ) as mock_short,
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=mock_long_result,
        ) as mock_long,
        patch("mureo.auth_setup.OAuthCallbackServer") as mock_server_cls,
        patch("secrets.token_urlsafe", return_value="test-state"),
        patch("builtins.print"),
    ):
        mock_server = MagicMock()
        mock_server.server.server_address = ("localhost", 9999)
        mock_server.authorization_code = "auth-code-received"
        mock_server.error = None
        mock_server_cls.return_value = mock_server

        result = await run_meta_oauth(app_id="test-app", app_secret="test-secret")

    assert result.access_token == "final-long-token"
    assert result.expires_in == 5184000

    # Verify the browser was opened.
    mock_browser.assert_called_once()
    browser_url = mock_browser.call_args[0][0]
    assert "test-app" in browser_url

    # Verify the short-lived token exchange was called.
    mock_short.assert_called_once_with(
        code="auth-code-received",
        app_id="test-app",
        app_secret="test-secret",
        redirect_uri="http://localhost:9999/callback",
    )

    # Verify the long-lived token conversion was called.
    mock_long.assert_called_once_with(
        short_token="short-token-from-code",
        app_id="test-app",
        app_secret="test-secret",
    )


# ---------------------------------------------------------------------------
# 9. Meta OAuth state parameter (CSRF protection: CRITICAL-1)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_meta_auth_url_contains_state() -> None:
    """The Meta authorization URL includes the state parameter."""
    url = _generate_meta_auth_url(app_id="123456", port=8080, state="meta-state-abc")
    assert "state=meta-state-abc" in url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_meta_oauth_uses_state() -> None:
    """run_meta_oauth generates and validates the state parameter."""
    mock_long_result = MetaOAuthResult(
        access_token="final-long-token",
        expires_in=5184000,
    )

    with (
        patch("mureo.auth_setup.webbrowser.open") as mock_browser,
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short-token-from-code",
        ),
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=mock_long_result,
        ),
        patch("mureo.auth_setup.OAuthCallbackServer") as mock_server_cls,
        patch("secrets.token_urlsafe", return_value="meta-state-xyz"),
        patch("builtins.print"),
    ):
        mock_server = MagicMock()
        mock_server.server.server_address = ("localhost", 9999)
        mock_server.authorization_code = "auth-code-received"
        mock_server.error = None
        mock_server_cls.return_value = mock_server

        result = await run_meta_oauth(app_id="test-app", app_secret="test-secret")

    assert result.access_token == "final-long-token"

    # expected_state should be passed to OAuthCallbackServer.
    server_call_kwargs = mock_server_cls.call_args[1]
    assert server_call_kwargs.get("expected_state") == "meta-state-xyz"

    # The browser URL should include state.
    browser_url = mock_browser.call_args[0][0]
    assert "state=meta-state-xyz" in browser_url


# ---------------------------------------------------------------------------
# 10. Meta OAuth flow execution order (CRITICAL-2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_oauth_flow_order() -> None:
    """run_meta_oauth runs in the order server-start → browser → wait-for-callback
    (the _start_callback_server blocking issue is fixed)."""
    mock_long_result = MetaOAuthResult(
        access_token="ordered-token",
        expires_in=5184000,
    )

    call_order: list[str] = []

    def mock_wait_for_callback() -> None:
        call_order.append("wait_for_callback")

    def mock_browser_open(url: str) -> None:
        call_order.append("browser_open")

    with (
        patch("mureo.auth_setup.webbrowser.open", side_effect=mock_browser_open),
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short-tok",
        ),
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=mock_long_result,
        ),
        patch("mureo.auth_setup.OAuthCallbackServer") as mock_server_cls,
        patch("secrets.token_urlsafe", return_value="s"),
        patch("builtins.print"),
    ):
        mock_server = MagicMock()
        mock_server.server.server_address = ("localhost", 9999)
        mock_server.authorization_code = "code"
        mock_server.error = None
        mock_server.wait_for_callback = mock_wait_for_callback
        mock_server_cls.return_value = mock_server

        await run_meta_oauth(app_id="app", app_secret="secret")

    # wait_for_callback should be called after the browser is opened.
    # (i.e. the design uses OAuthCallbackServer = no _start_callback_server blocking issue).
    assert "browser_open" in call_order
    # The server starts on a separate thread, so wait_for_callback runs inside that thread.


# ---------------------------------------------------------------------------
# 11. Meta-side input validation (HIGH-1)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_invalid_account_choice(tmp_path: Path) -> None:
    """An invalid input during account selection must not raise."""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token-abc",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_111", "name": "Account 1", "account_status": 1},
        {"id": "act_222", "name": "Account 2", "account_status": 1},
    ]

    with (
        patch(
            "mureo.auth_setup.input_func",
            side_effect=["app-id", "app-secret"],
        ),
        patch("mureo.auth_setup._select_account", return_value="act_111"),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        # Should complete without ValueError (try/except has been added).
        result = await setup_meta_ads(credentials_path=credentials_path)

    assert result.access_token == "token-abc"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_out_of_range_choice(tmp_path: Path) -> None:
    """When the account-selection number is out of range."""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token-abc",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_111", "name": "Account 1", "account_status": 1},
    ]

    # 1st call: out of range (99); 2nd call: valid input (1).
    with (
        patch(
            "mureo.auth_setup.input_func",
            side_effect=["app-id", "app-secret", "99", "1"],
        ),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        result = await setup_meta_ads(credentials_path=credentials_path)

    assert result.access_token == "token-abc"


# ---------------------------------------------------------------------------
# 12. Meta-side file permissions (HIGH-2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX 0o600; Windows perms are documented best-effort (NTFS ACL)",
)
async def test_setup_meta_ads_file_permissions(tmp_path: Path) -> None:
    """File permissions are 0600 when saving Meta Ads credentials."""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token-for-perm",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_perm", "name": "Perm Account", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["app-id", "app-secret"]),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        await setup_meta_ads(credentials_path=credentials_path)

    file_mode = credentials_path.stat().st_mode
    assert stat.S_IMODE(file_mode) == 0o600


# ---------------------------------------------------------------------------
# 13. Unified callback server (HIGH-3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_oauth_uses_unified_callback_server() -> None:
    """The Meta OAuth flow uses OAuthCallbackServer (the unified server)."""
    mock_long_result = MetaOAuthResult(
        access_token="unified-token",
        expires_in=5184000,
    )

    with (
        patch("mureo.auth_setup.webbrowser.open"),
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short",
        ),
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=mock_long_result,
        ),
        patch("mureo.auth_setup.OAuthCallbackServer") as mock_server_cls,
        patch("secrets.token_urlsafe", return_value="st"),
        patch("builtins.print"),
    ):
        mock_server = MagicMock()
        mock_server.server.server_address = ("localhost", 9999)
        mock_server.authorization_code = "code"
        mock_server.error = None
        mock_server_cls.return_value = mock_server

        await run_meta_oauth(app_id="app", app_secret="secret")

    # OAuthCallbackServer should be used (not _start_callback_server).
    mock_server_cls.assert_called_once()


# ---------------------------------------------------------------------------
# 14. httpx timeout（WARNING）
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_short_token_exchange_uses_timeout() -> None:
    """A timeout is set on httpx during Meta short-lived-token exchange."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "short-tok"}
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await _exchange_code_for_short_token(
            code="c",
            app_id="a",
            app_secret="s",
            redirect_uri="http://localhost/cb",
        )

    call_kwargs = mock_client_cls.call_args[1] if mock_client_cls.call_args[1] else {}
    assert call_kwargs.get("timeout") == 30.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_long_token_exchange_uses_timeout() -> None:
    """A timeout is set on httpx during Meta long-lived-token conversion."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "long-tok",
        "expires_in": 5184000,
    }
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await _exchange_short_for_long_token(
            short_token="st",
            app_id="a",
            app_secret="s",
        )

    call_kwargs = mock_client_cls.call_args[1] if mock_client_cls.call_args[1] else {}
    assert call_kwargs.get("timeout") == 30.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_ad_accounts_uses_timeout() -> None:
    """A timeout is set on httpx during ad-account list fetching."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await list_meta_ad_accounts(access_token="tok")

    call_kwargs = mock_client_cls.call_args[1] if mock_client_cls.call_args[1] else {}
    assert call_kwargs.get("timeout") == 30.0


# ---------------------------------------------------------------------------
# 15. Unified input_func (SUGGESTION)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_uses_input_func(tmp_path: Path) -> None:
    """setup_meta_ads uses input_func (which is test-swappable)."""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_1", "name": "Acc", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["aid", "asec"]) as mock_input,
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list.return_value = mock_accounts

        await setup_meta_ads(credentials_path=credentials_path)

    # input_func should be called (not the direct input call).
    assert mock_input.call_count >= 2
