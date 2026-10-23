"""The load-time import cycles removed in #879 stage 1 stay removed.

Each pair below used to close a cycle that a function-local import kept
open (``# noqa: PLC0415 — import cycle: ... (#879)``). The shared names now
live one layer down (``mureo.cli._skill_paths``,
``mureo.core.tool_names.MUTATION_PREFIXES``, ``mureo.mcp._plugin_tables``,
``mureo.google_ads._placement_mappers``,
``mureo.creative_studio.providers._base``, and since #917
``mureo.context.state_io`` / ``mureo.context.campaign_store``) and both
sides import at top level, so either side has to import as the FIRST import
of a fresh interpreter. A reintroduced back-import fails here in the default suite,
rather than only in the exhaustive ``-m slow`` sweep of every module.

The #917 store modules are also pinned statically, by the source walker of
:mod:`tests.test_import_graph`: ``state_io`` imports neither the facade nor a
store, and a store imports no other store but the one known edge.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

import mureo
from tests._measurement_child import (
    StandaloneSweep,
    assert_imports_alone,
    run_in_fresh_interpreter,
)
from tests.test_import_graph import _imports_of, _package_of

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
    # #917: the lock, the clock and the platform-entry helpers moved below
    # ``mureo.context.state``. ``decisions``, ``settings`` and
    # ``action_log_guard`` still cycle with ``state_io`` (through
    # ``state_codec`` / ``write_state_file``), so they are not listed.
    ("mureo.context.daily", "mureo.context.state"),
    ("mureo.context.ops_linkage", "mureo.context.state"),
)

#: The modules the shared names moved into; each has to import first too.
NEW_LOWER_MODULES: tuple[str, ...] = (
    "mureo.cli._skill_paths",
    "mureo.mcp._plugin_tables",
    "mureo.creative_studio.providers._base",
    "mureo.context.state_io",
    "mureo.context.campaign_store",
    "mureo.context.action_log_store",
    "mureo.context.batch_store",
    "mureo.context.platform_store",
    "mureo.context.report_store",
)

#: The store modules split out of ``mureo.context.state`` (#917).
_STATE_STORES: tuple[str, ...] = (
    "mureo.context.campaign_store",
    "mureo.context.action_log_store",
    "mureo.context.batch_store",
    "mureo.context.platform_store",
    "mureo.context.report_store",
)

#: The one store -> store import: a platform entry is built on the campaign
#: store's platform-entry helpers.
_ALLOWED_STORE_EDGES: frozenset[tuple[str, str]] = frozenset(
    {("mureo.context.platform_store", "mureo.context.campaign_store")}
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


def _imports_from(module: str, target: str) -> list[str]:
    """The ``target*`` modules ``module``'s source imports, outside TYPE_CHECKING."""
    path = pathlib.Path(mureo.__file__).parent.joinpath(*module.split(".")[1:])
    path = path.with_suffix(".py")
    tree = ast.parse(path.read_text("utf-8"))
    return [name for _, name in _imports_of(tree, _package_of(path), target)]


@pytest.mark.unit
def test_state_io_imports_neither_the_facade_nor_a_store() -> None:
    """``state_io`` is the bottom of the split; nothing above may come back in."""
    found = [
        name
        for target in ("mureo.context.state", *_STATE_STORES)
        for name in _imports_from("mureo.context.state_io", target)
    ]
    assert found == []


@pytest.mark.unit
@pytest.mark.parametrize("store", _STATE_STORES)
def test_a_store_imports_no_other_store(store: str) -> None:
    edges = {
        (store, name)
        for other in _STATE_STORES
        if other != store
        for name in _imports_from(store, other)
    }
    assert edges <= _ALLOWED_STORE_EDGES
