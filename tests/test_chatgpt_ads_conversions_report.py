"""The ChatGPT Ads conversion report (#995): ``POST /conversions/insights``.

A POST that only reads: marked ``readOnlyHint``, retried like a GET, and its
failures never say a change may have been applied. Pinned here: the body for
each argument (only the keys given, plus ``aggregation_level`` and
``time_ranges``), the ``time_ranges`` string for a fixed clock and zone, and
the ``entity_ids`` and ``event_names`` rules, all checked before any request.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from mureo.chatgpt_ads import _period
from mureo.chatgpt_ads._errors import MAY_HAVE_BEEN_APPLIED
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools import TOOLS
from mureo.chatgpt_ads.tools_measurement import (
    EVENT_NAME_MAX_CHARS,
    MAX_EVENT_NAMES,
    MAX_REPORT_ENTITIES,
    MEASUREMENT_TOOLS,
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

_REPORT = "chatgpt_ads_conversions_report"
_TOOL = by_name(MEASUREMENT_TOOLS)[_REPORT]
_INSIGHTS = by_name(TOOLS)["chatgpt_ads_insights_report"]
_ANSWER = {"object": "list", "data": [], "count": 0, "account_currency": "USD"}
#: 2026-09-08 12:00 in New York.
_NOW = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)
#: The reference's own example: September 1-7, 2026 in America/New_York.
_SEPT_1_TO_7 = '{"type":"unix_range","start":"1788235200","end":"1788840000"}'


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    monkeypatch.setattr(_period.clock, "server_now", lambda: _NOW)
    fake = install_fake_api(monkeypatch)
    fake.add("/ad_account", body={"id": "adacct_1", "timezone": "America/New_York"})
    fake.add("/conversions/insights", body=_ANSWER)
    return fake


async def _body(api: FakeAPI, arguments: dict[str, Any]) -> dict[str, Any]:
    assert await call_tool(_REPORT, arguments) == _ANSWER
    request = api.requests[-1]
    assert (request.method, request.url.path) == ("POST", "/v1/conversions/insights")
    body: dict[str, Any] = sent_body(request)
    return body


async def _refused(arguments: dict[str, Any]) -> str:
    with pytest.raises(ValueError) as info:
        await ChatGPTAdsProvider().handle_mcp_tool(_REPORT, arguments)
    return str(info.value)


class TestDefinition:
    def test_read_only(self) -> None:
        semantics = derive_semantics(_TOOL)
        assert semantics.read_only_hint is True and semantics.mutating is False

    def test_shares_the_insights_argument_names(self) -> None:
        shared = {"period", "level", "time_granularity", "attribution_window_days"}
        assert shared <= set(_TOOL.inputSchema["properties"])
        assert shared <= set(_INSIGHTS.inputSchema["properties"])
        for key in ("period", "time_granularity"):
            assert (
                _TOOL.inputSchema["properties"][key]
                == _INSIGHTS.inputSchema["properties"][key]
            )

    def test_description_states_the_limits(self) -> None:
        text = _TOOL.description or ""
        for phrase in ("No pagination", "2,000", "at least one day", "insights_report"):
            assert phrase in text, phrase

    @pytest.mark.parametrize(
        "arguments",
        [
            {"entity_ids": []},
            {"entity_ids": [f"c_{i}" for i in range(MAX_REPORT_ENTITIES + 1)]},
            {"entity_ids": ["a/b"]},
            {"event_names": []},
            {"event_names": ["x" * (EVENT_NAME_MAX_CHARS + 1)]},
            {"event_names": ["e"] * (MAX_EVENT_NAMES + 1)},
            {"event_names": ["   "]},
            {"view_through_attribution_window_days": 2},
            {"level": "account"},
        ],
        ids=[
            "no-entities",
            "too-many-entities",
            "bad-entity",
            "no-events",
            "long-event",
            "too-many-events",
            "blank-event",
            "view-window",
            "level",
        ],
    )
    def test_schema_bounds(self, arguments: dict[str, Any]) -> None:
        assert schema_errors(_TOOL, arguments)


class TestBody:
    async def test_minimal_body_and_the_reference_time_range(
        self, api: FakeAPI
    ) -> None:
        body = await _body(
            api, {"entity_ids": ["cmpn_123"], "period": "2026-09-01..2026-09-07"}
        )
        assert body == {
            "aggregation_level": "campaign",
            "entity_ids": ["cmpn_123"],
            "time_ranges": [_SEPT_1_TO_7],
        }

    async def test_a_preset_resolves_in_the_account_zone(self, api: FakeAPI) -> None:
        body = await _body(api, {"entity_ids": ["cmpn_123"], "period": "last_7d"})
        assert body["time_ranges"] == [_SEPT_1_TO_7]

    async def test_the_default_period_is_the_last_30_days(self, api: FakeAPI) -> None:
        body = await _body(api, {"entity_ids": ["cmpn_123"]})
        window = json.loads(body["time_ranges"][0])
        # 2026-08-09 00:00 to 2026-09-08 00:00 in New York (EDT, UTC-4).
        assert window == {
            "type": "unix_range",
            "start": "1786248000",
            "end": "1788840000",
        }

    async def test_every_option_as_given(self, api: FakeAPI) -> None:
        arguments = {
            "level": "ad_group",
            "entity_ids": ["adgrp_1", "adgrp_2"],
            "group_by_entity": True,
            "time_granularity": "daily",
            "breakdown": "device",
            "attribution_time_basis": "conversion_time",
            "attribution_window_days": 7,
            "view_through_attribution_window_days": 0,
            "include_events": True,
            "event_names": ["order_created", "demo-request"],
            "include_zero_rows": False,
        }
        body = await _body(api, arguments)
        assert body == {
            "aggregation_level": "ad_group",
            "entity_ids": ["adgrp_1", "adgrp_2"],
            "group_by_entity": True,
            "time_granularity": "daily",
            "breakdown": "device",
            "attribution_time_basis": "conversion_time",
            "attribution_window_days": 7,
            "view_through_attribution_window_days": 0,
            "include": ["attributed_events"],
            "event_names": ["order_created", "demo-request"],
            "include_zero_rows": False,
            "time_ranges": body["time_ranges"],
        }

    async def test_account_wide_without_entities(self, api: FakeAPI) -> None:
        body = await _body(api, {"group_by_entity": False, "level": "ad"})
        assert body["group_by_entity"] is False
        assert "entity_ids" not in body

    async def test_include_events_false_sends_no_include(self, api: FakeAPI) -> None:
        body = await _body(api, {"entity_ids": ["c_1"], "include_events": False})
        assert "include" not in body


class TestRefusals:
    @pytest.mark.parametrize(
        ("arguments", "match"),
        [
            ({}, "entity_ids is required while group_by_entity is true"),
            ({"group_by_entity": True}, "entity_ids is required"),
            ({"entity_ids": "c_1"}, "entity_ids must be an array"),
            ({"entity_ids": ["c_1"] * 101}, "entity_ids must be an array of 1 to 100"),
            ({"entity_ids": ["../x"]}, "entity_ids[]"),
            ({"entity_ids": ["c_1"], "event_names": ["lead"]}, "needs include_events"),
            (
                {"entity_ids": ["c_1"], "include_events": True, "event_names": []},
                "event_names must be an array",
            ),
            (
                {"entity_ids": ["c_1"], "include_events": True, "event_names": [" "]},
                "not all spaces",
            ),
            ({"entity_ids": ["c_1"], "level": "account"}, "level"),
            ({"entity_ids": ["c_1"], "breakdown": "region"}, "breakdown"),
            (
                {"entity_ids": ["c_1"], "view_through_attribution_window_days": True},
                "view_through",
            ),
            ({"entity_ids": ["c_1"], "attribution_window_days": 28}, "7, 14 or 30"),
            ({"entity_ids": ["c_1"], "period": "last_400d"}, "period"),
            ({"entity_ids": ["c_1"], "include_zero_rows": "no"}, "include_zero_rows"),
            ({"entity_ids": ["c_1"], "time_granularity": "hourly"}, "time_granularity"),
        ],
        ids=[
            "no-entities",
            "grouped-no-entities",
            "entities-type",
            "too-many-entities",
            "bad-entity",
            "names-without-events",
            "empty-names",
            "blank-name",
            "level",
            "breakdown",
            "view-window-bool",
            "click-window",
            "period",
            "zero-rows",
            "granularity",
        ],
    )
    async def test_refused_before_any_request(
        self, api: FakeAPI, arguments: dict[str, Any], match: str
    ) -> None:
        message = await _refused(arguments)
        assert match in message
        assert api.requests == []


class TestRetries:
    async def test_a_5xx_is_retried_like_a_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_period.clock, "server_now", lambda: _NOW)
        api = install_fake_api(monkeypatch)
        api.add("/ad_account", body={"timezone": "UTC"})
        api.add("/conversions/insights", 503, {"error": {"message": "busy"}})
        api.add("/conversions/insights", body=_ANSWER)
        assert await call_tool(_REPORT, {"entity_ids": ["c_1"]}) == _ANSWER
        assert [r.url.path for r in api.requests].count("/v1/conversions/insights") == 2

    async def test_a_final_5xx_never_says_applied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_period.clock, "server_now", lambda: _NOW)
        api = install_fake_api(monkeypatch)
        api.add("/ad_account", body={"timezone": "UTC"})
        api.add("/conversions/insights", 500, {"error": {"message": "boom"}})
        failure = await fail_tool(_REPORT, {"entity_ids": ["c_1"]})
        assert MAY_HAVE_BEEN_APPLIED not in failure.detail
        assert "idempotency_key" not in failure.detail

    async def test_a_404_is_not_the_feature_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_period.clock, "server_now", lambda: _NOW)
        api = install_fake_api(monkeypatch)
        api.add("/ad_account", body={"timezone": "UTC"})
        failure = await fail_tool(_REPORT, {"entity_ids": ["c_1"]})
        assert failure.code != "feature_not_enabled"
