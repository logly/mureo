"""Plugin budget declarations for the StrategyPolicyGate (#414).

The gate's budget extraction was hard-wired to the Google/Meta argument
keys, so a plugin tool carrying its budget under any other name sailed
past every ``## Guardrails`` cap — silently: no startup error, no
warning, just an unenforced platform. Three known plugins each
hand-rolled the same normalize-and-delegate workaround gate.

This adds the declaration seam (issue option A): a plugin declares its
budget argument keys in standard MCP metadata —

    _meta={"mureo": {"budget": {"daily": "daily_budget_micros",
                                 "unit": "micros"}}}

— ``derive_semantics`` parses it, the server registers it, and
``StrategyPolicyGate`` consults it for that tool ahead of the built-in
key scan. Undeclared tools keep today's behavior byte-identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mureo.policy.strategy_gate import (
    BudgetDeclaration,
    Guardrails,
    budget_declaration_for,
    evaluate_guardrails,
    register_budget_declaration,
    reset_budget_declarations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Isolate the process-global registry WITHOUT destroying it.

    ``mureo.mcp.server`` populates it once at import from real plugin
    discovery; a destructive clear would drop those declarations for the
    rest of the pytest session (inert only while no shipped plugin
    declares a budget).

    Also resets the process-cached RuntimeContext and the gate's TTL
    guardrail cache around each test: the end-to-end gate test resolves
    STRATEGY.md through the active state store, which a context cached by
    an earlier test (pointing at ITS workspace) would otherwise win.
    """
    import mureo.policy.strategy_gate as sg
    from mureo.core.runtime_context import reset_runtime_context
    from mureo.policy.strategy_gate import _BUDGET_DECLARATIONS

    saved = dict(_BUDGET_DECLARATIONS)
    reset_budget_declarations()
    reset_runtime_context()
    sg._cache.clear()
    yield
    reset_budget_declarations()
    _BUDGET_DECLARATIONS.update(saved)
    reset_runtime_context()
    sg._cache.clear()


def _tool(meta_mureo: dict[str, Any]) -> Any:
    from mcp.types import Tool

    return Tool(
        name="acme_ads_update_budget",
        description="x",
        inputSchema={"type": "object", "properties": {}},
        _meta={"mureo": meta_mureo},
    )


# ---------------------------------------------------------------------------
# derive_semantics — parsing the meta["mureo"]["budget"] declaration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeriveSemanticsBudget:
    def test_parses_full_declaration(self) -> None:
        from mureo.mcp.plugin_semantics import derive_semantics

        sem = derive_semantics(
            _tool(
                {
                    "budget": {
                        "daily": "daily_budget_micros",
                        "lifetime": "total_micros",
                        "current": "current_micros",
                        "unit": "micros",
                    }
                }
            )
        )
        assert sem.budget == BudgetDeclaration(
            daily_key="daily_budget_micros",
            lifetime_key="total_micros",
            current_key="current_micros",
            micros=True,
        )

    def test_defaults_to_currency_unit(self) -> None:
        from mureo.mcp.plugin_semantics import derive_semantics

        sem = derive_semantics(_tool({"budget": {"daily": "spend_limit"}}))
        assert sem.budget == BudgetDeclaration(daily_key="spend_limit")
        assert sem.budget.micros is False

    @pytest.mark.parametrize(
        "raw",
        [
            "daily_budget",  # bare string, not a dict
            {"unit": "micros"},  # neither daily nor lifetime key
            {"daily": 123},  # non-str key name
            {"daily": "x", "unit": "yen"},  # unknown unit
            {"current": "cur"},  # current alone declares no proposal
            {"daily": "ok", "lifetime": 123},  # one good key, one malformed
        ],
    )
    def test_malformed_declaration_is_rejected(self, raw: Any) -> None:
        """A malformed hint must not half-apply — the whole point of #414
        is that silent misconfiguration is the failure mode to avoid."""
        from mureo.mcp.plugin_semantics import derive_semantics

        sem = derive_semantics(_tool({"budget": raw}))
        assert sem.budget is None

    def test_absent_budget_is_none(self) -> None:
        from mureo.mcp.plugin_semantics import derive_semantics

        assert derive_semantics(_tool({})).budget is None


# ---------------------------------------------------------------------------
# evaluate_guardrails — declared extraction (pure)
# ---------------------------------------------------------------------------

_CAPS = Guardrails(max_daily_budget_per_campaign=10_000.0)


