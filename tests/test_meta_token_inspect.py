"""Unit tests for the Meta ``debug_token`` inspection probe (#726/#740).

A Business Manager system-user token is minted with a 60-day life unless the
operator asked for none, so the paste route has to learn when the token it is
about to store dies — or that it never does.

``mureo.meta_ads.accounts.inspect_meta_access_token`` asks Graph for
``GET /debug_token?input_token=<token>`` authenticated with the **app access
token** (``<app_id>|<app_secret>``) of the app that issued it, per
https://developers.facebook.com/docs/graph-api/reference/debug_token/. Three
facts, established against a real system-user token, are pinned here (#740):

* the edge is GET-only — a POST is refused with "Unsupported post request"
  (``subcode=33``);
* a system-user token cannot inspect itself — Graph answers "(#100) You must
  provide an app access token, or a user access token that is an owner or
  developer of the app". Without the app pair there is no call to make, and
  the probe says so with :class:`MetaTokenInspectUnavailable` rather than
  reporting a failure;
* a token Graph calls permanent comes back as ``expires_at: 0``, which is
  reported as ``never_expires`` — a distinct fact from "unknown".

The inspected token therefore rides in the query string, so the probe filters
the ``httpx``/``httpcore`` loggers for the duration of the call — pinned
below, because it is a security property and not an implementation detail.

Only the curated fields come back — ``type``, ``expires_at``,
``data_access_expires_at``, ``issued_at``, ``never_expires``. The rest of the
envelope (``scopes``, ``user_id``, ``app_id``) is not echoed anywhere, so the
#605 rule that a Graph body never travels verbatim to a UI or a log still
holds.

httpx is mocked so the tests never touch the network.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.unit

_TOKEN = "sys-tok"
_APP_ID = "app-123"
_APP_SECRET = "secret-456"

# 2026-11-01T00:00:00+00:00 / 2026-12-30T00:00:00+00:00 / 2026-05-01T...
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
    """One recorded request: the verb, the URL, the query, the headers."""

    def __init__(
        self,
        method: str,
        url: str,
        params: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        self.method = method
        self.url = url
        self.params = params
        self.headers = headers


def _patched_client(route: Any) -> Any:
    """An ``httpx.AsyncClient`` double recording both verbs.

    It records POST too, even though nothing may POST any more: a regression
    that puts ``debug_token`` back on the verb Graph refuses has to show up
    as a wrong method, not as a missing call.
    """

    instance = AsyncMock()
    calls: list[_Call] = []

    async def _get(
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ) -> MagicMock:
        calls.append(_Call("GET", url, dict(params or {}), dict(headers or {})))
        return route(url)

    async def _post(
        url: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ) -> MagicMock:
        calls.append(_Call("POST", url, dict(params or {}), dict(headers or {})))
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


async def _inspect() -> Any:
    from mureo.meta_ads.accounts import inspect_meta_access_token

    return await inspect_meta_access_token(
        _TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET
    )


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
async def test_gets_debug_token_authenticated_with_the_app_access_token() -> None:
    """GET, ``input_token`` in the query, the app access token in the header.

    ``debug_token`` is GET-only (a POST is refused with subcode 33) and it
    will not accept the inspected token as its own credential — Graph
    demands an app access token or an app developer's user token (#740).
    """

    patcher = _patched_client(_debug_route(_FULL_DATA))
    with patcher:
        await _inspect()

    calls: list[_Call] = patcher.calls  # type: ignore[attr-defined]
    assert len(calls) == 1
    call = calls[0]

    assert call.method == "GET"
    assert call.url.endswith("/debug_token")
    assert call.params == {"input_token": _TOKEN}
    # The app access token authenticates the call, in the header — never in
    # the query, where httpx would log it as part of the URL.
    assert call.headers["Authorization"] == f"Bearer {_APP_ID}|{_APP_SECRET}"
    assert _APP_SECRET not in str(call.params)
    assert _APP_SECRET not in call.url


@pytest.mark.asyncio
async def test_without_the_app_pair_nothing_is_called() -> None:
    """A system-user token cannot inspect itself, so there is no fallback
    call to make: mureo says "cannot", not "failed" (#740)."""

    from mureo.meta_ads.accounts import (
        MetaTokenInspectError,
        MetaTokenInspectUnavailable,
        inspect_meta_access_token,
    )

    patcher = _patched_client(_debug_route(_FULL_DATA))
    with patcher, pytest.raises(MetaTokenInspectUnavailable) as exc:
        await inspect_meta_access_token(_TOKEN)

    assert patcher.calls == []  # type: ignore[attr-defined]
    assert issubclass(MetaTokenInspectUnavailable, MetaTokenInspectError)
    assert "app ID and app secret" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_id", "app_secret"),
    [(None, _APP_SECRET), (_APP_ID, None), ("", _APP_SECRET), (_APP_ID, "  ")],
)
async def test_half_an_app_pair_is_no_app_pair(
    app_id: str | None, app_secret: str | None
) -> None:
    from mureo.meta_ads.accounts import (
        MetaTokenInspectUnavailable,
        inspect_meta_access_token,
    )

    patcher = _patched_client(_debug_route(_FULL_DATA))
    with patcher, pytest.raises(MetaTokenInspectUnavailable):
        await inspect_meta_access_token(_TOKEN, app_id=app_id, app_secret=app_secret)

    assert patcher.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_returns_only_curated_fields_as_iso_utc() -> None:
    with _patched_client(_debug_route(_FULL_DATA)):
        info = await _inspect()

    assert set(info) == {
        "type",
        "expires_at",
        "data_access_expires_at",
        "issued_at",
        "never_expires",
    }
    assert info["type"] == "SYSTEM_USER"
    assert info["expires_at"] == _iso(_EXPIRES_AT)
    assert info["data_access_expires_at"] == _iso(_DATA_ACCESS_EXPIRES_AT)
    assert info["issued_at"] == _iso(_ISSUED_AT)
    assert info["never_expires"] is False


