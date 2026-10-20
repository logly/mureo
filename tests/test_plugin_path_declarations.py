"""Plugin ``_meta`` budget / bid declarations that name NESTED paths (#868).

A plugin tool that takes the platform's request object under one argument
(``body``) carries its budget below the top level. A flat ``_meta`` key could
not name it, so the tool either went uncapped or needed a hand-rolled gate.
A proposal channel now also accepts a path in the
:class:`~mureo.policy.declarations.ArgumentPaths` syntax, or a list of paths.

What is pinned here:

- parsing — a path-shaped string or a list compiles to ``ArgumentPaths``, a
  malformed one rejects the WHOLE declaration, ``current`` stays flat, and a
  parsed declaration never sets ``scan_floor``;
- end to end through the server's own registration, with the pattern fallback
  registered too — a plugin's path declaration REPLACES the scan exactly like a
  flat key, so a lifetime budget the scan would have folded into the daily
  channel is no longer refused;
- a flat key spelled with a ``.`` still matches a top-level argument literally
  named like it, so a declaration written before paths keeps its cap;
- floor parity — mureo's own bridged table keeps the scan as a floor because it
  sets ``scan_floor``, and the floor follows the flag, not the key shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mureo.amazon_ads import money_paths
from mureo.policy.declarations import _declared_amount, _Unreadable
from mureo.policy.pattern_scan import (
    register_pattern_fallback_tool,
    reset_pattern_fallback_tools,
)
from mureo.policy.strategy_gate import (
    ArgumentPaths,
    BidDeclaration,
    BudgetDeclaration,
    StrategyPolicyGate,
    register_budget_declaration,
    reset_bid_declarations,
    reset_budget_declarations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_BUDGET_TOOL = "acme_ads_update_campaign_native"
_FANOUT_TOOL = "acme_ads_update_campaigns_batch"
_BID_TOOL = "acme_ads_update_ad_group_native"
_FLOOR_TOOL = "acme_ads_update_floor_probe"
_ALTERNATIVES_TOOL = "acme_ads_update_campaign_alternatives"
_WILDCARD_TOOL = "acme_ads_update_campaign_regions"
_DOTTED_TOOL = "acme_ads_update_campaign_dotted"

_GUARDRAILS = (
    "## Guardrails\n"
    "- max_daily_budget_per_campaign: 50000\n"
    "- max_lifetime_budget_per_campaign: 500000\n"
    "- max_cpc_bid_per_ad_group: 100\n"
)


@pytest.fixture(autouse=True)
def _clean_registries() -> Iterator[None]:
    """Isolate the process-global registries WITHOUT destroying them.

    Same isolation as the other declaration suites: ``mureo.mcp.server``
    populates these once at import, so they are saved and restored rather than
    cleared for the rest of the session. The runtime context and the gate's TTL
    cache are reset too, because the gate resolves STRATEGY.md through them.
    """
    import mureo.policy.strategy_gate as sg
    from mureo.core.runtime_context import reset_runtime_context
    from mureo.policy.declarations import _BID_DECLARATIONS, _BUDGET_DECLARATIONS
    from mureo.policy.pattern_scan import _PATTERN_FALLBACK_TOOLS

    saved_budget = dict(_BUDGET_DECLARATIONS)
    saved_bid = dict(_BID_DECLARATIONS)
    saved_fallback = set(_PATTERN_FALLBACK_TOOLS)
    reset_budget_declarations()
    reset_bid_declarations()
    reset_pattern_fallback_tools()
    reset_runtime_context()
    sg._cache.clear()
    yield
    reset_budget_declarations()
    reset_bid_declarations()
    reset_pattern_fallback_tools()
    _BUDGET_DECLARATIONS.update(saved_budget)
    _BID_DECLARATIONS.update(saved_bid)
    _PATTERN_FALLBACK_TOOLS.update(saved_fallback)
    reset_runtime_context()
    sg._cache.clear()


@pytest.fixture
def gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StrategyPolicyGate:
    """The built-in gate over a STRATEGY.md carrying the caps above."""
    (tmp_path / "STRATEGY.md").write_text(_GUARDRAILS, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return StrategyPolicyGate()


def _tool(name: str, meta_mureo: dict[str, Any]) -> Any:
    from mcp.types import Tool

    return Tool(
        name=name,
        description="x",
        inputSchema={"type": "object", "properties": {}},
        _meta={"mureo": meta_mureo},
    )


def _register_like_the_server(*tools: Any) -> None:
    """Register ``tools`` exactly as the server does at import.

    The pattern fallback is registered as well (every tool here is a
    mutation), so a pass proves the DECLARATION won over the scan rather than
    that no scan ran.
    """
    from mureo.mcp.plugin_semantics import derive_semantics
    from mureo.mcp.server import (
        _register_plugin_bid_declarations,
        _register_plugin_budget_declarations,
        _register_plugin_pattern_fallbacks,
    )
    from mureo.policy.pattern_scan import has_pattern_fallback

    semantics = {t.name: derive_semantics(t) for t in tools}
    _register_plugin_budget_declarations(semantics)
    _register_plugin_bid_declarations(semantics)
    _register_plugin_pattern_fallbacks(semantics)
    assert all(has_pattern_fallback(t.name) for t in tools)


def _budget(raw: Any) -> BudgetDeclaration | None:
    from mureo.mcp.plugin_semantics import _parse_budget

    return _parse_budget(raw)


def _bid(raw: Any) -> BidDeclaration | None:
    from mureo.mcp.plugin_semantics import _parse_bid

    return _parse_bid(raw)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

#: Every one rejects the WHOLE declaration. The bracket and inner-whitespace
#: strings used to be accepted as flat keys that never matched; they now reach
#: the path parser (``is_path_spec``) and fail loudly there.
_MALFORMED_CHANNELS: list[Any] = [
    "a..b",
    "a[]]",
    "a]",
    "*x",
    "items[0]",
    "items[0].budget",
    "a[",
    "x]",
    "body. daily",
    "a . b",
    "   ",
    None,
    5,
    {},
    [],
    [""],
    ["a", 1],
]


@pytest.mark.unit
class TestParsing:
    def test_a_dotted_string_is_a_path(self) -> None:
        decl = _budget({"daily": "body.daily_budget_micros", "unit": "micros"})
        assert decl == BudgetDeclaration(
            daily_key=ArgumentPaths.parse("body.daily_budget_micros"), micros=True
        )

    def test_a_flat_string_is_unchanged(self) -> None:
        assert _budget({"daily": "spend_limit"}) == BudgetDeclaration(
            daily_key="spend_limit"
        )

    def test_a_list_is_alternative_paths_for_one_channel(self) -> None:
        decl = _budget({"lifetime": ["body.total", "body.flight.total"]})
        assert decl is not None
        assert decl.lifetime_key == ArgumentPaths.parse(
            "body.total", "body.flight.total"
        )

    def test_array_and_wildcard_segments_are_paths(self) -> None:
        decl = _budget({"daily": "body.items[].budget", "lifetime": "caps.*.v"})
        assert decl is not None
        assert decl.daily_key == ArgumentPaths.parse("body.items[].budget")
        assert decl.lifetime_key == ArgumentPaths.parse("caps.*.v")

    def test_the_bid_twin_parses_paths_too(self) -> None:
        decl = _bid({"cpc_bid": "body.bid.cpc_micro", "bid_amount": ["a.b", "c"]})
        assert decl == BidDeclaration(
            bid_amount_key=ArgumentPaths.parse("a.b", "c"),
            cpc_bid_key=ArgumentPaths.parse("body.bid.cpc_micro"),
        )

    @pytest.mark.parametrize("channel", _MALFORMED_CHANNELS)
    def test_a_malformed_budget_path_rejects_the_whole_declaration(
        self, channel: Any
    ) -> None:
        assert _budget({"daily": channel}) is None
        assert _budget({"daily": "ok", "lifetime": channel}) is None

    @pytest.mark.parametrize("channel", _MALFORMED_CHANNELS)
    def test_a_malformed_bid_path_rejects_the_whole_declaration(
        self, channel: Any
    ) -> None:
        assert _bid({"cpc_bid": channel}) is None
        assert _bid({"bid_amount": "ok", "cpc_bid": channel}) is None

    @pytest.mark.parametrize("current", ["body.current", "cur.rent", ["current"]])
    def test_current_stays_flat(self, current: Any) -> None:
        assert _budget({"daily": "body.daily", "current": current}) is None

    def test_a_parsed_declaration_never_sets_scan_floor(self) -> None:
        budget = _budget({"daily": "body.daily", "lifetime": "total"})
        bid = _bid({"cpc_bid": ["body.bid", "bid"]})
        assert budget is not None and budget.scan_floor is False
        assert bid is not None and bid.scan_floor is False


# ---------------------------------------------------------------------------
# End to end — registered like the server, with the fallback registered too
# ---------------------------------------------------------------------------


@pytest.fixture
def budget_tool() -> None:
    """A plugin tool declaring both budget channels by path.

    The leaves are spelled with a singular ``micro`` on purpose: the
    best-effort scan does not recognise that as micros and would read the raw
    figure, so a correct currency-unit verdict can only come from the
    declaration.
    """
    _register_like_the_server(
        _tool(
            _BUDGET_TOOL,
            {
                "budget": {
                    "daily": "body.daily_budget_micro",
                    "lifetime": "body.spending_limit_micro",
                    "unit": "micros",
                }
            },
        )
    )


@pytest.mark.unit
@pytest.mark.usefixtures("budget_tool")
class TestBudgetPathEndToEnd:
    def test_a_daily_budget_under_the_cap_is_allowed(
        self, gate: StrategyPolicyGate
    ) -> None:
        args = {"body": {"daily_budget_micro": 40_000_000_000}}
        assert gate.evaluate(_BUDGET_TOOL, args).allowed is True

    def test_a_daily_budget_over_the_cap_is_denied_in_currency_units(
        self, gate: StrategyPolicyGate
    ) -> None:
        args = {"body": {"daily_budget_micro": 60_000_000_000}}
        decision = gate.evaluate(_BUDGET_TOOL, args)
        reason = decision.reason or ""
        assert decision.allowed is False
        assert "max_daily_budget_per_campaign" in reason
        assert "60,000" in reason
        assert "60,000,000,000" not in reason

    def test_a_lifetime_budget_alone_is_not_folded_into_the_daily_cap(
        self, gate: StrategyPolicyGate
    ) -> None:
        """The regression: the scan alone reads 400,000,000,000 raw and holds
        it to the daily cap. The declaration names it as a lifetime figure of
        400,000, under the 500,000 lifetime cap."""
        args = {"body": {"spending_limit_micro": 400_000_000_000}}
        assert gate.evaluate(_BUDGET_TOOL, args).allowed is True

    @pytest.mark.parametrize(
        "body",
        [
            {"daily_budget_micro": 40_000_000_000},
            {"spending_limit_micro": 400_000_000_000},
        ],
    )
    def test_the_scan_alone_would_refuse_both_allowed_calls(
        self, gate: StrategyPolicyGate, body: dict[str, Any]
    ) -> None:
        """The control: an undeclared fallback tool with the same payload is
        refused, so the two allows above are the declaration replacing it."""
        register_pattern_fallback_tool(_FLOOR_TOOL)
        assert gate.evaluate(_FLOOR_TOOL, {"body": body}).allowed is False

    def test_a_lifetime_budget_over_its_cap_is_denied(
        self, gate: StrategyPolicyGate
    ) -> None:
        args = {"body": {"spending_limit_micro": 600_000_000_000}}
        decision = gate.evaluate(_BUDGET_TOOL, args)
        reason = decision.reason or ""
        assert decision.allowed is False
        assert "max_lifetime_budget_per_campaign" in reason
        assert "600,000" in reason

    def test_null_at_the_leaf_proposes_nothing(self, gate: StrategyPolicyGate) -> None:
        args = {"body": {"daily_budget_micro": None}}
        assert gate.evaluate(_BUDGET_TOOL, args).allowed is True

    def test_an_object_at_the_leaf_is_denied_as_unreadable(
        self, gate: StrategyPolicyGate
    ) -> None:
        """Same outcome as a flat key holding a nested object: a path is not
        the lenient way to declare."""
        args = {"body": {"daily_budget_micro": {"value": 1}}}
        decision = gate.evaluate(_BUDGET_TOOL, args)
        assert decision.allowed is False
        assert "body.daily_budget_micro" in (decision.reason or "")
        assert "not a usable number" in (decision.reason or "")


@pytest.mark.unit
class TestArrayFanOut:
    @pytest.fixture(autouse=True)
    def _fanout_tool(self) -> None:
        _register_like_the_server(
            _tool(
                _FANOUT_TOOL,
                {"budget": {"daily": "body.items[].budget_micro", "unit": "micros"}},
            )
        )

    def test_the_largest_item_is_compared(self, gate: StrategyPolicyGate) -> None:
        items = [{"budget_micro": v * 1_000_000} for v in (10_000, 70_000, 20_000)]
        decision = gate.evaluate(_FANOUT_TOOL, {"body": {"items": items}})
        assert decision.allowed is False
        assert "70,000" in (decision.reason or "")

    def test_every_item_under_the_cap_is_allowed(
        self, gate: StrategyPolicyGate
    ) -> None:
        items = [{"budget_micro": v * 1_000_000} for v in (10_000, 45_000, 20_000)]
        decision = gate.evaluate(_FANOUT_TOOL, {"body": {"items": items}})
        assert decision.allowed is True


@pytest.mark.unit
class TestBidPathEndToEnd:
    @pytest.fixture(autouse=True)
    def _bid_tool(self) -> None:
        _register_like_the_server(
            _tool(
                _BID_TOOL,
                {"bid": {"cpc_bid": "body.bid.cpc_micro", "unit": "micros"}},
            )
        )

    def test_a_bid_under_the_cap_is_allowed(self, gate: StrategyPolicyGate) -> None:
        args = {"body": {"bid": {"cpc_micro": 80_000_000}}}
        assert gate.evaluate(_BID_TOOL, args).allowed is True

    def test_a_bid_over_the_cap_is_denied(self, gate: StrategyPolicyGate) -> None:
        args = {"body": {"bid": {"cpc_micro": 150_000_000}}}
        decision = gate.evaluate(_BID_TOOL, args)
        assert decision.allowed is False
        assert "max_cpc_bid_per_ad_group" in (decision.reason or "")

    def test_an_unrelated_bid_looking_key_is_not_scanned(
        self, gate: StrategyPolicyGate
    ) -> None:
        """The declaration replaces the bid scan; the control shows the scan
        alone would have refused the same payload on the stray key."""
        args = {
            "body": {"bid": {"cpc_micro": 80_000_000}, "forbidden_bid_note": 999_999}
        }
        assert gate.evaluate(_BID_TOOL, args).allowed is True
        register_pattern_fallback_tool(_FLOOR_TOOL)
        assert gate.evaluate(_FLOOR_TOOL, args).allowed is False


@pytest.mark.unit
class TestAlternativesAndWildcards:
    """A list of paths is one channel; a ``*`` segment fans out over values.

    Leaves are spelled with a singular ``micro`` so only the declaration can
    produce a verdict quoted in currency units.
    """

    @pytest.fixture(autouse=True)
    def _tools(self) -> None:
        _register_like_the_server(
            _tool(
                _ALTERNATIVES_TOOL,
                {
                    "budget": {
                        "daily": ["body.budget.amount_micro", "body.daily_micro"],
                        "unit": "micros",
                    }
                },
            ),
            _tool(
                _WILDCARD_TOOL,
                {"budget": {"daily": "body.budgets.*.amount_micro", "unit": "micros"}},
            ),
        )

    def test_the_second_alternative_alone_is_capped(
        self, gate: StrategyPolicyGate
    ) -> None:
        args = {"body": {"daily_micro": 60_000_000_000}}
        decision = gate.evaluate(_ALTERNATIVES_TOOL, args)
        reason = decision.reason or ""
        assert decision.allowed is False
        assert "60,000" in reason
        assert "60,000,000,000" not in reason

    def test_the_largest_wildcard_value_is_compared(
        self, gate: StrategyPolicyGate
    ) -> None:
        budgets = {
            "north": {"amount_micro": 20_000_000_000},
            "south": {"amount_micro": 70_000_000_000},
        }
        decision = gate.evaluate(_WILDCARD_TOOL, {"body": {"budgets": budgets}})
        assert decision.allowed is False
        assert "70,000" in (decision.reason or "")


@pytest.mark.unit
class TestLiteralDottedKey:
    """A flat key spelled with a ``.`` keeps the cap it had before paths (#868).

    ``"campaign.daily_budget"`` now compiles as a path, but a top-level
    argument literally named like it is still read, by the same rules.
    """

    @pytest.fixture(autouse=True)
    def _dotted_tool(self) -> None:
        _register_like_the_server(
            _tool(_DOTTED_TOOL, {"budget": {"daily": "campaign.daily_budget"}})
        )

    def test_over_the_cap_is_denied_in_currency_units(
        self, gate: StrategyPolicyGate
    ) -> None:
        decision = gate.evaluate(_DOTTED_TOOL, {"campaign.daily_budget": 90_000})
        reason = decision.reason or ""
        assert decision.allowed is False
        assert "max_daily_budget_per_campaign" in reason
        assert "90,000" in reason

    def test_under_the_cap_is_allowed(self, gate: StrategyPolicyGate) -> None:
        args = {"campaign.daily_budget": 40_000}
        assert gate.evaluate(_DOTTED_TOOL, args).allowed is True

    def test_an_object_at_the_literal_key_is_denied_as_unreadable(
        self, gate: StrategyPolicyGate
    ) -> None:
        decision = gate.evaluate(_DOTTED_TOOL, {"campaign.daily_budget": {"v": 1}})
        reason = decision.reason or ""
        assert decision.allowed is False
        assert "campaign.daily_budget" in reason
        assert "not a usable number" in reason

    def test_with_scan_floor_an_object_at_the_literal_key_is_skipped(self) -> None:
        path = ArgumentPaths.parse("campaign.daily_budget")
        args = {"campaign.daily_budget": {"v": 1}}
        assert _declared_amount(args, path, micros=False, scan_floor=True) is None


# ---------------------------------------------------------------------------
# Floor parity — the floor follows ``scan_floor``, not the key shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFloorParity:
    _PATH = ArgumentPaths.parse("body.x")

    def test_the_bridged_table_sets_scan_floor(self) -> None:
        assert money_paths._budget_declaration(("body.a",)).scan_floor is True
        assert money_paths._bid_declaration(("body.a",)).scan_floor is True

    def test_a_scan_floor_declaration_is_raised_to_the_scan(
        self, gate: StrategyPolicyGate
    ) -> None:
        register_budget_declaration(
            _FLOOR_TOOL, BudgetDeclaration(daily_key=self._PATH, scan_floor=True)
        )
        register_pattern_fallback_tool(_FLOOR_TOOL)
        args = {"body": {"x": 100}, "stray_budget": 70_000}
        decision = gate.evaluate(_FLOOR_TOOL, args)
        assert decision.allowed is False
        assert "70,000" in (decision.reason or "")

    def test_a_scan_floor_container_leaf_reads_as_not_found(
        self, gate: StrategyPolicyGate
    ) -> None:
        register_budget_declaration(
            _FLOOR_TOOL, BudgetDeclaration(daily_key=self._PATH, scan_floor=True)
        )
        register_pattern_fallback_tool(_FLOOR_TOOL)
        args = {"body": {"x": {"amount": 1}}}
        assert gate.evaluate(_FLOOR_TOOL, args).allowed is True
        assert _declared_amount(args, self._PATH, micros=False, scan_floor=True) is (
            None
        )

    def test_without_scan_floor_a_container_leaf_is_unreadable(self) -> None:
        args = {"body": {"x": {"amount": 1}}}
        result = _declared_amount(args, self._PATH, micros=False)
        assert isinstance(result, _Unreadable)
        assert result.key == "body.x"

    def test_without_scan_floor_the_scan_does_not_raise_it(
        self, gate: StrategyPolicyGate
    ) -> None:
        register_budget_declaration(
            _FLOOR_TOOL, BudgetDeclaration(daily_key=self._PATH, scan_floor=False)
        )
        register_pattern_fallback_tool(_FLOOR_TOOL)
        args = {"body": {"x": 100}, "stray_budget": 70_000}
        assert gate.evaluate(_FLOOR_TOOL, args).allowed is True
