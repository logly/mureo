"""Every platform submodule must import on its own, as the first import.

A package ``__init__`` that eagerly imports the API client hides an import
cycle: ``client`` imports the mixins to build its class, the mixins import a
shared helper back out of ``client``, and that only resolves because
``__init__`` guaranteed ``client`` was the module that started executing.
Removing the eager import for the MCP server's startup budget (#807) removed
that guarantee, and importing a mixin *first* then failed with
``ImportError: cannot import name ... from partially initialized module``.

The full suite does not catch this: some earlier-collected test module imports
``client`` and warms the cycle for everyone behind it. What breaks is a single
file (``pytest tests/test_google_ads_extensions.py``), ``--lf``, and ``-k``
filtering — the everyday development loop, and nothing CI runs.

So each submodule is imported first in a child interpreter of its own. That is
one process per module, and sweeping both packages whole cost 57 s of the
suite's wall time — more than the problem is worth paying for on every run. Two
lanes instead:

* the default lane sweeps the submodules that **import a sibling**, found by
  reading the source rather than by listing them (an import cycle needs an edge,
  and this is where the edges are);
* ``pytest -m slow`` sweeps every submodule, for the case where the shape of the
  cycle is not what we think it is.

Both lanes share one sweeper, so asking for both does not pay twice.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from tests._measurement_child import CHILD_TIMEOUT_SECONDS, measurement_child_env

if TYPE_CHECKING:
    from collections.abc import Sequence

# Packages whose submodules must each be importable first. Both are mixin-built
# API clients with the same shape, and both have a lazy ``__init__`` (#807).
STANDALONE_IMPORT_PACKAGES = ("mureo.google_ads", "mureo.meta_ads")

# Child interpreters to keep in flight. Each one imports one submodule and
# exits; the work is process startup plus the submodule's own imports, so a
# handful in parallel keeps the sweep off the suite's critical path without
# oversubscribing a CI runner.
_MAX_IN_FLIGHT = 8


def _package_submodules(package: str) -> list[str]:
    """Fully qualified names of ``package``'s submodules, without importing it."""
    names = []
    for location in _package_locations(package):
        for path in sorted(location.glob("*.py")):
            if path.name != "__init__.py":
                names.append(f"{package}.{path.stem}")
    return names


def _package_subpackages(package: str) -> list[str]:
    """Fully qualified names of ``package``'s sub*packages*, if it grows any.

    :func:`_package_submodules` globs ``*.py``, so a subpackage would drop out of
    the sweep without anyone noticing. There are none today; the test below says
    so, and fails if that changes.
    """
    return [
        f"{package}.{path.name}"
        for location in _package_locations(package)
        for path in sorted(location.iterdir())
        if (path / "__init__.py").is_file()
    ]


def _package_locations(package: str) -> list[pathlib.Path]:
    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.submodule_search_locations is not None, package
    return [pathlib.Path(location) for location in spec.submodule_search_locations]


def _module_path(module: str) -> pathlib.Path:
    package, _, stem = module.rpartition(".")
    return _package_locations(package)[0] / f"{stem}.py"


