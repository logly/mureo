"""The ChatGPT Ads API key never leaves the client.

With a sentinel key, every outcome — success, each failure class, the paths
where httpx itself raises with the request in hand — is checked for the
sentinel in log records (DEBUG and up), exception text and repr, tool results
and the credentials dataclass repr.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads.credentials import (
    ChatGPTAdsCredentials,
    load_chatgpt_ads_credentials,
)
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI

pytestmark = pytest.mark.unit


def _leaky(request: httpx.Request) -> str:
    """Text an httpx error might carry: the full request, headers included."""
    return f"{request!r} {dict(request.headers)!r}"


def _answers() -> list[tuple[str, Any]]:
    return [
        ("ok", (200, {"id": "a"})),
        ("401", (401, {"error": {"message": "bad"}})),
        ("403", (403, {"error": {"message": "nope"}})),
        ("gate", (403, {"error": {"code": "x_disabled"}})),
        ("404", (404, "Not found")),
        ("429", (429, {})),
        ("500", (500, "boom")),
        ("junk", (200, "{not json")),
    ]


@pytest.fixture()
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATGPT_ADS_API_KEY", SENTINEL_KEY)


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize(("label", "answer"), _answers())
async def test_no_outcome_carries_the_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    label: str,
    answer: tuple[int, Any],
) -> None:
    api = FakeAPI().add("/ad_account", *answer)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: api.client())
    caplog.set_level(logging.DEBUG)
    result = await ChatGPTAdsProvider().handle_mcp_tool("chatgpt_ads_account_get", {})
    assert SENTINEL_KEY not in result[0].text
    assert SENTINEL_KEY not in caplog.text
    # The key did reach the platform: the fake saw it in the header.
    assert api.requests[0].headers["Authorization"] == f"Bearer {SENTINEL_KEY}"


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize(
    "exc_type", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError]
)
async def test_httpx_errors_carrying_the_request_are_not_quoted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exc_type: type[httpx.RequestError],
) -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise exc_type(_leaky(request), request=request)

    def _client(_key: str) -> Any:
        from mureo.chatgpt_ads.client import ChatGPTAdsClient

        return ChatGPTAdsClient(_key, transport=httpx.MockTransport(_raise))

    monkeypatch.setattr(handlers, "_open_client", _client)
    caplog.set_level(logging.DEBUG)
    result = await ChatGPTAdsProvider().handle_mcp_tool("chatgpt_ads_account_get", {})
    assert SENTINEL_KEY not in result[0].text
    assert SENTINEL_KEY not in caplog.text


@pytest.mark.parametrize(("label", "answer"), _answers()[1:])
async def test_client_exceptions_do_not_carry_the_key(
    label: str, answer: tuple[int, Any]
) -> None:
    api = FakeAPI().add("/ad_account", *answer)
    with pytest.raises(Exception) as info:
        await api.client().get("/ad_account")
    error = info.value
    chain = [error, error.__cause__, error.__context__]
    for item in chain:
        if item is not None:
            assert SENTINEL_KEY not in str(item)
            assert SENTINEL_KEY not in repr(item)
            assert SENTINEL_KEY not in repr(getattr(item, "__dict__", {}))


async def test_transport_exception_chain_does_not_carry_the_key() -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(_leaky(request), request=request)

    from mureo.chatgpt_ads.client import ChatGPTAdsClient

    client = ChatGPTAdsClient(SENTINEL_KEY, transport=httpx.MockTransport(_raise))
    with pytest.raises(Exception) as info:
        await client.get("/ad_account")
    assert SENTINEL_KEY not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize("status", [400, 401, 403])
@pytest.mark.parametrize(
    "message",
    [
        f"echo Authorization: Bearer {SENTINEL_KEY}",
        f"Incorrect API key provided: {SENTINEL_KEY}",
        f"{SENTINEL_KEY}{SENTINEL_KEY} twice",
    ],
)
async def test_a_key_echoed_by_the_platform_never_reaches_the_result(
    monkeypatch: pytest.MonkeyPatch, status: int, message: str
) -> None:
    api = FakeAPI().add("/ad_account", status, {"error": {"message": message}})
    monkeypatch.setattr(handlers, "_open_client", lambda _key: api.client())
    result = await ChatGPTAdsProvider().handle_mcp_tool("chatgpt_ads_account_get", {})
    assert SENTINEL_KEY not in result[0].text


def test_credentials_repr_hides_the_key() -> None:
    creds = ChatGPTAdsCredentials(api_key=SENTINEL_KEY)
    assert SENTINEL_KEY not in repr(creds)
    assert SENTINEL_KEY not in str(creds)


def test_client_repr_hides_the_key() -> None:
    client = FakeAPI().client()
    assert SENTINEL_KEY not in repr(client)


@pytest.mark.usefixtures("_key")
def test_loaded_credentials_repr_hides_the_key() -> None:
    creds = load_chatgpt_ads_credentials()
    assert creds is not None
    assert SENTINEL_KEY not in repr(creds)
