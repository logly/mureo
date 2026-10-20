"""The import graph between ``mureo.core`` and ``mureo.context`` (#863).

``mureo.core`` is the lower layer. It used to import ``mureo.context`` at load
time (``core/__init__`` -> ``runtime_context`` -> ``state_store`` ->
``mureo.context.state``), so any top-level ``from mureo.core.<x> import ...``
inside ``mureo.context`` failed with a partially initialised module whenever a
``context`` module was imported first — and two dozen imports in ``context``
were function-local only to dodge that. The default ``FilesystemStateStore``
now lives in :mod:`mureo.context.state_store`, ``runtime_context`` reaches it
by object reference, and these tests pin the direction:

* importing ``mureo.core`` alone loads nothing from ``mureo.context``;
* either package can be imported first;
* ``pytest -m slow``: every module under ``mureo/`` imports on its own, as the
  first import of a fresh interpreter.

The children are the same ones :mod:`tests.test_platform_submodule_imports`
runs (``tests/_measurement_child.py``, shared through the ``standalone_sweep``
fixture), so nothing the parent has imported can warm a cycle for them.
"""

from __future__ import annotations

import json
import pkgutil

import pytest

import mureo
import mureo.context
import mureo.core
import mureo.core.state_store
from mureo.context.state_store import FilesystemStateStore
from tests._measurement_child import (
    StandaloneSweep,
    assert_imports_alone,
    run_in_fresh_interpreter,
)

#: Child: import ``mureo.core`` and nothing else, then report which
#: ``mureo.context`` modules came with it.
_CORE_ALONE = (
    "import json, sys\n"
    "import mureo.core\n"
    "print(json.dumps(sorted(m for m in sys.modules"
    " if m == 'mureo.context' or m.startswith('mureo.context.'))))\n"
)


def _raise_on_unimportable_package(name: str) -> None:
    """Fail collection instead of silently dropping a package's submodules.

    ``pkgutil.walk_packages`` imports each package to find its children and,
    by default, skips one that raises — which would shrink the sweep without
    anyone noticing.
    """
    raise ImportError(f"cannot walk {name}: importing it failed")


def _all_mureo_modules() -> list[str]:
    return [
        info.name
        for info in pkgutil.walk_packages(
            mureo.__path__, "mureo.", onerror=_raise_on_unimportable_package
        )
    ]


#: The ``slow`` lane: every module under ``mureo/``.
ALL_MUREO_MODULES = tuple(_all_mureo_modules())


@pytest.mark.unit
def test_core_alone_loads_nothing_from_context() -> None:
    """``mureo.core`` sits below ``mureo.context`` and must not import it."""
    proc = run_in_fresh_interpreter(_CORE_ALONE)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("first", "second"),
    [("mureo.context", "mureo.core"), ("mureo.core", "mureo.context")],
)
def test_core_and_context_import_in_either_order(first: str, second: str) -> None:
    proc = run_in_fresh_interpreter(f"import {first}\nimport {second}\n")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.unit
def test_filesystem_state_store_resolves_from_every_published_path() -> None:
    """The class moved to ``mureo.context.state_store``; ``mureo.core`` (an ABI
    re-export) and the old ``mureo.core.state_store`` path still resolve to it.
    """
    assert mureo.core.FilesystemStateStore is FilesystemStateStore
    assert mureo.core.state_store.FilesystemStateStore is FilesystemStateStore
    assert mureo.context.FilesystemStateStore is FilesystemStateStore
    with pytest.raises(AttributeError):
        _ = mureo.core.NoSuchName
    with pytest.raises(AttributeError):
        _ = mureo.core.state_store.NoSuchName


@pytest.mark.slow
@pytest.mark.parametrize("module", ALL_MUREO_MODULES)
@pytest.mark.usefixtures("only_when_asked_for")
def test_every_mureo_module_imports_as_the_first_import(
    module: str, standalone_sweep: StandaloneSweep
) -> None:
    returncode, stderr = standalone_sweep.result(module, ALL_MUREO_MODULES)
    assert_imports_alone(module, returncode, stderr)
