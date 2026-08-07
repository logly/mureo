"""Import verification tests.

Two checks, both reaching the whole package, and both getting their reach
from the same source: a walk of ``mureo/``. That is stated here because a
green run means nothing without knowing the set it ran over.

- **The DB/LLM import ban covers everything.** ``TestNoForbiddenImports``
  walks ``mureo/`` with ``rglob`` and AST-parses every ``.py`` file.
- **The clean-import check covers everything.** ``TestModuleImports``
  parametrises over ``_discover_modules()``, which turns that same walk into
  dotted module names. There is no list to extend: a module is under test
  the moment its file exists, and stops being under test when the file is
  deleted. Omission is not unlikely — it is unreachable, because nothing is
  written down that could disagree with the tree.

This replaces (#555) a hand-maintained ``_ALL_MODULES`` that had drifted to
46 of the 288 modules, leaving ``mcp``, ``web``, ``core``, ``cli``,
``analytics``, ``creative_studio``, ``amazon_ads`` and eight other packages
with no clean-import coverage at all. Deriving the list retires the failure
mode instead of correcting one instance of it.

**There are no exclusions.** All 288 modules under ``mureo/`` import
standalone. Widening the check turned up exactly one that did not:
``mureo.mcp.__main__`` ran ``asyncio.run(main())`` at module scope with no
``if __name__ == "__main__"`` guard, so importing it *started the stdio MCP
server*, which read stdin to EOF and closed ``sys.stdout``. That was a
defect and was fixed, not skipped. If some future module genuinely cannot
import standalone, its exclusion belongs in this file with the reason
written beside it — an exclusion nobody has to justify is how the old list
got to 46.

**Cost.** In a full run the imports are amortised — the heavy transitive
deps (``mcp``, ``google-ads``, ``facebook-business``) are already loaded by
other tests, and the suite total does not move. Run this file *by itself*
and you pay them alone: roughly 2x the wall time and ~40MB more RSS than
the 46-module version. That is the workflow of someone debugging an import
problem, so it is written down rather than left to be discovered.
``_leave_interpreter_globals_as_found`` keeps the process state this file
touches from leaking into the rest of a session.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import sys
import warnings
from collections.abc import Iterator
from typing import Any

import pytest

# mureo-core package root
_MUREO_ROOT = pathlib.Path(__file__).resolve().parent.parent / "mureo"

# Forbidden import patterns (DB / LLM)
_FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "sqlalchemy",
        "alembic",
        "asyncpg",
        "aiosqlite",
        "supabase",
        "openai",
        "anthropic",
        "google.generativeai",
        "langchain",
        "slack_bolt",
        "slack_sdk",
        "apscheduler",
        "fastapi",
        "uvicorn",
        "redis",
    }
)


def _collect_py_files() -> list[pathlib.Path]:
    """Every ``.py`` file under ``mureo/``, sorted for a stable test order."""
    return sorted(_MUREO_ROOT.rglob("*.py"))


def _module_name(filepath: pathlib.Path) -> str:
    """Dotted module name for a file under ``mureo/``.

    ``mureo/mcp/server.py`` -> ``mureo.mcp.server``;
    ``mureo/mcp/__init__.py`` -> ``mureo.mcp``.
    """
    parts = list(filepath.relative_to(_MUREO_ROOT.parent).parts)
    parts[-1] = parts[-1].removesuffix(".py")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _discover_modules() -> list[str]:
    """The modules under test, derived from the tree rather than listed.

    One name per ``.py`` file, no filtering. Nothing here can fall behind
    ``mureo/`` because nothing here is written down separately from it.
    """
    return [_module_name(path) for path in _collect_py_files()]


# Modules under test — derived, never hand-maintained. See the module
# docstring for why there is no exclusion list.
_ALL_MODULES: list[str] = _discover_modules()


@pytest.fixture(scope="module", autouse=True)
def _leave_interpreter_globals_as_found() -> Iterator[None]:
    """Restore the process globals that importing 288 modules can move.

    Importing this much of the tree pulls in transitive dependencies that
    mutate interpreter state on import: ``google-ads``/``requests`` append
    to ``warnings.filters``, and the ``exceptiongroup`` backport replaces
    ``sys.excepthook``. Neither is mureo's doing and neither is a defect.

    **Measured, this fixture is currently a no-op**, but not for a reason
    worth relying on. ``warnings.filters`` is already restored around every
    item by pytest's warnings plugin (which ``-p no:warnings`` switches
    off), and ``sys.excepthook`` is already the backport's before collection
    starts because ``exceptiongroup`` is a hard pytest dependency on Python
    3.10 — ``import pytest`` alone installs it, with no mureo loaded. That
    dependency is gone on 3.11+, where ``ExceptionGroup`` is a builtin. So
    "we inherit a clean interpreter" rests on two pytest internals across
    two Python versions, and this file would be the one to notice.

    Snapshotting at module setup makes the restore incapable of harm: it
    reverts only what moved *during* these tests and re-installs whatever
    state the module inherited, so it can never strip a mutation another
    test depends on. Nothing in ``mureo/`` or ``tests/`` reads
    ``sys.excepthook``.
    """
    excepthook = sys.excepthook
    with warnings.catch_warnings():
        yield
    sys.excepthook = excepthook


def _collect_imports_from_file(filepath: pathlib.Path) -> list[str]:
    """Collect imported module names from a Python file using the AST."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


