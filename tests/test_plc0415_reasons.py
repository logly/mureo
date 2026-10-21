"""Every function-local import under ``mureo/`` names its reason (#863).

``PLC0415`` (import outside the module's top level) is on for the whole
package. Ruff itself finds every function-local import, with ``--ignore-noqa``
so that no suppression can hide one, and each one outside the ratcheted
packages has to carry ``# noqa: PLC0415 — <reason>`` with one of the four
reasons AGENTS.md lists. An ``import cycle`` reason names two real modules,
and the second one is the module the statement imports. No file-level
``# ruff: noqa`` may cover the rule.

The per-file ignore that switches the rule off for ``web`` / ``cli`` is
temporary (#863 stage 4c) and only shrinks, and nothing else in the
ruff config may switch the rule off.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import io
import json
import pathlib
import re
import subprocess
import sys
import tokenize
from typing import Any

import pytest

import mureo

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

_PACKAGE_ROOT = pathlib.Path(mureo.__file__).resolve().parent
_REPO_ROOT = _PACKAGE_ROOT.parent
_RULE = "PLC0415"

#: ``per-file-ignores`` globs allowed to switch the rule off under ``mureo/``.
_PLC0415_RATCHET = frozenset({"mureo/web/**", "mureo/cli/**"})

#: Every ``per-file-ignores`` key allowed to list the rule at all.
_PLC0415_IGNORE_KEYS = _PLC0415_RATCHET | {"tests/**"}

_NOQA = re.compile(
    r"#\s*noqa:\s*(?P<codes>[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)(?P<reason>.*)"
)
_BLANKET_NOQA = re.compile(r"#\s*noqa(?!\s*:)", re.IGNORECASE)
_FILE_NOQA = re.compile(r"#\s*(?:ruff|flake8)\s*:\s*noqa\b(?P<codes>.*)", re.IGNORECASE)

#: The four reasons, after the em dash the repo's other ``noqa`` reasons use.
_REASON = re.compile(
    r" — (?:startup cost \(#\d+\)"
    r"|optional dependency"
    r"|import cycle: (?P<a>mureo(?:\.\w+)+) -> (?P<b>mureo(?:\.\w+)+) \(#879\)"
    r"|PEP 562 re-export \(#863\))"
)


def _code_covers_rule(code: str) -> bool:
    """Does a ruff selector (a code, a prefix or ``ALL``) cover the rule?"""
    return code == "ALL" or _RULE.startswith(code)


def _is_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _plc0415_reason_is_known(comment: str, imported: tuple[str, ...]) -> bool:
    """Does ``comment`` suppress the rule with a known reason?

    ``imported`` holds the modules the commented statement loads; an
    ``import cycle: a -> b`` reason has to name one of them, or a parent
    package of one, as ``b``.
    """
    noqa = _NOQA.search(comment)
    if noqa is None or _BLANKET_NOQA.search(comment):
        return False
    if _RULE not in re.split(r"\s*,\s*", noqa["codes"]):
        return False
    reason = _REASON.fullmatch(noqa["reason"].rstrip())
    if reason is None:
        return False
    if reason["a"] is None:
        return True
    target = reason["b"]
    return (
        _is_module(reason["a"])
        and _is_module(target)
        and any(m == target or m.startswith(f"{target}.") for m in imported)
    )


def _file_noqa_covers_rule(comment: str) -> bool:
    """Is ``comment`` a file-level ``# ruff: noqa`` that covers the rule?"""
    match = _FILE_NOQA.match(comment)
    if match is None:
        return False
    codes = [c for c in re.split(r"[\s,:]+", match["codes"]) if c]
    return not codes or any(_code_covers_rule(c) for c in codes)


def _comments(source: str) -> dict[int, str]:
    """``{line: comment}`` of every comment token in ``source``."""
    return {
        token.start[0]: token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    }


