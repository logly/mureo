"""Regression: Meta OAuth token calls must POST secrets in the body, not GET.

httpx logs ``request.url`` at INFO. If the ``client_secret`` and the token
material (``code`` / ``fb_exchange_token`` / the token being refreshed) were
sent as GET query parameters, they would leak into any INFO-level log. Meta's
Graph ``/oauth/access_token`` accepts these token-grant parameters via POST as
well as GET, so all three call sites POST them in the request body.

These tests assert, for each of the three endpoints, that:
* ``client.post`` is used (``client.get`` is never called), and
* the secret + token material ride in the ``data`` (body) kwarg, never in a
  ``params`` (query-string) kwarg or in the request URL.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"


def _mock_client(json_body: dict[str, Any]) -> tuple[Any, Any]:
    """An httpx.AsyncClient double whose ``post`` returns ``json_body``.

    ``get`` is wired to fail loudly so a regression back to GET is caught
    rather than silently mocked away.
    """
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = json_body
    response.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(side_effect=AssertionError("must not send secrets via GET"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client, response


def _assert_body_carries(call: Any, *secret_values: str) -> None:
    """The POST body holds every secret value; the URL/query holds none."""
    url = call.args[0] if call.args else call.kwargs.get("url", "")
    assert url == _TOKEN_URL
    # No query-string transport — that is the whole point of the fix.
    assert "params" not in call.kwargs, "secrets must not ride in the query string"
    body = call.kwargs.get("data") or {}
    body_values = set(body.values())
    for value in secret_values:
        assert value in body_values, f"{value!r} must be in the POST body"
    # And never smuggled into the URL itself.
    for value in secret_values:
        assert value not in url


@pytest.mark.unit
async def test_refresh_api_posts_secret_in_body() -> None:
    from mureo.auth import MetaAdsCredentials, _call_refresh_api

    creds = MetaAdsCredentials(
        access_token="OLD-TOKEN",
        app_id="app-123",
        app_secret="SECRET-456",
        token_obtained_at=None,
    )
    client, _ = _mock_client({"access_token": "NEW-TOKEN", "expires_in": 5183944})

    with patch("mureo.auth.httpx.AsyncClient", return_value=client):
        new_token, _ = await _call_refresh_api(creds)

    assert new_token == "NEW-TOKEN"
    client.post.assert_awaited_once()
    client.get.assert_not_called()
    _assert_body_carries(client.post.call_args, "SECRET-456", "OLD-TOKEN")


@pytest.mark.unit
async def test_code_exchange_posts_secret_and_code_in_body() -> None:
    from mureo.auth_setup import _exchange_code_for_short_token

    client, _ = _mock_client({"access_token": "SHORT-TOKEN"})

    with patch("mureo.auth_setup.httpx.AsyncClient", return_value=client):
        token = await _exchange_code_for_short_token(
            code="AUTH-CODE",
            app_id="app-123",
            app_secret="SECRET-456",
            redirect_uri="http://localhost:8080/callback",
        )

    assert token == "SHORT-TOKEN"
    client.post.assert_awaited_once()
    client.get.assert_not_called()
    _assert_body_carries(client.post.call_args, "SECRET-456", "AUTH-CODE")


@pytest.mark.unit
async def test_long_exchange_posts_secret_and_token_in_body() -> None:
    from mureo.auth_setup import MetaOAuthResult, _exchange_short_for_long_token

    client, _ = _mock_client({"access_token": "LONG-TOKEN", "expires_in": 5184000})

    with patch("mureo.auth_setup.httpx.AsyncClient", return_value=client):
        result = await _exchange_short_for_long_token(
            short_token="SHORT-TOKEN",
            app_id="app-123",
            app_secret="SECRET-456",
        )

    assert isinstance(result, MetaOAuthResult)
    assert result.access_token == "LONG-TOKEN"
    client.post.assert_awaited_once()
    client.get.assert_not_called()
    _assert_body_carries(client.post.call_args, "SECRET-456", "SHORT-TOKEN")
