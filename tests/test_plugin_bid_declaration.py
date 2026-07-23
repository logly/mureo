"""Plugin bid declarations for the StrategyPolicyGate (#455 follow-up).

The gate's bid extraction is hard-wired to the Google/Meta argument keys
(``bid_amount`` in minor units, ``cpc_bid_micros`` in micros), so a plugin
tool carrying its bid under any other name sails past every
``max_bid_amount_per_ad_set`` / ``max_cpc_bid_per_ad_group`` cap — silently:
no startup error, no warning, just an unenforced platform. This mirrors the
budget seam #414 already shipped: a plugin declares its bid argument keys in
standard MCP metadata —

    _meta={"mureo": {"bid": {"cpc_bid": "bid_cap_micros", "unit": "micros"}}}

— ``derive_semantics`` parses it, the server registers it, and
``StrategyPolicyGate`` consults it for that tool ahead of the built-in key
scan. Undeclared tools keep today's behavior byte-identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mureo.policy.strategy_gate import (
    BidDeclaration,
    Guardrails,
    bid_declaration_for,
    evaluate_guardrails,
    register_bid_declaration,
    reset_bid_declarations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Isolate the process-global bid registry WITHOUT destroying it.

    ``mureo.mcp.server`` populates it once at import from real plugin
    discovery; a destructive clear would drop those declarations for the
    rest of the pytest session (inert only while no shipped plugin declares
    a bid). Also resets the process-cached RuntimeContext and the gate's TTL
    guardrail cache around each test so the end-to-end gate test resolves the
    STRATEGY.md it wrote, not one a context cached by an earlier test points
    at. Mirrors ``test_plugin_budget_declaration``'s fixture.
    """
    import mureo.policy.strategy_gate as sg
    from mureo.core.runtime_context import reset_runtime_context
    from mureo.policy.strategy_gate import _BID_DECLARATIONS

    saved = dict(_BID_DECLARATIONS)
    reset_bid_declarations()
    reset_runtime_context()
    sg._cache.clear()
    yield
    reset_bid_declarations()
    _BID_DECLARATIONS.update(saved)
    reset_runtime_context()
    sg._cache.clear()


def _tool(meta_mureo: dict[str, Any]) -> Any:
    from mcp.types import Tool

    return Tool(
        name="acme_ads_update_bid",
        description="x",
        inputSchema={"type": "object", "properties": {}},
        _meta={"mureo": meta_mureo},
    )


# ---------------------------------------------------------------------------
# derive_semantics — parsing the meta["mureo"]["bid"] declaration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeriveSemanticsBid:
    def test_parses_full_declaration(self) -> None:
        from mureo.mcp.plugin_semantics import derive_semantics

        sem = derive_semantics(
            _tool(
                {
                    "bid": {
                        "bid_amount": "ad_set_bid",
                        "cpc_bid": "cpc_micros",
                        "unit": "micros",
                    }
                }
            )
        )
        assert sem.bid == BidDeclaration(
            bid_amount_key="ad_set_bid",
            cpc_bid_key="cpc_micros",
            micros=True,
        )

    def test_defaults_to_currency_unit(self) -> None:
        from mureo.mcp.plugin_semantics import derive_semantics

        sem = derive_semantics(_tool({"bid": {"bid_amount": "max_bid"}}))
        assert sem.bid == BidDeclaration(bid_amount_key="max_bid")
        assert sem.bid.micros is False

    @pytest.mark.parametrize(
        "raw",
        [
            "bid_amount",  # bare string, not a dict
            {"unit": "micros"},  # neither bid_amount nor cpc_bid key
            {"bid_amount": 123},  # non-str key name
            {"cpc_bid": "x", "unit": "yen"},  # unknown unit
            {"bid_amount": "ok", "cpc_bid": 123},  # one good key, one malformed
        ],
    )
    def test_malformed_declaration_is_rejected(self, raw: Any) -> None:
        """A malformed hint must not half-apply — silent misconfiguration is
        the exact failure mode this seam exists to avoid."""
        from mureo.mcp.plugin_semantics import derive_semantics

        sem = derive_semantics(_tool({"bid": raw}))
        assert sem.bid is None

    def test_absent_bid_is_none(self) -> None:
        from mureo.mcp.plugin_semantics import derive_semantics

        assert derive_semantics(_tool({})).bid is None

    def test_bid_and_budget_coexist(self) -> None:
        """A tool that carries both a budget and a bid declares both; parsing
        one must not clobber the other."""
        from mureo.mcp.plugin_semantics import derive_semantics
        from mureo.policy.strategy_gate import BudgetDeclaration

        sem = derive_semantics(
            _tool(
                {
                    "budget": {"daily": "daily_micros", "unit": "micros"},
                    "bid": {"cpc_bid": "cpc_micros", "unit": "micros"},
                }
            )
        )
        assert sem.budget == BudgetDeclaration(daily_key="daily_micros", micros=True)
        assert sem.bid == BidDeclaration(cpc_bid_key="cpc_micros", micros=True)


