"""The ChatGPT Ads API key never leaves the client.

With a sentinel key, every outcome — success, each failure class, the paths
where httpx itself raises with the request in hand — is checked for the
sentinel in log records (DEBUG and up), exception text and repr, tool results
and the credentials dataclass repr. The same holds for a mutation (a POST and
the read before it) and for the before-state capture that runs ahead of one.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads._errors import MAY_HAVE_BEEN_APPLIED
from mureo.chatgpt_ads.client import ChatGPTAdsClient
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


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize(("label", "answer"), _answers())
async def test_no_mutation_outcome_carries_the_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    label: str,
    answer: tuple[int, Any],
) -> None:
    api = FakeAPI().add("/campaigns/c_1", *answer)
    api.add("/campaigns/c_1/pause", *answer)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: api.client())
    caplog.set_level(logging.DEBUG)
    provider = ChatGPTAdsProvider()
    arguments = {"campaign_id": "c_1"}
    captured = await provider.capture_reversal("chatgpt_ads_campaigns_pause", arguments)
    result = await provider.handle_mcp_tool("chatgpt_ads_campaigns_pause", arguments)
    assert SENTINEL_KEY not in repr(captured)
    assert SENTINEL_KEY not in result[0].text
    assert SENTINEL_KEY not in caplog.text


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize(
    "exc_type", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError]
)
async def test_httpx_errors_on_a_mutation_and_its_capture_are_not_quoted(
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
    provider = ChatGPTAdsProvider()
    arguments = {"campaign_id": "c_1", "budget": {"daily_spend_limit_micros": 10**6}}
    name = "chatgpt_ads_campaigns_update_budget"
    assert await provider.capture_reversal(name, arguments) is None
    result = await provider.handle_mcp_tool(name, arguments)
    assert SENTINEL_KEY not in result[0].text
    assert SENTINEL_KEY not in caplog.text


_ECHO = {"error": {"message": f"upstream saw Authorization: Bearer {SENTINEL_KEY}"}}


def _assert_chain_is_clean(error: BaseException) -> None:
    for item in (error, error.__cause__, error.__context__):
        if item is not None:
            assert SENTINEL_KEY not in str(item)
            assert SENTINEL_KEY not in repr(item)
            assert SENTINEL_KEY not in repr(getattr(item, "__dict__", {}))


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize("status", [500, 502, 503])
async def test_a_post_5xx_echoing_the_key_never_reaches_the_result(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    api = FakeAPI().add("/campaigns/c_1/pause", status, _ECHO)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: api.client())
    caplog.set_level(logging.DEBUG)
    result = await ChatGPTAdsProvider().handle_mcp_tool(
        "chatgpt_ads_campaigns_pause", {"campaign_id": "c_1"}
    )
    assert result[0].text.endswith(MAY_HAVE_BEEN_APPLIED)
    assert SENTINEL_KEY not in result[0].text
    assert SENTINEL_KEY not in caplog.text


@pytest.mark.parametrize(
    "answer",
    [(500, _ECHO), (422, _ECHO), (401, _ECHO), (200, f"<html>{SENTINEL_KEY}</html>")],
    ids=["500", "422", "401", "not-json"],
)
async def test_a_failed_post_chain_does_not_carry_the_key(
    answer: tuple[int, Any],
) -> None:
    api = FakeAPI().add("/campaigns/c_1/pause", *answer)
    with pytest.raises(Exception) as info:
        await api.client().post("/campaigns/c_1/pause")
    _assert_chain_is_clean(info.value)


async def test_a_post_transport_error_chain_does_not_carry_the_key() -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(_leaky(request), request=request)

    client = ChatGPTAdsClient(SENTINEL_KEY, transport=httpx.MockTransport(_raise))
    with pytest.raises(Exception) as info:
        await client.post("/campaigns/c_1/pause")
    _assert_chain_is_clean(info.value)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


async def test_a_mutation_past_the_deadline_does_not_carry_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _hang(_client: Any, _arguments: dict[str, Any]) -> Any:
        await asyncio.sleep(10)

    monkeypatch.setitem(handlers.HANDLERS, "chatgpt_ads_campaigns_pause", _hang)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: FakeAPI().client())
    caplog.set_level(logging.DEBUG)
    with pytest.raises(Exception) as info:
        await handlers.run_tool(
            "chatgpt_ads_campaigns_pause",
            {"campaign_id": "c_1"},
            SENTINEL_KEY,
            deadline=0.01,
        )
    assert str(info.value).endswith(MAY_HAVE_BEEN_APPLIED)
    _assert_chain_is_clean(info.value)
    assert SENTINEL_KEY not in caplog.text


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize("status", [400, 401, 500])
async def test_a_capture_read_echoing_the_key_logs_only_the_type(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    api = FakeAPI().add("/campaigns/c_1", status, _ECHO)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: api.client())
    caplog.set_level(logging.DEBUG)
    captured = await ChatGPTAdsProvider().capture_reversal(
        "chatgpt_ads_campaigns_pause", {"campaign_id": "c_1"}
    )
    assert captured is None
    assert any("capture failed" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        assert SENTINEL_KEY not in record.getMessage()
        assert SENTINEL_KEY not in repr(record.args)
        assert record.exc_info is None
    assert SENTINEL_KEY not in caplog.text
