"""Tests for the built-in strategy policy gate (mureo.policy.strategy_gate)."""

from __future__ import annotations

import pytest

from mureo.policy.strategy_gate import (
    Guardrails,
    StrategyPolicyGate,
    evaluate_guardrails,
    guardrails_from_strategy_text,
    parse_guardrails,
)

pytestmark = pytest.mark.unit


class TestParseGuardrails:
    def test_parses_all_known_keys(self) -> None:
        g = parse_guardrails(
            "- max_daily_budget_per_campaign: 50,000\n"
            "- max_daily_budget_increase_pct: 20\n"
            "- max_total_daily_budget: 300000\n"
            "- blocked_operations: google_ads_campaigns_remove, meta_ads_x\n"
        )
        assert g.max_daily_budget_per_campaign == 50000
        assert g.max_daily_budget_increase_pct == 20
        assert g.max_total_daily_budget == 300000
        assert g.blocked_operations == frozenset(
            {"google_ads_campaigns_remove", "meta_ads_x"}
        )

    def test_unknown_keys_ignored_and_empty_when_none(self) -> None:
        assert parse_guardrails("- some_future_rule: 5\nprose line").is_empty()

    def test_malformed_number_drops_only_that_rule(self) -> None:
        g = parse_guardrails(
            "- max_daily_budget_per_campaign: abc\n- max_total_daily_budget: 100"
        )
        assert g.max_daily_budget_per_campaign is None
        assert g.max_total_daily_budget == 100

    def test_extracts_section_from_full_strategy_text(self) -> None:
        text = (
            "## Persona\nSMB owners\n\n"
            "## Guardrails\n- max_daily_budget_per_campaign: 50000\n\n"
            "## Operation Mode\nEFFICIENCY_STABILIZE\n"
        )
        assert (
            guardrails_from_strategy_text(text).max_daily_budget_per_campaign == 50000
        )

    def test_no_section_is_empty(self) -> None:
        assert guardrails_from_strategy_text("## Persona\nx").is_empty()


class TestEvaluateGuardrails:
    def test_empty_guardrails_always_allow(self) -> None:
        d = evaluate_guardrails(
            "google_ads_budget_update", {"daily_budget": 9_999_999}, Guardrails()
        )
        assert d.allowed is True

    def test_absolute_cap_denies(self) -> None:
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails("google_ads_budget_update", {"daily_budget": 80000}, g)
        assert d.allowed is False
        assert "50,000" in d.reason and "80,000" in d.reason

    def test_under_cap_allows(self) -> None:
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails("google_ads_budget_update", {"daily_budget": 40000}, g)
        assert d.allowed is True

    def test_micros_budget_converted(self) -> None:
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "google_ads_budget_update", {"budget_amount_micros": 80_000_000_000}, g
        )
        assert d.allowed is False  # 80,000 > 50,000

    def test_increase_pct_denies(self) -> None:
        g = Guardrails(max_daily_budget_increase_pct=20)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 15000, "current_daily_budget": 10000},
            g,
        )
        assert d.allowed is False

    def test_increase_within_pct_allows(self) -> None:
        g = Guardrails(max_daily_budget_increase_pct=20)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 11000, "current_daily_budget": 10000},
            g,
        )
        assert d.allowed is True

    def test_blocked_operation_denies(self) -> None:
        g = Guardrails(blocked_operations=frozenset({"google_ads_campaigns_remove"}))
        d = evaluate_guardrails("google_ads_campaigns_remove", {"campaign_id": "1"}, g)
        assert d.allowed is False

    def test_total_cap_denies_when_projected_provided(self) -> None:
        g = Guardrails(max_total_daily_budget=300000)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 10000, "projected_total_daily_budget": 350000},
            g,
        )
        assert d.allowed is False

    def test_non_budget_tool_with_budget_cap_allows(self) -> None:
        # A status change carries no budget → the budget cap does not apply.
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "google_ads_campaigns_update_status", {"status": "ENABLED"}, g
        )
        assert d.allowed is True


class TestStrategyPolicyGate:
    def test_conforms_to_policy_gate_protocol(self) -> None:
        from mureo.core.policy import PolicyGate

        assert isinstance(StrategyPolicyGate(), PolicyGate)

    def test_fail_open_when_no_strategy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mureo.policy.strategy_gate as sg

        sg._cache.clear()
        monkeypatch.setattr(
            sg, "guardrails_from_strategy_text", lambda _t: Guardrails()
        )
        d = StrategyPolicyGate().evaluate(
            "google_ads_budget_update", {"daily_budget": 9_999_999}
        )
        assert d.allowed is True

    def test_enforces_loaded_guardrails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mureo.policy.strategy_gate as sg

        sg._cache.clear()
        monkeypatch.setattr(
            sg,
            "_load_guardrails",
            lambda: Guardrails(max_daily_budget_per_campaign=50000),
        )
        d = StrategyPolicyGate().evaluate(
            "google_ads_budget_update", {"daily_budget": 80000}
        )
        assert d.allowed is False


class TestDispatcherIntegration:
    """End-to-end: the built-in gate is consulted by handle_call_tool and can
    refuse a mutation before dispatch — with no third-party gate registered."""

    @pytest.mark.asyncio
    async def test_builtin_gate_refuses_over_cap_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mureo.policy.strategy_gate as sg
        from mureo.mcp.server import handle_call_tool

        sg._cache.clear()
        monkeypatch.setattr(
            sg,
            "_load_guardrails",
            lambda: Guardrails(max_daily_budget_per_campaign=50000),
        )
        # No entry-point gates; the built-in gate must still fire.
        monkeypatch.setattr("mureo.mcp.server._load_policy_gates", lambda: ())

        result = await handle_call_tool(
            "google_ads_budget_update",
            {"campaign_id": "111", "budget_id": "1", "daily_budget": 80000},
        )
        text = result[0].text
        assert "google_ads_budget_update" in text
        assert "50,000" in text  # the guardrail reason surfaced verbatim
        assert "refused" in text.lower() or "denied" in text.lower()

    # The fail-open allow path (no guardrails ⇒ dispatch proceeds) is covered by
    # the unit test_fail_open_when_no_strategy above and by
    # test_policy_gate.py::test_no_gates_registered_dispatches_as_today.
