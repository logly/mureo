"""Before-state capture for the ChatGPT Ads mutations (#994).

``ChatGPTAdsProvider.capture_reversal`` reads the entity through one of the
provider's own read tools before a mutation runs and returns the reversal the
server records into ``STATE.json``'s ``action_log``. Pinned here: every row of
the reversal table, the cases that record no reversal, the caveats that make a
plan PARTIAL, the failure rules (never raises, logs the exception type only,
a stop is re-raised), and the whole path through the server, the planner and
the rollback executor.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import pytest

from mureo.amazon_ads.reversal import CAPTURE_DEADLINE_SECONDS
from mureo.chatgpt_ads import handlers, reversal
from mureo.chatgpt_ads._api import REVERSAL_READ_DEADLINE_SECONDS
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.context.models import StateDocument
from mureo.context.state import read_state_file, write_state_file
from mureo.mcp import plugin_audit
from mureo.mcp.tool_provider import MCPReversibleToolProvider
from mureo.rollback.executor import execute_rollback
from mureo.rollback.models import RollbackStatus
from mureo.rollback.planner import plan_rollback
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI
from tests._chatgpt_ads_reversal_check import capture_checked as _capture
from tests._server_reload import reloaded_server

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_LIFETIME_CAVEAT = (
    "the platform rejects a lifetime budget below the amount already spent"
)


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = FakeAPI()
    monkeypatch.setenv("CHATGPT_ADS_API_KEY", SENTINEL_KEY)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: fake.client())
    return fake


def test_the_provider_opts_into_capture() -> None:
    assert isinstance(ChatGPTAdsProvider(), MCPReversibleToolProvider)


def test_the_read_deadline_matches_the_amazon_capture_deadline() -> None:
    assert REVERSAL_READ_DEADLINE_SECONDS == CAPTURE_DEADLINE_SECONDS


_TOGGLES = [
    # (mutation, read path, id key, id, prior status, expected operation)
    ("chatgpt_ads_campaigns_pause", "/campaigns/c_1", "campaign_id", "c_1", "active",
     "chatgpt_ads_campaigns_enable"),
    ("chatgpt_ads_campaigns_enable", "/campaigns/c_1", "campaign_id", "c_1", "paused",
     "chatgpt_ads_campaigns_pause"),
    ("chatgpt_ads_ad_groups_pause", "/ad_groups/g_1", "ad_group_id", "g_1", "active",
     "chatgpt_ads_ad_groups_enable"),
    ("chatgpt_ads_ad_groups_enable", "/ad_groups/g_1", "ad_group_id", "g_1", "paused",
     "chatgpt_ads_ad_groups_pause"),
    ("chatgpt_ads_ads_pause", "/ads/a_1", "ad_id", "a_1", "active",
     "chatgpt_ads_ads_enable"),
    ("chatgpt_ads_ads_enable", "/ads/a_1", "ad_id", "a_1", "paused",
     "chatgpt_ads_ads_pause"),
]  # fmt: skip


class TestToggles:
    @pytest.mark.parametrize(
        ("name", "path", "key", "value", "status", "operation"), _TOGGLES
    )
    async def test_the_opposite_tool(  # noqa: PLR0913
        self,
        api: FakeAPI,
        name: str,
        path: str,
        key: str,
        value: str,
        status: str,
        operation: str,
    ) -> None:
        api.add(path, body={"id": value, "status": status})
        assert await _capture(name, {key: value}, restores=None) == {
            "operation": operation,
            "params": {key: value},
        }
        assert [(r.method, r.url.path) for r in api.requests] == [("GET", f"/v1{path}")]

    @pytest.mark.parametrize(
        ("name", "path", "key", "value", "status", "_op"), _TOGGLES
    )
    @pytest.mark.parametrize("other", ["archived", "same", None, "brand_new"])
    async def test_no_reversal_from_any_other_status(  # noqa: PLR0913
        self,
        api: FakeAPI,
        name: str,
        path: str,
        key: str,
        value: str,
        status: str,
        _op: str,
        other: str | None,
    ) -> None:
        # "same" = the entity already sits in the state the call asks for.
        prior = (
            ("paused" if status == "active" else "active") if other == "same" else other
        )
        api.add(path, body={"id": value, "status": prior})
        assert await _capture(name, {key: value}) is None

    @pytest.mark.parametrize(
        ("name", "path", "arguments"),
        [
            ("chatgpt_ads_ads_pause", "/ads/a_1", {"ad_id": "a_1"}),
            (
                "chatgpt_ads_campaigns_update",
                "/campaigns/c_1",
                {"campaign_id": "c_1", "name": "New"},
            ),
            (
                "chatgpt_ads_campaigns_update_budget",
                "/campaigns/c_1",
                {"campaign_id": "c_1", "budget": {"daily_spend_limit_micros": 1}},
            ),
            (
                "chatgpt_ads_ad_groups_update",
                "/ad_groups/g_1",
                {"ad_group_id": "g_1", "name": "New"},
            ),
            (
                "chatgpt_ads_ad_groups_update_bid",
                "/ad_groups/g_1",
                {"ad_group_id": "g_1", "bidding_config": {}},
            ),
            (
                "chatgpt_ads_account_daily_spend_limit_set",
                "/ad_account/spend_limit_windows",
                {"amount_micros": 1},
            ),
        ],
    )
    async def test_a_non_object_answer_records_nothing(
        self, api: FakeAPI, name: str, path: str, arguments: dict[str, Any]
    ) -> None:
        api.add(path, body=["active"])
        assert await _capture(name, arguments) is None


class TestCampaignUpdate:
    async def test_each_field_the_call_sets_gets_its_prior_value(
        self, api: FakeAPI
    ) -> None:
        api.add(
            "/campaigns/c_1",
            body={
                "id": "c_1",
                "name": "Old name",
                "start_time": 1_700_000_000,
                "end_time": None,
                "budget": {"daily_spend_limit_micros": 5_000_000},
            },
        )
        found = await _capture(
            "chatgpt_ads_campaigns_update",
            {"campaign_id": "c_1", "name": "New", "end_time": 1_900_000_000},
            restores={"name": "Old name", "end_time": None},
        )
        assert found == {
            "operation": "chatgpt_ads_campaigns_update",
            "params": {"campaign_id": "c_1", "name": "Old name", "end_time": None},
        }

    async def test_an_unreadable_field_is_a_caveat(self, api: FakeAPI) -> None:
        api.add("/campaigns/c_1", body={"id": "c_1", "name": "Old name"})
        found = await _capture(
            "chatgpt_ads_campaigns_update",
            {"campaign_id": "c_1", "name": "New", "start_time": 1_800_000_000},
            restores={"name": "Old name"},
        )
        assert found is not None
        assert found["params"] == {"campaign_id": "c_1", "name": "Old name"}
        assert len(found["caveats"]) == 1
        assert "start_time" in found["caveats"][0]

    @pytest.mark.parametrize(
        "prior",
        [
            {"name": 5, "start_time": "soon"},
            {"name": "ab"},
            {"name": "Old\nname"},
            {"start_time": True},
            {},
        ],
    )
    async def test_nothing_readable_records_nothing(
        self, api: FakeAPI, prior: dict[str, Any]
    ) -> None:
        api.add("/campaigns/c_1", body={"id": "c_1", **prior})
        found = await _capture(
            "chatgpt_ads_campaigns_update",
            {"campaign_id": "c_1", "name": "New", "start_time": 1_800_000_000},
        )
        assert found is None


class TestCampaignBudget:
    async def test_the_prior_budget_reduced_to_the_known_keys(
        self, api: FakeAPI
    ) -> None:
        api.add(
            "/campaigns/c_1",
            body={
                "id": "c_1",
                "budget": {
                    "daily_spend_limit_micros": 50_000_000,
                    "lifetime_spend_limit_micros": None,
                    "locations": {"countries": ["US"]},
                },
            },
        )
        found = await _capture(
            "chatgpt_ads_campaigns_update_budget",
            {"campaign_id": "c_1", "budget": {"daily_spend_limit_micros": 75_000_000}},
            restores={"budget": {"daily_spend_limit_micros": 50_000_000}},
        )
        assert found == {
            "operation": "chatgpt_ads_campaigns_update_budget",
            "params": {
                "campaign_id": "c_1",
                "budget": {"daily_spend_limit_micros": 50_000_000},
            },
        }

    async def test_lowering_a_lifetime_budget_carries_the_caveat(
        self, api: FakeAPI
    ) -> None:
        api.add(
            "/campaigns/c_1",
            body={"budget": {"lifetime_spend_limit_micros": 100_000_000}},
        )
        found = await _capture(
            "chatgpt_ads_campaigns_update_budget",
            {
                "campaign_id": "c_1",
                "budget": {"lifetime_spend_limit_micros": 300_000_000},
            },
            restores={"budget": {"lifetime_spend_limit_micros": 100_000_000}},
        )
        assert found is not None
        assert found["params"]["budget"] == {"lifetime_spend_limit_micros": 100_000_000}
        assert found["caveats"] == [_LIFETIME_CAVEAT]

    async def test_raising_a_lifetime_budget_back_carries_none(
        self, api: FakeAPI
    ) -> None:
        api.add(
            "/campaigns/c_1",
            body={"budget": {"lifetime_spend_limit_micros": 300_000_000}},
        )
        found = await _capture(
            "chatgpt_ads_campaigns_update_budget",
            {
                "campaign_id": "c_1",
                "budget": {"lifetime_spend_limit_micros": 100_000_000},
            },
            restores={"budget": {"lifetime_spend_limit_micros": 300_000_000}},
        )
        assert found is not None and "caveats" not in found

    @pytest.mark.parametrize(
        "prior",
        [
            {"budget": {}},
            {"budget": {"daily_spend_limit_micros": 0}},
            {"budget": {"daily_spend_limit_micros": True}},
            {"budget": {"daily_spend_limit_micros": "5"}},
            {"budget": None},
            {},
        ],
    )
    async def test_no_readable_budget_records_nothing(
        self, api: FakeAPI, prior: dict[str, Any]
    ) -> None:
        api.add("/campaigns/c_1", body=prior)
        found = await _capture(
            "chatgpt_ads_campaigns_update_budget",
            {"campaign_id": "c_1", "budget": {"daily_spend_limit_micros": 75_000_000}},
        )
        assert found is None


class TestAdGroupUpdates:
    async def test_rename_restores_the_prior_name(self, api: FakeAPI) -> None:
        api.add("/ad_groups/g_1", body={"id": "g_1", "name": "Old group"})
        found = await _capture(
            "chatgpt_ads_ad_groups_update",
            {"ad_group_id": "g_1", "name": "New"},
            restores={"name": "Old group"},
        )
        assert found == {
            "operation": "chatgpt_ads_ad_groups_update",
            "params": {"ad_group_id": "g_1", "name": "Old group"},
        }

    async def test_an_unreadable_name_records_nothing(self, api: FakeAPI) -> None:
        api.add("/ad_groups/g_1", body={"id": "g_1"})
        found = await _capture(
            "chatgpt_ads_ad_groups_update", {"ad_group_id": "g_1", "name": "New"}
        )
        assert found is None

    @pytest.mark.parametrize(
        ("prior", "restored"),
        [
            (
                {
                    "billing_event_type": "click",
                    "strategy": "fixed_bid",
                    "max_bid_micros": 2_000_000,
                    "custom_audience_bid_multipliers": [
                        {
                            "custom_audience_id": "aud_1",
                            "bid_multiplier_micros": 1_500_000,
                        }
                    ],
                },
                {
                    "billing_event_type": "click",
                    "strategy": "fixed_bid",
                    "max_bid_micros": 2_000_000,
                    "custom_audience_bid_multipliers": [
                        {
                            "custom_audience_id": "aud_1",
                            "bid_multiplier_micros": 1_500_000,
                        }
                    ],
                },
            ),
            (
                {
                    "billing_event_type": "impression",
                    "strategy": "automated_bid",
                    "max_bid_micros": 60_000,
                    "custom_audience_bid_multipliers": [],
                },
                # An empty list is restored as one: it is the prior state.
                {
                    "billing_event_type": "impression",
                    "custom_audience_bid_multipliers": [],
                },
            ),
            (
                {"billing_event_type": "click", "max_bid_micros": 3_000_000},
                {"billing_event_type": "click", "max_bid_micros": 3_000_000},
            ),
            (
                # A null value is absent; a key the request does not know is
                # a response-only field and is not restored.
                {
                    "billing_event_type": "click",
                    "strategy": "maximize_clicks",
                    "max_bid_micros": None,
                    "brand_new": 1,
                },
                {"billing_event_type": "click", "strategy": "maximize_clicks"},
            ),
        ],
    )
    async def test_bid_restores_the_prior_config_in_request_shape(
        self, api: FakeAPI, prior: dict[str, Any], restored: dict[str, Any]
    ) -> None:
        api.add("/ad_groups/g_1", body={"id": "g_1", "bidding_config": prior})
        found = await _capture(
            "chatgpt_ads_ad_groups_update_bid",
            {"ad_group_id": "g_1", "bidding_config": {"billing_event_type": "click"}},
            restores={"bidding_config": restored},
        )
        assert found == {
            "operation": "chatgpt_ads_ad_groups_update_bid",
            "params": {"ad_group_id": "g_1", "bidding_config": restored},
        }

    @pytest.mark.parametrize(
        "prior",
        [
            {"bidding_config": {"strategy": "fixed_bid", "max_bid_micros": 5}},
            {"bidding_config": {"billing_event_type": "brand_new_event"}},
            {"bidding_config": {"billing_event_type": "click", "strategy": "new_one"}},
            {"bidding_config": {"billing_event_type": "click", "max_bid_micros": 0}},
            {"bidding_config": "click"},
            {},
        ],
    )
    async def test_an_unmappable_bid_records_nothing(
        self, api: FakeAPI, prior: dict[str, Any]
    ) -> None:
        api.add("/ad_groups/g_1", body=prior)
        found = await _capture(
            "chatgpt_ads_ad_groups_update_bid",
            {"ad_group_id": "g_1", "bidding_config": {"billing_event_type": "click"}},
        )
        assert found is None


class TestAccountDailySpendLimit:
    async def test_one_daily_rule_is_restored(self, api: FakeAPI) -> None:
        api.add(
            "/ad_account/spend_limit_windows",
            body={"daily_limits": [{"amount_micros": 40_000_000}], "revision": 3},
        )
        found = await _capture(
            "chatgpt_ads_account_daily_spend_limit_set",
            {"amount_micros": 9},
            restores={"amount_micros": 40_000_000, "expected_revision": 0},
        )
        assert found == {
            "operation": "chatgpt_ads_account_daily_spend_limit_set",
            "params": {"amount_micros": 40_000_000},
        }

    async def test_the_single_field_is_read_without_the_array(
        self, api: FakeAPI
    ) -> None:
        api.add(
            "/ad_account/spend_limit_windows",
            body={"daily_limit": {"amount_micros": 0}},
        )
        found = await _capture(
            "chatgpt_ads_account_daily_spend_limit_set",
            {"amount_micros": 9},
            restores={"amount_micros": 0, "expected_revision": 0},
        )
        assert found is not None and found["params"] == {"amount_micros": 0}

    @pytest.mark.parametrize(
        "windows",
        [
            {"daily_limit": None},
            {"daily_limits": []},
            {"daily_limits": [{"amount_micros": 1}, {"amount_micros": 2}]},
            {"daily_limits": [{"amount_micros": "1"}]},
            {"daily_limits": [{"amount_micros": True}]},
            {"daily_limits": "x"},
        ],
    )
    async def test_none_or_several_rules_record_nothing(
        self, api: FakeAPI, windows: dict[str, Any]
    ) -> None:
        api.add("/ad_account/spend_limit_windows", body=windows)
        found = await _capture(
            "chatgpt_ads_account_daily_spend_limit_set", {"amount_micros": 9}
        )
        assert found is None


class TestFailureRules:
    @pytest.mark.parametrize(
        "name",
        [
            "chatgpt_ads_campaigns_get",
            "chatgpt_ads_account_spend_limits_get",
            "chatgpt_ads_insights_report",
            "chatgpt_ads_nope",
        ],
    )
    async def test_reads_and_unknown_names_send_nothing(
        self, api: FakeAPI, name: str
    ) -> None:
        assert await _capture(name, {"campaign_id": "c_1"}) is None
        assert api.requests == []

    async def test_no_key_sends_nothing(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CHATGPT_ADS_API_KEY")
        assert await _capture("chatgpt_ads_ads_pause", {"ad_id": "a_1"}) is None
        assert api.requests == []

    @pytest.mark.parametrize(
        ("status", "body"),
        [(401, {"error": {"message": "bad"}}), (404, {}), (500, "boom")],
    )
    async def test_a_failed_read_records_nothing_and_logs_only_the_type(
        self,
        api: FakeAPI,
        caplog: pytest.LogCaptureFixture,
        status: int,
        body: Any,
    ) -> None:
        api.add("/ads/a_1", status, body)
        caplog.set_level(logging.DEBUG)
        assert await _capture("chatgpt_ads_ads_pause", {"ad_id": "a_1"}) is None
        records = [r for r in caplog.records if r.name == reversal.__name__]
        assert len(records) == 1
        assert records[0].exc_info is None
        text = records[0].getMessage()
        assert "chatgpt_ads_ads_pause" in text
        assert "Error" in text
        assert "a_1" not in text and "bad" not in text and "boom" not in text
        assert SENTINEL_KEY not in caplog.text

    async def test_an_invalid_id_records_nothing(self, api: FakeAPI) -> None:
        assert await _capture("chatgpt_ads_ads_pause", {"ad_id": "../x"}) is None
        assert api.requests == []

    async def test_the_read_runs_under_the_capture_deadline(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[float] = []

        async def _slow(_client: Any, _arguments: dict[str, Any]) -> Any:
            await asyncio.sleep(10)

        real_run_tool = handlers.run_tool

        async def _spy(
            name: str, arguments: dict[str, Any], key: str, **kw: Any
        ) -> Any:
            seen.append(kw["deadline"])
            return await real_run_tool(name, arguments, key, deadline=0.01)

        monkeypatch.setitem(handlers.HANDLERS, "chatgpt_ads_ads_get", _slow)
        monkeypatch.setattr(reversal, "run_tool", _spy)
        assert await _capture("chatgpt_ads_ads_pause", {"ad_id": "a_1"}) is None
        assert seen == [REVERSAL_READ_DEADLINE_SECONDS]

    @pytest.mark.parametrize("stop", [asyncio.CancelledError, KeyboardInterrupt])
    async def test_a_stop_is_re_raised(
        self,
        api: FakeAPI,
        monkeypatch: pytest.MonkeyPatch,
        stop: type[BaseException],
    ) -> None:
        async def _stop(*_a: Any, **_k: Any) -> Any:
            raise stop

        monkeypatch.setattr(reversal, "run_tool", _stop)
        with pytest.raises(stop):
            await _capture("chatgpt_ads_ads_pause", {"ad_id": "a_1"})

    async def test_any_other_exception_records_nothing(
        self,
        api: FakeAPI,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        async def _boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError(f"leak {SENTINEL_KEY}")

        monkeypatch.setattr(reversal, "run_tool", _boom)
        caplog.set_level(logging.DEBUG)
        assert await _capture("chatgpt_ads_ads_pause", {"ad_id": "a_1"}) is None
        assert "RuntimeError" in caplog.text
        assert SENTINEL_KEY not in caplog.text
        assert "leak" not in caplog.text


# ---------------------------------------------------------------------------
# Through the server, the planner and the rollback executor
# ---------------------------------------------------------------------------


def _no_thirdparty(**_kw: Any) -> tuple[()]:
    return ()


async def _dispatch_and_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: FakeAPI, name: str,
    arguments: dict[str, Any],
) -> tuple[Any, Any, Any]:  # fmt: skip
    """Dispatch ``name`` through a fresh server, then plan and apply its
    rollback through the same server. Returns (entry, plan, apply result)."""
    write_state_file(tmp_path / "STATE.json", StateDocument())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(plugin_audit, "_audit_path", lambda: tmp_path / "audit.jsonl")
    with reloaded_server(
        _no_thirdparty, patches={"mureo.core.providers.default_registry._entries": {}}
    ) as mod:
        await mod.handle_call_tool(name, arguments)
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        plan = plan_rollback(entry)
        applied = await execute_rollback(
            state_file=tmp_path / "STATE.json",
            index=0,
            confirm=True,
            dispatcher=mod.handle_call_tool,
        )
    return entry, plan, applied


@pytest.mark.integration
class TestEndToEndRollback:
    async def test_a_pause_is_rolled_back_by_enable(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        api.add("/campaigns/c_1", body={"id": "c_1", "status": "active"})
        api.add("/campaigns/c_1/pause", body={"id": "c_1", "status": "paused"})
        api.add("/campaigns/c_1/activate", body={"id": "c_1", "status": "active"})
        entry, plan, applied = await _dispatch_and_plan(
            tmp_path, monkeypatch, api, "chatgpt_ads_campaigns_pause",
            {"campaign_id": "c_1"},
        )  # fmt: skip
        assert entry.platform == "plugin:mureo-chatgpt-ads:chatgpt_ads"
        assert entry.campaign_id == "c_1"
        assert entry.reversible_params == {
            "operation": "chatgpt_ads_campaigns_enable",
            "params": {"campaign_id": "c_1"},
        }
        assert plan.status is RollbackStatus.SUPPORTED
        assert applied["status"] == "applied"
        assert applied["dispatched_tool"] == "chatgpt_ads_campaigns_enable"
        assert [(r.method, r.url.path) for r in api.requests] == [
            ("GET", "/v1/campaigns/c_1"),
            ("POST", "/v1/campaigns/c_1/pause"),
            # The reversal is itself a mutation, so it captures its own prior.
            ("GET", "/v1/campaigns/c_1"),
            ("POST", "/v1/campaigns/c_1/activate"),
        ]

    async def test_a_budget_edit_is_rolled_back_with_the_prior_budget(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        prior = {"daily_spend_limit_micros": 50_000_000}
        for _ in range(4):
            api.add("/campaigns/c_1", body={"id": "c_1", "budget": prior})
        entry, plan, applied = await _dispatch_and_plan(
            tmp_path, monkeypatch, api, "chatgpt_ads_campaigns_update_budget",
            {"campaign_id": "c_1", "budget": {"daily_spend_limit_micros": 75_000_000}},
        )  # fmt: skip
        assert plan.status is RollbackStatus.SUPPORTED
        assert plan.params == {"campaign_id": "c_1", "budget": prior}
        assert applied["dispatched_tool"] == "chatgpt_ads_campaigns_update_budget"
        posts = [r for r in api.requests if r.method == "POST"]
        assert [json.loads(r.content) for r in posts] == [
            {"budget": {"daily_spend_limit_micros": 75_000_000}},
            {"budget": prior},
        ]

    async def test_a_partial_capture_plans_partial(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        for _ in range(4):
            api.add("/campaigns/c_1", body={"id": "c_1", "name": "Old name"})
        entry, plan, applied = await _dispatch_and_plan(
            tmp_path, monkeypatch, api, "chatgpt_ads_campaigns_update",
            {"campaign_id": "c_1", "name": "New", "start_time": 1_800_000_000},
        )  # fmt: skip
        assert plan.status is RollbackStatus.PARTIAL
        assert plan.params == {"campaign_id": "c_1", "name": "Old name"}
        assert any("start_time" in c for c in plan.caveats)
        assert applied["status"] == "applied"
        last = [r for r in api.requests if r.method == "POST"][-1]
        assert json.loads(last.content) == {"name": "Old name"}

    async def test_a_platform_failure_lands_nothing(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        api.add("/ads/a_1", body={"id": "a_1", "status": "active"})
        api.add("/ads/a_1/pause", 500, {"error": {"message": "boom"}})
        write_state_file(tmp_path / "STATE.json", StateDocument())
        monkeypatch.chdir(tmp_path)
        with reloaded_server(
            _no_thirdparty,
            patches={"mureo.core.providers.default_registry._entries": {}},
        ) as mod:
            out = await mod.handle_call_tool("chatgpt_ads_ads_pause", {"ad_id": "a_1"})
        assert out[0].text.startswith("API error:")
        assert read_state_file(tmp_path / "STATE.json").action_log == ()