@pytest.mark.unit
class TestModuleDiscovery:
    """Guard the discovery itself, so a broken walk cannot pass as green.

    A derived parametrisation removes the *drift* failure mode but adds one
    of its own: if the walk silently yields nothing (wrong root, renamed
    package), ``TestModuleImports`` collects zero tests and the run is still
    green. These assertions turn that into a failure, and none of them
    hard-code a count that would itself need maintaining.
    """

    def test_package_root_resolves(self) -> None:
        """``_MUREO_ROOT`` points at the real package directory."""
        assert _MUREO_ROOT.is_dir(), f"package root not found: {_MUREO_ROOT}"
        assert (_MUREO_ROOT / "__init__.py").is_file()

    def test_every_python_file_yields_exactly_one_module(self) -> None:
        """The walk is a bijection: no file dropped, no name duplicated."""
        py_files = _collect_py_files()
        assert py_files, f"no .py files found under {_MUREO_ROOT}"
        assert len(_ALL_MODULES) == len(py_files)
        assert len(set(_ALL_MODULES)) == len(_ALL_MODULES), "duplicate module names"

    def test_module_names_round_trip_to_the_walked_files(self) -> None:
        """Every name maps back to a real file, and together they cover all.

        This is the assertion the old hand-maintained list would have
        failed — it named 46 files out of 288, omitting eight whole
        packages (#555). Any successor list would fail it the same way.
        """
        rebuilt: set[pathlib.Path] = set()
        for name in _ALL_MODULES:
            relative = pathlib.Path(*name.split("."))
            package_init = _MUREO_ROOT.parent / relative / "__init__.py"
            module_file = _MUREO_ROOT.parent / relative.with_suffix(".py")
            rebuilt.add(package_init if package_init.is_file() else module_file)

        assert rebuilt == set(_collect_py_files())


@pytest.mark.unit
class TestModuleImports:
    """Verify that every module under ``mureo/`` can be imported."""

    @pytest.mark.parametrize("module_name", _ALL_MODULES)
    def test_import_succeeds(self, module_name: str) -> None:
        """Each module imports successfully."""
        mod = importlib.import_module(module_name)
        assert mod is not None


@pytest.mark.unit
class TestNoForbiddenImports:
    """Verify no DB/LLM imports are present, using AST analysis."""

    def test_no_forbidden_imports_in_package(self) -> None:
        """No forbidden imports in any file under mureo/."""
        violations: list[str] = []

        for py_file in _collect_py_files():
            imports = _collect_imports_from_file(py_file)
            for imp in imports:
                # Compare on top-level module name
                top_module = imp.split(".")[0]
                for forbidden in _FORBIDDEN_MODULES:
                    if top_module == forbidden.split(".")[0] and imp.startswith(
                        forbidden
                    ):
                        violations.append(
                            f"{py_file.relative_to(_MUREO_ROOT.parent)}: "
                            f"import {imp}"
                        )

        assert violations == [], "Forbidden DB/LLM imports detected:\n" + "\n".join(
            violations
        )
