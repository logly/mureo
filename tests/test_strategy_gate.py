"""Tests for the built-in strategy policy gate (mureo.policy.strategy_gate)."""

from __future__ import annotations

import re
from pathlib import Path

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
            "- max_lifetime_budget_per_campaign: 900000\n"
            "- blocked_operations: google_ads_campaigns_remove, meta_ads_x\n"
        )
        assert g.max_daily_budget_per_campaign == 50000
        assert g.max_daily_budget_increase_pct == 20
        assert g.max_total_daily_budget == 300000
        assert g.max_lifetime_budget_per_campaign == 900000
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

    def test_lifetime_cap_denies(self) -> None:
        """lifetime_budget is gate-covered so it cannot sidestep caps (#367)."""
        g = Guardrails(max_lifetime_budget_per_campaign=900000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "lifetime_budget": 1_000_000},
            g,
        )
        assert d.allowed is False
        assert "max_lifetime_budget_per_campaign" in d.reason

    def test_lifetime_under_cap_allows(self) -> None:
        g = Guardrails(max_lifetime_budget_per_campaign=900000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "lifetime_budget": 500000},
            g,
        )
        assert d.allowed is True

    def test_total_amount_micros_hits_lifetime_cap(self) -> None:
        """Google total (CUSTOM_PERIOD) budgets are lifetime-capped too (#366)."""
        g = Guardrails(max_lifetime_budget_per_campaign=900000)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"budget_id": "1", "total_amount_micros": 1_000_000_000_000},
            g,
        )
        assert d.allowed is False
        assert "max_lifetime_budget_per_campaign" in d.reason

    # A budget too large for a float64. Python ints are arbitrary precision, so
    # ``float(10**400)`` raises OverflowError, not a value the extractor floors —
    # and the handler downstream forwards the bare int happily. The gate must
    # saturate to inf (which exceeds any finite cap and denies), never let the
    # OverflowError bubble to StrategyPolicyGate.evaluate's blanket except, which
    # would abstain and wave the call through.
    _OVERSIZED_INT = int("9" * 309)

    def test_oversized_daily_budget_denies_not_abstains(self) -> None:
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update", {"daily_budget": self._OVERSIZED_INT}, g
        )
        assert d.allowed is False

    def test_oversized_micros_budget_denies(self) -> None:
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"budget_amount_micros": self._OVERSIZED_INT},
            g,
        )
        assert d.allowed is False

    def test_oversized_lifetime_budget_denies(self) -> None:
        g = Guardrails(max_lifetime_budget_per_campaign=900000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"lifetime_budget": self._OVERSIZED_INT},
            g,
        )
        assert d.allowed is False

    def test_oversized_int_reaches_the_gate_without_raising(self) -> None:
        """End-to-end: the bare-int overflow must not fall through evaluate()'s
        blanket except into a silent abstain."""
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "google_ads_budget_update", {"daily_budget": self._OVERSIZED_INT}, g
        )
        assert d.allowed is False

    def test_oversized_projected_total_denies(self) -> None:
        """The account-wide total cap funnels through the same saturation —
        a bare-int projected total must deny, not raise-then-abstain."""
        g = Guardrails(max_total_daily_budget=300000)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {
                "daily_budget": 10000,
                "projected_total_daily_budget": self._OVERSIZED_INT,
            },
            g,
        )
        assert d.allowed is False

    def test_oversized_current_does_not_neutralize_increase_pct(self) -> None:
        """An oversized ``current`` makes ``(proposed-current)/current`` a NaN
        that ``> cap`` reads as False. With only the pct cap configured, that
        would let an arbitrarily large proposed budget through — so a
        non-finite ``current`` must fail closed."""
        g = Guardrails(max_daily_budget_increase_pct=20)  # NO absolute cap
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"daily_budget": 5_000_000, "current_daily_budget": self._OVERSIZED_INT},
            g,
        )
        assert d.allowed is False

    @pytest.mark.parametrize(
        ("key", "guardrails"),
        [
            ("daily_budget", Guardrails(max_daily_budget_per_campaign=50000)),
            ("lifetime_budget", Guardrails(max_lifetime_budget_per_campaign=900000)),
            (
                "projected_total_daily_budget",
                Guardrails(max_total_daily_budget=300000),
            ),
        ],
    )
    def test_nan_budget_denies_not_abstains(
        self, key: str, guardrails: Guardrails
    ) -> None:
        """A bare ``NaN`` needs no overflow: ``nan > cap`` is always False, so
        without a guard it silently defeats the cap. ``json.loads`` accepts the
        ``NaN`` token, so this is wire-reachable. Non-finite ⇒ deny."""
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update", {key: float("nan")}, guardrails
        )
        assert d.allowed is False

    def test_nan_current_denies_not_abstains(self) -> None:
        g = Guardrails(max_daily_budget_increase_pct=20)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"daily_budget": 11000, "current_daily_budget": float("nan")},
            g,
        )
        assert d.allowed is False

    def test_total_amount_units_hits_lifetime_cap(self) -> None:
        """The currency-unit form total_amount cannot sidestep the cap."""
        g = Guardrails(max_lifetime_budget_per_campaign=900000)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"budget_id": "1", "total_amount": 1_000_000},
            g,
        )
        assert d.allowed is False
        assert "max_lifetime_budget_per_campaign" in d.reason

    def test_amount_micros_hits_daily_cap(self) -> None:
        """The micros form amount_micros cannot sidestep the daily cap."""
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"budget_id": "1", "amount_micros": 80_000_000_000},
            g,
        )
        assert d.allowed is False

    def test_total_amount_micros_under_lifetime_cap_allows(self) -> None:
        g = Guardrails(max_lifetime_budget_per_campaign=900000)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"budget_id": "1", "total_amount_micros": 500_000_000_000},
            g,
        )
        assert d.allowed is True

    def test_lifetime_budget_ignores_daily_cap(self) -> None:
        """Daily and lifetime caps have distinct semantics — no cross-check."""
        g = Guardrails(max_daily_budget_per_campaign=50000)
        d = evaluate_guardrails(
            "meta_ads_ad_sets_update",
            {"ad_set_id": "1", "lifetime_budget": 80000},
            g,
        )
        assert d.allowed is True

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


