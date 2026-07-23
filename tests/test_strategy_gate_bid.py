"""Tests for bid-cap guardrails in the built-in strategy policy gate.

Covers the bid parameters that are separate from budgets: Meta's ad-set
``bid_amount`` (account-currency minor units) and Google's ad-group
``cpc_bid_micros`` (micros). A bid cap has distinct semantics from a budget
cap, so it gets its own guardrail field and its own key scan — a
``bid_constraints`` ROAS floor is NOT a spend amount and must not trip it.
"""

from __future__ import annotations

import json

import pytest

from mureo.policy.strategy_gate import (
    Guardrails,
    evaluate_guardrails,
    parse_guardrails,
)

pytestmark = pytest.mark.unit


class TestParseBidGuardrails:
    def test_parses_bid_amount_cap(self) -> None:
        g = parse_guardrails("- max_bid_amount_per_ad_set: 5000\n")
        assert g.max_bid_amount_per_ad_set == 5000

    def test_parses_cpc_bid_cap(self) -> None:
        g = parse_guardrails("- max_cpc_bid_per_ad_group: 100\n")
        assert g.max_cpc_bid_per_ad_group == 100

    def test_absent_bid_fields_are_none_and_empty(self) -> None:
        g = parse_guardrails("- max_daily_budget_per_campaign: 50000\n")
        assert g.max_bid_amount_per_ad_set is None
        assert g.max_cpc_bid_per_ad_group is None

    def test_only_bid_cap_is_not_empty(self) -> None:
        assert not parse_guardrails("- max_bid_amount_per_ad_set: 5000\n").is_empty()
        assert not parse_guardrails("- max_cpc_bid_per_ad_group: 100\n").is_empty()

    def test_malformed_bid_number_drops_only_that_rule(self) -> None:
        g = parse_guardrails(
            "- max_bid_amount_per_ad_set: abc\n- max_daily_budget_per_campaign: 100\n"
        )
        assert g.max_bid_amount_per_ad_set is None
        assert g.max_daily_budget_per_campaign == 100


class TestEvaluateBidAmountGuardrail:
    def test_bid_under_cap_allows(self) -> None:
        g = Guardrails(max_bid_amount_per_ad_set=5000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "bid_amount": 3000},
            g,
        )
        assert d.allowed is True

    def test_bid_over_cap_denies_and_names_guardrail(self) -> None:
        g = Guardrails(max_bid_amount_per_ad_set=5000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "bid_amount": 8000},
            g,
        )
        assert d.allowed is False
        assert "max_bid_amount_per_ad_set" in d.reason
        assert "5,000" in d.reason and "8,000" in d.reason

    def test_bid_over_cap_on_create_denies(self) -> None:
        g = Guardrails(max_bid_amount_per_ad_set=5000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_create",
            {"campaign_id": "1", "name": "x", "bid_amount": 8000},
            g,
        )
        assert d.allowed is False
        assert "max_bid_amount_per_ad_set" in d.reason

    def test_no_bid_cap_means_ungated(self) -> None:
        # Some OTHER cap is set so guardrails are non-empty, but no bid cap.
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "bid_amount": 9_999_999},
            g,
        )
        assert d.allowed is True

    def test_empty_guardrails_allow_high_bid(self) -> None:
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "bid_amount": 9_999_999},
            Guardrails(),
        )
        assert d.allowed is True

    def test_bid_constraints_dict_does_not_trip_bid_cap(self) -> None:
        """A ROAS floor is not a spend amount, so bid_constraints must not be
        read as a proposed bid_amount and must not trip the cap."""
        g = Guardrails(max_bid_amount_per_ad_set=5000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "bid_constraints": {"roas_average_floor": 9_999_999}},
            g,
        )
        assert d.allowed is True

    def test_oversized_bid_denies_not_abstains(self) -> None:
        """A bare int too large for float64 saturates to inf (which exceeds any
        finite cap) rather than raising into evaluate()'s blanket except."""
        g = Guardrails(max_bid_amount_per_ad_set=5000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "bid_amount": int("9" * 309)},
            g,
        )
        assert d.allowed is False


