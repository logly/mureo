"""Unit tests for the Meta access-token validation probe (#458).

``mureo.meta_ads.accounts.validate_meta_access_token`` backs the
configure-UI "paste a system-user token" path: it reports which of the
required OAuth scopes the pasted token actually carries (GET
/me/permissions) and which ad accounts it can reach (GET /me/adaccounts)
so the operator can pick an account before saving. An invalid/expired
token surfaces Meta's own error.message (plus subcode / fbtrace_id when
present), mirroring the error-surfacing convention in
``mureo.meta_ads.client._request``.

httpx is mocked so the tests never touch the network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth_setup import _META_OAUTH_SCOPES

_REQUIRED = [s.strip() for s in _META_OAUTH_SCOPES.split(",") if s.strip()]


def _resp(status: int, payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = "error-body"

    def _raise() -> None:
        if status != 200:
            raise RuntimeError(f"HTTP {status}")

    resp.raise_for_status = MagicMock(side_effect=_raise)
    return resp


def _patched_client(route: Any) -> Any:
    """Patch httpx.AsyncClient so ``get(url, ...)`` dispatches on ``url``.

    ``route`` is a callable ``url -> MagicMock`` response used for both the
    /me/permissions probe and the /me/adaccounts walk (both open their own
    ``async with httpx.AsyncClient()``).
    """
    instance = AsyncMock()

    async def _get(url: str, params: dict[str, Any] | None = None) -> MagicMock:
        return route(url)

    instance.get = AsyncMock(side_effect=_get)
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=False)
    mock_cls = MagicMock(return_value=instance)
    return patch("httpx.AsyncClient", mock_cls)


def _route(permissions: dict[str, Any], adaccounts: dict[str, Any]) -> Any:
    def _dispatch(url: str) -> MagicMock:
        if "/me/permissions" in url:
            return _resp(200, permissions)
        if "/me/adaccounts" in url:
            return _resp(200, adaccounts)
        raise AssertionError(f"unexpected URL: {url}")

    return _dispatch


@pytest.mark.unit
@pytest.mark.asyncio
async def test_returns_granted_and_missing_scopes() -> None:
    from mureo.meta_ads.accounts import validate_meta_access_token

    perms = {
        "data": [
            {"permission": "ads_management", "status": "granted"},
            {"permission": "ads_read", "status": "granted"},
            {"permission": "business_management", "status": "declined"},
        ]
    }
    accts = {"data": [{"id": "act_1", "name": "Acct One", "account_status": 1}]}

    with _patched_client(_route(perms, accts)):
        result = await validate_meta_access_token("sys-tok")

    assert set(result["scopes"]) == {"ads_management", "ads_read"}
    # Everything required except the two granted scopes is missing.
    assert "business_management" in result["missing_scopes"]
    assert "ads_management" not in result["missing_scopes"]
    for scope in _REQUIRED:
        if scope not in {"ads_management", "ads_read"}:
            assert scope in result["missing_scopes"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_required_scopes_granted_yields_no_missing() -> None:
    from mureo.meta_ads.accounts import validate_meta_access_token

    perms = {"data": [{"permission": s, "status": "granted"} for s in _REQUIRED]}
    accts = {"data": []}

    with _patched_client(_route(perms, accts)):
        result = await validate_meta_access_token("sys-tok")

    assert result["missing_scopes"] == []
    assert set(result["scopes"]) == set(_REQUIRED)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_accounts_reduced_to_id_and_name() -> None:
    from mureo.meta_ads.accounts import validate_meta_access_token

    perms = {"data": [{"permission": "ads_management", "status": "granted"}]}
    accts = {
        "data": [
            {"id": "act_1", "name": "One", "account_status": 1},
            {"id": "act_2", "name": "Two", "account_status": 2},
        ]
    }

    with _patched_client(_route(perms, accts)):
        result = await validate_meta_access_token("sys-tok")

    assert result["accounts"] == [
        {"id": "act_1", "name": "One"},
        {"id": "act_2", "name": "Two"},
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_token_raises_with_meta_message() -> None:
    from mureo.meta_ads.accounts import validate_meta_access_token

    error_payload = {
        "error": {
            "message": "Invalid OAuth access token.",
            "error_subcode": 463,
            "fbtrace_id": "AbCdEf123",
        }
    }

    def _dispatch(url: str) -> MagicMock:
        if "/me/permissions" in url:
            return _resp(400, error_payload)
        raise AssertionError("adaccounts must not be reached on invalid token")

    with _patched_client(_dispatch), pytest.raises(RuntimeError) as exc:
        await validate_meta_access_token("bad-tok")

    text = str(exc.value)
    assert "Invalid OAuth access token." in text
    assert "463" in text
    assert "AbCdEf123" in text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_message_redacts_token() -> None:
    from mureo.meta_ads.accounts import validate_meta_access_token

    secret = "super-secret-token-value"

    def _dispatch(url: str) -> MagicMock:
        if "/me/permissions" in url:
            # Meta echoing the token back in the message must be scrubbed.
            return _resp(400, {"error": {"message": f"token {secret} is invalid"}})
        raise AssertionError("adaccounts must not be reached")

    with _patched_client(_dispatch), pytest.raises(RuntimeError) as exc:
        await validate_meta_access_token(secret)

    assert secret not in str(exc.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_token_rejected() -> None:
    from mureo.meta_ads.accounts import (
        MetaTokenInvalidError,
        validate_meta_access_token,
    )

    with pytest.raises(MetaTokenInvalidError):
        await validate_meta_access_token("")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_token_raises_token_invalid_subtype() -> None:
    from mureo.meta_ads.accounts import (
        MetaTokenInvalidError,
        validate_meta_access_token,
    )

    def _dispatch(url: str) -> MagicMock:
        if "/me/permissions" in url:
            return _resp(400, {"error": {"message": "bad token"}})
        raise AssertionError("adaccounts must not be reached")

    with _patched_client(_dispatch), pytest.raises(MetaTokenInvalidError):
        await validate_meta_access_token("bad-tok")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_account_listing_failure_is_distinct_error() -> None:
    """A valid token (permissions OK) whose /me/adaccounts walk fails raises
    MetaAccountFetchError — NOT MetaTokenInvalidError — so the caller can tell
    "retry" from "the token is bad"."""
    from mureo.meta_ads.accounts import (
        MetaAccountFetchError,
        MetaTokenInvalidError,
        validate_meta_access_token,
    )

    perms = {"data": [{"permission": "ads_management", "status": "granted"}]}

    def _dispatch(url: str) -> MagicMock:
        if "/me/permissions" in url:
            return _resp(200, perms)
        if "/me/adaccounts" in url:
            # Graph 500 after a good permissions probe -> account walk fails.
            return _resp(500, {"error": {"message": "transient graph error"}})
        raise AssertionError(f"unexpected URL: {url}")

    with _patched_client(_dispatch), pytest.raises(MetaAccountFetchError) as exc:
        await validate_meta_access_token("good-tok")

    assert not isinstance(exc.value, MetaTokenInvalidError)
