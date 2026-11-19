"""The ChatGPT Ads API key never leaves the client.

With a sentinel key, every outcome — success, each failure class, the paths
where httpx itself raises with the request in hand — is checked for the
sentinel in log records (DEBUG and up), exception text and repr, tool results
and the credentials dataclass repr. The same holds for a mutation (a POST and
the read before it), for the before-state capture that runs ahead of one, and
for the change feed and the import outcome a failed feed read becomes, and
for the create, archive, upload, preview and location-search tools: a create
sent with an idempotency key, the multipart upload and the preview's
read-only POST each fail through their own request path, and the create's
deadline message names the key.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mureo.change_import import (
    ChangeImportStatus,
    clear_change_feed_registry,
    default_change_feed_registry,
    import_external_changes,
    register_change_feed,
)
from mureo.chatgpt_ads import change_feed, handlers
from mureo.chatgpt_ads._errors import MAY_HAVE_BEEN_APPLIED
from mureo.chatgpt_ads.change_feed import ChatGPTAdsChangeFeed
from mureo.chatgpt_ads.client import ChatGPTAdsClient
from mureo.chatgpt_ads.credentials import (
    ChatGPTAdsCredentials,
    load_chatgpt_ads_credentials,
)
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.core.auth_failure import PlatformAuthError
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI

if TYPE_CHECKING:
    from pathlib import Path

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


_FEED_KEY = "plugin:mureo-chatgpt-ads:chatgpt_ads"
_UNTIL = datetime(2026, 3, 2, tzinfo=timezone.utc)


def _hanging_client(_key: str) -> ChatGPTAdsClient:
    async def _hang(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        raise AssertionError("unreachable")

    return ChatGPTAdsClient(_key, transport=httpx.MockTransport(_hang))


def _raising_client(_key: str) -> ChatGPTAdsClient:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(_leaky(request), request=request)

    return ChatGPTAdsClient(_key, transport=httpx.MockTransport(_raise))


def _feed_failures() -> list[Any]:
    def _answer(status: int, body: Any) -> Any:
        def _client(_key: str) -> ChatGPTAdsClient:
            return FakeAPI().add("/audit_logs", status, body).client()

        return _client

    return [
        pytest.param(_answer(401, _ECHO), id="401-echo"),
        pytest.param(_answer(403, _ECHO), id="403-echo"),
        pytest.param(_answer(500, _ECHO), id="500-echo"),
        pytest.param(_answer(200, f"<html>{SENTINEL_KEY}</html>"), id="not-json"),
        pytest.param(_raising_client, id="transport"),
        pytest.param(_hanging_client, id="deadline"),
    ]


def _feed_state(tmp_path: Path) -> Path:
    path = tmp_path / "STATE.json"
    path.write_text(
        json.dumps(
            {
                "version": "2",
                "platforms": {_FEED_KEY: {"account_id": "", "campaigns": []}},
                "action_log": [],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize("opener", _feed_failures())
async def test_no_change_feed_failure_carries_the_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    opener: Any,
) -> None:
    monkeypatch.setattr(handlers, "_open_client", opener)
    monkeypatch.setattr(change_feed, "TOOL_DEADLINE_SECONDS", 0.05)
    caplog.set_level(logging.DEBUG)
    feed = ChatGPTAdsChangeFeed()
    with pytest.raises(Exception) as info:
        await feed.fetch_change_events(
            "", since=datetime(2026, 3, 1, tzinfo=timezone.utc), until=_UNTIL
        )
    _assert_chain_is_clean(info.value)

    clear_change_feed_registry()
    default_change_feed_registry().clear()
    try:
        register_change_feed(feed, source_distribution="mureo-chatgpt-ads")
        outcomes = await import_external_changes(_feed_state(tmp_path), now=_UNTIL)
    finally:
        clear_change_feed_registry()
    assert outcomes[0].status is ChangeImportStatus.ERROR
    assert SENTINEL_KEY not in repr(outcomes[0])
    assert SENTINEL_KEY not in caplog.text


#: A body that spells the key only in JSON escapes: the raw text never
#: contains it, the decoded message and code do.
_ESCAPED_KEY = "".join(f"\\u{ord(char):04x}" for char in SENTINEL_KEY)
_ESCAPED_ECHO = (
    '{"error": {"message": "upstream saw ' + _ESCAPED_KEY + '", '
    '"code": "' + _ESCAPED_KEY + '"}}'
)


def test_the_escaped_body_really_spells_the_key() -> None:
    assert SENTINEL_KEY not in _ESCAPED_ECHO
    decoded = json.loads(_ESCAPED_ECHO)["error"]
    assert decoded == {"message": f"upstream saw {SENTINEL_KEY}", "code": SENTINEL_KEY}


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize("status", [401, 500])
async def test_a_key_in_json_escapes_never_reaches_a_tool_result(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    api = FakeAPI().add("/ad_account", status, _ESCAPED_ECHO)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: api.client())
    caplog.set_level(logging.DEBUG)
    result = await ChatGPTAdsProvider().handle_mcp_tool("chatgpt_ads_account_get", {})
    assert SENTINEL_KEY not in result[0].text
    assert SENTINEL_KEY not in caplog.text

    with pytest.raises(Exception) as info:
        await api.client().get("/ad_account")
    _assert_chain_is_clean(info.value)


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize("status", [401, 500])
async def test_a_key_in_json_escapes_never_reaches_the_feed_or_the_import(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    status: int,
) -> None:
    def _client(_key: str) -> ChatGPTAdsClient:
        return FakeAPI().add("/audit_logs", status, _ESCAPED_ECHO).client()

    monkeypatch.setattr(handlers, "_open_client", _client)
    caplog.set_level(logging.DEBUG)
    feed = ChatGPTAdsChangeFeed()
    with pytest.raises(Exception) as info:
        await feed.fetch_change_events(
            "", since=datetime(2026, 3, 1, tzinfo=timezone.utc), until=_UNTIL
        )
    _assert_chain_is_clean(info.value)

    clear_change_feed_registry()
    default_change_feed_registry().clear()
    try:
        register_change_feed(feed, source_distribution="mureo-chatgpt-ads")
        outcomes = await import_external_changes(_feed_state(tmp_path), now=_UNTIL)
    finally:
        clear_change_feed_registry()
    assert outcomes[0].status is ChangeImportStatus.ERROR
    assert SENTINEL_KEY not in repr(outcomes[0])
    assert SENTINEL_KEY not in caplog.text


async def test_a_missing_key_fails_the_feed_without_a_request(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("CHATGPT_ADS_API_KEY", raising=False)
    opened: list[str] = []
    monkeypatch.setattr(handlers, "_open_client", opened.append)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(PlatformAuthError) as info:
        await ChatGPTAdsChangeFeed().fetch_change_events(
            "", since=datetime(2026, 3, 1, tzinfo=timezone.utc), until=_UNTIL
        )
    assert opened == []
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


# ---------------------------------------------------------------------------
# Create, archive, upload, preview and location search (#995)
# ---------------------------------------------------------------------------

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x02\x80" * 2


def _new_tool_calls(tmp_path: Path) -> list[tuple[str, str, dict[str, Any]]]:
    """(tool, the path it requests, valid arguments) for every new tool."""
    image = tmp_path / "card.png"
    image.write_bytes(_PNG + b"\x08\x06\x00\x00\x00" + b"\x00" * 4)
    creative = {
        "type": "chat_card",
        "title": "Trail shoes",
        "body": "Light shoes.",
        "target_url": "https://example.com",
    }
    return [
        (
            "chatgpt_ads_campaigns_create",
            "/campaigns",
            {
                "name": "Spring",
                "budget": {"daily_spend_limit_micros": 10**6},
                "bidding_type": "clicks",
            },
        ),
        (
            "chatgpt_ads_ad_groups_create",
            "/ad_groups",
            {
                "campaign_id": "c_1",
                "name": "Shoes",
                "bidding_config": {"billing_event_type": "click"},
            },
        ),
        (
            "chatgpt_ads_ads_create",
            "/ads",
            {"ad_group_id": "g_1", "name": "Card", "creative": creative},
        ),
        (
            "chatgpt_ads_campaigns_archive",
            "/campaigns/c_1/archive",
            {"campaign_id": "c_1"},
        ),
        (
            "chatgpt_ads_ad_groups_archive",
            "/ad_groups/g_1/archive",
            {"ad_group_id": "g_1"},
        ),
        ("chatgpt_ads_ads_archive", "/ads/a_1/archive", {"ad_id": "a_1"}),
        ("chatgpt_ads_images_upload_file", "/upload", {"file_path": str(image)}),
        ("chatgpt_ads_ads_preview", "/ads/a_1/preview", {"ad_id": "a_1"}),
        ("chatgpt_ads_locations_search", "/geo_lookup/search", {"query": "calif"}),
    ]


_NEW_TOOLS = [
    "chatgpt_ads_campaigns_create",
    "chatgpt_ads_ad_groups_create",
    "chatgpt_ads_ads_create",
    "chatgpt_ads_campaigns_archive",
    "chatgpt_ads_ad_groups_archive",
    "chatgpt_ads_ads_archive",
    "chatgpt_ads_images_upload_file",
    "chatgpt_ads_ads_preview",
    "chatgpt_ads_locations_search",
]


def _new_call(tmp_path: Path, name: str) -> tuple[str, dict[str, Any]]:
    path, arguments = next((p, a) for n, p, a in _new_tool_calls(tmp_path) if n == name)
    return path, arguments


async def _run_clean(
    caplog: pytest.LogCaptureFixture, name: str, arguments: dict[str, Any]
) -> None:
    """Run ``name`` through the provider; neither the result nor the log may
    carry the key."""
    caplog.set_level(logging.DEBUG)
    result = await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
    assert SENTINEL_KEY not in result[0].text
    assert SENTINEL_KEY not in caplog.text


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize("name", _NEW_TOOLS)
@pytest.mark.parametrize(
    "answer",
    [answer for _, answer in _answers()]
    + [(500, _ECHO), (422, _ECHO), (500, _ESCAPED_ECHO), (401, _ESCAPED_ECHO)],
    ids=[label for label, _ in _answers()]
    + ["500-echo", "422-echo", "500-escaped", "401-escaped"],
)
async def test_no_new_tool_outcome_carries_the_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    name: str,
    answer: tuple[int, Any],
) -> None:
    path, arguments = _new_call(tmp_path, name)
    api = FakeAPI().add(path, *answer)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: api.client())
    await _run_clean(caplog, name, arguments)
    assert api.requests[0].headers["Authorization"] == f"Bearer {SENTINEL_KEY}"


@pytest.mark.usefixtures("_key")
@pytest.mark.parametrize("name", _NEW_TOOLS)
@pytest.mark.parametrize(
    "exc_type", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError]
)
async def test_httpx_errors_on_a_new_tool_are_not_quoted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    name: str,
    exc_type: type[httpx.RequestError],
) -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise exc_type(_leaky(request), request=request)

    monkeypatch.setattr(
        handlers,
        "_open_client",
        lambda _key: ChatGPTAdsClient(_key, transport=httpx.MockTransport(_raise)),
    )
    _, arguments = _new_call(tmp_path, name)
    await _run_clean(caplog, name, arguments)


@pytest.mark.parametrize(
    ("call", "answer"),
    [
        ("post_key", (500, _ECHO)),
        ("post_key", (500, _ESCAPED_ECHO)),
        ("post_read", (500, _ECHO)),
        ("post_file", (500, _ECHO)),
        ("post_file", (500, _ESCAPED_ECHO)),
    ],
    ids=["create", "create-escaped", "read", "upload", "upload-escaped"],
)
async def test_a_failed_new_post_chain_does_not_carry_the_key(
    call: str, answer: tuple[int, Any]
) -> None:
    api = FakeAPI().add("/ads", *answer).add("/ads/a_1/preview", *answer)
    api.add("/upload", *answer)
    client = api.client()
    requests = {
        "post_key": lambda: client.post("/ads", {"name": "x"}, idempotency_key="k"),
        "post_read": lambda: client.post_read("/ads/a_1/preview"),
        "post_file": lambda: client.post_file(
            "/upload", filename="card.png", content=_PNG, content_type="image/png"
        ),
    }
    with pytest.raises(Exception) as info:
        await requests[call]()
    _assert_chain_is_clean(info.value)


async def test_a_create_past_the_deadline_does_not_carry_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _hang(_client: Any, _arguments: dict[str, Any]) -> Any:
        await asyncio.sleep(10)

    monkeypatch.setitem(handlers.HANDLERS, "chatgpt_ads_ads_create", _hang)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: FakeAPI().client())
    caplog.set_level(logging.DEBUG)
    with pytest.raises(Exception) as info:
        await handlers.run_tool(
            "chatgpt_ads_ads_create",
            {"idempotency_key": "k"},
            SENTINEL_KEY,
            deadline=0.01,
        )
    assert 'idempotency_key="k"' in str(info.value)
    _assert_chain_is_clean(info.value)
    assert SENTINEL_KEY not in caplog.text
