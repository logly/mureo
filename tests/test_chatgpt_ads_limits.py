"""Bounds on one ChatGPT Ads tool call: the overall deadline, and the schema
limits that mirror what the handlers enforce."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from mureo.chatgpt_ads import _api, handlers
from mureo.chatgpt_ads._errors import ChatGPTAdsAPIError
from mureo.chatgpt_ads.client import ChatGPTAdsClient
from mureo.chatgpt_ads.tools import DEFAULT_INSIGHTS_LIMIT, TOOLS
from tests._chatgpt_ads_fakes import SENTINEL_KEY

pytestmark = pytest.mark.unit

_BY_NAME = {t.name: t for t in TOOLS}


def _never_answering_client(_key: str) -> ChatGPTAdsClient:
    async def _hang(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    return ChatGPTAdsClient(_key, transport=httpx.MockTransport(_hang))


class TestDeadline:
    def test_the_default_deadline(self) -> None:
        assert _api.TOOL_DEADLINE_SECONDS == 120

    async def test_a_call_past_the_deadline_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(handlers, "_open_client", _never_answering_client)
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await handlers.run_tool(
                "chatgpt_ads_account_get", {}, SENTINEL_KEY, deadline=0.05
            )
        error = info.value
        assert error.status == 0
        assert "did not finish within 0.05 seconds" in str(error)
        assert error.__context__ is None
        assert error.__cause__ is None

    async def test_a_validation_error_is_not_turned_into_a_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(handlers, "_open_client", _never_answering_client)
        with pytest.raises(ValueError):
            await handlers.run_tool(
                "chatgpt_ads_ads_get", {"ad_id": "a/b"}, SENTINEL_KEY, deadline=5
            )


class TestSchemaMatchesHandlers:
    @pytest.mark.parametrize(
        "tool",
        [
            "chatgpt_ads_campaigns_list",
            "chatgpt_ads_ad_groups_list",
            "chatgpt_ads_ads_list",
        ],
    )
    def test_name_filter_bounds(self, tool: str) -> None:
        name = _BY_NAME[tool].inputSchema["properties"]["name"]
        assert (name["minLength"], name["maxLength"]) == (3, 1000)

    def test_metrics_are_unique(self) -> None:
        metrics = _BY_NAME["chatgpt_ads_insights_report"].inputSchema["properties"][
            "metrics"
        ]
        assert metrics["uniqueItems"] is True

    def test_insights_limit_default_and_description(self) -> None:
        assert DEFAULT_INSIGHTS_LIMIT == 1000
        limit = _BY_NAME["chatgpt_ads_insights_report"].inputSchema["properties"][
            "limit"
        ]
        text = limit["description"]
        assert "Default 1000." in text
        assert "dropped without notice" in text
        assert "one row per entity per day" in text


class TestRunToolEdges:
    async def test_run_tool_refuses_an_unknown_name(self) -> None:
        with pytest.raises(ValueError, match="chatgpt_ads_nope"):
            await handlers.run_tool("chatgpt_ads_nope", {}, SENTINEL_KEY)

    async def test_the_real_opener_builds_a_client(self) -> None:
        async with handlers._open_client(SENTINEL_KEY) as client:
            assert isinstance(client, ChatGPTAdsClient)

    async def test_an_empty_key_redacts_nothing(self) -> None:
        def _answer(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": {"message": "plain text"}})

        client = ChatGPTAdsClient("", transport=httpx.MockTransport(_answer))
        with pytest.raises(ChatGPTAdsAPIError, match="plain text"):
            await client.get("/ad_account")