@pytest.mark.asyncio
async def test_expires_at_zero_means_never_expires() -> None:
    """Graph stamps a permanent token with ``expires_at: 0``. That is not a
    date, and it is not "unknown" either — it is a promise, and mureo has to
    keep it apart from an absent field, because only one of the two may go
    back on the 53-day refresh clock (#740)."""

    payload = {"data": {"type": "SYSTEM_USER", "expires_at": 0}}
    with _patched_client(_debug_route(payload)):
        info = await _inspect()

    assert info["never_expires"] is True
    assert info["expires_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [-1, None, "", "not-a-number", True, False])
async def test_only_a_literal_zero_reads_as_never(raw: Any) -> None:
    """An absent, negative or non-numeric ``expires_at`` is an UNKNOWN
    expiry — never a promise that the token lives forever. ``False`` is an
    ``int`` in Python and must not sneak through as a zero."""

    payload = {"data": {"type": "SYSTEM_USER", "expires_at": raw}}
    with _patched_client(_debug_route(payload)):
        info = await _inspect()

    assert info["expires_at"] is None
    assert info["never_expires"] is False
    assert info["issued_at"] is None


@pytest.mark.asyncio
async def test_non_200_raises_inspect_error_without_the_secrets() -> None:
    from mureo.meta_ads.accounts import (
        MetaTokenInspectError,
        MetaTokenValidationError,
    )

    payload = {
        "error": {
            "message": f"Invalid OAuth access token {_TOKEN} {_APP_SECRET}",
            "error_subcode": 463,
            "fbtrace_id": "H2il2t5bn4e",
        }
    }
    with (
        _patched_client(_debug_route(payload, status=400)),
        pytest.raises(MetaTokenInspectError) as exc,
    ):
        await _inspect()

    assert issubclass(MetaTokenInspectError, MetaTokenValidationError)
    assert _TOKEN not in str(exc.value)
    assert _APP_SECRET not in str(exc.value)
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
        await _inspect()

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
    )

    payload = {"error": {"message": "nope", "fbtrace_id": "F" * 900}}
    with (
        _patched_client(_debug_route(payload, status=400)),
        pytest.raises(MetaTokenInspectError) as exc,
    ):
        await _inspect()

    assert "F" * (_GRAPH_ERROR_CODE_MAX_CHARS + 1) not in str(exc.value)


