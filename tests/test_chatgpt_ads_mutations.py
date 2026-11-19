"""The ChatGPT Ads mutation tools (#994), end to end through the provider.

Each call goes provider → handler → client → ``httpx.MockTransport``; the
contract fixture checks every request's method, path and body keys. Pinned
here: what each tool sends, the argument checks that run before any request,
the account spend-limit preconditions, the POST retry rule, the failure
envelopes and the budget-type check. What the safety layer reads off these
tools is in ``test_chatgpt_ads_mutation_policy``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads._errors import MAY_HAVE_BEEN_APPLIED, ChatGPTAdsAPIError
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools import TOOLS
from mureo.chatgpt_ads.tools_create import CREATE_TOOLS
from mureo.chatgpt_ads.tools_creative import CREATIVE_TOOLS
from mureo.chatgpt_ads.tools_mutations import MUTATION_TOOLS
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

_BY_NAME = by_name(MUTATION_TOOLS)

#: Pause / enable tool → (path it posts to, its id argument).
_STATUS_TOOLS = {
    "chatgpt_ads_campaigns_pause": ("/campaigns/c_1/pause", "campaign_id", "c_1"),
    "chatgpt_ads_campaigns_enable": ("/campaigns/c_1/activate", "campaign_id", "c_1"),
    "chatgpt_ads_ad_groups_pause": ("/ad_groups/g_1/pause", "ad_group_id", "g_1"),
    "chatgpt_ads_ad_groups_enable": ("/ad_groups/g_1/activate", "ad_group_id", "g_1"),
    "chatgpt_ads_ads_pause": ("/ads/a_1/pause", "ad_id", "a_1"),
    "chatgpt_ads_ads_enable": ("/ads/a_1/activate", "ad_id", "a_1"),
}

_MUTATIONS = (
    *_STATUS_TOOLS,
    "chatgpt_ads_campaigns_update",
    "chatgpt_ads_campaigns_update_budget",
    "chatgpt_ads_ad_groups_update",
    "chatgpt_ads_ad_groups_update_bid",
    "chatgpt_ads_account_daily_spend_limit_set",
)

_BIDDING = {
    "billing_event_type": "click",
    "strategy": "fixed_bid",
    "max_bid_micros": 2_500_000,
    "custom_audience_bid_multipliers": [
        {"custom_audience_id": "aud_1", "bid_multiplier_micros": 1_500_000}
    ],
}


def _campaign(**budget: int | None) -> dict[str, Any]:
    """A campaign answer whose budget holds ``budget``."""
    return {"id": "c_1", "object": "campaign", "budget": budget}


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    return install_fake_api(monkeypatch)


class TestDefinitions:
    def test_twelve_tools_follow_the_stage_one_tuple(self) -> None:
        names = tuple(t.name for t in MUTATION_TOOLS)
        assert names == (*_MUTATIONS, "chatgpt_ads_account_spend_limits_get")
        assert ChatGPTAdsProvider().mcp_tools() == (
            *TOOLS,
            *MUTATION_TOOLS,
            *CREATE_TOOLS,
            *CREATIVE_TOOLS,
        )

    @pytest.mark.parametrize("tool", MUTATION_TOOLS, ids=lambda t: t.name)
    def test_closed_schema_and_throttle(self, tool) -> None:  # type: ignore[no-untyped-def]
        semantics = derive_semantics(tool)
        assert tool.inputSchema["additionalProperties"] is False
        assert semantics.throttle is not None
        assert (semantics.throttle.rate, semantics.throttle.burst) == (8.0, 5)
        read = tool.name == "chatgpt_ads_account_spend_limits_get"
        assert semantics.mutating is not read
        assert semantics.read_only_hint is read

    @pytest.mark.parametrize(
        ("name", "phrases"),
        [
            ("chatgpt_ads_campaigns_enable", ("eligible to spend", "reversal")),
            (
                "chatgpt_ads_campaigns_pause",
                ("reversal", "chatgpt_ads_campaigns_archive", "cannot be undone"),
            ),
            (
                "chatgpt_ads_campaigns_update_budget",
                (
                    "replaces",
                    "micros",
                    "already spent",
                    "reversal",
                    "budget type cannot change",
                    "one more request",
                ),
            ),
            (
                "chatgpt_ads_ad_groups_update_bid",
                (
                    "micros",
                    "per impression",
                    "automatic bidding",
                    "reversal",
                    "multipliers (up to 10x)",
                    "not bounded by them",
                    "CPM = amount x 1000",
                    "campaign budget is what bounds spend",
                ),
            ),
            (
                "chatgpt_ads_account_daily_spend_limit_set",
                ("invoice", "micros", "max_daily_budget_per_campaign"),
            ),
        ],
    )
    def test_descriptions_state_what_the_operator_must_know(
        self, name: str, phrases: tuple[str, ...]
    ) -> None:
        description = _BY_NAME[name].description or ""
        for phrase in phrases:
            assert phrase in description, phrase

    def test_nested_objects_are_closed(self) -> None:
        budget = _BY_NAME["chatgpt_ads_campaigns_update_budget"].inputSchema
        bid = _BY_NAME["chatgpt_ads_ad_groups_update_bid"].inputSchema
        assert budget["properties"]["budget"]["additionalProperties"] is False
        assert budget["properties"]["budget"]["minProperties"] == 1
        bidding = bid["properties"]["bidding_config"]
        assert bidding["additionalProperties"] is False
        assert bidding["required"] == ["billing_event_type"]
        item = bidding["properties"]["custom_audience_bid_multipliers"]["items"]
        assert item["additionalProperties"] is False


class TestRequests:
    @pytest.mark.parametrize("name", list(_STATUS_TOOLS))
    async def test_pause_and_enable_post_without_a_body(
        self, api: FakeAPI, name: str
    ) -> None:
        path, key, value = _STATUS_TOOLS[name]
        api.add(path, body={"id": value, "status": "x"})
        assert await call_tool(name, {key: value}) == {"id": value, "status": "x"}
        sent = api.requests[0]
        assert sent.method == "POST"
        assert sent.content == b""
        assert "content-type" not in sent.headers

    async def test_campaign_update_sends_only_the_given_fields(
        self, api: FakeAPI
    ) -> None:
        api.add("/campaigns/c_1", body={"id": "c_1"})
        await call_tool(
            "chatgpt_ads_campaigns_update",
            {"campaign_id": "c_1", "name": "Spring", "end_time": None},
        )
        assert api.requests[0].method == "POST"
        assert sent_body(api.requests[0]) == {"name": "Spring", "end_time": None}
        assert b'"end_time": null' in api.requests[0].content or (
            b'"end_time":null' in api.requests[0].content
        )

    async def test_campaign_schedule_is_sent_as_given(self, api: FakeAPI) -> None:
        api.add("/campaigns/c_1", body={"id": "c_1"})
        args = {"campaign_id": "c_1", "start_time": 1_800_000_000, "end_time": None}
        await call_tool("chatgpt_ads_campaigns_update", args)
        assert sent_body(api.requests[0]) == {
            "start_time": 1_800_000_000,
            "end_time": None,
        }

    async def test_budget_is_sent_unchanged(self, api: FakeAPI) -> None:
        api.add("/campaigns/c_1", body=_campaign(daily_spend_limit_micros=50_000_000))
        api.add("/campaigns/c_1", body={"id": "c_1"})
        budget = {"daily_spend_limit_micros": 75_000_000}
        await call_tool(
            "chatgpt_ads_campaigns_update_budget",
            {"campaign_id": "c_1", "budget": budget},
        )
        assert [r.method for r in api.requests] == ["GET", "POST"]
        assert sent_body(api.requests[1]) == {"budget": budget}

    async def test_ad_group_rename(self, api: FakeAPI) -> None:
        api.add("/ad_groups/g_1", body={"id": "g_1"})
        await call_tool(
            "chatgpt_ads_ad_groups_update", {"ad_group_id": "g_1", "name": "abc"}
        )
        assert sent_body(api.requests[0]) == {"name": "abc"}

    async def test_bidding_config_is_sent_unchanged(self, api: FakeAPI) -> None:
        api.add("/ad_groups/g_1", body={"id": "g_1"})
        await call_tool(
            "chatgpt_ads_ad_groups_update_bid",
            {"ad_group_id": "g_1", "bidding_config": _BIDDING},
        )
        assert sent_body(api.requests[0]) == {"bidding_config": _BIDDING}

    async def test_automatic_bidding_is_the_bare_billing_event(
        self, api: FakeAPI
    ) -> None:
        api.add("/ad_groups/g_1", body={"id": "g_1"})
        config = {"billing_event_type": "impression"}
        await call_tool(
            "chatgpt_ads_ad_groups_update_bid",
            {"ad_group_id": "g_1", "bidding_config": config},
        )
        assert sent_body(api.requests[0]) == {"bidding_config": config}


_INVALID = [
    ("chatgpt_ads_campaigns_pause", {}),
    ("chatgpt_ads_ads_enable", {"ad_id": "a/b"}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1"}),
    ("chatgpt_ads_campaigns_update", {"name": "Spring"}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "name": None}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "name": "ab"}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "start_time": True}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "end_time": 1.5e9}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "end_time": 10}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "end_time": 5 * 10**9}),
    ("chatgpt_ads_campaigns_update_budget", {"campaign_id": "c_1"}),
    ("chatgpt_ads_campaigns_update_budget", {"campaign_id": "c_1", "budget": {}}),
    (
        "chatgpt_ads_campaigns_update_budget",
        {"campaign_id": "c_1", "budget": {"daily_spend_limit_micros": 999_999}},
    ),
    (
        "chatgpt_ads_campaigns_update_budget",
        {"campaign_id": "c_1", "budget": {"daily_spend_limit_micros": True}},
    ),
    (
        "chatgpt_ads_campaigns_update_budget",
        {"campaign_id": "c_1", "budget": {"daily": 5_000_000}},
    ),
    ("chatgpt_ads_campaigns_update_budget", {"campaign_id": "c_1", "budget": [1]}),
    ("chatgpt_ads_ad_groups_update", {"ad_group_id": "g_1"}),
    ("chatgpt_ads_ad_groups_update", {"ad_group_id": "g_1", "name": "   "}),
    ("chatgpt_ads_ad_groups_update_bid", {"ad_group_id": "g_1"}),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {"ad_group_id": "g_1", "bidding_config": {"strategy": "fixed_bid"}},
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {"ad_group_id": "g_1", "bidding_config": {"billing_event_type": "view"}},
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {
            "ad_group_id": "g_1",
            "bidding_config": {"billing_event_type": "click", "bid": 1},
        },
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {
            "ad_group_id": "g_1",
            "bidding_config": {
                "billing_event_type": "click",
                "strategy": "automated_bid",
            },
        },
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {
            "ad_group_id": "g_1",
            "bidding_config": {"billing_event_type": "click", "max_bid_micros": 0},
        },
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {
            "ad_group_id": "g_1",
            "bidding_config": {
                "billing_event_type": "click",
                "max_bid_micros": 30_400_000_000_001,
            },
        },
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {
            "ad_group_id": "g_1",
            "bidding_config": {
                "billing_event_type": "click",
                "custom_audience_bid_multipliers": [
                    {"custom_audience_id": "aud_1", "bid_multiplier_micros": 99_999}
                ],
            },
        },
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {
            "ad_group_id": "g_1",
            "bidding_config": {
                "billing_event_type": "click",
                "custom_audience_bid_multipliers": [
                    {
                        "custom_audience_id": "aud_1",
                        "bid_multiplier_micros": 200_000,
                        "extra": 1,
                    }
                ],
            },
        },
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {
            "ad_group_id": "g_1",
            "bidding_config": {
                "billing_event_type": "click",
                "custom_audience_bid_multipliers": [{"custom_audience_id": 7}],
            },
        },
    ),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {
            "ad_group_id": "g_1",
            "bidding_config": {
                "billing_event_type": "click",
                "custom_audience_bid_multipliers": "aud_1",
            },
        },
    ),
    *(
        (
            "chatgpt_ads_ad_groups_update_bid",
            {
                "ad_group_id": "g_1",
                "bidding_config": {
                    "billing_event_type": "click",
                    "custom_audience_bid_multipliers": [
                        {
                            "custom_audience_id": audience_id,
                            "bid_multiplier_micros": 1_000_000,
                        }
                    ],
                },
            },
        )
        for audience_id in ("", "aud 1", "aud/1", "a" * 129)
    ),
    ("chatgpt_ads_account_daily_spend_limit_set", {}),
    ("chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": -1}),
    ("chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": False}),
    ("chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": "5"}),
]


@pytest.mark.parametrize(("name", "arguments"), _INVALID)
async def test_invalid_arguments_send_nothing(
    api: FakeAPI, name: str, arguments: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
    assert api.requests == []


@pytest.mark.parametrize(
    "key", ["current_daily_budget", "projected_total_daily_budget"]
)
async def test_a_context_figure_too_large_for_a_float_is_refused(
    api: FakeAPI, key: str
) -> None:
    """The schema takes any number of at least 0; the handler needs a finite one."""
    arguments = {
        "campaign_id": "c_1",
        "budget": {"daily_spend_limit_micros": 1_000_000},
        key: 10**400,
    }
    with pytest.raises(ValueError, match="finite"):
        await ChatGPTAdsProvider().handle_mcp_tool(
            "chatgpt_ads_campaigns_update_budget", arguments
        )
    assert api.requests == []


#: Invalid cases the schema cannot express, with the reason.
_HANDLER_ONLY = {
    # "At least one of name, start_time, end_time": the tool schemas keep to
    # type, properties, required and additionalProperties at the top level.
    ("chatgpt_ads_campaigns_update", '{"campaign_id": "c_1"}'),
    # JSON Schema counts 1.5e9 as an integer (no fractional part); the
    # handler takes Python ints only.
    (
        "chatgpt_ads_campaigns_update",
        '{"campaign_id": "c_1", "end_time": 1500000000.0}',
    ),
}

_VALID = [
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "name": "Spring"}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "name": " a b "}),
    ("chatgpt_ads_campaigns_update", {"campaign_id": "c_1", "end_time": None}),
    ("chatgpt_ads_ad_groups_update", {"ad_group_id": "g_1", "name": "abc"}),
    (
        "chatgpt_ads_ad_groups_update_bid",
        {"ad_group_id": "g_1", "bidding_config": _BIDDING},
    ),
    (
        "chatgpt_ads_campaigns_update_budget",
        {
            "campaign_id": "c_1",
            "budget": {"daily_spend_limit_micros": 1_000_000},
            "current_daily_budget": 0,
            "projected_total_daily_budget": 12.5,
        },
    ),
    ("chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 0}),
]


@pytest.mark.parametrize(("name", "arguments"), _INVALID)
def test_the_schema_refuses_what_the_handler_refuses(
    name: str, arguments: dict[str, Any]
) -> None:
    if (name, json.dumps(arguments)) in _HANDLER_ONLY:
        assert schema_errors(_BY_NAME[name], arguments) == []
    else:
        assert schema_errors(_BY_NAME[name], arguments) != []


@pytest.mark.parametrize(("name", "arguments"), _VALID)
async def test_valid_arguments_pass_the_schema_and_the_handler(
    api: FakeAPI, name: str, arguments: dict[str, Any]
) -> None:
    assert schema_errors(_BY_NAME[name], arguments) == []
    api.add("/campaigns/c_1", body=_campaign(daily_spend_limit_micros=5_000_000))
    api.add("/campaigns/c_1", body={"id": "c_1"})
    api.add("/ad_groups/g_1", body={"id": "g_1"})
    api.add("/ad_account/spend_limit_windows", body={"object": "list"})
    api.add("/ad_account/daily_spend_limit", body={"spend_limits": {}})
    await call_tool(name, arguments)
    assert api.requests[-1].method == "POST"


class TestBudgetType:
    _SET = "chatgpt_ads_campaigns_update_budget"

    async def test_the_same_type_reads_once_and_posts_once(self, api: FakeAPI) -> None:
        current = {
            "daily_spend_limit_micros": 5_000_000,
            "lifetime_spend_limit_micros": None,
        }
        api.add("/campaigns/c_1", body=_campaign(**current))
        api.add("/campaigns/c_1", body={"id": "c_1"})
        budget = {"daily_spend_limit_micros": 7_000_000}
        await call_tool(self._SET, {"campaign_id": "c_1", "budget": budget})
        assert [r.method for r in api.requests] == ["GET", "POST"]
        assert sent_body(api.requests[1]) == {"budget": budget}

    @pytest.mark.parametrize(
        ("current", "sent"),
        [
            (
                {"daily_spend_limit_micros": 5_000_000},
                {"lifetime_spend_limit_micros": 90_000_000},
            ),
            (
                {"daily_spend_limit_micros": 5_000_000},
                {
                    "daily_spend_limit_micros": 5_000_000,
                    "lifetime_spend_limit_micros": 90_000_000,
                },
            ),
            (
                {
                    "daily_spend_limit_micros": 5_000_000,
                    "lifetime_spend_limit_micros": 90_000_000,
                },
                {"daily_spend_limit_micros": 6_000_000},
            ),
        ],
        ids=["daily-to-lifetime", "daily-to-both", "both-to-daily"],
    )
    async def test_a_different_type_is_refused_without_a_post(
        self, api: FakeAPI, current: dict[str, int], sent: dict[str, int]
    ) -> None:
        api.add("/campaigns/c_1", body=_campaign(**current))
        failure = await fail_tool(self._SET, {"campaign_id": "c_1", "budget": sent})
        assert (failure.status, failure.code) == ("refused", "budget_kind_change")
        for key in (*current, *sent):
            assert key in failure.detail
        assert "Ads Manager" in failure.detail
        assert [r.method for r in api.requests] == ["GET"]

    @pytest.mark.parametrize(
        "campaign",
        [
            {"id": "c_1"},
            {"id": "c_1", "budget": None},
            {"id": "c_1", "budget": "daily"},
            _campaign(daily_spend_limit_micros=None, lifetime_spend_limit_micros=None),
            [],
        ],
        ids=["no-budget", "null", "string", "both-null", "not-an-object"],
    )
    async def test_an_unreadable_budget_is_refused_without_a_post(
        self, api: FakeAPI, campaign: object
    ) -> None:
        api.add("/campaigns/c_1", body=campaign)
        budget = {"daily_spend_limit_micros": 5_000_000}
        failure = await fail_tool(self._SET, {"campaign_id": "c_1", "budget": budget})
        assert (failure.status, failure.code) == ("refused", "budget_unreadable")
        assert "Ads Manager" in failure.detail
        assert [r.method for r in api.requests] == ["GET"]


class TestAccountDailySpendLimit:
    async def test_the_revision_comes_from_the_read(self, api: FakeAPI) -> None:
        api.add(
            "/ad_account/spend_limit_windows",
            body={
                "object": "list",
                "data": [],
                "daily_limits": [{"window_id": "w_1", "amount_micros": 1}],
                "revision": 7,
            },
        )
        api.add("/ad_account/daily_spend_limit", body={"spend_limits": {}})
        out = await call_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 50_000_000}
        )
        assert out == {"spend_limits": {}}
        assert [r.method for r in api.requests] == ["GET", "POST"]
        assert sent_body(api.requests[1]) == {
            "amount_micros": 50_000_000,
            "expected_revision": 7,
        }

    async def test_an_absent_revision_is_zero(self, api: FakeAPI) -> None:
        windows = {"object": "list", "data": [], "daily_limit": None}
        api.add("/ad_account/spend_limit_windows", body=windows)
        api.add("/ad_account/daily_spend_limit", body={"spend_limits": {}})
        await call_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 0}
        )
        assert sent_body(api.requests[1]) == {
            "amount_micros": 0,
            "expected_revision": 0,
        }

    @pytest.mark.parametrize("revision", [None, "7", -1, True, 1.0])
    async def test_an_unusable_revision_stops_the_write(
        self, api: FakeAPI, revision: object
    ) -> None:
        windows = {"object": "list", "daily_limit": None, "revision": revision}
        api.add("/ad_account/spend_limit_windows", body=windows)
        failure = await fail_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 1}
        )
        assert "unusable revision" in failure.detail
        assert MAY_HAVE_BEEN_APPLIED not in failure.detail
        assert [r.method for r in api.requests] == ["GET"]

    # A str body is sent as raw text, so '"ok"' and "null" are JSON values.
    @pytest.mark.parametrize("answer", [[], '"ok"', 7, "null"], ids=repr)
    async def test_an_answer_that_is_not_an_object_stops_the_write(
        self, api: FakeAPI, answer: object
    ) -> None:
        api.add("/ad_account/spend_limit_windows", body=answer)
        failure = await fail_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 1}
        )
        assert "not a JSON object" in failure.detail
        assert [r.method for r in api.requests] == ["GET"]

    @pytest.mark.parametrize(
        "windows",
        [
            {"daily_limits": {"a": {}, "b": {}}},
            {"daily_limits": "two"},
            {"daily_limits": [], "daily_limit": [{}, {}]},
            {"daily_limit": "one"},
        ],
    )
    async def test_daily_rules_in_an_unexpected_shape_stop_the_write(
        self, api: FakeAPI, windows: dict[str, Any]
    ) -> None:
        answer = {"object": "list", "revision": 4, **windows}
        api.add("/ad_account/spend_limit_windows", body=answer)
        failure = await fail_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 1}
        )
        assert "unexpected shape" in failure.detail
        assert "nothing was changed" in failure.detail
        assert [r.method for r in api.requests] == ["GET"]

    async def test_an_empty_list_beside_a_single_rule_counts_as_one(
        self, api: FakeAPI
    ) -> None:
        windows = {
            "object": "list",
            "daily_limits": [],
            "daily_limit": {"amount_micros": 9},
            "revision": 4,
        }
        api.add("/ad_account/spend_limit_windows", body=windows)
        api.add("/ad_account/daily_spend_limit", body={"spend_limits": {}})
        await call_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 5}
        )
        assert [r.method for r in api.requests] == ["GET", "POST"]
        assert sent_body(api.requests[1])["expected_revision"] == 4

    @pytest.mark.parametrize(
        "windows",
        [
            {"daily_limits": [{"window_id": "w_1"}, {"window_id": "w_2"}]},
            {"daily_limits": [{}, {}, {}], "daily_limit": None},
        ],
    )
    async def test_several_daily_rules_are_refused_without_a_post(
        self, api: FakeAPI, windows: dict[str, Any]
    ) -> None:
        api.add("/ad_account/spend_limit_windows", body={"object": "list", **windows})
        failure = await fail_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 1}
        )
        assert (failure.status, failure.code) == (
            "refused",
            "multiple_daily_spend_limits",
        )
        assert str(len(windows["daily_limits"])) in failure.detail
        assert "Ads Manager" in failure.detail
        assert [r.method for r in api.requests] == ["GET"]

    async def test_the_single_daily_limit_field_is_the_fallback(
        self, api: FakeAPI
    ) -> None:
        api.add(
            "/ad_account/spend_limit_windows",
            body={"object": "list", "daily_limit": {"amount_micros": 9}, "revision": 2},
        )
        api.add("/ad_account/daily_spend_limit", body={"spend_limits": {}})
        await call_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 5}
        )
        assert sent_body(api.requests[1])["expected_revision"] == 2

    async def test_the_read_tool(self, api: FakeAPI) -> None:
        windows = {"object": "list", "data": [], "daily_limit": None, "revision": 3}
        api.add("/ad_account/spend_limit_windows", body=windows)
        assert await call_tool("chatgpt_ads_account_spend_limits_get", {}) == windows


class TestFailures:
    async def test_401_is_token_invalid(self, api: FakeAPI) -> None:
        api.add("/ads/a_1/pause", 401, {"error": {"message": "bad key"}})
        failure = await fail_tool("chatgpt_ads_ads_pause", {"ad_id": "a_1"})
        assert (failure.status, failure.code) == ("auth_error", "token_invalid")

    async def test_feature_gate(self, api: FakeAPI) -> None:
        api.add(
            "/ad_account/spend_limit_windows",
            403,
            {"error": {"message": "Spend limits are not enabled for this account"}},
        )
        failure = await fail_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 1}
        )
        assert (failure.status, failure.code) == ("error", "feature_not_enabled")

    async def test_422_names_the_platform_code(self, api: FakeAPI) -> None:
        api.add("/ad_account/spend_limit_windows", body={"object": "list"})
        api.add(
            "/ad_account/daily_spend_limit",
            422,
            {
                "error": {
                    "message": "below spend",
                    "code": "budget_window_amount_below_spend",
                }
            },
        )
        failure = await fail_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 1}
        )
        assert failure.code == "api_error"
        assert failure.detail.startswith("API error:")
        assert "budget_window_amount_below_spend" in failure.detail
        assert MAY_HAVE_BEEN_APPLIED not in failure.detail

    async def test_no_key(self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CHATGPT_ADS_API_KEY")
        failure = await fail_tool("chatgpt_ads_campaigns_pause", {"campaign_id": "c_1"})
        assert failure.code == "no_credentials"
        assert api.requests == []


class TestRetries:
    @pytest.mark.parametrize("status", [500, 502, 503])
    async def test_a_5xx_post_is_final(self, api: FakeAPI, status: int) -> None:
        api.add("/campaigns/c_1/pause", status, {"error": {"message": "boom"}})
        api.add("/campaigns/c_1/pause", body={"id": "c_1"})
        failure = await fail_tool("chatgpt_ads_campaigns_pause", {"campaign_id": "c_1"})
        assert len(api.requests) == 1
        assert failure.detail.endswith(MAY_HAVE_BEEN_APPLIED)

    async def test_a_transport_error_on_post_is_final(self, api: FakeAPI) -> None:
        api.raise_on["/v1/campaigns/c_1/pause"] = httpx.ReadTimeout("slow")
        failure = await fail_tool("chatgpt_ads_campaigns_pause", {"campaign_id": "c_1"})
        assert len(api.requests) == 1
        assert "ReadTimeout" in failure.detail
        assert failure.detail.endswith(MAY_HAVE_BEEN_APPLIED)

    async def test_a_429_post_is_retried(self, api: FakeAPI) -> None:
        api.add("/campaigns/c_1/pause", 429, {})
        api.add("/campaigns/c_1/pause", body={"id": "c_1"})
        assert await call_tool("chatgpt_ads_campaigns_pause", {"campaign_id": "c_1"})
        assert len(api.requests) == 2

    async def test_a_429_post_exhausted_was_not_applied(self, api: FakeAPI) -> None:
        api.add("/campaigns/c_1/pause", 429, {"error": {"message": "slow down"}})
        failure = await fail_tool("chatgpt_ads_campaigns_pause", {"campaign_id": "c_1"})
        assert len(api.requests) == 3
        assert MAY_HAVE_BEEN_APPLIED not in failure.detail

    async def test_a_5xx_on_the_prior_get_is_still_retried(self, api: FakeAPI) -> None:
        api.add("/ad_account/spend_limit_windows", 500, {})
        api.add("/ad_account/spend_limit_windows", body={"object": "list"})
        api.add("/ad_account/daily_spend_limit", body={"spend_limits": {}})
        await call_tool(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 1}
        )
        assert [r.method for r in api.requests] == ["GET", "GET", "POST"]

    async def test_a_mutation_past_the_deadline_may_have_been_applied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _hang(_client: Any, _arguments: dict[str, Any]) -> Any:
            await asyncio.sleep(10)

        monkeypatch.setitem(handlers.HANDLERS, "chatgpt_ads_campaigns_pause", _hang)
        monkeypatch.setitem(handlers.HANDLERS, "chatgpt_ads_campaigns_get", _hang)
        monkeypatch.setattr(handlers, "_open_client", lambda _k: FakeAPI().client())
        with pytest.raises(ChatGPTAdsAPIError) as mutation:
            await handlers.run_tool(
                "chatgpt_ads_campaigns_pause", {}, "k", deadline=0.01
            )
        assert str(mutation.value).endswith(MAY_HAVE_BEEN_APPLIED)
        with pytest.raises(ChatGPTAdsAPIError) as read:
            await handlers.run_tool("chatgpt_ads_campaigns_get", {}, "k", deadline=0.01)
        assert MAY_HAVE_BEEN_APPLIED not in str(read.value)