class TestEvaluateCpcBidGuardrail:
    def test_cpc_bid_under_cap_allows(self) -> None:
        g = Guardrails(max_cpc_bid_per_ad_group=100)
        d = evaluate_guardrails(
            "google_ads_ad_groups_update",
            {"ad_group_id": "1", "cpc_bid_micros": 50_000_000},  # 50 units
            g,
        )
        assert d.allowed is True

    def test_cpc_bid_over_cap_denies_and_names_guardrail(self) -> None:
        g = Guardrails(max_cpc_bid_per_ad_group=100)
        d = evaluate_guardrails(
            "google_ads_ad_groups_update",
            {"ad_group_id": "1", "cpc_bid_micros": 150_000_000},  # 150 units
            g,
        )
        assert d.allowed is False
        assert "max_cpc_bid_per_ad_group" in d.reason

    def test_cpc_bid_over_cap_on_create_denies(self) -> None:
        g = Guardrails(max_cpc_bid_per_ad_group=100)
        d = evaluate_guardrails(
            "google_ads_ad_groups_create",
            {"campaign_id": "1", "name": "x", "cpc_bid_micros": 150_000_000},
            g,
        )
        assert d.allowed is False
        assert "max_cpc_bid_per_ad_group" in d.reason

    def test_no_cpc_cap_means_ungated(self) -> None:
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "google_ads_ad_groups_update",
            {"ad_group_id": "1", "cpc_bid_micros": 999_000_000},
            g,
        )
        assert d.allowed is True

    def test_bid_modifier_does_not_trip_cpc_cap(self) -> None:
        """bid_modifier is a 0.1-10.0 multiplier (bid adjustment), not a spend
        amount, so it must not be read as a proposed CPC bid."""
        g = Guardrails(max_cpc_bid_per_ad_group=100)
        d = evaluate_guardrails(
            "google_ads_bid_adjustments_update",
            {"campaign_id": "1", "criterion_id": "2", "bid_modifier": 10.0},
            g,
        )
        assert d.allowed is True

    def test_oversized_cpc_bid_denies_not_abstains(self) -> None:
        g = Guardrails(max_cpc_bid_per_ad_group=100)
        d = evaluate_guardrails(
            "google_ads_ad_groups_update",
            {"ad_group_id": "1", "cpc_bid_micros": int("9" * 309)},
            g,
        )
        assert d.allowed is False


class TestBidNonFiniteFailsClosed:
    """A bare ``NaN`` / ``Infinity`` needs no overflow: ``nan > cap`` is always
    False, so without a fail-closed choke point it silently defeats the bid
    caps. ``json.loads`` accepts the ``NaN`` / ``Infinity`` tokens, and the gate
    runs before schema validation, so this is wire-reachable through JSON-RPC
    arguments. Non-finite on any capped bid channel ⇒ deny (mirrors the #419
    budget coverage). Args are built with ``json.loads`` to prove reachability.
    """

    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    @pytest.mark.parametrize(
        ("tool", "base"),
        [
            ("meta_ads_ad_sets_create", '{"campaign_id": "1", "name": "x"'),
            ("meta_ads_ad_sets_update", '{"ad_set_id": "1"'),
        ],
    )
    def test_non_finite_bid_amount_denies(
        self, tool: str, base: str, token: str
    ) -> None:
        args = json.loads(f'{base}, "bid_amount": {token}}}')
        g = Guardrails(max_bid_amount_per_ad_set=5000)
        d = evaluate_guardrails(tool, args, g)
        assert d.allowed is False
        assert "not a usable number" in d.reason

    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    @pytest.mark.parametrize(
        ("tool", "base"),
        [
            ("google_ads_ad_groups_create", '{"campaign_id": "1", "name": "x"'),
            ("google_ads_ad_groups_update", '{"ad_group_id": "1"'),
        ],
    )
    def test_non_finite_cpc_bid_denies(self, tool: str, base: str, token: str) -> None:
        # Non-finite must be caught POST micros->currency division, which is why
        # _bid_inputs checks math.isfinite on the divided value.
        args = json.loads(f'{base}, "cpc_bid_micros": {token}}}')
        g = Guardrails(max_cpc_bid_per_ad_group=100)
        d = evaluate_guardrails(tool, args, g)
        assert d.allowed is False
        assert "not a usable number" in d.reason
