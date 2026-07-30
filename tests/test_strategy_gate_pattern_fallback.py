"""Pattern fallback for declaration-less plugin mutations (audit #17/#18).

A plugin whose tools come from a manifest snapshot cannot carry mureo
``_meta`` declarations, so :class:`BudgetDeclaration` / :class:`BidDeclaration`
are unavailable to it and every ``## Guardrails`` budget/bid cap was silently
unenforced for its mutations — on a surface where real money moves.

This adds a conservative, best-effort pattern scan: for a MUTATING plugin tool
with no registered declaration, numeric arguments under budget-shaped /
bid-shaped key names are read as proposals and held to the same caps, with the
same fail-closed discipline and the same deny envelope as the built-in scan.
Exact-key declarations always take precedence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mureo.policy.pattern_scan import (
    has_pattern_fallback,
    is_bid_key,
    is_budget_key,
    register_pattern_fallback_tool,
    reset_pattern_fallback_tools,
    scan_bid_amount,
    scan_budget_amount,
)
from mureo.policy.strategy_gate import (
    BidDeclaration,
    BudgetDeclaration,
    Guardrails,
    evaluate_guardrails,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_CAPS = Guardrails(max_daily_budget_per_campaign=10_000)
_BID_CAPS = Guardrails(max_bid_amount_per_ad_set=500)


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Isolate the process-global fallback registry WITHOUT destroying it.

    ``mureo.mcp.server`` populates it once at import from real plugin
    discovery; a destructive clear would drop those registrations for the
    rest of the pytest session.
    """
    from mureo.policy.pattern_scan import _PATTERN_FALLBACK_TOOLS

    saved = set(_PATTERN_FALLBACK_TOOLS)
    reset_pattern_fallback_tools()
    yield
    reset_pattern_fallback_tools()
    _PATTERN_FALLBACK_TOOLS.update(saved)


# ---------------------------------------------------------------------------
# Key predicates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBudgetKeyPredicate:
    @pytest.mark.parametrize(
        "key",
        [
            "budget",
            "daily_budget",
            "dailyBudget",
            "BUDGET",
            "budget_amount_micros",
            "campaign_budget",
        ],
    )
    def test_budget_shaped_keys_match(self, key: str) -> None:
        assert is_budget_key(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "amount",
            "spend",
            # mureo's own caller-supplied convention keys are context, not a
            # proposal — reading them as one would deny a decrease.
            "current_daily_budget",
            "projected_total_daily_budget",
            # identifiers are never amounts
            "budget_id",
            "budget_ids",
            "budgetId",
        ],
    )
    def test_non_proposal_keys_do_not_match(self, key: str) -> None:
        assert is_budget_key(key) is False


@pytest.mark.unit
class TestBidKeyPredicate:
    @pytest.mark.parametrize(
        "key",
        [
            "bid",
            "bid_amount",
            "bidAmount",
            "default_bid",
            "maxBid",
            "cpc_bid_micros",
            "BID",
        ],
    )
    def test_bid_shaped_keys_match(self, key: str) -> None:
        assert is_bid_key(key) is True

    @pytest.mark.parametrize(
        "key",
        ["forbidden", "forbidden_zone", "budget", "morbidity", "bid_id", "bidId"],
    )
    def test_false_positives_are_excluded(self, key: str) -> None:
        assert is_bid_key(key) is False


