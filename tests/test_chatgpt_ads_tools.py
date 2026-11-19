"""The nine ChatGPT Ads read tools, end to end through the provider.

Each call goes provider → handler → client → ``httpx.MockTransport``; the
contract fixture checks every request, and the result is read back the way the
server and the journal read it (``failure_of``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mureo.chatgpt_ads import _period, handlers
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.core.tool_failure import failure_of
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI, page, rows

pytestmark = pytest.mark.unit

#: 2026-03-01 00:30 in Tokyo == 2026-02-28 15:30 UTC.
_NOW = datetime(2026, 2, 28, 15, 30, tzinfo=timezone.utc)
_ACCOUNT = {"id": "adacct_1", "timezone": "Asia/Tokyo", "new_field": {"x": 1}}


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = FakeAPI()
    monkeypatch.setenv("CHATGPT_ADS_API_KEY", SENTINEL_KEY)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: fake.client())
    monkeypatch.setattr(_period.clock, "server_now", lambda: _NOW)
    return fake


async def _call(name: str, arguments: dict[str, Any] | None = None) -> Any:
    result = await ChatGPTAdsProvider().handle_mcp_tool(name, arguments or {})
    assert failure_of(result) is None, result[0].text
    return json.loads(result[0].text)


async def _fail(name: str, arguments: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
    result = await ChatGPTAdsProvider().handle_mcp_tool(name, arguments or {})
    failure = failure_of(result)
    assert failure is not None, result[0].text
    return failure


def _time_range(api: FakeAPI) -> dict[str, str]:
    value = dict(api.params())["time_ranges[]"]
    return json.loads(value)


class TestEntityReads:
    async def test_account_get_returns_the_object_unchanged(self, api: FakeAPI) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        assert await _call("chatgpt_ads_account_get") == _ACCOUNT

    async def test_campaigns_list_forwards_filters_and_default_limit(
        self, api: FakeAPI
    ) -> None:
        api.add("/campaigns", body=page(rows("cmpn", 0, 2), has_more=False))
        out = await _call(
            "chatgpt_ads_campaigns_list",
            {"name": "Spring", "include_serving_issues": True},
        )
        assert [r["id"] for r in out] == ["cmpn_0", "cmpn_1"]
        params = api.params()
        assert ("name", "Spring") in params
        assert ("include[]", "serving_issues") in params
        assert ("limit", "50") in params

    async def test_campaigns_list_paginates_to_the_tool_limit(
        self, api: FakeAPI
    ) -> None:
        api.add("/campaigns", body=page(rows("cmpn", 0, 3), has_more=True))
        api.add("/campaigns", body=page(rows("cmpn", 3, 3), has_more=True))
        out = await _call("chatgpt_ads_campaigns_list", {"limit": 4})
        assert len(out) == 4
        assert ("after", "cmpn_2") in api.params()

    async def test_campaigns_get_with_serving_issues(self, api: FakeAPI) -> None:
        api.add("/campaigns/cmpn_1", body={"id": "cmpn_1", "status": "brand_new"})
        out = await _call(
            "chatgpt_ads_campaigns_get",
            {"campaign_id": "cmpn_1", "include_serving_issues": True},
        )
        assert out == {"id": "cmpn_1", "status": "brand_new"}
        assert api.params() == [("include[]", "serving_issues")]

    async def test_ad_groups_list_sends_the_parent_campaign(self, api: FakeAPI) -> None:
        api.add("/ad_groups", body=page(rows("adgrp", 0, 1), has_more=False))
        await _call("chatgpt_ads_ad_groups_list", {"campaign_id": "cmpn_1"})
        assert ("campaign_id", "cmpn_1") in api.params()

    async def test_ad_groups_list_requires_campaign_id(self, api: FakeAPI) -> None:
        with pytest.raises(ValueError, match="campaign_id"):
            await ChatGPTAdsProvider().handle_mcp_tool("chatgpt_ads_ad_groups_list", {})
        assert api.requests == []

    async def test_ad_groups_get_and_ads_get(self, api: FakeAPI) -> None:
        api.add("/ad_groups/adgrp_1", body={"id": "adgrp_1"})
        api.add("/ads/ad_1", body={"id": "ad_1"})
        assert await _call("chatgpt_ads_ad_groups_get", {"ad_group_id": "adgrp_1"})
        assert await _call("chatgpt_ads_ads_get", {"ad_id": "ad_1"}) == {"id": "ad_1"}

    async def test_ads_list_filters_by_ad_group(self, api: FakeAPI) -> None:
        api.add("/ads", body=page(rows("ad", 0, 1), has_more=False))
        await _call("chatgpt_ads_ads_list", {"ad_group_id": "adgrp_1", "name": "Blue"})
        assert ("ad_group_id", "adgrp_1") in api.params()
        assert ("name", "Blue") in api.params()

    @pytest.mark.parametrize("bad", ["../ad_account", "a/b", "", "x" * 129, "ad 1"])
    async def test_a_path_id_outside_the_pattern_is_refused(
        self, api: FakeAPI, bad: str
    ) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                "chatgpt_ads_ads_get", {"ad_id": bad}
            )
        assert api.requests == []

    @pytest.mark.parametrize("bad", [0, -1, True, "5", 1001])
    async def test_an_invalid_limit_is_refused(self, api: FakeAPI, bad: object) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                "chatgpt_ads_campaigns_list", {"limit": bad}
            )

    async def test_a_non_string_name_is_refused(self, api: FakeAPI) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                "chatgpt_ads_campaigns_list", {"name": 5}
            )

    async def test_a_non_bool_include_flag_is_refused(self, api: FakeAPI) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                "chatgpt_ads_campaigns_list", {"include_serving_issues": "yes"}
            )

    async def test_an_unknown_tool_is_refused(self, api: FakeAPI) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool("chatgpt_ads_nope", {})

    async def test_an_unknown_tool_is_refused_before_credentials(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CHATGPT_ADS_API_KEY")
        with pytest.raises(ValueError, match="chatgpt_ads_nope"):
            await ChatGPTAdsProvider().handle_mcp_tool("chatgpt_ads_nope", {})

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "ab",
            "   ",
            pytest.param("x" * 1001, id="1001_chars"),
            pytest.param(" " * 1000, id="1000_spaces"),
            "Spring\n",
            "Spring\nSale",
            "Spring\rSale",
            "Spring\u2028Sale",
            "Spring\u2029",
        ],
    )
    @pytest.mark.parametrize(
        "tool", ["chatgpt_ads_campaigns_list", "chatgpt_ads_ads_list"]
    )
    async def test_a_name_filter_outside_the_api_bounds_is_refused(
        self, api: FakeAPI, tool: str, name: str
    ) -> None:
        with pytest.raises(ValueError, match="name"):
            await ChatGPTAdsProvider().handle_mcp_tool(tool, {"name": name})
        assert api.requests == []

    async def test_a_name_filter_at_the_bounds_is_sent(self, api: FakeAPI) -> None:
        api.add("/campaigns", body=page([], has_more=False))
        await _call("chatgpt_ads_campaigns_list", {"name": "abc"})
        await _call("chatgpt_ads_campaigns_list", {"name": "x" * 1000})
        assert ("name", "abc") in api.params(0)
        assert ("name", "x" * 1000) in api.params(1)


class TestInsights:
    async def test_defaults(self, api: FakeAPI) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        api.add(
            "/ad_account/insights",
            body=page([{"id": "r1", "spend": 1.5}], has_more=False),
        )
        out = await _call("chatgpt_ads_insights_report")
        assert out == [{"id": "r1", "spend": 1.5}]
        params = api.params()
        assert ("aggregation_level", "campaign") in params
        assert ("time_granularity", "none") in params
        assert ("limit", "1000") in params
        fields = [v for k, v in params if k == "fields[]"]
        assert fields == [
            "campaign.id",
            "campaign.name",
            "campaign.impressions",
            "campaign.clicks",
            "campaign.spend",
            "campaign.ctr",
            "campaign.cpc",
            "campaign.cpm",
        ]
        # last_30d ending yesterday in Tokyo, not in UTC.
        assert _time_range(api) == {
            "type": "date_range",
            "since": "2026-01-30",
            "until": "2026-02-28",
        }

    async def test_scope_level_granularity_metrics_and_window(
        self, api: FakeAPI
    ) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        api.add("/ad_groups/adgrp_1/insights", body=page([], has_more=False))
        await _call(
            "chatgpt_ads_insights_report",
            {
                "ad_group_id": "adgrp_1",
                "level": "ad",
                "time_granularity": "daily",
                "metrics": ["clicks", "conversions"],
                "attribution_window_days": 7,
                "period": "2026-02-01..2026-02-07",
                "limit": 10,
            },
        )
        params = api.params()
        assert ("aggregation_level", "ad") in params
        assert ("time_granularity", "daily") in params
        assert ("attribution_window_days", "7") in params
        assert [v for k, v in params if k == "fields[]"] == [
            "ad.id",
            "ad.name",
            "metadata.readable_time",
            "ad.clicks",
            "conversions",
        ]
        assert _time_range(api)["since"] == "2026-02-01"

    async def test_account_level_maps_to_ad_account(self, api: FakeAPI) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        api.add("/ad_account/insights", body=page([], has_more=False))
        await _call("chatgpt_ads_insights_report", {"level": "account"})
        assert ("aggregation_level", "ad_account") in api.params()
        assert ("fields[]", "ad_account.id") in api.params()

    async def test_default_level_follows_a_scope_below_campaign(
        self, api: FakeAPI
    ) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        api.add("/ads/ad_1/insights", body=page([], has_more=False))
        await _call("chatgpt_ads_insights_report", {"ad_id": "ad_1"})
        assert ("aggregation_level", "ad") in api.params()

    async def test_insights_rows_paginate(self, api: FakeAPI) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        api.add("/campaigns/cmpn_1/insights", body=page(rows("r", 0, 2), has_more=True))
        api.add(
            "/campaigns/cmpn_1/insights", body=page(rows("r", 2, 2), has_more=False)
        )
        out = await _call("chatgpt_ads_insights_report", {"campaign_id": "cmpn_1"})
        assert len(out) == 4

    @pytest.mark.parametrize(
        "arguments",
        [
            {"campaign_id": "c", "ad_id": "a"},
            {"ad_group_id": "g", "level": "campaign"},
            {"ad_id": "a", "level": "account"},
            {"level": "keyword"},
            {"metrics": ["reach"]},
            {"metrics": []},
            {"metrics": "clicks"},
            {"attribution_window_days": 3},
            {"time_granularity": "hourly"},
            {"period": "2024-01-01..2025-06-01"},
            {"level": ["campaign"]},
            {"attribution_window_days": 7.0},
            {"attribution_window_days": True},
            {"metrics": ["clicks", "clicks"]},
        ],
    )
    async def test_invalid_arguments_are_refused_before_any_report(
        self, api: FakeAPI, arguments: dict[str, Any]
    ) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                "chatgpt_ads_insights_report", arguments
            )
        assert not [r for r in api.requests if r.url.path.endswith("/insights")]


class TestChangeHistory:
    async def test_period_becomes_unix_bounds_in_the_account_zone(
        self, api: FakeAPI
    ) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        api.add("/audit_logs", body=page([{"id": "alog_1", "ts": 1}], has_more=False))
        out = await _call(
            "chatgpt_ads_change_history_list",
            {"period": "yesterday", "campaign_id": "cmpn_1", "limit": 500},
        )
        assert out == [{"id": "alog_1", "ts": 1}]
        params = dict(api.params())
        tokyo = ZoneInfo("Asia/Tokyo")
        assert params["start_time"] == str(
            int(datetime(2026, 2, 28, tzinfo=tokyo).timestamp())
        )
        assert params["end_time"] == str(
            int(datetime(2026, 3, 1, tzinfo=tokyo).timestamp()) - 1
        )
        assert params["campaign_id"] == "cmpn_1"
        assert params["limit"] == "100"

    async def test_default_window_is_seven_days(self, api: FakeAPI) -> None:
        api.add("/ad_account", body=_ACCOUNT)
        api.add("/audit_logs", body=page([], has_more=False))
        await _call("chatgpt_ads_change_history_list", {"ad_id": "ad_1"})
        params = dict(api.params())
        assert int(params["end_time"]) - int(params["start_time"]) == 7 * 86400 - 1
        assert params["ad_id"] == "ad_1"


class TestFailures:
    async def test_no_key_is_an_auth_error_naming_both_routes(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CHATGPT_ADS_API_KEY")
        failure = await _fail("chatgpt_ads_account_get")
        assert (failure.status, failure.code) == ("auth_error", "no_credentials")
        assert "CHATGPT_ADS_API_KEY" in failure.detail
        assert "mureo configure" in failure.detail
        assert api.requests == []

    async def test_401_is_token_invalid(self, api: FakeAPI) -> None:
        api.add("/ad_account", 401, {"error": {"message": "Invalid key"}})
        failure = await _fail("chatgpt_ads_account_get")
        assert (failure.status, failure.code) == ("auth_error", "token_invalid")

    async def test_403_feature_gate(self, api: FakeAPI) -> None:
        api.add("/ad_account", 403, {"error": {"message": "Hotel is not enabled"}})
        failure = await _fail("chatgpt_ads_account_get")
        assert (failure.status, failure.code) == ("error", "feature_not_enabled")
        assert "Hotel is not enabled" in failure.detail

    async def test_403_without_gate_is_token_invalid(self, api: FakeAPI) -> None:
        api.add("/ad_account", 403, {"error": {"message": "Forbidden"}})
        failure = await _fail("chatgpt_ads_account_get")
        assert (failure.status, failure.code) == ("auth_error", "token_invalid")

    async def test_plain_404_is_an_api_error(self, api: FakeAPI) -> None:
        api.add("/ads/ad_9", 404, {"error": {"message": "Not found"}})
        failure = await _fail("chatgpt_ads_ads_get", {"ad_id": "ad_9"})
        assert (failure.status, failure.code) == ("error", "api_error")
        assert failure.detail.startswith("API error:")
        assert "Not found" in failure.detail

    async def test_404_with_disabled_code_is_a_feature_gate(self, api: FakeAPI) -> None:
        api.add("/ads/ad_9", 404, {"error": {"code": "segments_disabled"}})
        failure = await _fail("chatgpt_ads_ads_get", {"ad_id": "ad_9"})
        assert failure.code == "feature_not_enabled"

    async def test_429_then_success(self, api: FakeAPI) -> None:
        api.add("/ad_account", 429, {})
        api.add("/ad_account", body=_ACCOUNT)
        assert await _call("chatgpt_ads_account_get") == _ACCOUNT

    async def test_429_exhausted(self, api: FakeAPI) -> None:
        api.add("/ad_account", 429, {"error": {"message": "Rate limited"}})
        failure = await _fail("chatgpt_ads_account_get")
        assert failure.code == "api_error"
        assert "429" in failure.detail

    async def test_500(self, api: FakeAPI) -> None:
        api.add("/ad_account", 500, {"error": {"message": "Internal"}})
        failure = await _fail("chatgpt_ads_account_get")
        assert failure.code == "api_error"
        assert "Internal" in failure.detail

    async def test_malformed_json_error_body(self, api: FakeAPI) -> None:
        api.add("/ad_account", 400, "{not json")
        failure = await _fail("chatgpt_ads_account_get")
        assert failure.code == "api_error"
        assert "400" in failure.detail

    async def test_malformed_json_success_body(self, api: FakeAPI) -> None:
        api.add("/ad_account", 200, "{not json")
        failure = await _fail("chatgpt_ads_account_get")
        assert failure.code == "api_error"

    async def test_transport_error(self, api: FakeAPI) -> None:
        import httpx

        api.raise_on["/v1/ad_account"] = httpx.ReadTimeout("timed out")
        failure = await _fail("chatgpt_ads_account_get")
        assert failure.code == "api_error"
        assert "ReadTimeout" in failure.detail
