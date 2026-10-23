"""Every broad ``except`` under ``mureo/`` and ``tests/`` names its reason (#865).

``BLE001`` (blind ``except Exception`` / ``except BaseException``) is on for
the package and its tests alike. Ruff itself finds every broad except, with
``--ignore-noqa`` so that no suppression can hide one, and each one has to
carry ``# noqa: BLE001 — <reason>``: the em dash the repo's other ``noqa``
reasons use, then a reason of at least two words that is not a placeholder.
Unlike ``PLC0415`` the reason is free text — why a site may catch everything
is particular to the site. No file-level ``# ruff: noqa`` may cover the rule.

The rule stays in ``select``, and no ``per-file-ignores`` key may list it:
``tests/`` is not exempt, so both trees are scanned below.
"""

from __future__ import annotations

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
#: The trees held to the rule: the package and its tests.
_SCANNED_ROOTS = (_PACKAGE_ROOT, _REPO_ROOT / "tests")
_RULE = "BLE001"
_LINTER = "BLE"

_NOQA = re.compile(
    r"#\s*noqa:\s*(?P<codes>[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)(?P<reason>.*)"
)
_BLANKET_NOQA = re.compile(r"#\s*noqa(?!\s*:)", re.IGNORECASE)
_FILE_NOQA = re.compile(r"#\s*(?:ruff|flake8)\s*:\s*noqa\b(?P<codes>.*)", re.IGNORECASE)

#: The em dash the repo's other ``noqa`` reasons use, then the free text.
_REASON = re.compile(r" — (?P<text>\S.*)")

#: Words that only stand in for a reason.
_PLACEHOLDERS = frozenset(
    {"reason", "todo", "ok", "fixme", "tbd", "xxx", "n/a", "none", "broad", "ble001"}
)

#: A reason has at least this many words.
_MIN_REASON_WORDS = 2


def _code_covers_rule(code: str) -> bool:
    """Does a ruff selector (a code, a prefix or ``ALL``) cover the rule?

    The prefix has to name the ``BLE`` linter: ``B`` is flake8-bugbear,
    which shares the letter but not the rule.
    """
    return code == "ALL" or (code.startswith(_LINTER) and _RULE.startswith(code))


def _reason_is_given(text: str) -> bool:
    """Is ``text`` a reason rather than a placeholder?"""
    words = re.findall(r"[\w/'#-]+", text.lower())
    if len(words) < _MIN_REASON_WORDS:
        return False
    return not any(word in _PLACEHOLDERS for word in words[:1])


def _ble001_reason_is_given(comment: str) -> bool:
    """Does ``comment`` suppress the rule with a reason?"""
    noqa = _NOQA.search(comment)
    if noqa is None or _BLANKET_NOQA.search(comment):
        return False
    if _RULE not in re.split(r"\s*,\s*", noqa["codes"]):
        return False
    reason = _REASON.fullmatch(noqa["reason"].rstrip())
    return reason is not None and _reason_is_given(reason["text"])


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


def _ble001_hits() -> list[tuple[str, int]]:
    """``(repo-relative path, line)`` of every broad except ruff finds under
    ``mureo/`` and ``tests/`` with every suppression ignored."""
    command = [sys.executable, "-m", "ruff", "check", "--isolated", "--select"]
    command += [_RULE, "--ignore-noqa", "--exit-zero", "--output-format", "json"]
    proc = subprocess.run(
        [*command, *(str(root) for root in _SCANNED_ROOTS)],
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
    """``rel:line: comment`` when the except at ``rel:line`` gives no reason."""
    comment = _comments((_REPO_ROOT / rel).read_text("utf-8")).get(line, "")
    if _ble001_reason_is_given(comment):
        return None
    return f"{rel}:{line}: {comment or '(no comment)'}"


@pytest.mark.unit
def test_every_broad_except_names_a_reason() -> None:
    hits = _ble001_hits()
    for root in _SCANNED_ROOTS:
        tree = root.relative_to(_REPO_ROOT).as_posix()
        assert any(rel.startswith(f"{tree}/") for rel, _ in hits), tree
    unreasoned = [_unreasoned_site(rel, line) for rel, line in hits]
    assert [site for site in unreasoned if site is not None] == []


@pytest.mark.unit
def test_no_file_level_noqa_covers_ble001() -> None:
    found = [
        f"{path.relative_to(_REPO_ROOT).as_posix()}:{line}: {comment}"
        for root in _SCANNED_ROOTS
        for path in sorted(root.rglob("*.py"))
        for line, comment in _comments(path.read_text("utf-8")).items()
        if _file_noqa_covers_rule(comment)
    ]
    assert found == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("comment", "given"),
    [
        ("# noqa: BLE001 — per-plugin isolation", True),
        ("# noqa: BLE001 — never break startup on a hint", True),
        ("# noqa: BLE001 — opaque hook; never 500.", True),
        ("# noqa: F401, BLE001 — per-plugin isolation", True),
        ("# noqa: BLE001, PLC0415 — optional dependency", True),
        ("# noqa: BLE001 — reason", False),
        ("# noqa: BLE001 — todo", False),
        ("# noqa: BLE001 — ok", False),
        ("# noqa: BLE001 — TODO: add one", False),
        ("# noqa: BLE001 — reason here", False),
        ("# noqa: BLE001 — isolation", False),
        ("# noqa: BLE001 — ", False),
        ("# noqa: BLE001 —", False),
        ("# noqa: BLE001", False),
        ("# noqa: BLE001 - per-plugin isolation", False),
        ("# noqa: BLE001 -- per-plugin isolation", False),
        ("# noqa: BLE001: per-plugin isolation", False),
        ("# noqa: PLC0415 — optional dependency", False),
        ("# noqa", False),
        ("# NOQA", False),
        ("# noqa  # noqa: BLE001 — per-plugin isolation", False),
        ("# noqa: BLE001 — per-plugin isolation  # noqa", False),
        ("# ruff: noqa: BLE001", False),
        ("", False),
    ],
)
def test_ble001_reason_matcher(comment: str, given: bool) -> None:
    assert _ble001_reason_is_given(comment) is given


@pytest.mark.unit
@pytest.mark.parametrize(
    ("comment", "covers"),
    [
        ("# ruff: noqa", True),
        ("# ruff: noqa: BLE001", True),
        ("# ruff: noqa: TC001, BLE001", True),
        ("# ruff: noqa: BLE", True),
        ("# flake8: noqa", True),
        ("# Ruff: NOQA", True),
        ("# ruff: noqa: TC001, TC003", False),
        ("# ruff: noqa: B", False),
        ("# noqa: BLE001 — per-plugin isolation", False),
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
def test_ble_is_selected_and_never_switched_off() -> None:
    ruff = _ruff_config()
    lint = ruff.get("lint", {})
    assert _covers(lint.get("select", []))
    for table in (ruff, lint):
        for key in ("ignore", "extend-ignore"):
            assert not _covers(table.get(key, [])), key
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            ignoring = [g for g, codes in table.get(key, {}).items() if _covers(codes)]
            assert ignoring == [], key
