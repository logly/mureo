"""The ChatGPT Ads HTTP client: auth header, retries, pagination, errors.

Every request goes through ``httpx.MockTransport`` and is checked against the
contract fixture cut from the OpenAPI document, so a path or query name the
API does not document fails here rather than against a live account.
"""

from __future__ import annotations

from datetime import timezone

import httpx
import pytest

from mureo.chatgpt_ads import client as client_module
from mureo.chatgpt_ads._api import OPENAPI_VERSION
from mureo.chatgpt_ads._errors import NO_ERROR_DETAIL, ChatGPTAdsAPIError
from mureo.chatgpt_ads.client import ChatGPTAdsClient
from mureo.core.auth_failure import AUTH_CAUSE_TOKEN_INVALID, PlatformAuthError
from tests._chatgpt_ads_fakes import (
    SENTINEL_KEY,
    FakeAPI,
    openapi_fixture_version,
    page,
    rows,
)

pytestmark = pytest.mark.unit


class TestGet:
    async def test_sends_the_key_as_a_bearer_header(self) -> None:
        api = FakeAPI().add("/ad_account", body={"id": "adacct_1"})
        client = api.client()
        assert await client.get("/ad_account") == {"id": "adacct_1"}
        await client.aclose()
        sent = api.requests[0]
        assert sent.headers["Authorization"] == f"Bearer {SENTINEL_KEY}"
        assert str(sent.url).startswith("https://api.ads.openai.com/v1/ad_account")

    async def test_429_then_success_retries_with_backoff(self) -> None:
        api = FakeAPI().add("/ad_account", 429, {"error": {"message": "slow"}})
        api.add("/ad_account", body={"id": "adacct_1"})
        sleeps: list[float] = []
        client = api.client(sleeps)
        assert await client.get("/ad_account") == {"id": "adacct_1"}
        assert len(api.requests) == 2
        assert sleeps == [1.0]

    async def test_numeric_retry_after_is_honoured(self) -> None:
        api = FakeAPI()
        api.add("/ad_account", 429, {}, {"Retry-After": "4"})
        api.add("/ad_account", 503, {}, {"Retry-After": "30"})
        api.add("/ad_account", body={"id": "x"})
        sleeps: list[float] = []
        await api.client(sleeps).get("/ad_account")
        assert sleeps == [4.0, 30.0]

    @pytest.mark.parametrize("value", ["31", "9999", "inf"])
    async def test_retry_after_above_the_cap_is_reported_at_once(
        self, value: str
    ) -> None:
        api = FakeAPI().add("/ad_account", 429, {}, {"Retry-After": value})
        api.add("/ad_account", body={"id": "x"})
        sleeps: list[float] = []
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client(sleeps).get("/ad_account")
        assert info.value.status == 429
        assert sleeps == []
        assert len(api.requests) == 1

    @pytest.mark.parametrize("value", ["-1", "nan", "soon", ""])
    async def test_unusable_retry_after_falls_back_to_backoff(self, value: str) -> None:
        api = FakeAPI().add("/ad_account", 429, {}, {"Retry-After": value})
        api.add("/ad_account", body={})
        sleeps: list[float] = []
        await api.client(sleeps).get("/ad_account")
        assert sleeps == [1.0]

    async def test_non_numeric_retry_after_falls_back_to_backoff(self) -> None:
        api = FakeAPI().add("/ad_account", 429, {}, {"Retry-After": "soon"})
        api.add("/ad_account", body={})
        sleeps: list[float] = []
        await api.client(sleeps).get("/ad_account")
        assert sleeps == [1.0]

    async def test_429_exhausted_raises_an_api_error(self) -> None:
        api = FakeAPI().add("/ad_account", 429, {"error": {"message": "Too many"}})
        sleeps: list[float] = []
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client(sleeps).get("/ad_account")
        assert info.value.status == 429
        assert "Too many" in str(info.value)
        assert len(api.requests) == 3
        assert sleeps == [1.0, 2.0]

    async def test_500_is_retried_then_reported(self) -> None:
        api = FakeAPI().add("/ad_account", 500, "upstream exploded")
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client().get("/ad_account")
        assert info.value.status == 500
        assert str(info.value) == f"HTTP 500: {NO_ERROR_DETAIL}"
        assert len(api.requests) == 3

    async def test_400_is_not_retried(self) -> None:
        api = FakeAPI().add("/ad_account", 400, {"error": {"message": "bad"}})
        with pytest.raises(ChatGPTAdsAPIError):
            await api.client().get("/ad_account")
        assert len(api.requests) == 1

    async def test_401_raises_platform_auth_error(self) -> None:
        api = FakeAPI().add("/ad_account", 401, {"error": {"message": "Bad key"}})
        with pytest.raises(PlatformAuthError) as info:
            await api.client().get("/ad_account")
        assert info.value.cause == AUTH_CAUSE_TOKEN_INVALID

    async def test_malformed_success_body_is_an_api_error(self) -> None:
        api = FakeAPI().add("/ad_account", 200, "<html>not json</html>")
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client().get("/ad_account")
        assert info.value.__cause__ is None
        assert info.value.__context__ is None

    async def test_transport_error_names_only_the_error_class(self) -> None:
        api = FakeAPI()
        api.raise_on["/v1/ad_account"] = httpx.ConnectError(
            f"boom Authorization: Bearer {SENTINEL_KEY}"
        )
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client().get("/ad_account")
        assert "ConnectError" in str(info.value)
        assert SENTINEL_KEY not in str(info.value)
        assert info.value.__cause__ is None
        assert info.value.__context__ is None

    async def test_a_transport_error_is_not_retried(self) -> None:
        api = FakeAPI()
        api.raise_on["/v1/ad_account"] = httpx.ReadTimeout("slow")
        sleeps: list[float] = []
        with pytest.raises(ChatGPTAdsAPIError):
            await api.client(sleeps).get("/ad_account")
        assert len(api.requests) == 1
        assert sleeps == []

    async def test_an_invalid_url_is_a_transport_error(self) -> None:
        api = FakeAPI()
        api.raise_on["/v1/ad_account"] = httpx.InvalidURL("bad url")
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client().get("/ad_account")
        assert "InvalidURL" in str(info.value)
        assert info.value.__context__ is None

    async def test_a_success_body_nested_past_the_recursion_limit(self) -> None:
        api = FakeAPI().add("/ad_account", 200, "[" * 100_000)
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client().get("/ad_account")
        assert info.value.__context__ is None
        assert info.value.__cause__ is None

    async def test_the_key_echoed_in_an_error_body_is_replaced(self) -> None:
        body = {"error": {"message": f"Incorrect API key provided: {SENTINEL_KEY}"}}
        api = FakeAPI().add("/ad_account", 400, body)
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client().get("/ad_account")
        assert SENTINEL_KEY not in str(info.value)
        assert "Incorrect API key provided: ***" in str(info.value)

    async def test_client_works_as_an_async_context_manager(self) -> None:
        api = FakeAPI().add("/ad_account", body={"id": "a"})
        async with api.client() as client:
            assert await client.get("/ad_account") == {"id": "a"}


