"""The ChatGPT Ads create and archive tools (#995), end to end through the provider.

Each call goes provider → handler → client → ``httpx.MockTransport``; the
contract fixture checks every request's method, path, headers and body
fields. Pinned here: what each tool sends (always ``status: paused``), the
argument checks that run before any request, the ``Idempotency-Key`` a create
carries and reuses across retries, the failure sentence that names the key,
and that archive is a one-way change with no reversal.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads._errors import (
    MAY_HAVE_BEEN_APPLIED,
    REPEAT_WITH_IDEMPOTENCY_KEY,
    ChatGPTAdsAPIError,
)
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools_create import (
    CREATE_TOOLS,
)
from mureo.mcp.plugin_semantics import derive_semantics
from tests._chatgpt_ads_fakes import (
    FakeAPI,
    by_name,
    call_tool,
    fail_tool,
    install_fake_api,
    schema_errors,
    sent_body,
)

pytestmark = pytest.mark.unit

_BY_NAME = by_name(CREATE_TOOLS)

_CREATES = (
    "chatgpt_ads_campaigns_create",
    "chatgpt_ads_ad_groups_create",
    "chatgpt_ads_ads_create",
)
#: Archive tool → (path it posts to, its id argument, the id).
_ARCHIVES = {
    "chatgpt_ads_campaigns_archive": ("/campaigns/c_1/archive", "campaign_id", "c_1"),
    "chatgpt_ads_ad_groups_archive": ("/ad_groups/g_1/archive", "ad_group_id", "g_1"),
    "chatgpt_ads_ads_archive": ("/ads/a_1/archive", "ad_id", "a_1"),
}

_CAMPAIGN = {
    "name": "Spring sale",
    "budget": {"daily_spend_limit_micros": 50_000_000},
    "bidding_type": "clicks",
}
_AD_GROUP = {
    "campaign_id": "c_1",
    "name": "Running shoes",
    "bidding_config": {"billing_event_type": "click", "strategy": "maximize_clicks"},
}
_CREATIVE = {
    "type": "chat_card",
    "title": "Trail shoes",
    "body": "Light shoes for long runs.",
    "target_url": "https://example.com/shoes",
}
_AD = {"ad_group_id": "g_1", "name": "Card one", "creative": _CREATIVE}
_TARGETING = {
    "locations": {
        "countries": ["US"],
        "include": [{"id": "1014044", "name": "California", "type": "region"}],
    },
    "excluded_locations": {"countries": ["CA"]},
    "custom_audiences": {"ids": ["aud_1"]},
    "excluded_custom_audiences": {"ids": ["aud_2"]},
    "platforms": {"included": ["ios_app", "web"]},
}

#: Create tool → (its POST path, valid arguments).
_CREATE_CALLS = {
    "chatgpt_ads_campaigns_create": ("/campaigns", _CAMPAIGN),
    "chatgpt_ads_ad_groups_create": ("/ad_groups", _AD_GROUP),
    "chatgpt_ads_ads_create": ("/ads", _AD),
}


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    return install_fake_api(monkeypatch)


def _key_header(request: httpx.Request) -> str | None:
    return request.headers.get("Idempotency-Key")


class TestDefinitions:
    def test_the_six_tools(self) -> None:
        assert tuple(_BY_NAME) == (*_CREATES, *_ARCHIVES)

    @pytest.mark.parametrize("tool", CREATE_TOOLS, ids=lambda t: t.name)
    def test_closed_mutating_and_throttled(self, tool) -> None:  # type: ignore[no-untyped-def]
        semantics = derive_semantics(tool)
        assert tool.inputSchema["additionalProperties"] is False
        assert semantics.mutating is True
        assert semantics.throttle is not None
        assert (semantics.throttle.rate, semantics.throttle.burst) == (8.0, 5)

    @pytest.mark.parametrize("name", _CREATES)
    def test_no_status_argument_and_an_optional_key(self, name: str) -> None:
        schema = _BY_NAME[name].inputSchema
        assert "status" not in schema["properties"]
        key = schema["properties"]["idempotency_key"]
        assert (key["minLength"], key["maxLength"]) == (1, 255)
        assert key["pattern"] == "^[A-Za-z0-9_-]{1,255}$"
        assert "idempotency_key" not in schema["required"]

    @pytest.mark.parametrize(
        ("name", "phrases"),
        [
            (
                "chatgpt_ads_campaigns_create",
                (
                    "paused",
                    "chatgpt_ads_campaigns_enable",
                    "cannot be changed later",
                    "chatgpt_ads_locations_search",
                    "idempotency_key",
                    "exactly one",
                ),
            ),
            (
                "chatgpt_ads_ad_groups_create",
                (
                    "paused",
                    "chatgpt_ads_ad_groups_enable",
                    "multipliers (up to 10x)",
                    "not bounded by them",
                    "CPM = amount x 1000",
                ),
            ),
            (
                "chatgpt_ads_ads_create",
                ("paused", "chatgpt_ads_ads_enable", "review", "creative.file_id"),
            ),
            (
                "chatgpt_ads_campaigns_archive",
                (
                    "cannot be undone",
                    "pause",
                    "ad groups and ads are not archived with it",
                ),
            ),
            (
                "chatgpt_ads_ad_groups_archive",
                ("cannot be undone", "pause", "ads are archived with it is not"),
            ),
            ("chatgpt_ads_ads_archive", ("cannot be undone", "pause")),
        ],
    )
    def test_descriptions_state_what_the_operator_must_know(
        self, name: str, phrases: tuple[str, ...]
    ) -> None:
        description = _BY_NAME[name].description or ""
        for phrase in phrases:
            assert phrase in description, phrase

    @pytest.mark.parametrize("name", list(_ARCHIVES))
    def test_archive_is_destructive(self, name: str) -> None:
        annotations = _BY_NAME[name].annotations
        assert annotations is not None
        assert (annotations.readOnlyHint, annotations.destructiveHint) == (False, True)

    def test_nested_objects_are_closed(self) -> None:
        campaign = _BY_NAME["chatgpt_ads_campaigns_create"].inputSchema["properties"]
        targeting = campaign["targeting"]
        assert targeting["additionalProperties"] is False
        for key in ("locations", "excluded_locations"):
            geo = targeting["properties"][key]
            assert geo["additionalProperties"] is False
            assert geo["properties"]["include"]["maxItems"] == 2500
            assert (
                geo["properties"]["include"]["items"]["additionalProperties"] is False
            )
        for key in ("custom_audiences", "excluded_custom_audiences", "platforms"):
            assert targeting["properties"][key]["additionalProperties"] is False
        assert campaign["budget"]["maxProperties"] == 1
        creative = _BY_NAME["chatgpt_ads_ads_create"].inputSchema["properties"][
            "creative"
        ]
        assert creative["additionalProperties"] is False
        assert creative["properties"]["type"]["enum"] == ["chat_card"]
        assert creative["properties"]["image_crop"]["additionalProperties"] is False


class TestRequests:
    async def test_campaign_create_sends_paused(self, api: FakeAPI) -> None:
        api.add("/campaigns", body={"id": "cmpn_1", "status": "paused"})
        args = {
            **_CAMPAIGN,
            "targeting": _TARGETING,
            "start_time": 1_800_000_000,
            "end_time": 1_900_000_000,
            "conversion_event_setting_ids": ["ces_1"],
            "projected_total_daily_budget": 400.0,
        }
        assert await call_tool("chatgpt_ads_campaigns_create", args) == {
            "id": "cmpn_1",
            "status": "paused",
        }
        sent = api.requests[0]
        assert (sent.method, sent.url.path) == ("POST", "/v1/campaigns")
        assert sent_body(sent) == {
            "name": "Spring sale",
            "status": "paused",
            "budget": {"daily_spend_limit_micros": 50_000_000},
            "bidding_type": "clicks",
            "targeting": _TARGETING,
            "start_time": 1_800_000_000,
            "end_time": 1_900_000_000,
            "conversion_event_setting_ids": ["ces_1"],
        }

    async def test_ad_group_create_sends_paused(self, api: FakeAPI) -> None:
        api.add("/ad_groups", body={"id": "adgrp_1"})
        await call_tool(
            "chatgpt_ads_ad_groups_create",
            {**_AD_GROUP, "context_hints": ["trail running", "marathon"]},
        )
        assert sent_body(api.requests[0]) == {
            "campaign_id": "c_1",
            "name": "Running shoes",
            "status": "paused",
            "bidding_config": _AD_GROUP["bidding_config"],
            "context_hints": ["trail running", "marathon"],
        }

    async def test_ad_create_sends_paused(self, api: FakeAPI) -> None:
        api.add("/ads", body={"id": "ad_1", "review_status": "in_review"})
        creative = {
            **_CREATIVE,
            "file_id": "file_1",
            "image_crop": {"x": 0, "y": 0.1, "width": 0.8, "height": 1},
        }
        await call_tool("chatgpt_ads_ads_create", {**_AD, "creative": creative})
        assert sent_body(api.requests[0]) == {
            "ad_group_id": "g_1",
            "name": "Card one",
            "status": "paused",
            "creative": creative,
        }

    @pytest.mark.parametrize("name", list(_ARCHIVES))
    async def test_archive_posts_without_a_body(self, api: FakeAPI, name: str) -> None:
        path, key, value = _ARCHIVES[name]
        api.add(path, body={"id": value, "status": "archived"})
        assert await call_tool(name, {key: value}) == {
            "id": value,
            "status": "archived",
        }
        sent = api.requests[0]
        assert sent.method == "POST"
        assert sent.content == b""
        assert _key_header(sent) is None

    @pytest.mark.parametrize("name", _CREATES)
    async def test_status_cannot_be_overridden(self, api: FakeAPI, name: str) -> None:
        path, args = _CREATE_CALLS[name]
        with pytest.raises(ValueError, match="paused"):
            await ChatGPTAdsProvider().handle_mcp_tool(
                name, {**args, "status": "active"}
            )
        assert api.requests == []
        assert schema_errors(_BY_NAME[name], {**args, "status": "active"}) != []


class TestIdempotency:
    def test_the_repeat_sentence_keeps_the_platform_condition(self) -> None:
        """The platform returns the earlier object only "if a matching prior
        create is visible"; no text promises more than that."""
        condition = "when the platform can see the earlier create"
        assert condition in REPEAT_WITH_IDEMPOTENCY_KEY
        for name in _CREATES:
            assert condition in (_BY_NAME[name].description or "")
            key = _BY_NAME[name].inputSchema["properties"]["idempotency_key"]
            assert "when the platform can see it" in key["description"]
            assert "Never reuse a key for a different entity" in key["description"]

    @pytest.mark.parametrize("name", _CREATES)
    async def test_a_429_repeats_the_same_key_and_body(
        self, api: FakeAPI, name: str
    ) -> None:
        path, args = _CREATE_CALLS[name]
        api.add(path, 429, {"error": {"message": "slow down"}})
        api.add(path, body={"id": "x"})
        await call_tool(name, args)
        first, second = api.requests
        assert _key_header(first) == _key_header(second) is not None
        assert sent_body(first) == sent_body(second)

    @pytest.mark.parametrize("name", _CREATES)
    async def test_a_key_is_generated_when_absent(
        self, api: FakeAPI, name: str
    ) -> None:
        path, args = _CREATE_CALLS[name]
        api.add(path, body={"id": "x"})
        await call_tool(name, args)
        await call_tool(name, args)
        first, second = (_key_header(r) for r in api.requests)
        assert first and second and first != second
        assert len(first) == 32 and first.isalnum()

    @pytest.mark.parametrize("name", _CREATES)
    async def test_the_given_key_is_sent(self, api: FakeAPI, name: str) -> None:
        path, args = _CREATE_CALLS[name]
        api.add(path, body={"id": "x"})
        await call_tool(name, {**args, "idempotency_key": "spring-sale_01"})
        assert _key_header(api.requests[0]) == "spring-sale_01"
        assert "idempotency_key" not in sent_body(api.requests[0])

    async def test_a_5xx_is_retried_with_the_same_key_and_body(
        self, api: FakeAPI
    ) -> None:
        api.add("/campaigns", 503, {"error": {"message": "busy"}})
        api.add("/campaigns", 500, "oops")
        api.add("/campaigns", body={"id": "cmpn_1"})
        assert await call_tool("chatgpt_ads_campaigns_create", _CAMPAIGN) == {
            "id": "cmpn_1"
        }
        assert len(api.requests) == 3
        assert len({_key_header(r) for r in api.requests}) == 1
        assert len({r.content for r in api.requests}) == 1

    async def test_a_final_5xx_names_the_key(self, api: FakeAPI) -> None:
        api.add("/ads", 502, {"error": {"message": "bad gateway"}})
        failure = await fail_tool(
            "chatgpt_ads_ads_create", {**_AD, "idempotency_key": "k1"}
        )
        assert len(api.requests) == 3
        assert failure.detail.endswith(REPEAT_WITH_IDEMPOTENCY_KEY.format(key="k1"))
        assert MAY_HAVE_BEEN_APPLIED not in failure.detail

    async def test_a_transport_error_names_the_generated_key(
        self, api: FakeAPI
    ) -> None:
        api.raise_on["/v1/ad_groups"] = httpx.ConnectError("refused")
        failure = await fail_tool("chatgpt_ads_ad_groups_create", _AD_GROUP)
        key = _key_header(api.requests[0])
        assert key is not None
        assert {_key_header(r) for r in api.requests} == {key}
        assert failure.detail.endswith(REPEAT_WITH_IDEMPOTENCY_KEY.format(key=key))

    async def test_a_4xx_is_final_without_the_sentence(self, api: FakeAPI) -> None:
        api.add("/campaigns", 400, {"error": {"message": "bad budget"}})
        failure = await fail_tool("chatgpt_ads_campaigns_create", _CAMPAIGN)
        assert len(api.requests) == 1
        assert "bad budget" in failure.detail
        assert "idempotency_key" not in failure.detail

    async def test_the_deadline_names_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _hang(_client: Any, _arguments: dict[str, Any]) -> Any:
            await asyncio.sleep(10)

        monkeypatch.setitem(handlers.HANDLERS, "chatgpt_ads_campaigns_create", _hang)
        monkeypatch.setattr(handlers, "_open_client", lambda _k: FakeAPI().client())
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await handlers.run_tool(
                "chatgpt_ads_campaigns_create",
                {**_CAMPAIGN, "idempotency_key": "late-1"},
                "k",
                deadline=0.01,
            )
        assert str(info.value).endswith(
            REPEAT_WITH_IDEMPOTENCY_KEY.format(key="late-1")
        )

    async def test_the_deadline_names_the_key_the_handler_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        async def _hang(_client: Any, arguments: dict[str, Any]) -> Any:
            seen.append(arguments["idempotency_key"])
            await asyncio.sleep(10)

        monkeypatch.setitem(handlers.HANDLERS, "chatgpt_ads_ads_create", _hang)
        monkeypatch.setattr(handlers, "_open_client", lambda _k: FakeAPI().client())
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await handlers.run_tool("chatgpt_ads_ads_create", _AD, "k", deadline=0.01)
        assert len(seen) == 1
        assert str(info.value).endswith(REPEAT_WITH_IDEMPOTENCY_KEY.format(key=seen[0]))

    async def test_an_archive_past_the_deadline_may_have_been_applied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _hang(_client: Any, _arguments: dict[str, Any]) -> Any:
            await asyncio.sleep(10)

        monkeypatch.setitem(handlers.HANDLERS, "chatgpt_ads_ads_archive", _hang)
        monkeypatch.setattr(handlers, "_open_client", lambda _k: FakeAPI().client())
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await handlers.run_tool(
                "chatgpt_ads_ads_archive", {"ad_id": "a_1"}, "k", deadline=0.01
            )
        assert str(info.value).endswith(MAY_HAVE_BEEN_APPLIED)

    async def test_a_5xx_archive_is_final(self, api: FakeAPI) -> None:
        api.add("/campaigns/c_1/archive", 500, {"error": {"message": "boom"}})
        failure = await fail_tool(
            "chatgpt_ads_campaigns_archive", {"campaign_id": "c_1"}
        )
        assert len(api.requests) == 1
        assert failure.detail.endswith(MAY_HAVE_BEEN_APPLIED)