@pytest.mark.unit
class TestDeclaredBudgetExtraction:
    def test_declared_daily_key_is_enforced(self) -> None:
        decl = BudgetDeclaration(daily_key="spend_limit")
        decision = evaluate_guardrails(
            "acme_ads_update_budget",
            {"spend_limit": 20_000},
            _CAPS,
            budget_declaration=decl,
        )
        assert decision.allowed is False
        assert "max_daily_budget_per_campaign" in (decision.reason or "")

    def test_under_cap_is_allowed(self) -> None:
        decl = BudgetDeclaration(daily_key="spend_limit")
        decision = evaluate_guardrails(
            "acme_ads_update_budget",
            {"spend_limit": 5_000},
            _CAPS,
            budget_declaration=decl,
        )
        assert decision.allowed is True

    def test_micros_are_converted(self) -> None:
        decl = BudgetDeclaration(daily_key="daily_micros", micros=True)
        decision = evaluate_guardrails(
            "t",
            {"daily_micros": 20_000_000_000},  # 20,000 currency units
            _CAPS,
            budget_declaration=decl,
        )
        assert decision.allowed is False

    def test_numeric_string_is_coerced(self) -> None:
        """Plugins hit stringified numbers in the wild (issue report) — a
        declared key accepts them rather than silently skipping the cap."""
        decl = BudgetDeclaration(daily_key="spend_limit")
        decision = evaluate_guardrails(
            "t", {"spend_limit": "20000"}, _CAPS, budget_declaration=decl
        )
        assert decision.allowed is False

    def test_declared_current_key_drives_increase_pct(self) -> None:
        decl = BudgetDeclaration(daily_key="new_budget", current_key="old_budget")
        caps = Guardrails(max_daily_budget_increase_pct=10.0)
        decision = evaluate_guardrails(
            "t",
            {"new_budget": 2_000, "old_budget": 1_000},
            caps,
            budget_declaration=decl,
        )
        assert decision.allowed is False
        assert "max_daily_budget_increase_pct" in (decision.reason or "")

    def test_undeclared_current_falls_back_to_the_built_in_key(self) -> None:
        """A plugin declares where ITS OWN arguments carry a budget. The
        *current* budget is not one of them: it is context the caller supplies,
        under mureo's own cross-provider convention (``current_daily_budget``;
        see the _mureo-strategy skill). Dropping it because the tool declared
        `daily` would silently disable max_daily_budget_increase_pct for every
        plugin that adopts the seam — the same silent underenforcement #414
        exists to remove.
        """
        decl = BudgetDeclaration(daily_key="daily_budget_micros", micros=True)
        caps = Guardrails(max_daily_budget_increase_pct=20.0)
        decision = evaluate_guardrails(
            "t",
            {"daily_budget_micros": 15_000_000_000, "current_daily_budget": 10_000},
            caps,
            budget_declaration=decl,
        )
        assert decision.allowed is False  # 10,000 -> 15,000 is +50%
        assert "50%" in (decision.reason or "")

    def test_the_fallback_current_is_currency_not_micros(self) -> None:
        """The built-in ``current_daily_budget`` is currency units even when the
        tool's own budget is micros — ``micros`` describes the DECLARED keys.
        Dividing it by 1e6 would read ¥10,000 as ¥0.01 and report a 149,999,900%
        increase.
        """
        decl = BudgetDeclaration(daily_key="daily_budget_micros", micros=True)
        caps = Guardrails(max_daily_budget_increase_pct=20.0)
        reason = (
            evaluate_guardrails(
                "t",
                {
                    "daily_budget_micros": 15_000_000_000,
                    "current_daily_budget": 10_000,
                },
                caps,
                budget_declaration=decl,
            ).reason
            or ""
        )
        assert "10,000 → 15,000" in reason

    def test_the_fallback_ignores_the_bare_current_alias(self) -> None:
        """The built-in scan also accepts a bare ``current``, but a DECLARING
        plugin owns its vocabulary, and ``current`` is a plausible name for
        something else entirely (an index, a status). Misreading one as the
        baseline is the dangerous direction: a large stray value yields a small
        percentage, i.e. it would ALLOW a raise that should have been refused.
        """
        decl = BudgetDeclaration(daily_key="daily_budget_micros", micros=True)
        caps = Guardrails(max_daily_budget_increase_pct=20.0)
        decision = evaluate_guardrails(
            "t",
            # `current` here is the plugin's own field, not a budget baseline.
            # Read as one it would say "+50% of 1,000,000" — comfortably under
            # the cap — and wave the ¥15,000 raise through.
            {"daily_budget_micros": 15_000_000_000, "current": 1_000_000},
            caps,
            budget_declaration=decl,
        )
        assert decision.allowed is True  # no baseline ⇒ the pct rule abstains
        assert "increase" not in (decision.reason or "")

    def test_a_declared_current_key_still_wins(self) -> None:
        """The fallback only fills a gap; an explicit declaration still owns
        the channel."""
        decl = BudgetDeclaration(
            daily_key="new_budget", current_key="old_budget", micros=False
        )
        caps = Guardrails(max_daily_budget_increase_pct=20.0)
        decision = evaluate_guardrails(
            "t",
            # The declared key says +10% (allowed); the built-in key would say
            # +900% if it were consulted. The declaration must win.
            {"new_budget": 1_100, "old_budget": 1_000, "current_daily_budget": 110},
            caps,
            budget_declaration=decl,
        )
        assert decision.allowed is True

    def test_declared_lifetime_key_is_enforced(self) -> None:
        decl = BudgetDeclaration(lifetime_key="package_total")
        caps = Guardrails(max_lifetime_budget_per_campaign=50_000.0)
        decision = evaluate_guardrails(
            "t", {"package_total": 60_000}, caps, budget_declaration=decl
        )
        assert decision.allowed is False
        assert "max_lifetime_budget_per_campaign" in (decision.reason or "")

    def test_declaration_replaces_builtin_key_scan(self) -> None:
        """With a declaration, the built-in Google/Meta keys are NOT
        scanned — the plugin owns its argument vocabulary, so a stray
        ``amount`` field (e.g. a non-budget amount) cannot false-trip."""
        decl = BudgetDeclaration(daily_key="spend_limit")
        decision = evaluate_guardrails(
            "t",
            {"amount": 99_999},  # built-in key; NOT the declared one
            _CAPS,
            budget_declaration=decl,
        )
        assert decision.allowed is True

    def test_no_declaration_keeps_builtin_scan(self) -> None:
        decision = evaluate_guardrails("t", {"daily_budget": 20_000}, _CAPS)
        assert decision.allowed is False