class TestListAll:
    async def test_follows_last_id_until_the_limit(self) -> None:
        api = FakeAPI()
        api.add("/campaigns", body=page(rows("cmpn", 0, 2), has_more=True))
        api.add("/campaigns", body=page(rows("cmpn", 2, 2), has_more=True))
        api.add("/campaigns", body=page(rows("cmpn", 4, 2), has_more=True))
        result = await api.client().list_all("/campaigns", [], limit=3, page_max=500)
        assert [r["id"] for r in result] == ["cmpn_0", "cmpn_1", "cmpn_2"]
        assert len(api.requests) == 2
        assert ("limit", "3") in api.params(0)
        assert ("after", "cmpn_1") in api.params(1)
        assert ("limit", "1") in api.params(1)

    async def test_has_more_false_stops(self) -> None:
        api = FakeAPI().add("/campaigns", body=page(rows("cmpn", 0, 2), has_more=False))
        result = await api.client().list_all("/campaigns", [], limit=50, page_max=500)
        assert len(result) == 2
        assert len(api.requests) == 1

    async def test_page_size_is_capped_by_the_api_maximum(self) -> None:
        api = FakeAPI().add("/audit_logs", body=page([], has_more=False))
        await api.client().list_all("/audit_logs", [], limit=1000, page_max=100)
        assert ("limit", "100") in api.params(0)

    async def test_an_empty_page_claiming_more_does_not_loop(self) -> None:
        api = FakeAPI().add("/ads", body=page([], has_more=True))
        assert await api.client().list_all("/ads", [], limit=10, page_max=500) == []
        assert len(api.requests) == 1

    async def test_a_body_without_a_data_list_is_an_api_error(self) -> None:
        api = FakeAPI().add("/ads", body={"object": "list"})
        with pytest.raises(ChatGPTAdsAPIError):
            await api.client().list_all("/ads", [], limit=10, page_max=500)