@pytest.mark.asyncio
async def test_non_envelope_fallback_is_bounded_too() -> None:
    """A body that is not the error envelope falls back to ``response.text``
    — which is still content Graph chose."""

    from mureo.meta_ads.accounts import (
        _GRAPH_ERROR_MESSAGE_MAX_CHARS,
        MetaTokenInspectError,
    )

    def _route(url: str) -> MagicMock:
        resp = _resp(500, {"not": "an error envelope"})
        resp.text = "B" * 5000
        return resp

    with (
        _patched_client(_route),
        pytest.raises(MetaTokenInspectError) as exc,
    ):
        await _inspect()

    assert "B" * (_GRAPH_ERROR_MESSAGE_MAX_CHARS + 1) not in str(exc.value)


@pytest.mark.asyncio
async def test_token_type_is_capped_before_it_is_echoed() -> None:
    """``type`` is a short enum in practice, but it is platform-authored text
    crossing into a response body that a future UI will render."""

    from mureo.meta_ads.accounts import _TOKEN_TYPE_MAX_CHARS

    payload = {"data": {"type": "S" * 9000, "expires_at": _EXPIRES_AT}}
    with _patched_client(_debug_route(payload)):
        info = await _inspect()

    assert info["type"] is not None
    assert len(info["type"]) <= _TOKEN_TYPE_MAX_CHARS + len("...")


@pytest.mark.asyncio
async def test_empty_token_rejected() -> None:
    from mureo.meta_ads.accounts import MetaTokenInspectError, inspect_meta_access_token

    with pytest.raises(MetaTokenInspectError):
        await inspect_meta_access_token("", app_id=_APP_ID, app_secret=_APP_SECRET)


# ---------------------------------------------------------------------------
# The token rides in the query string now, so the log must not
# ---------------------------------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _real_client_on(handler: Any) -> Any:
    """Patch ``httpx.AsyncClient`` to a REAL client over a mock transport.

    The ``AsyncMock`` double used elsewhere in this file never builds a
    request, so it cannot show what httpx and httpcore log. These tests need
    the real stack with a fake socket underneath.
    """

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient

    def _factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client_cls(transport=transport, **kwargs)

    return patch("httpx.AsyncClient", side_effect=_factory)


class _AttachedCapture:
    """A capturing handler on ``name``, at DEBUG, restored on exit."""

    def __init__(self, name: str) -> None:
        self.logger = logging.getLogger(name)
        self.capture = _Capture()
        self._level = self.logger.level

    def __enter__(self) -> _Capture:
        self.logger.addHandler(self.capture)
        self.logger.setLevel(logging.DEBUG)
        return self.capture

    def __exit__(self, *_exc: Any) -> None:
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self._level)


@pytest.mark.asyncio
async def test_the_token_never_reaches_an_httpx_log_record() -> None:
    """``debug_token`` is GET-only, so the inspected token has to travel in
    the URL — and httpx logs ``request.url`` at INFO, which
    ``MUREO_LOG_LEVEL`` does not bound. The probe filters the httpx loggers
    for the duration of the call; this test runs the real client against a
    mock transport, with a capturing handler attached, and reads what came
    out (#605/#740)."""

    from mureo.meta_ads.accounts import inspect_meta_access_token

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert _TOKEN in str(request.url)
        return httpx.Response(200, json=_FULL_DATA)

    transport = httpx.MockTransport(_handler)
    real_client_cls = httpx.AsyncClient

    def _factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client_cls(transport=transport, **kwargs)

    capture = _Capture()
    httpx_logger = logging.getLogger("httpx")
    prior_level = httpx_logger.level
    httpx_logger.addHandler(capture)
    httpx_logger.setLevel(logging.INFO)
    try:
        with patch("httpx.AsyncClient", side_effect=_factory):
            info = await inspect_meta_access_token(
                _TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET
            )
    finally:
        httpx_logger.removeHandler(capture)
        httpx_logger.setLevel(prior_level)

    assert info["type"] == "SYSTEM_USER"
    for message in capture.messages:
        assert _TOKEN not in message, f"the token leaked into a log record: {message}"
        assert _APP_SECRET not in message