def _imports_inside(package: str, path: pathlib.Path) -> bool:
    """Whether ``path``'s source imports anything from its own package.

    Static, because importing it to find out is the very thing under test. Both
    spellings count: ``from mureo.google_ads.x import y`` and the relative
    ``from .x import y`` (nothing in-tree uses the latter today, and a cycle
    written that way would be just as real). A module counts as inside the
    package by name, not by prefix: ``mureo.google_adsx`` is not
    ``mureo.google_ads``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0:
                return True
            if node.module is not None and _is_inside(node.module, package):
                return True
        elif isinstance(node, ast.Import):
            if any(_is_inside(alias.name, package) for alias in node.names):
                return True
    return False


def _is_inside(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def _all_submodules() -> list[str]:
    return [
        name
        for package in STANDALONE_IMPORT_PACKAGES
        for name in _package_submodules(package)
    ]


def _sibling_importing_submodules() -> list[str]:
    return [
        name
        for package in STANDALONE_IMPORT_PACKAGES
        for name in _package_submodules(package)
        if _imports_inside(package, _module_path(name))
    ]


#: The default lane: the submodules that can be in a cycle at all.
SIBLING_IMPORTING_SUBMODULES = tuple(_sibling_importing_submodules())
#: The ``slow`` lane: all of them.
ALL_SUBMODULES = tuple(_all_submodules())


def _import_alone(module: str, env: dict[str, str]) -> tuple[str, int, str]:
    proc = subprocess.run(
        [sys.executable, "-c", f"__import__({module!r})"],
        capture_output=True,
        text=True,
        env=env,
        timeout=CHILD_TIMEOUT_SECONDS,
    )
    return module, proc.returncode, proc.stderr


class _StandaloneSweep:
    """Imports modules first, each in its own child, once per session."""

    def __init__(self) -> None:
        self._results: dict[str, tuple[int, str]] = {}

    def result(self, module: str, within: Sequence[str]) -> tuple[int, str]:
        """Return ``module``'s outcome, sweeping all of ``within`` if needed.

        Taking the whole lane rather than one module keeps the child spawning
        batched — one pass of ``_MAX_IN_FLIGHT`` at a time instead of one
        process per test — while the memo means the two lanes never sweep the
        same module twice.
        """
        missing = [name for name in within if name not in self._results]
        if missing:
            env = measurement_child_env()
            with ThreadPoolExecutor(max_workers=_MAX_IN_FLIGHT) as pool:
                for name, code, stderr in pool.map(
                    lambda candidate: _import_alone(candidate, env), missing
                ):
                    self._results[name] = (code, stderr)
        return self._results[module]


@pytest.fixture(scope="session")
def standalone_sweep() -> _StandaloneSweep:
    """One sweeper for the session, so both lanes share their children."""
    return _StandaloneSweep()


def _assert_imports_alone(module: str, returncode: int, stderr: str) -> None:
    assert returncode == 0, (
        f"{module} cannot be imported first. Something it imports imports it "
        f"back — move the shared name into a leaf module instead of relying on "
        f"a package __init__ to enter the cycle at a lucky point.\n{stderr}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("module", SIBLING_IMPORTING_SUBMODULES)
def test_submodule_with_a_sibling_import_imports_as_the_first_import(
    module: str, standalone_sweep: _StandaloneSweep
) -> None:
    returncode, stderr = standalone_sweep.result(module, SIBLING_IMPORTING_SUBMODULES)
    _assert_imports_alone(module, returncode, stderr)


@pytest.mark.slow
@pytest.mark.parametrize("module", ALL_SUBMODULES)
@pytest.mark.usefixtures("only_when_asked_for")
def test_every_submodule_imports_as_the_first_import(
    module: str, standalone_sweep: _StandaloneSweep
) -> None:
    returncode, stderr = standalone_sweep.result(module, ALL_SUBMODULES)
    _assert_imports_alone(module, returncode, stderr)


#: The default lane held 33 submodules when this was written (27 Google Ads, 6
#: Meta). The floor sits near that rather than near zero, so a scan that quietly
#: lost most of the lane fails here; lower it when sibling imports are removed.
_DEFAULT_LANE_FLOOR = 30


@pytest.mark.unit
def test_the_default_lane_is_not_empty() -> None:
    """A source-driven lane that silently finds nothing would pass forever."""
    assert len(SIBLING_IMPORTING_SUBMODULES) >= _DEFAULT_LANE_FLOOR, len(
        SIBLING_IMPORTING_SUBMODULES
    )
    covered = {name.rpartition(".")[0] for name in SIBLING_IMPORTING_SUBMODULES}
    assert covered == set(STANDALONE_IMPORT_PACKAGES), covered
    assert set(SIBLING_IMPORTING_SUBMODULES) <= set(ALL_SUBMODULES)


@pytest.mark.unit
@pytest.mark.parametrize("package", STANDALONE_IMPORT_PACKAGES)
def test_no_subpackage_drops_out_of_the_sweep(package: str) -> None:
    """The sweep globs ``*.py``; a subpackage would not be swept at all.

    Asserted rather than handled, because handling it means deciding how deep to
    recurse and there is nothing to recurse into yet. When one of these packages
    grows a subpackage, this fails and that decision gets made then.
    """
    assert _package_subpackages(package) == [], (
        f"{package} has subpackages, which the ``*.py`` glob in "
        f"_package_submodules does not see: {_package_subpackages(package)}"
    )
