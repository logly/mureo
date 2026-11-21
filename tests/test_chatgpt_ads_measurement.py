"""The ChatGPT Ads pixel and conversion event setting tools (#995).

Each call goes provider → handler → client → ``httpx.MockTransport``; the
contract fixture checks every request. Pinned here: what each tool sends,
the ``custom_event_name`` rule, ``source_ids`` as a one-item list, the fixed
attribution window, and that a 404 on the pixel paths is reported as
``feature_not_enabled`` (the reference's answer there when conversions are
not enabled for the account) while a 404 on the event-setting paths stays an
ordinary error. The conversion report has its own module.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.chatgpt_ads._errors import MAY_HAVE_BEEN_APPLIED
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools_measurement import (
    CUSTOM_EVENT_NAME_MAX_CHARS,
    EVENT_ATTRIBUTION_WINDOW_DAYS,
    EVENT_SETTING_NAME_MAX_CHARS,
    EVENT_TYPES,
    MEASUREMENT_TOOLS,
)
from tests._chatgpt_ads_fakes import (
    FakeAPI,
    by_name,
    call_tool,
    fail_tool,
    install_fake_api,
    page,
    rows,
    schema_errors,
    sent_body,
)

pytestmark = pytest.mark.unit

_BY_NAME = by_name(MEASUREMENT_TOOLS)
_EVENTS_CREATE = "chatgpt_ads_conversion_events_create"
_EVENT = {"name": "Orders", "event_type": "order_created", "source_id": "clidsrc_1"}


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    return install_fake_api(monkeypatch)


async def _refused(name: str, arguments: dict[str, Any]) -> str:
    with pytest.raises(ValueError) as info:
        await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
    return str(info.value)


class TestDefinitions:
    def test_the_five_tools(self) -> None:
        assert list(_BY_NAME) == [
            "chatgpt_ads_pixels_list",
            "chatgpt_ads_pixels_create",
            "chatgpt_ads_conversion_events_list",
            "chatgpt_ads_conversion_events_create",
            "chatgpt_ads_conversions_report",
        ]

    def test_event_create_leads_with_permanence_and_names_the_source(self) -> None:
        text = _BY_NAME[_EVENTS_CREATE].description or ""
        assert text.startswith("Creates one conversion event setting, permanently")
        assert "not its pixel_id" in text
        for event_type in EVENT_TYPES:
            assert event_type in text

    def test_pixel_create_says_it_cannot_be_edited(self) -> None:
        text = _BY_NAME["chatgpt_ads_pixels_create"].description or ""
        assert "cannot be edited or deleted" in text

    @pytest.mark.parametrize(
        "arguments",
        [
            {**_EVENT, "name": "x" * (EVENT_SETTING_NAME_MAX_CHARS + 1)},
            {**_EVENT, "event_type": "order created"},
            {**_EVENT, "custom_event_name": "x" * (CUSTOM_EVENT_NAME_MAX_CHARS + 1)},
            {**_EVENT, "custom_event_name": "_lead"},
            {**_EVENT, "source_id": "a/b"},
        ],
        ids=["name", "event-type", "custom-length", "custom-edge", "source"],
    )
    def test_schema_bounds(self, arguments: dict[str, Any]) -> None:
        assert schema_errors(_BY_NAME[_EVENTS_CREATE], arguments)


class TestPixels:
    async def test_list(self, api: FakeAPI) -> None:
        api.add("/conversions/pixels", body=page(rows("clidsrc", 0, 2), has_more=False))
        result = await call_tool("chatgpt_ads_pixels_list", {"limit": 5})
        assert [r["id"] for r in result] == ["clidsrc_0", "clidsrc_1"]
        assert api.params() == [("limit", "5")]

    async def test_create_always_sends_web(self, api: FakeAPI) -> None:
        answer = {"id": "clidsrc_1", "pixel_id": "1345"}
        api.add("/conversions/pixels", body=answer)
        assert await call_tool("chatgpt_ads_pixels_create", {"name": "Site"}) == answer
        assert sent_body(api.requests[0]) == {"name": "Site", "client_type": "web"}

    async def test_create_refuses_a_bad_name(self, api: FakeAPI) -> None:
        await _refused("chatgpt_ads_pixels_create", {"name": "  "})
        assert api.requests == []

    async def test_a_lost_create_may_have_been_applied(self, api: FakeAPI) -> None:
        api.add("/conversions/pixels", 500, {"error": {"message": "boom"}})
        failure = await fail_tool("chatgpt_ads_pixels_create", {"name": "Site"})
        assert len(api.requests) == 1
        assert failure.detail.endswith(MAY_HAVE_BEEN_APPLIED)


class TestEventSettings:
    async def test_list(self, api: FakeAPI) -> None:
        api.add(
            "/conversions/event_settings", body=page(rows("ces", 0, 1), has_more=False)
        )
        result = await call_tool("chatgpt_ads_conversion_events_list", {})
        assert result == [{"id": "ces_0", "name": "n0"}]
        assert api.params() == [("limit", "50")]

    async def test_create_sends_one_source_and_the_documented_window(
        self, api: FakeAPI
    ) -> None:
        api.add("/conversions/event_settings", body={"id": "ces_1"})
        assert await call_tool(_EVENTS_CREATE, _EVENT) == {"id": "ces_1"}
        assert sent_body(api.requests[0]) == {
            "name": "Orders",
            "event_type": "order_created",
            "attribution_window_days": EVENT_ATTRIBUTION_WINDOW_DAYS,
            "source_ids": ["clidsrc_1"],
        }
        assert EVENT_ATTRIBUTION_WINDOW_DAYS == 30

    async def test_a_custom_event_carries_its_name(self, api: FakeAPI) -> None:
        api.add("/conversions/event_settings", body={"id": "ces_2"})
        arguments = {
            **_EVENT,
            "event_type": "custom",
            "custom_event_name": "demo-request_v2",
        }
        await call_tool(_EVENTS_CREATE, arguments)
        body = sent_body(api.requests[0])
        assert body["custom_event_name"] == "demo-request_v2"
        assert body["attribution_window_days"] == EVENT_ATTRIBUTION_WINDOW_DAYS

    def test_the_window_is_not_an_argument(self) -> None:
        tool = _BY_NAME[_EVENTS_CREATE]
        assert "attribution_window_days" not in tool.inputSchema["properties"]
        assert schema_errors(tool, {**_EVENT, "attribution_window_days": 30})
        assert f"always {EVENT_ATTRIBUTION_WINDOW_DAYS}" in (tool.description or "")

    @pytest.mark.parametrize(
        ("arguments", "match"),
        [
            ({"event_type": "custom"}, "custom_event_name is required"),
            (
                {"event_type": "custom", "custom_event_name": "-x"},
                "custom_event_name is required",
            ),
            ({"custom_event_name": "lead"}, "only for event_type 'custom'"),
            ({"event_type": "a b"}, "event_type"),
            ({"source_id": None}, "source_id"),
            ({"name": ""}, "name"),
            ({"name": "x" * (EVENT_SETTING_NAME_MAX_CHARS + 1)}, "name"),
        ],
        ids=[
            "custom-without-name",
            "custom-bad-name",
            "name-without-custom",
            "event-type",
            "source",
            "empty-name",
            "long-name",
        ],
    )
    async def test_bad_arguments_send_nothing(
        self, api: FakeAPI, arguments: dict[str, Any], match: str
    ) -> None:
        message = await _refused(_EVENTS_CREATE, {**_EVENT, **arguments})
        assert match in message
        assert api.requests == []


class TestFeatureGate:
    @pytest.mark.parametrize(
        ("name", "arguments"),
        [
            ("chatgpt_ads_pixels_list", {}),
            ("chatgpt_ads_pixels_create", {"name": "Site"}),
        ],
    )
    async def test_a_404_on_the_pixel_paths_is_feature_not_enabled(
        self, api: FakeAPI, name: str, arguments: dict[str, Any]
    ) -> None:
        # No route: the fake answers 404 {"error": {"message": "Not found"}}.
        failure = await fail_tool(name, arguments)
        assert failure.code == "feature_not_enabled"
        assert "HTTP 404" in failure.detail

    @pytest.mark.parametrize(
        ("name", "arguments"),
        [("chatgpt_ads_conversion_events_list", {}), (_EVENTS_CREATE, _EVENT)],
        ids=["list", "create"],
    )
    @pytest.mark.parametrize("message", ["Not found", "Client data source not found"])
    async def test_a_404_on_event_settings_is_an_ordinary_error(
        self, api: FakeAPI, name: str, arguments: dict[str, Any], message: str
    ) -> None:
        api.add("/conversions/event_settings", 404, {"error": {"message": message}})
        failure = await fail_tool(name, arguments)
        assert failure.code != "feature_not_enabled"
        assert f"HTTP 404: {message}" in failure.detail

    async def test_a_404_on_an_audience_is_an_ordinary_error(
        self, api: FakeAPI
    ) -> None:
        failure = await fail_tool(
            "chatgpt_ads_audiences_get", {"audience_id": "caud_9"}
        )
        assert failure.code != "feature_not_enabled"
        assert "HTTP 404" in failure.detail

    @pytest.mark.parametrize(
        "name", ["chatgpt_ads_pixels_list", "chatgpt_ads_pixels_create"]
    )
    def test_only_the_pixel_tools_mention_the_gate(self, name: str) -> None:
        assert "feature_not_enabled" in (_BY_NAME[name].description or "")

    @pytest.mark.parametrize(
        "name",
        [
            "chatgpt_ads_conversion_events_list",
            _EVENTS_CREATE,
            "chatgpt_ads_conversions_report",
        ],
    )
    def test_the_other_tools_do_not_mention_the_gate(self, name: str) -> None:
        assert "feature_not_enabled" not in (_BY_NAME[name].description or "")

    def test_event_create_explains_an_unknown_source(self) -> None:
        text = _BY_NAME[_EVENTS_CREATE].description or ""
        assert "Client data source not found" in text

    async def test_other_errors_keep_their_meaning(self, api: FakeAPI) -> None:
        api.add("/conversions/pixels", 400, {"error": {"message": "bad name"}})
        failure = await fail_tool("chatgpt_ads_pixels_create", {"name": "Site"})
        assert failure.code != "feature_not_enabled"
        assert "bad name" in failure.detail
