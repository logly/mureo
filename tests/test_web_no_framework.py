"""Charter regression: ``mureo/web/`` must not depend on any web framework.

AGENTS.md (L191) declares: "No web framework dependencies — no FastAPI,
no Flask. CLI (Typer) and MCP (stdio) only." The configure UI is built
on stdlib ``http.server`` exclusively. This test walks the entire
``mureo/web/`` source tree and parses each file with ``ast`` to assert
that none of the forbidden frameworks are imported, even transitively.

Failing this test means a dependency creep regression — the
implementer must restore the stdlib-only constraint, not loosen the
test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import mureo.web as web_pkg

# Closed allow-list of forbidden top-level package names. If a future
# author adds e.g. ``django`` they should be caught here too. Keep this
# in lock-step with AGENTS.md.
FORBIDDEN_FRAMEWORKS: frozenset[str] = frozenset(
    {
        "fastapi",
        "flask",
        "starlette",
        "uvicorn",
        "hypercorn",
        "aiohttp",
        "bottle",
        "tornado",
        "sanic",
        "quart",
        "falcon",
        "django",
        "pyramid",
        "cherrypy",
        "werkzeug",
    }
)


def _web_source_files() -> list[Path]:
    """Every ``.py`` file under ``mureo/web/``."""
    root = Path(web_pkg.__file__).parent
    return sorted(root.rglob("*.py"))


def _top_level_imports(tree: ast.AST) -> set[str]:
    """Return the top-level (first segment) of every ``import`` /
    ``from ... import`` statement in ``tree``."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if node.level and node.level > 0:
                continue
            found.add(node.module.split(".", 1)[0])
    return found


@pytest.mark.unit
class TestWebPackageHasNoForbiddenFrameworkImports:
    """No file under ``mureo/web/`` may import any forbidden framework."""

    def test_web_directory_exists_and_is_nonempty(self) -> None:
        files = _web_source_files()
        assert files, "Expected at least one .py file under mureo/web/"

    def test_every_file_in_web_is_framework_free(self) -> None:
        offenders: list[tuple[str, str]] = []
        for path in _web_source_files():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            imported_top_level = _top_level_imports(tree)
            forbidden_hits = imported_top_level & FORBIDDEN_FRAMEWORKS
            for hit in sorted(forbidden_hits):
                offenders.append((str(path), hit))
        assert offenders == [], (
            "Forbidden web-framework imports detected under mureo/web/: "
            f"{offenders}. See AGENTS.md L191 — stdlib http.server only."
        )

    @pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_FRAMEWORKS))
    def test_forbidden_name_does_not_appear_as_substring_in_source(
        self, forbidden: str
    ) -> None:
        """Belt-and-braces: defend against ``importlib.import_module
        ("fastapi")`` style runtime imports that ``ast`` could miss
        because the literal would still appear in the source string."""
        for path in _web_source_files():
            source = path.read_text(encoding="utf-8")
            assert forbidden not in source.lower(), (
                f"Forbidden framework name {forbidden!r} appeared in "
                f"{path}. Either it's an import (banned by AGENTS.md "
                "L191) or a comment that risks confusion — rename it."
            )


@pytest.mark.unit
class TestServerUsesStdlibHttpServer:
    """The configure-UI server module specifically must use stdlib
    ``http.server`` — the entire charter rests on this."""

    def test_server_module_imports_http_server(self) -> None:
        from mureo.web import server

        source = Path(server.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = _top_level_imports(tree)
        assert "http" in imports, (
            "mureo.web.server must import stdlib http.server; got "
            f"top-level imports: {sorted(imports)}"
        )

    def test_handlers_module_uses_base_http_request_handler(self) -> None:
        """``handlers.ConfigureHandler`` must subclass
        ``http.server.BaseHTTPRequestHandler`` — that's the stdlib
        contract the charter mandates."""
        from http.server import BaseHTTPRequestHandler

        from mureo.web.handlers import ConfigureHandler

        assert issubclass(ConfigureHandler, BaseHTTPRequestHandler)
