"""The load-time import cycles removed in #879 stage 1 stay removed.

Each pair below used to close a cycle that a function-local import kept
open (``# noqa: PLC0415 — import cycle: ... (#879)``). The shared names now
live one layer down (``mureo.cli._skill_paths``,
``mureo.core.tool_names.MUTATION_PREFIXES``, ``mureo.mcp._plugin_tables``,
``mureo.google_ads._placement_mappers``,
``mureo.creative_studio.providers._base``) and both sides import at top
level, so either side has to import as the FIRST import of a fresh
interpreter. A reintroduced back-import fails here in the default suite,
rather than only in the exhaustive ``-m slow`` sweep of every module.
"""

from __future__ import annotations

import json

import pytest

from tests._measurement_child import (
    StandaloneSweep,
    assert_imports_alone,
    run_in_fresh_interpreter,
)

#: ``(a, b)`` — the two sides of each cycle removed in stage 1.
REMOVED_CYCLES: tuple[tuple[str, str], ...] = (
    ("mureo.cli.setup_cmd", "mureo.cli.native_skills"),
    ("mureo.cli.setup_cmd", "mureo.cli.setup_codex"),
    ("mureo.analysis.delivery_collapse", "mureo.policy.strategy_gate"),
    ("mureo.mcp._journal_hook", "mureo.mcp.server"),
    ("mureo.google_ads._placement_mappers", "mureo.google_ads._placements"),
    ("mureo.creative_studio.providers", "mureo.creative_studio.providers.codex_cli"),
    ("mureo.creative_studio.providers", "mureo.creative_studio.providers.fal"),
    (
        "mureo.creative_studio.providers",
        "mureo.creative_studio.providers.google_images",
    ),
    (
        "mureo.creative_studio.providers",
        "mureo.creative_studio.providers.openai_images",
    ),
)

#: The modules the shared names moved into; each has to import first too.
NEW_LOWER_MODULES: tuple[str, ...] = (
    "mureo.cli._skill_paths",
    "mureo.mcp._plugin_tables",
    "mureo.creative_studio.providers._base",
)

#: Every side of every pair plus the new lower modules, once, in first-seen
#: order.
CYCLE_SIDES: tuple[str, ...] = tuple(
    dict.fromkeys(
        (*(side for pair in REMOVED_CYCLES for side in pair), *NEW_LOWER_MODULES)
    )
)

#: Child: import ``mureo.core.tool_names`` and nothing else, then report which
#: ``mureo.byod`` modules came with it.
_TOOL_NAMES_ALONE = (
    "import json, sys\n"
    "import mureo.core.tool_names\n"
    "print(json.dumps(sorted(m for m in sys.modules"
    " if m == 'mureo.byod' or m.startswith('mureo.byod.'))))\n"
)


@pytest.mark.unit
@pytest.mark.parametrize("module", CYCLE_SIDES)
def test_each_side_imports_as_the_first_import(
    module: str, standalone_sweep: StandaloneSweep
) -> None:
    returncode, stderr = standalone_sweep.result(module, CYCLE_SIDES)
    assert_imports_alone(module, returncode, stderr)


@pytest.mark.unit
def test_core_tool_names_loads_nothing_from_byod() -> None:
    """``core`` owns ``MUTATION_PREFIXES``; it never imports ``byod`` (#879)."""
    proc = run_in_fresh_interpreter(_TOOL_NAMES_ALONE)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []
