"""A recorded ChatGPT Ads reversal is one its tool accepts (#994).

A prior value the read returns can fail the check the reversal's tool runs on
its arguments: a string or float amount, a budget below the platform minimum,
an unknown bid strategy, a multiplier the tool would refuse, a name the tool
would refuse. Pinned here: each such prior records no reversal (or, for a
campaign update, leaves that field out with a caveat), every reversal that is
recorded passes the tool's schema and handler and sends the prior state, the
response-only ``automated_bid`` maps to the request's automatic bidding, a
fixed bid read back as ``target_cpc`` maps to the request's ``fixed_bid``, and
the multiplier count is bounded so one entry cannot grow STATE.json without
limit.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads.reversal import MAX_REVERSAL_MULTIPLIERS
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI
from tests._chatgpt_ads_reversal_check import capture_checked

pytestmark = pytest.mark.unit

_BUDGET = "chatgpt_ads_campaigns_update_budget"
_BID = "chatgpt_ads_ad_groups_update_bid"


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = FakeAPI()
    monkeypatch.setenv("CHATGPT_ADS_API_KEY", SENTINEL_KEY)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: fake.client())
    return fake


def _multipliers(count: int) -> list[dict[str, Any]]:
    return [
        {"custom_audience_id": f"aud_{i}", "bid_multiplier_micros": 1_000_000}
        for i in range(count)
    ]


class TestBudget:
    @pytest.mark.parametrize(
        "prior",
        [
            {"daily_spend_limit_micros": "50000000"},
            {"daily_spend_limit_micros": 50_000_000.0},
            {"daily_spend_limit_micros": 999_999},
            {"daily_spend_limit_micros": 0},
            {
                "daily_spend_limit_micros": 50_000_000,
                "lifetime_spend_limit_micros": "x",
            },
            {"daily_spend_limit_micros": 50_000_000, "lifetime_spend_limit_micros": 0},
        ],
        ids=[
            "string",
            "float",
            "below-minimum",
            "zero",
            "lifetime-string",
            "lifetime-0",
        ],
    )
    async def test_an_amount_the_tool_refuses_records_nothing(
        self, api: FakeAPI, prior: dict[str, Any]
    ) -> None:
        api.add("/campaigns/c_1", body={"id": "c_1", "budget": prior})
        arguments = {
            "campaign_id": "c_1",
            "budget": {"daily_spend_limit_micros": 75_000_000},
        }
        assert await capture_checked(_BUDGET, arguments) is None

    async def test_both_amounts_are_restored_together(self, api: FakeAPI) -> None:
        prior = {
            "daily_spend_limit_micros": 50_000_000,
            "lifetime_spend_limit_micros": 900_000_000,
        }
        api.add("/campaigns/c_1", body={"id": "c_1", "budget": prior})
        arguments = {
            "campaign_id": "c_1",
            "budget": {**prior, "daily_spend_limit_micros": 75_000_000},
        }
        found = await capture_checked(_BUDGET, arguments, restores={"budget": prior})
        assert found is not None and found["params"]["budget"] == prior

    async def test_the_context_keys_are_not_carried(self, api: FakeAPI) -> None:
        prior = {"daily_spend_limit_micros": 50_000_000}
        api.add("/campaigns/c_1", body={"id": "c_1", "budget": prior})
        arguments = {
            "campaign_id": "c_1",
            "budget": {"daily_spend_limit_micros": 75_000_000},
            "current_daily_budget": 50.0,
            "projected_total_daily_budget": 300.0,
        }
        found = await capture_checked(_BUDGET, arguments, restores={"budget": prior})
        assert found is not None
        assert found["params"] == {"campaign_id": "c_1", "budget": prior}


def _bid_prior(**config: Any) -> dict[str, Any]:
    return {"id": "g_1", "bidding_config": {"billing_event_type": "click", **config}}


class TestBid:
    @pytest.mark.parametrize(
        "config",
        [
            pytest.param(
                {"strategy": "brand_new_strategy", "max_bid_micros": 2_000_000},
                id="unknown-strategy-with-a-bid",
            ),
            pytest.param({"strategy": 7}, id="strategy-not-a-string"),
            pytest.param({"max_bid_micros": "2000000"}, id="bid-string"),
            pytest.param({"max_bid_micros": 2_000_000.0}, id="bid-float"),
            pytest.param(
                {
                    "custom_audience_bid_multipliers": [
                        {
                            "custom_audience_id": "aud_1",
                            "bid_multiplier_micros": 1_000_000,
                            "extra": 1,
                        }
                    ]
                },
                id="multiplier-extra-key",
            ),
            pytest.param(
                {
                    "custom_audience_bid_multipliers": [
                        {"custom_audience_id": "aud_1", "bid_multiplier_micros": 1}
                    ]
                },
                id="multiplier-below-range",
            ),
            pytest.param(
                {
                    "custom_audience_bid_multipliers": [
                        {
                            "custom_audience_id": "aud_1",
                            "bid_multiplier_micros": 10_000_001,
                        }
                    ]
                },
                id="multiplier-above-range",
            ),
            pytest.param(
                {"custom_audience_bid_multipliers": "aud_1"}, id="multipliers-string"
            ),
            pytest.param(
                {
                    "custom_audience_bid_multipliers": _multipliers(
                        MAX_REVERSAL_MULTIPLIERS + 1
                    )
                },
                id="one-multiplier-too-many",
            ),
        ],
    )
    async def test_a_value_the_tool_refuses_records_nothing(
        self, api: FakeAPI, config: dict[str, Any]
    ) -> None:
        api.add("/ad_groups/g_1", body=_bid_prior(**config))
        arguments = {
            "ad_group_id": "g_1",
            "bidding_config": {"billing_event_type": "click"},
        }
        assert await capture_checked(_BID, arguments) is None

    async def test_the_multiplier_bound_is_inclusive(self, api: FakeAPI) -> None:
        multipliers = _multipliers(MAX_REVERSAL_MULTIPLIERS)
        api.add(
            "/ad_groups/g_1",
            body=_bid_prior(custom_audience_bid_multipliers=multipliers),
        )
        restored = {
            "billing_event_type": "click",
            "custom_audience_bid_multipliers": multipliers,
        }
        arguments = {
            "ad_group_id": "g_1",
            "bidding_config": {"billing_event_type": "click"},
        }
        found = await capture_checked(
            _BID, arguments, restores={"bidding_config": restored}
        )
        assert found is not None

    def test_the_multiplier_bound(self) -> None:
        assert MAX_REVERSAL_MULTIPLIERS == 1000

    async def test_automated_bid_is_restored_as_automatic_bidding(
        self, api: FakeAPI
    ) -> None:
        api.add(
            "/ad_groups/g_1",
            body=_bid_prior(strategy="automated_bid", max_bid_micros=1_234_567),
        )
        arguments = {
            "ad_group_id": "g_1",
            "bidding_config": {"billing_event_type": "click"},
        }
        found = await capture_checked(
            _BID,
            arguments,
            restores={"bidding_config": {"billing_event_type": "click"}},
        )
        assert found is not None

    async def test_a_target_cpc_is_restored_as_a_fixed_bid(self, api: FakeAPI) -> None:
        api.add(
            "/ad_groups/g_1",
            body=_bid_prior(target_strategy="target_cpc", target_micros=2_000_000),
        )
        arguments = {
            "ad_group_id": "g_1",
            "bidding_config": {"billing_event_type": "click"},
        }
        restored = {
            "billing_event_type": "click",
            "strategy": "fixed_bid",
            "max_bid_micros": 2_000_000,
        }
        found = await capture_checked(
            _BID, arguments, restores={"bidding_config": restored}
        )
        assert found is not None


class TestNames:
    @pytest.mark.parametrize("name", ["Old\nname", "\nOld", "   ", "ab", 5], ids=repr)
    async def test_an_ad_group_name_the_tool_refuses_records_nothing(
        self, api: FakeAPI, name: object
    ) -> None:
        api.add("/ad_groups/g_1", body={"id": "g_1", "name": name})
        arguments = {"ad_group_id": "g_1", "name": "New"}
        assert await capture_checked("chatgpt_ads_ad_groups_update", arguments) is None

    async def test_a_campaign_name_the_tool_refuses_is_a_caveat(
        self, api: FakeAPI
    ) -> None:
        api.add(
            "/campaigns/c_1",
            body={"id": "c_1", "name": "Old\nname", "start_time": 1_700_000_000},
        )
        arguments = {"campaign_id": "c_1", "name": "New", "start_time": 1_800_000_000}
        found = await capture_checked(
            "chatgpt_ads_campaigns_update",
            arguments,
            restores={"start_time": 1_700_000_000},
        )
        assert found is not None
        assert found["params"] == {"campaign_id": "c_1", "start_time": 1_700_000_000}
        assert len(found["caveats"]) == 1 and found["caveats"][0].startswith("name")