# ---------------------------------------------------------------------------
# The scan itself
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScan:
    def test_absent_is_none(self) -> None:
        assert scan_budget_amount({"name": "x"}).value is None

    def test_reads_a_top_level_numeric(self) -> None:
        assert scan_budget_amount({"daily_budget": 250.0}).value == 250.0

    def test_reads_through_nested_dicts_and_lists(self) -> None:
        args = {"campaigns": [{"settings": {"dailyBudget": 400}}]}
        assert scan_budget_amount(args).value == 400

    def test_takes_the_maximum_of_several_matches(self) -> None:
        args = {"budget": 100, "nested": {"weekly_budget": 900}}
        assert scan_budget_amount(args).value == 900

    def test_micros_keys_are_scaled(self) -> None:
        assert scan_budget_amount({"budget_micros": 12_000_000}).value == 12.0

    def test_numeric_strings_are_read(self) -> None:
        assert scan_budget_amount({"daily_budget": "250"}).value == 250.0

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1,000", 1000.0),
            ("1,000,000", 1_000_000.0),
            ("1,234,567.89", 1_234_567.89),
            ("-2,500", -2500.0),
            ("  12,000  ", 12_000.0),
        ],
    )
    def test_comma_grouped_numeric_strings_are_read(
        self, text: str, expected: float
    ) -> None:
        """A form encoder / spreadsheet export groups its numerals; without
        this, a real budget read as 'no proposal' and sailed past the cap."""
        assert scan_budget_amount({"daily_budget": text}).value == expected
        assert scan_bid_amount({"bid_amount": text}).value == expected

    @pytest.mark.parametrize(
        "text",
        [
            # European decimal comma — reading this as 15 would be a 10x
            # over-read of a real-money figure, so ambiguous grouping is
            # ignored rather than guessed at.
            "1,5",
            "1,23",
            "12,34567",
            "1,000,00",
            ",000",
            "1,,000",
            "1,000,",
            "USD 1,000",
            "1,000 JPY",
        ],
    )
    def test_ambiguous_or_malformed_grouping_is_ignored(self, text: str) -> None:
        assert scan_budget_amount({"daily_budget": text}).value is None
        assert scan_bid_amount({"bid_amount": text}).value is None

    def test_a_grouped_micros_string_is_still_scaled(self) -> None:
        assert scan_budget_amount({"budget_micros": "12,000,000"}).value == 12.0

    def test_non_numeric_strings_are_ignored(self) -> None:
        assert scan_budget_amount({"budget_type": "DAILY"}).value is None

    def test_booleans_are_ignored(self) -> None:
        assert scan_budget_amount({"budget_enabled": True}).value is None

    @pytest.mark.parametrize("value", [float("inf"), float("nan"), 10**400])
    def test_a_non_finite_match_is_unreadable(self, value: Any) -> None:
        result = scan_budget_amount({"daily_budget": value})
        assert result.value is None
        assert result.unreadable_key == "daily_budget"

    def test_bid_scan_reads_bid_shaped_keys(self) -> None:
        assert scan_bid_amount({"ad_groups": [{"default_bid": 4.5}]}).value == 4.5

    def test_deeply_nested_beyond_the_depth_limit_is_ignored(self) -> None:
        node: dict[str, Any] = {"daily_budget": 99_999}
        for _ in range(20):
            node = {"wrap": node}
        assert scan_budget_amount(node).value is None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegistry:
    def test_register_and_lookup(self) -> None:
        assert has_pattern_fallback("acme-do_thing") is False
        register_pattern_fallback_tool("acme-do_thing")
        assert has_pattern_fallback("acme-do_thing") is True

    def test_reset_clears(self) -> None:
        register_pattern_fallback_tool("acme-do_thing")
        reset_pattern_fallback_tools()
        assert has_pattern_fallback("acme-do_thing") is False


