"""Unit tests for the Meta ``debug_token`` inspection probe (#726).

A Business Manager system-user token is minted with a 60-day life (the
"never expires" variant is no longer what the Business settings UI offers),
so the paste route has to learn when the token it is about to store dies.
``mureo.meta_ads.accounts.inspect_meta_access_token`` asks Graph:

    GET /debug_token?input_token=<token>&access_token=<token>

per https://developers.facebook.com/docs/facebook-login/access-tokens/debugging-and-error-handling
("replace {input-token} with the token you want information about and
{access-token} with a valid access token ... both tokens must be from the
same app") and keeps only the curated fields — ``type``, ``expires_at``,
``data_access_expires_at``, ``issued_at``. The rest of the envelope
(``scopes``, ``user_id``, ``app_id``) is not echoed anywhere, so the #605
rule that a Graph body never travels verbatim to a UI or a log still holds.

httpx is mocked so the tests never touch the network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_TOKEN = "sys-tok"

# 2026-11-01T00:00:00+00:00 / 2026-09-02T00:00:00+00:00 / 2026-09-01T...
_EXPIRES_AT = 1793491200
_DATA_ACCESS_EXPIRES_AT = 1798675200
_ISSUED_AT = 1788307200


def _iso(unix: int) -> str:
    return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat()


def _resp(status: int, payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = "error-body"
    return resp


def _patched_client(route: Any) -> Any:
    instance = AsyncMock()
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _get(url: str, params: dict[str, Any] | None = None) -> MagicMock:
        calls.append((url, dict(params or {})))
        return route(url)

    instance.get = AsyncMock(side_effect=_get)
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=False)
    mock_cls = MagicMock(return_value=instance)
    patcher = patch("httpx.AsyncClient", mock_cls)
    patcher.calls = calls  # type: ignore[attr-defined]
    return patcher


def _debug_route(payload: dict[str, Any], status: int = 200) -> Any:
    def _dispatch(url: str) -> MagicMock:
        assert "/debug_token" in url, f"unexpected URL: {url}"
        return _resp(status, payload)

    return _dispatch


_FULL_DATA = {
    "data": {
        "app_id": "111",
        "application": "Some App",
        "type": "SYSTEM_USER",
        "is_valid": True,
        "expires_at": _EXPIRES_AT,
        "data_access_expires_at": _DATA_ACCESS_EXPIRES_AT,
        "issued_at": _ISSUED_AT,
        "scopes": ["ads_management"],
        "user_id": "10215241773831025",
    }
}


@pytest.mark.asyncio
async def test_calls_debug_token_with_the_token_on_both_parameters() -> None:
    from mureo.meta_ads.accounts import inspect_meta_access_token

    patcher = _patched_client(_debug_route(_FULL_DATA))
    with patcher:
        await inspect_meta_access_token(_TOKEN)

    url, params = patcher.calls[0]  # type: ignore[attr-defined]
    assert url.endswith("/debug_token")
    assert params["input_token"] == _TOKEN
    assert params["access_token"] == _TOKEN


@pytest.mark.asyncio
async def test_returns_only_curated_fields_as_iso_utc() -> None:
    from mureo.meta_ads.accounts import inspect_meta_access_token

    with _patched_client(_debug_route(_FULL_DATA)):
        info = await inspect_meta_access_token(_TOKEN)

    assert set(info) == {
        "type",
        "expires_at",
        "data_access_expires_at",
        "issued_at",
    }
    assert info["type"] == "SYSTEM_USER"
    assert info["expires_at"] == _iso(_EXPIRES_AT)
    assert info["data_access_expires_at"] == _iso(_DATA_ACCESS_EXPIRES_AT)
    assert info["issued_at"] == _iso(_ISSUED_AT)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [0, -1, None, "", "not-a-number"])
async def test_unusable_timestamp_reads_as_no_expiry(raw: Any) -> None:
    """Graph stamps a non-expiring token with ``0`` and omits the field on
    some token types. Neither is a date, so neither may be rendered as one —
    an unknown expiry is ``None``, never epoch-zero."""

    from mureo.meta_ads.accounts import inspect_meta_access_token

    payload = {"data": {"type": "SYSTEM_USER", "expires_at": raw}}
    with _patched_client(_debug_route(payload)):
        info = await inspect_meta_access_token(_TOKEN)

    assert info["expires_at"] is None
    assert info["issued_at"] is None


@pytest.mark.asyncio
async def test_non_200_raises_inspect_error_without_the_token() -> None:
    from mureo.meta_ads.accounts import (
        MetaTokenInspectError,
        MetaTokenValidationError,
        inspect_meta_access_token,
    )

    payload = {
        "error": {
            "message": f"Invalid OAuth access token {_TOKEN}",
            "error_subcode": 463,
            "fbtrace_id": "H2il2t5bn4e",
        }
    }
    with (
        _patched_client(_debug_route(payload, status=400)),
        pytest.raises(MetaTokenInspectError) as exc,
    ):
        await inspect_meta_access_token(_TOKEN)

    assert issubclass(MetaTokenInspectError, MetaTokenValidationError)
    assert _TOKEN not in str(exc.value)
    assert "subcode=463" in str(exc.value)


@pytest.mark.asyncio
async def test_empty_token_rejected() -> None:
    from mureo.meta_ads.accounts import MetaTokenInspectError, inspect_meta_access_token

    with pytest.raises(MetaTokenInspectError):
        await inspect_meta_access_token("")


# ---------------------------------------------------------------------------
# validate_meta_access_token folds the inspection in (best-effort)
# ---------------------------------------------------------------------------


def _full_route(
    permissions: dict[str, Any],
    adaccounts: dict[str, Any],
    debug: dict[str, Any] | None,
) -> Any:
    def _dispatch(url: str) -> MagicMock:
        if "/me/permissions" in url:
            return _resp(200, permissions)
        if "/me/adaccounts" in url:
            return _resp(200, adaccounts)
        if "/debug_token" in url:
            if debug is None:
                return _resp(400, {"error": {"message": "nope"}})
            return _resp(200, debug)
        raise AssertionError(f"unexpected URL: {url}")

    return _dispatch


_PERMS = {"data": [{"permission": "ads_read", "status": "granted"}]}
_ACCTS = {"data": [{"id": "act_1", "name": "One"}]}


@pytest.mark.asyncio
async def test_validate_reports_token_info() -> None:
    from mureo.meta_ads.accounts import validate_meta_access_token

    with _patched_client(_full_route(_PERMS, _ACCTS, _FULL_DATA)):
        result = await validate_meta_access_token(_TOKEN)

    assert result["token_info"] == {
        "type": "SYSTEM_USER",
        "expires_at": _iso(_EXPIRES_AT),
        "data_access_expires_at": _iso(_DATA_ACCESS_EXPIRES_AT),
        "issued_at": _iso(_ISSUED_AT),
    }
    assert result["token_inspect_error"] is None
    # The pre-existing contract is untouched.
    assert result["scopes"] == ["ads_read"]
    assert result["accounts"] == [{"id": "act_1", "name": "One"}]


@pytest.mark.asyncio
async def test_validate_survives_a_failed_inspection() -> None:
    """``debug_token`` needs an app access token or an app developer's user
    token; a system-user token inspecting itself is not documented to work
    everywhere. A refusal must not cost the operator the whole probe — it is
    reported alongside the scopes, not instead of them."""

    from mureo.meta_ads.accounts import validate_meta_access_token

    with _patched_client(_full_route(_PERMS, _ACCTS, None)):
        result = await validate_meta_access_token(_TOKEN)

    assert result["token_info"] is None
    assert result["token_inspect_error"]
    assert _TOKEN not in result["token_inspect_error"]
    assert result["scopes"] == ["ads_read"]