_REPO_ROOT = Path(__file__).resolve().parent.parent
_STRATEGY_SKILL = _REPO_ROOT / "skills" / "_mureo-strategy" / "SKILL.md"
_ONBOARD_SKILL = _REPO_ROOT / "skills" / "onboard" / "SKILL.md"


def _real_tool_names() -> frozenset[str]:
    """Every native Google/Meta MCP tool name the dispatcher can route.

    Imported straight from the ``TOOLS`` lists (not ``server._ALL_TOOLS``) so
    the set is independent of the ``MUREO_DISABLE_*`` env gating that can hide
    a platform's tools in some environments.
    """
    from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS
    from mureo.mcp.tools_meta_ads import TOOLS as META_ADS_TOOLS

    return frozenset(t.name for t in (*GOOGLE_ADS_TOOLS, *META_ADS_TOOLS))


class TestBlockedOperationsExamplesAreReal:
    """C4 regression: the ``blocked_operations`` tool names the skills recommend
    MUST exist in the real MCP tool registry.

    ``evaluate_guardrails`` blocks on an EXACT string match against the
    dispatched tool name, so a recommended example that names a non-existent
    tool (the original ``google_ads_campaigns_remove`` /
    ``meta_ads_campaigns_delete``) can never fire — the guardrail is silently
    dead. These tests couple the skill docs to the tool definitions so that
    drift is caught in CI rather than by a surprised operator.
    """

    #: Distinct single-purpose destructive tools the _mureo-strategy skill lists
    #: as good ``blocked_operations`` examples. Keep in sync with that skill.
    RECOMMENDED = (
        "google_ads_keywords_remove",
        "google_ads_conversions_remove",
        "google_ads_negative_keywords_remove",
        "meta_ads_audiences_delete",
        "meta_ads_catalogs_delete",
        "meta_ads_ad_rules_delete",
    )

    def test_copy_paste_example_line_names_only_real_tools(self) -> None:
        """The ``- blocked_operations: A, B`` example a user would copy-paste
        must reference only tools that actually exist."""
        real = _real_tool_names()
        text = _STRATEGY_SKILL.read_text(encoding="utf-8")
        m = re.search(r"^- blocked_operations:\s*(.+)$", text, re.MULTILINE)
        assert m is not None, "blocked_operations example bullet not found in skill"
        names = [n.strip() for n in m.group(1).split(",") if n.strip()]
        assert names, "example bullet lists no tool names"
        missing = [n for n in names if n not in real]
        assert not missing, (
            f"blocked_operations example names not in the MCP tool registry: "
            f"{missing}"
        )

    def test_recommended_examples_all_exist(self) -> None:
        real = _real_tool_names()
        missing = [n for n in self.RECOMMENDED if n not in real]
        assert not missing, f"recommended block examples do not exist: {missing}"

    def test_recommended_examples_are_cited_in_skill(self) -> None:
        """Guards the coupling the other direction: every name this test
        blesses is actually the one the skill recommends."""
        text = _STRATEGY_SKILL.read_text(encoding="utf-8")
        missing = [n for n in self.RECOMMENDED if n not in text]
        assert not missing, f"skill no longer cites recommended examples: {missing}"

    def test_note_documents_that_campaign_delete_tools_are_absent(self) -> None:
        """The design-limit note claims there is no standalone campaign-delete
        tool. Pin that the claim stays true and that the redirect target
        (``google_ads_campaigns_update_status``) really is the real tool."""
        real = _real_tool_names()
        assert "google_ads_campaigns_remove" not in real
        assert "meta_ads_campaigns_delete" not in real
        # The note tells operators campaign removal goes through this tool.
        assert "google_ads_campaigns_update_status" in real

    def test_onboard_offer_names_only_real_tools(self) -> None:
        """onboard's opt-in offer must not resurrect the phantom tool names."""
        real = _real_tool_names()
        text = _ONBOARD_SKILL.read_text(encoding="utf-8")
        m = re.search(r"`blocked_operations`.*?(?=\n     - |\n\d+\. |\Z)", text, re.S)
        assert m is not None, "blocked_operations offer not found in onboard skill"
        cited = set(re.findall(r"`(google_ads_[a-z_]+|meta_ads_[a-z_]+)`", m.group(0)))
        # The offer example tools must exist; the phantom names appear only in
        # the "there is no ..." clause, so assert the two we recommend exist and
        # the phantom pair is correctly described as absent.
        assert "google_ads_keywords_remove" in cited
        assert "meta_ads_audiences_delete" in cited
        for name in ("google_ads_keywords_remove", "meta_ads_audiences_delete"):
            assert name in real
        assert "google_ads_campaigns_remove" not in real
        assert "meta_ads_campaigns_delete" not in real