# ---------------------------------------------------------------------------
# Registry + gate integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeclarationRegistry:
    def test_register_and_lookup(self) -> None:
        decl = BudgetDeclaration(daily_key="spend_limit")
        register_budget_declaration("acme_ads_update_budget", decl)
        assert budget_declaration_for("acme_ads_update_budget") == decl
        assert budget_declaration_for("unknown_tool") is None

    def test_gate_consults_registry(self, tmp_path: Any, monkeypatch: Any) -> None:
        """End to end: a registered plugin declaration makes the built-in
        StrategyPolicyGate deny an over-cap plugin call."""
        from mureo.policy.strategy_gate import StrategyPolicyGate

        strategy = tmp_path / "STRATEGY.md"
        strategy.write_text(
            "## Guardrails\n- max_daily_budget_per_campaign: 10000\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        register_budget_declaration(
            "acme_ads_update_budget", BudgetDeclaration(daily_key="spend_limit")
        )
        gate = StrategyPolicyGate()
        decision = gate.evaluate("acme_ads_update_budget", {"spend_limit": 20_000})
        assert decision.allowed is False


# ---------------------------------------------------------------------------
# Server wiring — plugin semantics land in the registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_server_registers_declared_plugin_budgets() -> None:
    from mureo.mcp import server as server_mod
    from mureo.mcp.plugin_semantics import ToolSemantics

    semantics = {
        "acme_ads_update_budget": ToolSemantics(
            mutating=True,
            budget=BudgetDeclaration(daily_key="spend_limit"),
        ),
        "acme_ads_list": ToolSemantics(mutating=False),
    }
    server_mod._register_plugin_budget_declarations(semantics)
    assert budget_declaration_for("acme_ads_update_budget") == BudgetDeclaration(
        daily_key="spend_limit"
    )
    assert budget_declaration_for("acme_ads_list") is None


@pytest.mark.unit
class TestUnreadableDeclaredBudget:
    """A declared key that is PRESENT but unreadable must fail CLOSED.

    Returning "no proposal" for garbage would re-open the exact silent
    bypass #414 exists to close — worse, it would make the declared path
    weaker than the built-in scan, where a raw ``inf`` simply exceeds any
    finite cap and denies.
    """

    _DECL = BudgetDeclaration(daily_key="spend_limit")

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
            True,  # bool is an int subclass — never a budget
            {"amount": 1},
            [],
        ],
    )
    def test_unreadable_value_is_denied(self, value: Any) -> None:
        decision = evaluate_guardrails(
            "acme_ads_update_budget",
            {"spend_limit": value},
            _CAPS,
            budget_declaration=self._DECL,
        )
        assert decision.allowed is False
        assert "spend_limit" in (decision.reason or "")

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_absent_like_value_carries_no_proposal(self, value: Any) -> None:
        """JSON ``null`` / a blank string mean 'no budget here', not garbage —
        they must not deny (the schema validator rejects a typed blank right
        after the gate anyway)."""
        decision = evaluate_guardrails(
            "acme_ads_update_budget",
            {"spend_limit": value},
            _CAPS,
            budget_declaration=self._DECL,
        )
        assert decision.allowed is True

    def test_unreadable_lifetime_is_denied(self) -> None:
        decision = evaluate_guardrails(
            "t",
            {"package_total": "inf"},
            Guardrails(max_lifetime_budget_per_campaign=50_000.0),
            budget_declaration=BudgetDeclaration(lifetime_key="package_total"),
        )
        assert decision.allowed is False

    def test_no_guardrails_still_fails_open(self) -> None:
        """Fail-closed only applies once the operator wrote a rule — an empty
        Guardrails section keeps mureo's 'no enforcement' default."""
        decision = evaluate_guardrails(
            "t", {"spend_limit": "inf"}, Guardrails(), budget_declaration=self._DECL
        )
        assert decision.allowed is True