@pytest.mark.asyncio
async def test_the_httpx_loggers_are_left_as_they_were_found() -> None:
    """The filter is scoped to the one call. A probe that permanently
    silenced httpx would hide every other request a host application logs —
    including on the failure path, hence the error response here."""

    from mureo.meta_ads.accounts import (
        MetaTokenInspectError,
        inspect_meta_access_token,
    )

    httpx_filters = list(logging.getLogger("httpx").filters)
    httpcore_filters = list(logging.getLogger("httpcore").filters)

    with (
        _patched_client(_debug_route({"error": {"message": "nope"}}, status=400)),
        pytest.raises(MetaTokenInspectError),
    ):
        await inspect_meta_access_token(_TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET)

    assert list(logging.getLogger("httpx").filters) == httpx_filters
    assert list(logging.getLogger("httpcore").filters) == httpcore_filters


#: The loggers httpcore actually emits through. ``httpcore`` itself never
#: logs anything — every trace record comes from one of these children, and
#: a ``logging.Filter`` on the parent is not consulted for them.
_HTTPCORE_EMITTERS = (
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("emitter", _HTTPCORE_EMITTERS)
async def test_the_token_never_reaches_an_httpcore_log_record(emitter: str) -> None:
    """A filter on the ``httpcore`` logger is inert.

    ``Logger.addFilter`` applies only to records logged through that exact
    logger object — filters are NOT inherited by child loggers the way
    handlers and levels are. httpcore logs its request trace through
    ``httpcore.connection`` / ``httpcore.http11`` / …, so the parent-only
    filter never saw a single one of those records, and a host application
    running httpcore at DEBUG would have got the token in its log.
    """

    from mureo.meta_ads.accounts import inspect_meta_access_token

    leak = "send_request_headers.started request=<Request [b'GET']> input_token=%s"
    emitter_logger = logging.getLogger(emitter)

    def _handler(request: httpx.Request) -> httpx.Response:
        # Emitted WHILE the call is in flight, which is the only moment the
        # filter is installed — exactly like httpcore's own trace records.
        emitter_logger.debug(leak, _TOKEN)
        return httpx.Response(200, json=_FULL_DATA)

    with _AttachedCapture(emitter) as capture, _real_client_on(_handler):
        info = await inspect_meta_access_token(
            _TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET
        )

        assert info["type"] == "SYSTEM_USER"
        for message in capture.messages:
            assert _TOKEN not in message, f"the token leaked: {message}"

        # And the silence is scoped to the call: the same record gets
        # through once the inspection has returned, so a host application's
        # own httpcore logging is not collateral damage.
        emitter_logger.debug(leak, _TOKEN)
        assert any(_TOKEN in message for message in capture.messages)


@pytest.mark.asyncio
async def test_every_filtered_logger_is_left_as_it_was_found() -> None:
    """Every name the probe touches is restored, not just the two parents."""

    from mureo.meta_ads.accounts import (
        _HTTP_LOGGER_NAMES,
        MetaTokenInspectError,
        inspect_meta_access_token,
    )

    assert "httpx" in _HTTP_LOGGER_NAMES
    assert "httpcore" in _HTTP_LOGGER_NAMES
    for emitter in _HTTPCORE_EMITTERS:
        assert emitter in _HTTP_LOGGER_NAMES, f"{emitter} is never filtered"

    before = {
        name: list(logging.getLogger(name).filters) for name in _HTTP_LOGGER_NAMES
    }

    with (
        _patched_client(_debug_route({"error": {"message": "nope"}}, status=400)),
        pytest.raises(MetaTokenInspectError),
    ):
        await inspect_meta_access_token(_TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET)

    for name, filters in before.items():
        assert list(logging.getLogger(name).filters) == filters, name


# ---------------------------------------------------------------------------
# A transport error quotes the request it failed on
# ---------------------------------------------------------------------------


def _exploding_transport_handler(request: httpx.Request) -> httpx.Response:
    """Fail the way a transport failure actually reads.

    httpx's transport exceptions carry the request, and the lower-level
    errors they wrap routinely quote the URL — which now holds the inspected
    token — and, in a proxy/TLS trace, the request headers, which hold the
    app access token.
    """

    raise httpx.ConnectError(
        f"boom url={request.url} auth={request.headers['Authorization']}",
        request=request,
    )


@pytest.mark.asyncio
async def test_a_transport_error_leaks_neither_secret() -> None:
    from mureo.meta_ads.accounts import (
        MetaTokenInspectError,
        inspect_meta_access_token,
    )

    with (
        _real_client_on(_exploding_transport_handler),
        pytest.raises(MetaTokenInspectError) as exc,
    ):
        await inspect_meta_access_token(_TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET)

    detail = str(exc.value)
    assert _TOKEN not in detail
    assert _APP_SECRET not in detail
    assert "REDACTED" in detail


@pytest.mark.asyncio
async def test_a_transport_error_is_scrubbed_on_the_validate_path_too() -> None:
    """``token_inspect_error`` is echoed to the configure card and written to
    ``configure.log``, so it is the same boundary."""

    from mureo.meta_ads.accounts import validate_meta_access_token

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/me/permissions" in url:
            return httpx.Response(200, json=_PERMS)
        if "/me/adaccounts" in url:
            return httpx.Response(200, json=_ACCTS)
        return _exploding_transport_handler(request)

    with _real_client_on(_handler):
        result = await validate_meta_access_token(
            _TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET
        )

    assert result["token_info"] is None
    error = result["token_inspect_error"]
    assert error
    assert _TOKEN not in error
    assert _APP_SECRET not in error


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
        result = await validate_meta_access_token(
            _TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET
        )

    assert result["token_info"] == {
        "type": "SYSTEM_USER",
        "expires_at": _iso(_EXPIRES_AT),
        "data_access_expires_at": _iso(_DATA_ACCESS_EXPIRES_AT),
        "issued_at": _iso(_ISSUED_AT),
        "never_expires": False,
    }
    assert result["token_inspect_error"] is None
    assert result["token_inspect_skipped"] is False
    # The pre-existing contract is untouched.
    assert result["scopes"] == ["ads_read"]
    assert result["accounts"] == [{"id": "act_1", "name": "One"}]


@pytest.mark.asyncio
async def test_validate_inspects_with_a_get_and_the_app_access_token() -> None:
    """The scope and account probes carry the token in a query string of
    their own; the inspection added by #726 is the one that has to prove it
    uses the app access token and the documented verb (#740)."""

    from mureo.meta_ads.accounts import validate_meta_access_token

    patcher = _patched_client(_full_route(_PERMS, _ACCTS, _FULL_DATA))
    with patcher:
        await validate_meta_access_token(_TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET)

    calls: list[_Call] = patcher.calls  # type: ignore[attr-defined]
    debug_calls = [c for c in calls if "/debug_token" in c.url]
    assert debug_calls, "the inspection never ran"
    for call in debug_calls:
        assert call.method == "GET"
        assert call.headers["Authorization"] == f"Bearer {_APP_ID}|{_APP_SECRET}"
        assert _APP_SECRET not in str(call.params)


@pytest.mark.asyncio
async def test_validate_without_the_app_pair_reports_skipped_not_failed() -> None:
    """ "mureo could not check" and "Meta refused" are different sentences
    for the operator, so they are different fields on the wire (#740)."""

    from mureo.meta_ads.accounts import validate_meta_access_token

    patcher = _patched_client(_full_route(_PERMS, _ACCTS, _FULL_DATA))
    with patcher:
        result = await validate_meta_access_token(_TOKEN)

    calls: list[_Call] = patcher.calls  # type: ignore[attr-defined]
    assert [c for c in calls if "/debug_token" in c.url] == []
    assert result["token_info"] is None
    assert result["token_inspect_error"] is None
    assert result["token_inspect_skipped"] is True
    assert result["scopes"] == ["ads_read"]


@pytest.mark.asyncio
async def test_validate_survives_a_failed_inspection() -> None:
    """A Graph that refuses the inspection costs the operator the expiry,
    not the whole probe — it is reported alongside the scopes, not instead
    of them."""

    from mureo.meta_ads.accounts import validate_meta_access_token

    with _patched_client(_full_route(_PERMS, _ACCTS, None)):
        result = await validate_meta_access_token(
            _TOKEN, app_id=_APP_ID, app_secret=_APP_SECRET
        )

    assert result["token_info"] is None
    assert result["token_inspect_error"]
    assert result["token_inspect_skipped"] is False
    assert _TOKEN not in result["token_inspect_error"]
    assert result["scopes"] == ["ads_read"]
