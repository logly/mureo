"""What mureo's safety layer reads off the ChatGPT Ads mutation tools (#994).

Pinned here: the declarations the plugin safety layer derives (identity, the
micros budget and bid amounts), how the STRATEGY.md gate compares them with
the caps, the caller-supplied budget context keys, and what the
learning-period pre-flight and the change-import kind matcher say about these
tools today.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mureo.change_import.dedupe import action_kind
from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools_mutations import BUDGET_CONTEXT_KEYS, MUTATION_TOOLS
from mureo.core.tool_failure import failure_of
from mureo.mcp.plugin_semantics import derive_semantics
from mureo.policy.declaration_resolution import (
    _CONVENTION_CURRENT_KEY,
    _CONVENTION_TOTAL_KEY,
    _proposed_budget,
)
from mureo.policy.declarations import ArgumentPaths
from mureo.policy.learning_reset import classify_change
from mureo.policy.learning_rules import ResetRisk, rules_for_tool
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI, sent_body

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from mureo.policy.strategy_gate import StrategyPolicyGate

pytestmark = pytest.mark.unit

_BY_NAME = {t.name: t for t in MUTATION_TOOLS}

_STATUS_TOOLS = tuple(
    f"chatgpt_ads_{family}_{action}"
    for family in ("campaigns", "ad_groups", "ads")
    for action in ("pause", "enable")
)

_MUTATIONS = tuple(
    t.name for t in MUTATION_TOOLS if t.name != "chatgpt_ads_account_spend_limits_get"
)


class TestSemantics:
    @pytest.mark.parametrize(
        ("name", "campaign", "ad", "entity"),
        [
            ("chatgpt_ads_campaigns_pause", "campaign_id", None, None),
            ("chatgpt_ads_campaigns_enable", "campaign_id", None, None),
            ("chatgpt_ads_campaigns_update", "campaign_id", None, None),
            ("chatgpt_ads_campaigns_update_budget", "campaign_id", None, None),
            ("chatgpt_ads_ad_groups_pause", None, None, ("ad_group", "ad_group_id")),
            ("chatgpt_ads_ad_groups_enable", None, None, ("ad_group", "ad_group_id")),
            ("chatgpt_ads_ad_groups_update", None, None, ("ad_group", "ad_group_id")),
            (
                "chatgpt_ads_ad_groups_update_bid",
                None,
                None,
                ("ad_group", "ad_group_id"),
            ),
            ("chatgpt_ads_ads_pause", None, "ad_id", None),
            ("chatgpt_ads_ads_enable", None, "ad_id", None),
        ],
    )
    def test_identity(
        self,
        name: str,
        campaign: str | None,
        ad: str | None,
        entity: tuple[str, str] | None,
    ) -> None:
        identity = derive_semantics(_BY_NAME[name]).identity
        assert identity is not None
        assert identity.campaign_id_key == campaign
        assert identity.ad_id_key == ad
        assert (identity.entity_type, identity.entity_id_key) == (
            entity if entity else (None, None)
        )

    def test_money_declarations(self) -> None:
        budget = derive_semantics(_BY_NAME["chatgpt_ads_campaigns_update_budget"])
        assert budget.budget is not None and budget.budget.micros is True
        assert budget.budget.daily_key == ArgumentPaths.parse(
            "budget.daily_spend_limit_micros"
        )
        assert budget.budget.lifetime_key == ArgumentPaths.parse(
            "budget.lifetime_spend_limit_micros"
        )
        assert budget.budget.current_key is None
        bid = derive_semantics(_BY_NAME["chatgpt_ads_ad_groups_update_bid"])
        assert bid.bid is not None and bid.bid.micros is True
        assert bid.bid.cpc_bid_key == ArgumentPaths.parse(
            "bidding_config.max_bid_micros"
        )
        account = derive_semantics(
            _BY_NAME["chatgpt_ads_account_daily_spend_limit_set"]
        )
        assert account.budget is not None and account.budget.micros is True
        assert account.budget.daily_key == "amount_micros"
        assert account.identity is None

    def test_the_built_in_scan_reads_amount_micros_as_a_daily_budget(self) -> None:
        # Why the account limit is declared: without a declaration the gate's
        # built-in scan holds ``amount_micros`` to the daily cap all the same.
        assert _proposed_budget({"amount_micros": 150_000_000}) == 150

    def test_the_context_keys_are_the_gate_convention(self) -> None:
        assert BUDGET_CONTEXT_KEYS == (_CONVENTION_CURRENT_KEY, _CONVENTION_TOTAL_KEY)
        schema = _BY_NAME["chatgpt_ads_campaigns_update_budget"].inputSchema
        for key in BUDGET_CONTEXT_KEYS:
            prop = schema["properties"][key]
            assert (prop["type"], prop["minimum"]) == ("number", 0)
            assert "NOT micros" in prop["description"]
            assert key not in schema["required"]

    @pytest.mark.parametrize(
        "name",
        [
            "chatgpt_ads_campaigns_update",
            "chatgpt_ads_ad_groups_update",
            *_STATUS_TOOLS,
        ],
    )
    def test_tools_that_move_no_money_declare_none(self, name: str) -> None:
        semantics = derive_semantics(_BY_NAME[name])
        assert semantics.budget is None and semantics.bid is None

    @pytest.mark.parametrize(
        ("name", "kind"),
        [
            *((name, "status") for name in _STATUS_TOOLS),
            ("chatgpt_ads_campaigns_update_budget", "budget"),
            ("chatgpt_ads_ad_groups_update_bid", "bid"),
            ("chatgpt_ads_campaigns_update", "campaign"),
            ("chatgpt_ads_ad_groups_update", "ad_group"),
            ("chatgpt_ads_account_daily_spend_limit_set", ""),
        ],
    )
    def test_change_import_reads_the_kind_off_the_name(
        self, name: str, kind: str
    ) -> None:
        assert action_kind(name) == kind

    @pytest.mark.parametrize("name", _MUTATIONS)
    def test_no_learning_rules_are_registered_today(self, name: str) -> None:
        assert rules_for_tool(name) is None
        assessment = classify_change(name, {})
        assert assessment.risk is ResetRisk.UNKNOWN
        assert assessment.platform == ""


_GUARDRAILS = (
    "## Guardrails\n"
    "- max_daily_budget_per_campaign: 100\n"
    "- max_lifetime_budget_per_campaign: 1000\n"
    "- max_cpc_bid_per_ad_group: 5\n"
    "- max_daily_budget_increase_pct: 20\n"
    "- max_total_daily_budget: 500\n"
)


@pytest.fixture()
def _clean_registries() -> Iterator[None]:
    """Save and restore the process-global declaration registries, the way
    the other declaration suites isolate them."""
    import mureo.policy.strategy_gate as sg
    from mureo.core.runtime_context import reset_runtime_context
    from mureo.policy.declarations import _BID_DECLARATIONS, _BUDGET_DECLARATIONS
    from mureo.policy.pattern_scan import (
        _PATTERN_FALLBACK_TOOLS,
        reset_pattern_fallback_tools,
    )
    from mureo.policy.strategy_gate import (
        reset_bid_declarations,
        reset_budget_declarations,
    )

    saved = (
        dict(_BUDGET_DECLARATIONS),
        dict(_BID_DECLARATIONS),
        set(_PATTERN_FALLBACK_TOOLS),
    )
    reset_budget_declarations()
    reset_bid_declarations()
    reset_pattern_fallback_tools()
    reset_runtime_context()
    sg._cache.clear()
    yield
    reset_budget_declarations()
    reset_bid_declarations()
    reset_pattern_fallback_tools()
    _BUDGET_DECLARATIONS.update(saved[0])
    _BID_DECLARATIONS.update(saved[1])
    _PATTERN_FALLBACK_TOOLS.update(saved[2])
    reset_runtime_context()
    sg._cache.clear()


@pytest.fixture()
def gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _clean_registries: None
) -> StrategyPolicyGate:
    from mureo.mcp.server import (
        _register_plugin_bid_declarations,
        _register_plugin_budget_declarations,
        _register_plugin_pattern_fallbacks,
    )
    from mureo.policy.strategy_gate import StrategyPolicyGate

    semantics = {t.name: derive_semantics(t) for t in MUTATION_TOOLS}
    _register_plugin_budget_declarations(semantics)
    _register_plugin_bid_declarations(semantics)
    _register_plugin_pattern_fallbacks(semantics)
    (tmp_path / "STRATEGY.md").write_text(_GUARDRAILS, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return StrategyPolicyGate()


def _daily(micros: int, **context: float) -> dict[str, Any]:
    return {
        "campaign_id": "c_1",
        "budget": {"daily_spend_limit_micros": micros},
        **context,
    }


def _bid(micros: int) -> dict[str, Any]:
    return {
        "ad_group_id": "g_1",
        "bidding_config": {"billing_event_type": "click", "max_bid_micros": micros},
    }


class TestStrategyGate:
    """Micros arguments are compared with the caps in currency units."""

    @pytest.mark.parametrize(
        ("name", "arguments", "allowed"),
        [
            ("chatgpt_ads_campaigns_update_budget", _daily(99_000_000), True),
            ("chatgpt_ads_campaigns_update_budget", _daily(101_000_000), False),
            (
                "chatgpt_ads_campaigns_update_budget",
                {
                    "campaign_id": "c_1",
                    "budget": {"lifetime_spend_limit_micros": 900_000_000},
                },
                True,
            ),
            (
                "chatgpt_ads_campaigns_update_budget",
                {
                    "campaign_id": "c_1",
                    "budget": {"lifetime_spend_limit_micros": 1_100_000_000},
                },
                False,
            ),
            ("chatgpt_ads_ad_groups_update_bid", _bid(4_000_000), True),
            ("chatgpt_ads_ad_groups_update_bid", _bid(6_000_000), False),
            (
                "chatgpt_ads_account_daily_spend_limit_set",
                {"amount_micros": 50_000_000},
                True,
            ),
            (
                "chatgpt_ads_account_daily_spend_limit_set",
                {"amount_micros": 150_000_000},
                False,
            ),
        ],
    )
    def test_caps(
        self,
        gate: StrategyPolicyGate,
        name: str,
        arguments: dict[str, Any],
        allowed: bool,
    ) -> None:
        assert gate.evaluate(name, arguments).allowed is allowed

    @pytest.mark.parametrize(
        ("context", "allowed", "cap"),
        [
            ({_CONVENTION_CURRENT_KEY: 75.0}, True, None),
            ({_CONVENTION_CURRENT_KEY: 50.0}, False, "max_daily_budget_increase_pct"),
            ({_CONVENTION_TOTAL_KEY: 480.0}, True, None),
            ({_CONVENTION_TOTAL_KEY: 520.0}, False, "max_total_daily_budget"),
        ],
    )
    def test_the_context_keys_reach_the_increase_and_total_caps(
        self,
        gate: StrategyPolicyGate,
        context: dict[str, float],
        allowed: bool,
        cap: str | None,
    ) -> None:
        # 80.00 a day: within the per-campaign cap, a 60% raise over 50.00,
        # a 6.7% raise over 75.00.
        decision = gate.evaluate(
            "chatgpt_ads_campaigns_update_budget", _daily(80_000_000, **context)
        )
        assert decision.allowed is allowed
        if cap is not None:
            assert cap in (decision.reason or "")


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = FakeAPI()
    monkeypatch.setenv("CHATGPT_ADS_API_KEY", SENTINEL_KEY)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: fake.client())
    return fake


class TestContextKeysAreNeverSent:
    async def test_the_request_body_carries_only_the_budget(self, api: FakeAPI) -> None:
        budget = {"daily_spend_limit_micros": 80_000_000}
        api.add("/campaigns/c_1", body={"id": "c_1", "budget": budget})
        context = {_CONVENTION_CURRENT_KEY: 75.0, _CONVENTION_TOTAL_KEY: 480}
        result = await ChatGPTAdsProvider().handle_mcp_tool(
            "chatgpt_ads_campaigns_update_budget", _daily(80_000_000, **context)
        )
        assert failure_of(result) is None, result[0].text
        assert json.loads(result[0].text) == {"id": "c_1", "budget": budget}
        assert [r.method for r in api.requests] == ["GET", "POST"]
        assert sent_body(api.requests[1]) == {"budget": budget}

    @pytest.mark.parametrize(
        "context",
        [
            {_CONVENTION_CURRENT_KEY: -1},
            {_CONVENTION_CURRENT_KEY: "75"},
            {_CONVENTION_TOTAL_KEY: True},
            {_CONVENTION_TOTAL_KEY: float("nan")},
        ],
        ids=["negative", "string", "bool", "nan"],
    )
    async def test_an_unusable_context_value_sends_nothing(
        self, api: FakeAPI, context: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                "chatgpt_ads_campaigns_update_budget", _daily(80_000_000, **context)
            )
        assert api.requests == []
