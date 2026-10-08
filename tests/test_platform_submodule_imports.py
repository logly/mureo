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

So each submodule is imported first in a child interpreter of its own. The
child spawning is shared by one session fixture and done concurrently; the
parametrisation is per module so a failure names the module that cannot stand
alone.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

# Packages whose submodules must each be importable first. Both are mixin-built
# API clients with the same shape, and both have a lazy ``__init__`` (#807).
STANDALONE_IMPORT_PACKAGES = ("mureo.google_ads", "mureo.meta_ads")

# Child interpreters to keep in flight. Each one imports one submodule and
# exits; the work is process startup plus the submodule's own imports, so a
# handful in parallel keeps the sweep off the suite's critical path without
# oversubscribing a CI runner.
_MAX_IN_FLIGHT = 8

# Coverage's subprocess hooks trace the child's imports, which is irrelevant
# here (the assertion is "did it import", not "how long did it take") and
# roughly halves the child's speed. Dropped so the sweep costs the same under
# `pytest --cov` as without it.
_COVERAGE_ENV_PREFIX = "COV_CORE_"


def _package_submodules(package: str) -> list[str]:
    """Fully qualified names of ``package``'s submodules, without importing it."""
    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.submodule_search_locations is not None, package
    names = []
    for location in spec.submodule_search_locations:
        for path in sorted(pathlib.Path(location).glob("*.py")):
            if path.name != "__init__.py":
                names.append(f"{package}.{path.stem}")
    return names


def _all_submodules() -> list[str]:
    return [
        name
        for package in STANDALONE_IMPORT_PACKAGES
        for name in _package_submodules(package)
    ]


def _child_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_COVERAGE_ENV_PREFIX)
    }
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    return env


def _import_alone(module: str, env: dict[str, str]) -> tuple[str, int, str]:
    proc = subprocess.run(
        [sys.executable, "-c", f"__import__({module!r})"],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    return module, proc.returncode, proc.stderr


@pytest.fixture(scope="session")
def standalone_import_results() -> Iterator[dict[str, tuple[int, str]]]:
    """Import every submodule first, each in its own child interpreter."""
    env = _child_env()
    modules = _all_submodules()
    with ThreadPoolExecutor(max_workers=_MAX_IN_FLIGHT) as pool:
        results = list(pool.map(lambda m: _import_alone(m, env), modules))
    yield {module: (code, stderr) for module, code, stderr in results}


@pytest.mark.unit
@pytest.mark.parametrize("module", _all_submodules())
def test_submodule_imports_as_the_first_import(
    module: str, standalone_import_results: dict[str, tuple[int, str]]
) -> None:
    returncode, stderr = standalone_import_results[module]
    assert returncode == 0, (
        f"{module} cannot be imported first. Something it imports imports it "
        f"back — move the shared name into a leaf module instead of relying on "
        f"a package __init__ to enter the cycle at a lucky point.\n{stderr}"
    )
