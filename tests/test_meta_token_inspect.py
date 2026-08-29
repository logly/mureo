"""Unit tests for the Meta ``debug_token`` inspection probe (#726).

A Business Manager system-user token is minted with a 60-day life (the
"never expires" variant is no longer what the Business settings UI offers),
so the paste route has to learn when the token it is about to store dies.
``mureo.meta_ads.accounts.inspect_meta_access_token`` asks Graph for
``/debug_token`` with ``input_token`` and ``access_token`` both set to the
pasted token, per
https://developers.facebook.com/docs/facebook-login/access-tokens/debugging-and-error-handling
("replace {input-token} with the token you want information about and
{access-token} with a valid access token ... both tokens must be from the
same app").

Meta documents that call as a GET with the tokens in the query string.
mureo sends them in a POST body instead: httpx logs ``request.url`` at
INFO, so the documented form leaks the raw credential into any log a host
application configures at INFO. The transport is pinned below, because it
is a security property and not an implementation detail.

Only the curated fields come back — ``type``, ``expires_at``,
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


class _Call:
    """One recorded request: the verb, the URL, the query, the body."""

    def __init__(
        self,
        method: str,
        url: str,
        params: dict[str, Any],
        data: dict[str, Any],
    ) -> None:
        self.method = method
        self.url = url
        self.params = params
        self.data = data


def _patched_client(route: Any) -> Any:
    """An ``httpx.AsyncClient`` double recording both verbs.

    ``debug_token`` is POSTed (the token may not ride in a URL) while the
    scope and account probes are still GETs, so the double has to answer
    both and keep them apart.
    """

    instance = AsyncMock()
    calls: list[_Call] = []

    async def _get(url: str, params: dict[str, Any] | None = None) -> MagicMock:
        calls.append(_Call("GET", url, dict(params or {}), {}))
        return route(url)

    async def _post(
        url: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> MagicMock:
        calls.append(_Call("POST", url, dict(params or {}), dict(data or {})))
        return route(url)

    instance.get = AsyncMock(side_effect=_get)
    instance.post = AsyncMock(side_effect=_post)
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
async def test_posts_debug_token_with_the_token_on_both_parameters() -> None:
    """The token rides in the POST body, on both parameters, and appears
    nowhere in the URL or the query string.

    httpx logs ``request.url`` at INFO. The query-string form Meta documents
    would therefore write the raw credential into any log a host application
    configures at INFO — and ``MUREO_LOG_LEVEL`` bounds mureo's own loggers,
    not httpx's. Same rule as ``mureo.auth._call_refresh_api``, pinned by
    ``tests/test_meta_oauth_secret_in_body.py`` for the other two Graph
    token calls.
    """

    from mureo.meta_ads.accounts import inspect_meta_access_token

    patcher = _patched_client(_debug_route(_FULL_DATA))
    with patcher:
        await inspect_meta_access_token(_TOKEN)

    calls: list[_Call] = patcher.calls  # type: ignore[attr-defined]
    assert len(calls) == 1
    call = calls[0]

    assert call.method == "POST"
    assert call.url.endswith("/debug_token")
    assert call.data["input_token"] == _TOKEN
    assert call.data["access_token"] == _TOKEN

    # The whole point: no query-string transport, and nothing smuggled into
    # the URL itself.
    assert call.params == {}
    assert _TOKEN not in call.url


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
async def test_graph_error_message_is_bounded_and_single_line() -> None:
    """``error.message`` is text Meta wrote, of unbounded length, and it
    reaches a ``logger.info`` record through
    :func:`validate_meta_access_token`. Unbounded it floods the log; with
    newlines in it, a platform-authored string can forge a second log
    record. Same treatment as ``mureo.auth._graph_error_detail``."""

    from mureo.meta_ads.accounts import (
        _GRAPH_ERROR_MESSAGE_MAX_CHARS,
        MetaTokenInspectError,
        inspect_meta_access_token,
    )

    payload = {
        "error": {
            "message": "line one\nline two\r\n" + ("A" * 5000),
            "error_subcode": 463,
        }
    }
    with (
        _patched_client(_debug_route(payload, status=400)),
        pytest.raises(MetaTokenInspectError) as exc,
    ):
        await inspect_meta_access_token(_TOKEN)

    detail = str(exc.value)
    assert "\n" not in detail
    assert "\r" not in detail
    assert "A" * (_GRAPH_ERROR_MESSAGE_MAX_CHARS + 1) not in detail
    assert len(detail) < 400
    # Still useful: the operator keeps the part they quote in a ticket.
    assert "line one line two" in detail
    assert "subcode=463" in detail


@pytest.mark.asyncio
async def test_unbounded_fbtrace_id_is_capped() -> None:
    from mureo.meta_ads.accounts import (
        _GRAPH_ERROR_CODE_MAX_CHARS,
        MetaTokenInspectError,
        inspect_meta_access_token,
    )

    payload = {"error": {"message": "nope", "fbtrace_id": "F" * 900}}
    with (
        _patched_client(_debug_route(payload, status=400)),
        pytest.raises(MetaTokenInspectError) as exc,
    ):
        await inspect_meta_access_token(_TOKEN)

    assert "F" * (_GRAPH_ERROR_CODE_MAX_CHARS + 1) not in str(exc.value)


@pytest.mark.asyncio
async def test_non_envelope_fallback_is_bounded_too() -> None:
    """A body that is not the error envelope falls back to ``response.text``
    — which is still content Graph chose."""

    from mureo.meta_ads.accounts import (
        _GRAPH_ERROR_MESSAGE_MAX_CHARS,
        MetaTokenInspectError,
        inspect_meta_access_token,
    )

    def _route(url: str) -> MagicMock:
        resp = _resp(500, {"not": "an error envelope"})
        resp.text = "B" * 5000
        return resp

    with (
        _patched_client(_route),
        pytest.raises(MetaTokenInspectError) as exc,
    ):
        await inspect_meta_access_token(_TOKEN)

    assert "B" * (_GRAPH_ERROR_MESSAGE_MAX_CHARS + 1) not in str(exc.value)


@pytest.mark.asyncio
async def test_token_type_is_capped_before_it_is_echoed() -> None:
    """``type`` is a short enum in practice, but it is platform-authored text
    crossing into a response body that a future UI will render."""

    from mureo.meta_ads.accounts import (
        _TOKEN_TYPE_MAX_CHARS,
        inspect_meta_access_token,
    )

    payload = {"data": {"type": "S" * 9000, "expires_at": _EXPIRES_AT}}
    with _patched_client(_debug_route(payload)):
        info = await inspect_meta_access_token(_TOKEN)

    assert info["type"] is not None
    assert len(info["type"]) <= _TOKEN_TYPE_MAX_CHARS + len("...")


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
async def test_no_probe_in_the_whole_flow_puts_the_token_in_a_url() -> None:
    """The scope and account probes carry the token in an ``Authorization``
    header or a query string of their own; whatever they do, the inspection
    added by #726 must not be the one that puts it in a logged URL."""

    from mureo.meta_ads.accounts import validate_meta_access_token

    patcher = _patched_client(_full_route(_PERMS, _ACCTS, _FULL_DATA))
    with patcher:
        await validate_meta_access_token(_TOKEN)

    calls: list[_Call] = patcher.calls  # type: ignore[attr-defined]
    debug_calls = [c for c in calls if "/debug_token" in c.url]
    assert debug_calls, "the inspection never ran"
    for call in debug_calls:
        assert call.method == "POST"
        assert _TOKEN not in call.url
        assert _TOKEN not in str(call.params)


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
