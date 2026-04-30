"""Registry of demo scenarios for ``mureo demo init --scenario <name>``.

To add a new scenario:
  1. Drop a module under ``mureo/demo/scenarios/`` exposing a
     ``SCENARIO: Scenario`` constant (see ``_base.Scenario``).
  2. Import it here and add it to :data:`SCENARIOS`.
  3. Confirm it passes the parametrized contract tests in
     ``tests/test_demo_scenarios.py`` — those run automatically for
     every entry in :data:`SCENARIOS`.
"""

from __future__ import annotations

from mureo.demo.scenarios import seasonality_trap
from mureo.demo.scenarios._base import Scenario, campaign_id

SCENARIOS: dict[str, Scenario] = {
    seasonality_trap.SCENARIO.name: seasonality_trap.SCENARIO,
}

DEFAULT_SCENARIO: str = seasonality_trap.SCENARIO.name


def get_scenario(name: str | None) -> Scenario:
    """Resolve a scenario name to its :class:`Scenario` instance.

    Args:
        name: Scenario key, or ``None`` to get :data:`DEFAULT_SCENARIO`.

    Returns:
        The matching scenario.

    Raises:
        ValueError: when ``name`` is not registered, with a message
            listing every available key.
    """
    if name is None:
        name = DEFAULT_SCENARIO
    if name not in SCENARIOS:
        available = ", ".join(sorted(SCENARIOS))
        raise ValueError(f"Unknown scenario: {name!r}. Available: {available}")
    return SCENARIOS[name]


__all__ = [
    "DEFAULT_SCENARIO",
    "SCENARIOS",
    "Scenario",
    "campaign_id",
    "get_scenario",
]
