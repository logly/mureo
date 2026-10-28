"""The last five import cycles of the #879 inventory stay removed (stage 4).

Each pair below used to close a cycle that a function-local import kept open
(``# noqa: PLC0415 — import cycle: ... (#879)``):

- ``monthly_budget`` read the platform-configured sum, and
  ``platform_monthly_budget`` imported ``MonthlyBudget`` back. The dataclass
  and its source constants now live in
  :mod:`mureo.context.monthly_budget_models`, which imports nothing from
  mureo at runtime.
- ``monthly_budget`` read the guardrail ceiling through ``strategy_gate``,
  which reaches the ``mureo.context`` package (and so ``monthly_budget``)
  through ``context.strategy``. The guardrail parser now lives in
  :mod:`mureo.policy.guardrails`, which imports nothing from
  ``mureo.context``.
- ``platform_guards`` read the analytics entry-point group from
  ``analytics.registry``, whose package loads the built-in modules, which
  load ``context.state`` and so ``platform_guards``. The group name is now
  defined in :mod:`mureo.core.platform_keys`.
- ``analytics.registry`` and ``change_import.registry`` loaded their
  built-ins, which imported the registry back to register themselves. The
  built-in packages now only build the instances (``builtin_*()``) and the
  registry registers them.

Every side and both new modules have to import as the FIRST import of a
fresh interpreter; the removed back-edges are pinned on the source, function
bodies included; and no line under ``mureo/`` carries the #879 cycle marker
any more, which closes the inventory.
"""

from __future__ import annotations

import pathlib

import pytest

import mureo
from tests._measurement_child import StandaloneSweep, assert_imports_alone
from tests.test_import_cycles_stage1 import _imports_from

#: ``(a, b)`` — the two sides of each cycle removed in stage 4.
REMOVED_CYCLES: tuple[tuple[str, str], ...] = (
    ("mureo.context.monthly_budget", "mureo.context.platform_monthly_budget"),
    ("mureo.context.monthly_budget", "mureo.policy.strategy_gate"),
    ("mureo.context.platform_guards", "mureo.analytics.registry"),
    ("mureo.analytics.registry", "mureo.analytics.builtin"),
    ("mureo.change_import.registry", "mureo.change_import.builtin"),
)

#: The modules the shared names moved into; each has to import first too.
NEW_LOWER_MODULES: tuple[str, ...] = (
    "mureo.context.monthly_budget_models",
    "mureo.policy.guardrails",
)

#: Every side of every pair plus the new lower modules, once, in first-seen
#: order.
CYCLE_SIDES: tuple[str, ...] = tuple(
    dict.fromkeys(
        (*(side for pair in REMOVED_CYCLES for side in pair), *NEW_LOWER_MODULES)
    )
)

#: ``(module, target)`` — an import (top level or function-local) that would
#: reopen one of the cycles above. ``TYPE_CHECKING`` imports do not count.
FORBIDDEN_EDGES: tuple[tuple[str, str], ...] = (
    ("mureo.context.platform_monthly_budget", "mureo.context.monthly_budget"),
    ("mureo.context.monthly_budget", "mureo.policy.strategy_gate"),
    ("mureo.policy.guardrails", "mureo.context"),
    ("mureo.context.monthly_budget_models", "mureo"),
    ("mureo.context.platform_guards", "mureo.analytics"),
    ("mureo.analytics.builtin", "mureo.analytics.registry"),
    ("mureo.change_import.builtin", "mureo.change_import.registry"),
)

#: ``(module, target)`` — the import that replaced each function-local one,
#: now made at module level.
TOP_LEVEL_EDGES: tuple[tuple[str, str], ...] = (
    ("mureo.analytics.registry", "mureo.analytics.builtin"),
    ("mureo.change_import.registry", "mureo.change_import.builtin"),
    ("mureo.context.monthly_budget", "mureo.context.platform_monthly_budget"),
    ("mureo.context.monthly_budget", "mureo.policy.guardrails"),
    ("mureo.context.platform_guards", "mureo.core.platform_keys"),
)

#: The whole package, scanned for leftover cycle markers.
_MUREO_DIR = pathlib.Path(mureo.__file__).parent

#: The two halves of the marker a cycle-driven function-local import carried.
_NOQA_RULE = "PLC0415"
_CYCLE_ISSUE = "#879"


@pytest.mark.unit
@pytest.mark.parametrize("module", CYCLE_SIDES)
def test_each_side_imports_as_the_first_import(
    module: str, standalone_sweep: StandaloneSweep
) -> None:
    returncode, stderr = standalone_sweep.result(module, CYCLE_SIDES)
    assert_imports_alone(module, returncode, stderr)


@pytest.mark.unit
@pytest.mark.parametrize(("module", "target"), FORBIDDEN_EDGES)
def test_a_removed_back_edge_stays_removed(module: str, target: str) -> None:
    assert _imports_from(module, target) == []


@pytest.mark.unit
@pytest.mark.parametrize(("module", "target"), TOP_LEVEL_EDGES)
def test_the_forward_edge_is_a_top_level_import(module: str, target: str) -> None:
    assert target in _imports_from(module, target, top_level_only=True)


@pytest.mark.unit
def test_no_mureo_module_keeps_a_cycle_driven_function_local_import() -> None:
    """No line under ``mureo/`` carries the #879 ``PLC0415`` marker any more."""
    leftovers = [
        f"{path.relative_to(_MUREO_DIR)}:{number}"
        for path in sorted(_MUREO_DIR.rglob("*.py"))
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if _NOQA_RULE in line and _CYCLE_ISSUE in line
    ]
    assert leftovers == []