@pytest.mark.unit
class TestDeclarationKeepsTheTotalCap:
    """``max_total_daily_budget`` is the same story as the percentage cap.

    ``projected_total_daily_budget`` is not a budget the tool proposes either —
    it is the account-wide figure the *skills* compute and pass, under the same
    cross-provider convention as ``current_daily_budget``. And a declaration
    cannot even name it: ``BudgetDeclaration`` has no total key, so a declaring
    plugin had NO way to keep ``max_total_daily_budget`` alive. Replacing that
    channel therefore switched the cap off outright, for every plugin that
    adopted the seam — the same silent underenforcement, one cap over.
    """

    _DECL = BudgetDeclaration(daily_key="daily_budget_micros", micros=True)
    _CAPS_TOTAL = Guardrails(max_total_daily_budget=50_000.0)

    def test_the_total_cap_still_fires_for_a_declaring_tool(self) -> None:
        decision = evaluate_guardrails(
            "t",
            {
                "daily_budget_micros": 15_000_000_000,
                "projected_total_daily_budget": 120_000,
            },
            self._CAPS_TOTAL,
            budget_declaration=self._DECL,
        )
        assert decision.allowed is False
        assert "max_total_daily_budget" in (decision.reason or "")

    def test_under_the_total_cap_is_allowed(self) -> None:
        decision = evaluate_guardrails(
            "t",
            {
                "daily_budget_micros": 15_000_000_000,
                "projected_total_daily_budget": 40_000,
            },
            self._CAPS_TOTAL,
            budget_declaration=self._DECL,
        )
        assert decision.allowed is True

    @pytest.mark.parametrize(
        "value", [float("nan"), float("inf"), float("-inf"), int("9" * 309)]
    )
    def test_a_non_finite_total_is_denied(self, value: Any) -> None:
        """Held to #419's fail-closed standard like every other channel."""
        decision = evaluate_guardrails(
            "t",
            {
                "daily_budget_micros": 15_000_000_000,
                "projected_total_daily_budget": value,
            },
            self._CAPS_TOTAL,
            budget_declaration=self._DECL,
        )
        assert decision.allowed is False
        assert "projected_total_daily_budget" in (decision.reason or "")


@pytest.mark.unit
class TestUnreadableFallbackCurrent:
    """The fallback ``current`` is a budget channel, so #419 governs it too.

    Every budget channel funnels through one choke point that saturates an
    oversized int and refuses a non-finite figure (#419). The fallback reaches
    ``current_daily_budget`` on a path the built-in scan does not walk, so it
    has to be held to the same standard — otherwise a declaring plugin gets a
    baseline the built-in gate would have refused, and in the dangerous
    direction: ``nan > 0`` is False, which takes the percentage cap dark, and a
    bare oversized int raises ``OverflowError`` into
    ``StrategyPolicyGate.evaluate``'s blanket ``except`` — an abstain, i.e. an
    allow. Both are the exact bypasses #419 closed on the built-in path.
    """

    _DECL = BudgetDeclaration(daily_key="daily_budget_micros", micros=True)
    _CAPS_PCT = Guardrails(max_daily_budget_increase_pct=20.0)

    @pytest.mark.parametrize(
        "value",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
            int("9" * 309),  # bare int: float() raises OverflowError, not inf
        ],
    )
    def test_a_non_finite_fallback_current_is_denied(self, value: Any) -> None:
        decision = evaluate_guardrails(
            "t",
            {"daily_budget_micros": 15_000_000_000, "current_daily_budget": value},
            self._CAPS_PCT,
            budget_declaration=self._DECL,
        )
        assert decision.allowed is False
        assert "current_daily_budget" in (decision.reason or "")

    def test_it_matches_the_built_in_scan(self) -> None:
        """Same garbage baseline, same verdict, declared or not — the seam must
        not be a weaker gate than the one it replaces."""
        args = {"current_daily_budget": float("nan")}
        declared = evaluate_guardrails(
            "t",
            {**args, "daily_budget_micros": 15_000_000_000},
            self._CAPS_PCT,
            budget_declaration=self._DECL,
        )
        built_in = evaluate_guardrails(
            "t", {**args, "daily_budget": 15_000}, self._CAPS_PCT
        )
        assert declared.allowed == built_in.allowed is False