def _more(rows_: list[dict[str, str]], last_id: object) -> dict[str, object]:
    """A page claiming more rows, with ``last_id`` forced to ``last_id``."""
    return {**page(rows_, has_more=True), "last_id": last_id}


class TestListAllBounds:
    """A list that cannot be walked to its end is an error, never a short
    list reported as complete."""

    @pytest.mark.parametrize("last_id", ["", None, 7])
    async def test_more_rows_without_a_usable_cursor(self, last_id: object) -> None:
        api = FakeAPI().add("/campaigns", body=_more(rows("c", 0, 2), last_id))
        with pytest.raises(ChatGPTAdsAPIError, match="cursor"):
            await api.client().list_all("/campaigns", [], limit=10, page_max=500)
        assert len(api.requests) == 1

    async def test_a_cursor_that_does_not_advance(self) -> None:
        api = FakeAPI()
        api.add("/campaigns", body=_more(rows("c", 0, 2), "c_1"))
        api.add("/campaigns", body=_more(rows("c", 2, 2), "c_1"))
        with pytest.raises(ChatGPTAdsAPIError, match="cursor"):
            await api.client().list_all("/campaigns", [], limit=10, page_max=500)
        assert len(api.requests) == 2

    async def test_the_page_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client_module, "MAX_PAGES_PER_CALL", 3)
        api = FakeAPI()
        for i in range(5):
            api.add("/campaigns", body=page(rows("c", i, 1), has_more=True))
        with pytest.raises(ChatGPTAdsAPIError, match="3 pages"):
            await api.client().list_all("/campaigns", [], limit=10, page_max=500)
        assert len(api.requests) == 3

    @pytest.mark.parametrize(("status", "retries"), [(429, 3), (500, 3), (400, 1)])
    async def test_an_error_on_the_second_page(self, status: int, retries: int) -> None:
        api = FakeAPI()
        api.add("/campaigns", body=page(rows("c", 0, 2), has_more=True))
        api.add("/campaigns", status, {"error": {"message": "second page"}})
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await api.client().list_all("/campaigns", [], limit=10, page_max=500)
        assert info.value.status == status
        assert len(api.requests) == 1 + retries

    async def test_a_transport_error_on_the_second_page(self) -> None:
        calls: list[httpx.Request] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 2:
                raise httpx.ConnectError("gone", request=request)
            return httpx.Response(200, json=page(rows("c", 0, 2), has_more=True))

        client = ChatGPTAdsClient(SENTINEL_KEY, transport=httpx.MockTransport(_handler))
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await client.list_all("/campaigns", [], limit=10, page_max=500)
        assert info.value.status == 0
        assert info.value.__context__ is None
        assert len(calls) == 2


class TestAccountTimezone:
    async def test_reads_and_caches_the_account_zone(self) -> None:
        api = FakeAPI().add("/ad_account", body={"timezone": "Asia/Tokyo"})
        client = api.client()
        first = await client.account_timezone()
        second = await client.account_timezone()
        assert str(first) == "Asia/Tokyo"
        assert second is first
        assert len(api.requests) == 1

    @pytest.mark.parametrize("value", [None, "", "Not/AZone", 42, "../etc"])
    async def test_an_absent_or_invalid_zone_falls_back_to_utc(
        self, value: object
    ) -> None:
        api = FakeAPI().add("/ad_account", body={"timezone": value})
        assert await api.client().account_timezone() == timezone.utc


def test_the_contract_fixture_is_cut_from_the_recorded_openapi_version() -> None:
    """The client's recorded document version and the fixture move together.

    The fixture is what the request-shape tests compare against; refreshing
    one without the other would leave the constant naming a document the
    tests no longer check.
    """
    assert openapi_fixture_version() == OPENAPI_VERSION