def _imported_modules(tree: ast.Module, line: int, package: str) -> tuple[str, ...]:
    """Modules the import statement that starts on ``line`` loads."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and node.lineno == line:
            return tuple(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.lineno == line:
            base = node.module or ""
            if node.level:
                base = importlib.util.resolve_name("." * node.level + base, package)
            return (base, *(f"{base}.{alias.name}" for alias in node.names))
    return ()


def _plc0415_hits() -> list[tuple[str, int]]:
    """``(repo-relative path, line)`` of every function-local import ruff
    finds under ``mureo/`` with every suppression ignored."""
    command = [sys.executable, "-m", "ruff", "check", "--isolated", "--select"]
    command += [_RULE, "--ignore-noqa", "--exit-zero", "--output-format", "json"]
    proc = subprocess.run(
        [*command, str(_PACKAGE_ROOT)],
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    return [
        (
            pathlib.Path(hit["filename"]).resolve().relative_to(_REPO_ROOT).as_posix(),
            hit["location"]["row"],
        )
        for hit in json.loads(proc.stdout)
    ]


def _unreasoned_site(rel: str, line: int) -> str | None:
    """``rel:line: comment`` when the import at ``rel:line`` has no known reason."""
    source = (_REPO_ROOT / rel).read_text("utf-8")
    module = rel.removesuffix(".py").replace("/", ".")
    package = module.removesuffix(".__init__")
    if not rel.endswith("__init__.py"):
        package = package.rpartition(".")[0]
    imported = _imported_modules(ast.parse(source), line, package)
    comment = _comments(source).get(line, "")
    if _plc0415_reason_is_known(comment, imported):
        return None
    return f"{rel}:{line}: {comment or '(no comment)'}"


@pytest.mark.unit
def test_every_function_local_import_names_a_known_reason() -> None:
    hits = [
        (rel, line)
        for rel, line in _plc0415_hits()
        if not any(fnmatch.fnmatchcase(rel, glob) for glob in _PLC0415_RATCHET)
    ]
    assert hits, "ruff found no function-local import outside the ratchet"
    unreasoned = [_unreasoned_site(rel, line) for rel, line in hits]
    assert [site for site in unreasoned if site is not None] == []


@pytest.mark.unit
def test_no_file_level_noqa_covers_plc0415() -> None:
    found = [
        f"{path.relative_to(_REPO_ROOT).as_posix()}:{line}: {comment}"
        for path in sorted(_PACKAGE_ROOT.rglob("*.py"))
        for line, comment in _comments(path.read_text("utf-8")).items()
        if _file_noqa_covers_rule(comment)
    ]
    assert found == []


_STATE = ("mureo.context.state", "mureo.context.state.read_state_file")
_CYCLE = "# noqa: PLC0415 — import cycle: "


@pytest.mark.unit
@pytest.mark.parametrize(
    ("comment", "imported", "known"),
    [
        ("# noqa: PLC0415 — startup cost (#809)", (), True),
        ("# noqa: PLC0415 — startup cost", (), False),
        ("# noqa: PLC0415 — optional dependency", (), True),
        ("# noqa: PLC0415 — optional", (), False),
        ("# noqa: PLC0415 — PEP 562 re-export (#863)", (), True),
        ("# noqa: PLC0415 — PEP 562 re-export", (), False),
        (f"{_CYCLE}mureo.context.daily -> mureo.context.state (#879)", _STATE, True),
        (f"{_CYCLE}mureo.context.daily -> mureo.context (#879)", _STATE, True),
        (f"{_CYCLE}mureo.context.daily -> mureo.context.state", _STATE, False),
        (f"{_CYCLE}mureo.context.nope -> mureo.context.state (#879)", _STATE, False),
        (f"{_CYCLE}mureo.context.daily -> mureo.context.nope (#879)", _STATE, False),
        (f"{_CYCLE}mureo.nope.daily -> mureo.context.state (#879)", _STATE, False),
        (
            f"{_CYCLE}mureo.context.daily -> mureo.context.settings (#879)",
            _STATE,
            False,
        ),
        (f"{_CYCLE}mureo.context.daily -> json (#879)", ("json",), False),
        ("# noqa: PLC0415", (), False),
        ("# noqa: PLC0415 - startup cost (#809)", (), False),
        ("# noqa: PLC0415 — because", (), False),
        ("# noqa: BLE001, PLC0415 — because", (), False),
        ("# noqa: BLE001, PLC0415", (), False),
        ("# noqa: F401, PLC0415 — optional dependency", (), True),
        ("# noqa: BLE001 — optional dependency", (), False),
        ("# noqa", (), False),
        ("# NOQA", (), False),
        ("# noqa  # noqa: PLC0415 — optional dependency", (), False),
        ("# noqa: PLC0415 — optional dependency  # noqa", (), False),
        ("# ruff: noqa: PLC0415", (), False),
        ("", (), False),
    ],
)
def test_plc0415_reason_matcher(
    comment: str, imported: tuple[str, ...], known: bool
) -> None:
    assert _plc0415_reason_is_known(comment, imported) is known


@pytest.mark.unit
@pytest.mark.parametrize(
    ("comment", "covers"),
    [
        ("# ruff: noqa", True),
        ("# ruff: noqa: PLC0415", True),
        ("# ruff: noqa: TC001, PLC0415", True),
        ("# ruff: noqa: PLC", True),
        ("# flake8: noqa", True),
        ("# Ruff: NOQA", True),
        ("# ruff: noqa: TC001, TC003", False),
        ("# noqa: PLC0415 — optional dependency", False),
    ],
)
def test_file_noqa_matcher(comment: str, covers: bool) -> None:
    assert _file_noqa_covers_rule(comment) is covers


def _ruff_config() -> dict[str, Any]:
    pyproject = _REPO_ROOT / "pyproject.toml"
    return tomllib.loads(pyproject.read_text("utf-8"))["tool"]["ruff"]


def _covers(codes: list[str]) -> bool:
    return any(_code_covers_rule(code) for code in codes)


@pytest.mark.unit
def test_plc0415_ratchet_only_shrinks() -> None:
    ruff = _ruff_config()
    lint = ruff.get("lint", {})
    assert _RULE in lint.get("select", [])
    for table in (ruff, lint):
        for key in ("ignore", "extend-ignore"):
            assert not _covers(table.get(key, [])), key
        extended = table.get("extend-per-file-ignores", {})
        assert [glob for glob, codes in extended.items() if _covers(codes)] == []
    ignoring = {
        glob
        for table in (ruff, lint)
        for glob, codes in table.get("per-file-ignores", {}).items()
        if _covers(codes)
    }
    assert ignoring <= _PLC0415_IGNORE_KEYS
