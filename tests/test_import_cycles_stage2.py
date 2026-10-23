"""The ``mureo.mcp.server`` back-imports removed in #879 stage 2 stay removed.

Three hooks below ``server`` used to import it from inside a function
(``# noqa: PLC0415 — import cycle: ... -> mureo.mcp.server (#879)``): the
journal hook for the family name sets, the automatic-evaluation hook for the
policy gates, and the rollback handlers for the dispatcher. ``server`` now
publishes those through :mod:`mureo.mcp._server_slots` at the end of its load
and the hooks import that module at top level.

What is verified here, and what is not: a child interpreter that imports a
hook still runs ``mureo/mcp/__init__.py`` first, and that imports ``server``,
so a child cannot tell "hook imported first" from "server imported first".
The children therefore only show that each hook (and the slots module)
imports cleanly in a fresh interpreter and finds the slots published. That
no hook imports ``server`` back — top level or function-local, with or
without a marker comment — is checked on the source, by an AST scan.
"""

from __future__ import annotations

import ast
import json
import pathlib
from unittest.mock import AsyncMock

import pytest

from mureo.core.policy import PolicyDecision
from mureo.mcp import (
    _auto_evaluation_hook,
    _handlers_rollback,
    _server_slots,
    journal,
    server,
)
from tests._measurement_child import (
    StandaloneSweep,
    assert_imports_alone,
    run_in_fresh_interpreter,
)
from tests.test_import_graph import _imports_of, _package_of

#: ``(a, b)`` — the hook and the module it no longer imports from a function.
REMOVED_CYCLES: tuple[tuple[str, str], ...] = (
    ("mureo.mcp._journal_hook", "mureo.mcp.server"),
    ("mureo.mcp._auto_evaluation_hook", "mureo.mcp.server"),
    ("mureo.mcp._handlers_rollback", "mureo.mcp.server"),
)

#: Every module a fresh interpreter has to import cleanly: each hook, then
#: the slots module.
FRESH_IMPORTS: tuple[str, ...] = (
    *(hook for hook, _ in REMOVED_CYCLES),
    "mureo.mcp._server_slots",
)

#: The ``mureo/mcp`` package directory, scanned for leftover cycle markers.
_MCP_DIR = pathlib.Path(__file__).resolve().parent.parent / "mureo" / "mcp"

#: The two halves of the marker a cycle-driven function-local import carried.
_NOQA_RULE = "PLC0415"
_CYCLE_ISSUE = "#879"

#: Slot name → the ``require_*`` function that reads it.
_REQUIRERS = {
    "tool_families": _server_slots.require_tool_families,
    "dispatcher": _server_slots.require_dispatcher,
    "policy_evaluator": _server_slots.require_policy_evaluator,
}

#: Child: import the module named in ``argv[1]``, then report which slots
#: ``server`` left unset.
_SLOTS_AFTER_IMPORT = (
    "import importlib, json, sys\n"
    "importlib.import_module(sys.argv[1])\n"
    "from mureo.mcp import _server_slots\n"
    "print(json.dumps(sorted(slot for slot in sys.argv[2:]"
    " if getattr(_server_slots, slot) is None)))\n"
)

#: The reason the monkeypatched gate below denies with.
_DENIAL_REASON = "read-only mode is active"


def _deny(_name: str, _arguments: dict[str, object]) -> PolicyDecision:
    return PolicyDecision(allowed=False, reason=_DENIAL_REASON)


@pytest.mark.unit
@pytest.mark.parametrize("module", FRESH_IMPORTS)
def test_each_module_imports_cleanly_in_a_fresh_interpreter(
    module: str, standalone_sweep: StandaloneSweep
) -> None:
    """Imports without error in a child; the package ``__init__`` loads
    ``server`` first, so this does not prove the hook can be imported before
    it — the AST scan below is what rules out a back-import."""
    returncode, stderr = standalone_sweep.result(module, FRESH_IMPORTS)
    assert_imports_alone(module, returncode, stderr)


@pytest.mark.unit
@pytest.mark.parametrize(("hook", "server_module"), REMOVED_CYCLES)
def test_hook_source_never_imports_the_server(hook: str, server_module: str) -> None:
    """Any ``import`` / ``from ... import`` of ``server`` in the hook's source,
    top level or function-local, marker comment or not."""
    path = _MCP_DIR / f"{hook.rpartition('.')[2]}.py"
    found = _imports_of(
        ast.parse(path.read_text("utf-8")), _package_of(path), server_module
    )
    assert found == []


@pytest.mark.unit
@pytest.mark.parametrize("hook", [hook for hook, _ in REMOVED_CYCLES])
def test_server_has_published_every_slot_once_a_hook_is_imported(hook: str) -> None:
    proc = run_in_fresh_interpreter(_SLOTS_AFTER_IMPORT, hook, *sorted(_REQUIRERS))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


@pytest.mark.unit
def test_no_mcp_module_keeps_a_cycle_driven_function_local_import() -> None:
    """No ``mureo/mcp`` line carries the #879 ``PLC0415`` marker any more."""
    leftovers = [
        f"{path.name}:{number}"
        for path in sorted(_MCP_DIR.rglob("*.py"))
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if _NOQA_RULE in line and _CYCLE_ISSUE in line
    ]
    assert leftovers == []


@pytest.mark.unit
@pytest.mark.parametrize("slot", sorted(_REQUIRERS))
def test_an_unpublished_slot_raises_naming_it(
    slot: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_server_slots, slot, None)
    with pytest.raises(RuntimeError, match=rf"has not been loaded; {slot} is unset"):
        _REQUIRERS[slot]()


@pytest.mark.unit
def test_auto_evaluation_policy_denial_follows_a_monkeypatched_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The published evaluator resolves ``_evaluate_policy_gates`` from the
    server's globals per call, so patching the server steers the hook."""
    monkeypatch.setattr(server, "_evaluate_policy_gates", _deny)
    assert _auto_evaluation_hook._policy_denial("rollback_apply") == _DENIAL_REASON


@pytest.mark.unit
async def test_rollback_dispatcher_policy_denial_follows_a_monkeypatched_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The dispatcher ``rollback_apply`` re-enters is the live server's, so a
    patched gate refuses the leg before any handler runs."""
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "JOURNAL.jsonl")
    monkeypatch.setattr(server, "_evaluate_policy_gates", _deny)
    handler = AsyncMock()
    monkeypatch.setattr(server, "handle_rollback_tool", handler)

    dispatcher = _handlers_rollback._get_dispatcher()
    result = await dispatcher("rollback_apply", {"index": 0, "confirm": True})

    handler.assert_not_awaited()
    assert f"Reason: {_DENIAL_REASON}" in result[0].text