# ---------------------------------------------------------------------------
# evaluate_guardrails — declared extraction (pure)
# ---------------------------------------------------------------------------

_CAPS_BID = Guardrails(max_bid_amount_per_ad_set=5_000.0)
_CAPS_CPC = Guardrails(max_cpc_bid_per_ad_group=100.0)


@pytest.mark.unit
class TestDeclaredBidExtraction:
    def test_declared_bid_amount_key_is_enforced(self) -> None:
        decl = BidDeclaration(bid_amount_key="max_bid")
        decision = evaluate_guardrails(
            "acme_ads_update_bid",
            {"max_bid": 8_000},
            _CAPS_BID,
            bid_declaration=decl,
        )
        assert decision.allowed is False
        assert "max_bid_amount_per_ad_set" in (decision.reason or "")

    def test_under_cap_is_allowed(self) -> None:
        decl = BidDeclaration(bid_amount_key="max_bid")
        decision = evaluate_guardrails(
            "acme_ads_update_bid",
            {"max_bid": 3_000},
            _CAPS_BID,
            bid_declaration=decl,
        )
        assert decision.allowed is True

    def test_declared_cpc_key_is_enforced(self) -> None:
        decl = BidDeclaration(cpc_bid_key="cpc_bid")
        decision = evaluate_guardrails(
            "t",
            {"cpc_bid": 150},
            _CAPS_CPC,
            bid_declaration=decl,
        )
        assert decision.allowed is False
        assert "max_cpc_bid_per_ad_group" in (decision.reason or "")

    def test_micros_are_converted_for_cpc(self) -> None:
        """The motivating LOGLY case: ``bid_cap_micros`` in micros, capped by
        ``max_cpc_bid_per_ad_group`` (currency units) after ÷1e6."""
        decl = BidDeclaration(cpc_bid_key="bid_cap_micros", micros=True)
        decision = evaluate_guardrails(
            "t",
            {"bid_cap_micros": 150_000_000},  # 150 currency units
            _CAPS_CPC,
            bid_declaration=decl,
        )
        assert decision.allowed is False

    def test_micros_under_cap_is_allowed(self) -> None:
        decl = BidDeclaration(cpc_bid_key="bid_cap_micros", micros=True)
        decision = evaluate_guardrails(
            "t",
            {"bid_cap_micros": 50_000_000},  # 50 currency units
            _CAPS_CPC,
            bid_declaration=decl,
        )
        assert decision.allowed is True

    def test_numeric_string_is_coerced(self) -> None:
        """Plugins hit stringified numbers in the wild — a declared key accepts
        them rather than silently skipping the cap."""
        decl = BidDeclaration(bid_amount_key="max_bid")
        decision = evaluate_guardrails(
            "t", {"max_bid": "8000"}, _CAPS_BID, bid_declaration=decl
        )
        assert decision.allowed is False

    def test_declaration_replaces_builtin_key_scan(self) -> None:
        """With a declaration, the built-in Meta/Google keys are NOT scanned —
        the plugin owns its argument vocabulary, so a stray ``bid_amount`` field
        cannot false-trip the cap for a declaring tool."""
        decl = BidDeclaration(cpc_bid_key="acme_cpc", micros=True)
        decision = evaluate_guardrails(
            "t",
            # built-in bid_amount key present, but NOT the declared one, and the
            # declared cpc key is absent ⇒ no bid proposed for this tool.
            {"bid_amount": 99_999, "acme_cpc": 10_000_000},  # 10 units, under cap
            _CAPS_BID,
            bid_declaration=decl,
        )
        assert decision.allowed is True

    def test_no_declaration_keeps_builtin_scan(self) -> None:
        decision = evaluate_guardrails(
            "meta_ads_ad_sets_update", {"bid_amount": 8_000}, _CAPS_BID
        )
        assert decision.allowed is False