# ---------------------------------------------------------------------------
# Enforcement through evaluate_guardrails
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateWithFallback:
    def test_over_cap_is_blocked(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"campaign": {"dailyBudget": 25_000}},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_daily_budget_per_campaign" in (decision.reason or "")
        assert "25,000" in (decision.reason or "")

    def test_under_cap_is_allowed(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"campaign": {"dailyBudget": 900}},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_without_the_fallback_it_sails_past(self) -> None:
        """The gap this closes: no declaration, no fallback ⇒ unenforced."""
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"campaign": {"dailyBudget": 25_000}},
            _CAPS,
        )
        assert decision.allowed is True

    def test_a_declaration_takes_precedence(self) -> None:
        """An exact-key declaration owns the tool's vocabulary; the
        best-effort scan must not second-guess it."""
        decision = evaluate_guardrails(
            "acme_update",
            {"stray_budget": 25_000, "spend_limit": 100},
            _CAPS,
            budget_declaration=BudgetDeclaration(daily_key="spend_limit"),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_increase_pct_uses_the_convention_baseline(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"dailyBudget": 5_000, "current_daily_budget": 1_000},
            Guardrails(max_daily_budget_increase_pct=20),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_daily_budget_increase_pct" in (decision.reason or "")

    def test_lifetime_cap_also_constrains_a_pattern_match(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"campaign_budget": 900_000},
            Guardrails(max_lifetime_budget_per_campaign=500_000),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_lifetime_budget_per_campaign" in (decision.reason or "")

    def test_a_non_finite_pattern_match_fails_closed(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"dailyBudget": float("inf")},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "dailyBudget" in (decision.reason or "")

    def test_no_guardrails_still_fails_open(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"dailyBudget": float("inf")},
            Guardrails(),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_bid_over_cap_is_blocked(self) -> None:
        decision = evaluate_guardrails(
            "ad_group_management-update_bid",
            {"ad_group": {"defaultBid": 900}},
            _BID_CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_bid_amount_per_ad_set" in (decision.reason or "")

    def test_cpc_bid_cap_also_constrains_a_pattern_match(self) -> None:
        decision = evaluate_guardrails(
            "ad_group_management-update_bid",
            {"bid_micros": 9_000_000},
            Guardrails(max_cpc_bid_per_ad_group=5),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_cpc_bid_per_ad_group" in (decision.reason or "")

    def test_a_bid_declaration_takes_precedence(self) -> None:
        decision = evaluate_guardrails(
            "acme_update",
            {"stray_bid": 900, "bid_cap": 10},
            _BID_CAPS,
            bid_declaration=BidDeclaration(bid_amount_key="bid_cap"),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_the_builtin_scan_still_applies_alongside(self) -> None:
        """The fallback is additive: built-in spellings keep working."""
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"daily_budget": 25_000},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False

    def test_an_identifier_argument_does_not_false_trip(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"budget_id": 1234567890123, "dailyBudget": 100},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Gate + registry integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGateIntegration:
    def test_gate_applies_the_fallback_for_a_registered_tool(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        import mureo.policy.strategy_gate as sg
        from mureo.core.runtime_context import reset_runtime_context
        from mureo.policy.strategy_gate import StrategyPolicyGate

        (tmp_path / "STRATEGY.md").write_text(
            "## Guardrails\n- max_daily_budget_per_campaign: 10000\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        reset_runtime_context()
        sg._cache.clear()
        try:
            register_pattern_fallback_tool("campaign_management-update_campaign")
            gate = StrategyPolicyGate()
            denied = gate.evaluate(
                "campaign_management-update_campaign", {"dailyBudget": 25_000}
            )
            assert denied.allowed is False
            allowed = gate.evaluate("some_unregistered_tool", {"dailyBudget": 25_000})
            assert allowed.allowed is True
        finally:
            reset_runtime_context()
            sg._cache.clear()


@pytest.mark.unit
def test_server_registers_mutating_plugin_tools_for_the_fallback() -> None:
    """A declaration-less MUTATING plugin tool is registered; a read is not."""
    from mcp.types import Tool, ToolAnnotations

    from mureo.mcp.plugin_semantics import derive_semantics
    from mureo.mcp.server import _register_plugin_pattern_fallbacks

    mutating = Tool(
        name="campaign_management-update_campaign",
        description="x",
        inputSchema={"type": "object", "properties": {}},
    )
    read_only = Tool(
        name="campaign_management-list_campaigns",
        description="x",
        inputSchema={"type": "object", "properties": {}},
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    semantics = {t.name: derive_semantics(t) for t in (mutating, read_only)}
    _register_plugin_pattern_fallbacks(semantics)

    assert has_pattern_fallback("campaign_management-update_campaign") is True
    assert has_pattern_fallback("campaign_management-list_campaigns") is False


def _semantics_for(*names: str) -> dict[str, Any]:
    """Semantics for tools that declare NOTHING — no annotations, no meta.

    This is the shape a manifest snapshot produces, and it is exactly the case
    that matters: ``derive_semantics`` defaults an undeclared tool to
    *mutating*, so the name is the only signal available.
    """
    from mcp.types import Tool

    from mureo.mcp.plugin_semantics import derive_semantics

    tools = [
        Tool(
            name=name,
            description="x",
            inputSchema={"type": "object", "properties": {}},
        )
        for name in names
    ]
    return {t.name: derive_semantics(t) for t in tools}


@pytest.mark.unit
class TestReadNameExemption:
    """A read tool without ``readOnlyHint`` must not be denial-gated.

    ``derive_semantics`` treats an undeclared tool as mutating (the right
    default for auditing), and a manifest snapshot declares nothing — so every
    read from a bridged surface arrived here as "mutating". Handing those to a
    heuristic budget/bid scan can only produce FALSE DENIALS: a listing call
    with a numeric budget-shaped *filter* argument would be refused.

    The exemption is keyed on read-shaped NAMES rather than on a mutation
    allow-list because the error costs are asymmetric: platform mutations are
    consistently verb-named (``create_`` / ``update_`` / ``delete_`` /
    ``set_``), so a read-shaped name is almost never a mutation, while a
    mutation-shaped name that is really a read costs only a scan of arguments
    that carry no budget.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "campaign_management-list_campaigns",
            "account_management-query_advertiser_account",
            "reporting-get_report",
            "reporting-search_terms",
            "insights-analyze_performance",
            # Native (hyphen-free) read names are exempted on the same rule.
            "list_campaigns",
        ],
    )
    def test_read_shaped_names_are_not_registered(self, name: str) -> None:
        from mureo.mcp.server import _register_plugin_pattern_fallbacks

        _register_plugin_pattern_fallbacks(_semantics_for(name))
        assert has_pattern_fallback(name) is False

    @pytest.mark.parametrize(
        "name",
        [
            "campaign_management-create_campaign",
            "campaign_management-update_campaign",
            "campaign_management-set_budget",
            "campaign_management-delete_campaign",
            # A mid-word hit is not a read prefix, so it stays registered.
            "campaign_management-listing_update",
            "acme_ads_update_budget",
        ],
    )
    def test_mutation_shaped_names_are_still_registered(self, name: str) -> None:
        from mureo.mcp.server import _register_plugin_pattern_fallbacks

        _register_plugin_pattern_fallbacks(_semantics_for(name))
        assert has_pattern_fallback(name) is True

    def test_the_exemption_uses_the_shared_read_vocabulary(self) -> None:
        """One list, two safety surfaces — see mureo.core.tool_names."""
        from mureo.core.tool_names import is_read_only_tool_name
        from mureo.rollback import planner

        assert planner._READ_ONLY_PREFIXES is not None
        assert is_read_only_tool_name("campaign_management-list_x") is True
        assert planner._is_read_only("campaign_management-list_x") is True

    def test_a_read_with_a_budget_shaped_filter_is_not_denied(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        """The bug this closes, end to end through the real gate."""
        import mureo.policy.strategy_gate as sg
        from mureo.core.runtime_context import reset_runtime_context
        from mureo.mcp.server import _register_plugin_pattern_fallbacks
        from mureo.policy.strategy_gate import StrategyPolicyGate

        (tmp_path / "STRATEGY.md").write_text(
            "## Guardrails\n- max_daily_budget_per_campaign: 10000\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        reset_runtime_context()
        sg._cache.clear()
        try:
            name = "campaign_management-list_campaigns"
            _register_plugin_pattern_fallbacks(_semantics_for(name))
            decision = StrategyPolicyGate().evaluate(
                name, {"min_daily_budget_filter": 50_000}
            )
            assert decision.allowed is True
        finally:
            reset_runtime_context()
            sg._cache.clear()
