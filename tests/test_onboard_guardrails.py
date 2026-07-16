"""onboard must proactively offer budget guardrails (#364).

v0.10.18 shipped hard budget-guardrail enforcement (``StrategyPolicyGate``
refuses native ``google_ads_*`` / ``meta_ads_*`` budget mutations that violate
a ``## Guardrails`` section in STRATEGY.md), but the gate is fail-open and there
was no onboarding prompt — so the safety feature stayed dormant for operators
who did not know to ask. onboard now offers to set the section during setup.
This pins that the step is present (with the machine-readable keys), skippable,
and honest about its native-only scope, in BOTH copies kept byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = _ROOT / "mureo" / "_data" / "skills" / "onboard" / "SKILL.md"
_MIRROR = _ROOT / "skills" / "onboard" / "SKILL.md"


def _body() -> str:
    return _PACKAGED.read_text(encoding="utf-8")


def test_onboard_copies_are_byte_identical() -> None:
    assert _PACKAGED.read_bytes() == _MIRROR.read_bytes()


def test_offers_the_guardrails_section_with_the_machine_keys() -> None:
    body = _body()
    assert "## Guardrails" in body
    for key in (
        "max_daily_budget_per_campaign",
        "max_daily_budget_increase_pct",
        "max_total_daily_budget",
        "blocked_operations",
    ):
        assert key in body, f"onboard does not seed {key}"
    # References the enforcement mechanism / its format source of truth.
    assert "StrategyPolicyGate" in body


def test_guardrails_offer_is_skippable() -> None:
    """Declining leaves the section absent (fail-open, unchanged behaviour)."""
    body = _body()
    assert "no guardrails for now" in body.lower()


def test_guardrails_scope_is_honest() -> None:
    """The copy states hard enforcement covers only mureo-dispatched native
    google_ads/meta_ads — hosted/official MCPs bypass the gate (#359)."""
    body = _body()
    assert "#359" in body