# ---------------------------------------------------------------------------
# Registry + gate integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeclarationRegistry:
    def test_register_and_lookup(self) -> None:
        decl = BidDeclaration(bid_amount_key="max_bid")
        register_bid_declaration("acme_ads_update_bid", decl)
        assert bid_declaration_for("acme_ads_update_bid") == decl
        assert bid_declaration_for("unknown_tool") is None

    def test_gate_consults_registry(self, tmp_path: Any, monkeypatch: Any) -> None:
        """End to end: a registered plugin declaration makes the built-in
        StrategyPolicyGate deny an over-cap plugin bid call."""
        from mureo.policy.strategy_gate import StrategyPolicyGate

        strategy = tmp_path / "STRATEGY.md"
        strategy.write_text(
            "## Guardrails\n- max_cpc_bid_per_ad_group: 100\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        register_bid_declaration(
            "acme_ads_update_bid",
            BidDeclaration(cpc_bid_key="bid_cap_micros", micros=True),
        )
        gate = StrategyPolicyGate()
        decision = gate.evaluate("acme_ads_update_bid", {"bid_cap_micros": 150_000_000})
        assert decision.allowed is False


# ---------------------------------------------------------------------------
# Server wiring — plugin semantics land in the registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_server_registers_declared_plugin_bids() -> None:
    from mureo.mcp import server as server_mod
    from mureo.mcp.plugin_semantics import ToolSemantics

    semantics = {
        "acme_ads_update_bid": ToolSemantics(
            mutating=True,
            bid=BidDeclaration(bid_amount_key="max_bid"),
        ),
        "acme_ads_list": ToolSemantics(mutating=False),
    }
    server_mod._register_plugin_bid_declarations(semantics)
    assert bid_declaration_for("acme_ads_update_bid") == BidDeclaration(
        bid_amount_key="max_bid"
    )
    assert bid_declaration_for("acme_ads_list") is None


@pytest.mark.unit
class TestUnreadableDeclaredBid:
    """A declared key that is PRESENT but unreadable must fail CLOSED.

    Returning "no proposal" for garbage would re-open the exact silent bypass
    the seam exists to close — worse, it would make the declared path weaker
    than the built-in scan, where a raw ``inf`` simply exceeds any finite cap
    and denies. Feeds the SAME ``_bid_inputs`` choke point as the built-in scan.
    """

    _DECL = BidDeclaration(bid_amount_key="max_bid")

    @pytest.mark.parametrize(
        "value",
        [
            float("inf"),
            float("-inf"),
            float("nan"),
            "inf",
            "Infinity",
            "nan",
            "not-a-number",
            "9" * 309,  # too large for float64 as a string — saturates to inf
            int("9" * 309),  # bare int: float() raises OverflowError, not inf
            True,  # bool is an int subclass — never a bid
            {"amount": 1},
            [],
        ],
    )
    def test_unreadable_value_is_denied(self, value: Any) -> None:
        decision = evaluate_guardrails(
            "acme_ads_update_bid",
            {"max_bid": value},
            _CAPS_BID,
            bid_declaration=self._DECL,
        )
        assert decision.allowed is False
        assert "max_bid" in (decision.reason or "")

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_absent_like_value_carries_no_proposal(self, value: Any) -> None:
        """JSON ``null`` / a blank string mean 'no bid here', not garbage —
        they must not deny."""
        decision = evaluate_guardrails(
            "acme_ads_update_bid",
            {"max_bid": value},
            _CAPS_BID,
            bid_declaration=self._DECL,
        )
        assert decision.allowed is True

    def test_unreadable_cpc_is_denied(self) -> None:
        decision = evaluate_guardrails(
            "t",
            {"cpc_micros": "inf"},
            _CAPS_CPC,
            bid_declaration=BidDeclaration(cpc_bid_key="cpc_micros", micros=True),
        )
        assert decision.allowed is False
        assert "cpc_micros" in (decision.reason or "")

    def test_no_guardrails_still_fails_open(self) -> None:
        """Fail-closed only applies once the operator wrote a rule — an empty
        Guardrails section keeps mureo's 'no enforcement' default."""
        decision = evaluate_guardrails(
            "t", {"max_bid": "inf"}, Guardrails(), bid_declaration=self._DECL
        )
        assert decision.allowed is True
