"""Regression tests: a raise from a zero baseline cannot skip the pct cap (M4).

``max_daily_budget_increase_pct`` is a *percentage* cap. From ``current == 0`` a
percentage increase is unbounded — no finite raise can satisfy it — so the old
``current > 0`` guard let a ``0 -> any-amount`` jump skip the cap entirely. When
the percentage cap is the only budget rule the operator wrote (no absolute cap),
that raise then hit no cap at all. The gate now fails CLOSED on that case,
consistent with the rest of its fail-closed contract.
"""

from __future__ import annotations

import pytest

from mureo.policy.strategy_gate import Guardrails, evaluate_guardrails


@pytest.mark.unit
class TestZeroBaselineIncrease:
    def test_zero_current_positive_proposed_denies_pct_only(self) -> None:
        """pct cap only, no absolute cap: 0 -> positive must be refused."""
        g = Guardrails(max_daily_budget_increase_pct=20)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 50000, "current_daily_budget": 0},
            g,
        )
        assert d.allowed is False
        assert d.reason is not None
        assert "max_daily_budget_increase_pct" in d.reason

    def test_zero_current_denies_even_with_absolute_cap_room(self) -> None:
        """The percentage rule is independent of the absolute cap: 0 -> a value
        under the absolute cap is still an unbounded percentage jump, so it is
        refused on the pct rule (fail-closed, single choke point)."""
        g = Guardrails(
            max_daily_budget_increase_pct=20,
            max_daily_budget_per_campaign=100000,
        )
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 50000, "current_daily_budget": 0},
            g,
        )
        assert d.allowed is False

    def test_zero_current_zero_proposed_allows(self) -> None:
        """0 -> 0 is not an increase, so it must not be refused."""
        g = Guardrails(max_daily_budget_increase_pct=20)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 0, "current_daily_budget": 0},
            g,
        )
        assert d.allowed is True

    def test_no_current_baseline_still_allows(self) -> None:
        """When no ``current_daily_budget`` baseline is supplied the pct cap is
        unevaluable and must be skipped (unchanged behaviour) — only an
        explicit zero baseline trips the new guard."""
        g = Guardrails(max_daily_budget_increase_pct=20)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 50000},
            g,
        )
        assert d.allowed is True

    def test_positive_current_within_pct_still_allows(self) -> None:
        """The normal positive-baseline path is unaffected by the new branch."""
        g = Guardrails(max_daily_budget_increase_pct=20)
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 11000, "current_daily_budget": 10000},
            g,
        )
        assert d.allowed is True

    def test_zero_current_absolute_cap_exceeded_still_denies(self) -> None:
        """When the proposed value also exceeds the absolute cap, the absolute
        cap denies first — the outcome is still a refusal."""
        g = Guardrails(
            max_daily_budget_increase_pct=20,
            max_daily_budget_per_campaign=40000,
        )
        d = evaluate_guardrails(
            "google_ads_budget_update",
            {"daily_budget": 50000, "current_daily_budget": 0},
            g,
        )
        assert d.allowed is False
