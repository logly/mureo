"""Find the prose in shipped files and test it with a caller's matcher.

The rule-agnostic half of the text checks in this directory
(``check_english_only.py``, ``check_comment_provenance.py``). This module
decides which tracked files are shipped prose and which parts of them are
prose:

* Python: comments, docstrings (the first statement of a module, class or
  function) and attribute docstrings (PEP 257: a bare string statement
  right after an assignment, directly in a module, class or function body).
  Optionally the names of ``test_`` functions and ``Test`` classes. Plain
  string literals are never prose.
* Markdown: every line outside a CommonMark fenced code block. Fences have
  at most three spaces of indentation, a run of three or more backticks or
  tildes, no backtick in a backtick fence's info string, and a closing run
  of the same character at least as long with nothing after it.
* CSS, HTML and JavaScript: the text inside ``/* */`` and ``<!-- -->``
  comments, and ``//`` comments that start their line.

What counts as a hit is the caller's: every scan takes a ``matcher``, a
predicate over one line (or one comment segment) of prose. Standard
library only, so the checks run before the package is installed.
"""

from __future__ import annotations

import argparse
import ast
import io
import itertools
import re
import subprocess
import sys
import tokenize
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

_PYTHON_DIRS = ("mureo/", "tests/", "scripts/")
_MARKDOWN_DIRS = ("docs/",)
_SKILL_DIRS = ("skills/", "mureo/_data/skills/")
_EXCLUDED_SUFFIXES = (".ja.md",)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_START_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)
WEB_COMMENTS: dict[str, tuple[re.Pattern[str], ...]] = {
    ".css": (_BLOCK_COMMENT,),
    ".html": (re.compile(r"<!--.*?-->", re.DOTALL),),
    ".js": (_BLOCK_COMMENT, _LINE_START_COMMENT),
}
_WEB_DIRS: dict[str, tuple[str, ...]] = {
    ".css": ("mureo/",),
    ".html": ("mureo/",),
    ".js": ("mureo/", "tests/js/"),
}

# CommonMark 4.5 fenced code blocks. Four or more spaces of indentation make
# an indented code block instead, which is not modelled: such a line is prose.
_FENCE_OPENER = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSER = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_BACKTICK = "`"

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
_TEST_FUNCTION_PREFIX = "test_"
_TEST_CLASS_PREFIX = "Test"
# A bare string statement right after one of these is an attribute docstring.
_ATTRIBUTE_ASSIGNMENTS = (ast.Assign, ast.AnnAssign)
# The line breaks ``ast`` counts. ``str.splitlines`` also breaks on form feed
# and U+001C-U+001E, which would shift ``ast`` line numbers against the text.
_AST_LINE_BREAK = re.compile(r"\r\n|\r|\n")

_MISSING_FILE = "skipped — not in the working tree"
_NOT_UTF8 = "cannot decode as UTF-8 — not checked"
_SYNTAX_ERROR = "syntax error — not checked"
_UNREADABLE = "cannot read ({reason}) — not checked"

Hit = tuple[int, str]
# A predicate over one line (or one comment segment) of prose.
Matcher = Callable[[str], bool]
# A rule's whole-file scan: ``(path, text) -> hits``.
Scanner = Callable[[str, str], list[Hit]]


class Diagnostic(NamedTuple):
    """Why a tracked file was not scanned, and whether that fails the run."""

    message: str
    fatal: bool


def is_scanned(path: str) -> bool:
    """Return True if the repository-relative ``path`` is shipped prose."""
    if path.endswith(_EXCLUDED_SUFFIXES):
        return False
    if path.startswith(_SKILL_DIRS):
        return True
    if path.endswith(".py"):
        return path.startswith(_PYTHON_DIRS)
    if path.endswith(".md"):
        return "/" not in path or path.startswith(_MARKDOWN_DIRS)
    suffix = Path(path).suffix
    if suffix in _WEB_DIRS:
        return path.startswith(_WEB_DIRS[suffix])
    return False


def _comment_hits(source: str, matcher: Matcher) -> list[Hit]:
    hits: list[Hit] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and matcher(token.string):
            hits.append((token.start[0], token.line.rstrip("\n")))
    return hits


def _is_string_statement(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _docstring_nodes(tree: ast.Module) -> list[ast.stmt]:
    """Return the docstrings and attribute docstrings of every owner body."""
    nodes: list[ast.stmt] = []
    for owner in ast.walk(tree):
        if not isinstance(owner, _DOCSTRING_OWNERS) or not owner.body:
            continue
        body = owner.body
        if _is_string_statement(body[0]):
            nodes.append(body[0])
        nodes.extend(
            node
            for previous, node in itertools.pairwise(body)
            if isinstance(previous, _ATTRIBUTE_ASSIGNMENTS)
            and _is_string_statement(node)
        )
    return nodes


def _docstring_hits(tree: ast.Module, lines: list[str], matcher: Matcher) -> list[Hit]:
    hits: list[Hit] = []
    for node in _docstring_nodes(tree):
        end = node.end_lineno or node.lineno
        for number in range(node.lineno, end + 1):
            text = lines[number - 1]
            if matcher(text):
                hits.append((number, text))
    return hits


def _test_name_hits(
    tree: ast.Module, lines: list[str], name_matcher: Matcher
) -> list[Hit]:
    hits: list[Hit] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = _TEST_FUNCTION_PREFIX
        elif isinstance(node, ast.ClassDef):
            prefix = _TEST_CLASS_PREFIX
        else:
            continue
        if node.name.startswith(prefix) and name_matcher(node.name):
            hits.append((node.lineno, lines[node.lineno - 1]))
    return hits


def scan_python(
    source: str, matcher: Matcher, name_matcher: Matcher | None = None
) -> list[Hit]:
    """Return ``(line, text)`` for matching comments and docstrings.

    With ``name_matcher``, a ``test_`` function or ``Test`` class whose
    name it matches is a hit too; without it, names are not checked.
    """
    tree = ast.parse(source)
    lines = _AST_LINE_BREAK.split(source)
    hits = set(_comment_hits(source, matcher)) | set(
        _docstring_hits(tree, lines, matcher)
    )
    if name_matcher is not None:
        hits |= set(_test_name_hits(tree, lines, name_matcher))
    return sorted(hits)


def _fence_opener(line: str) -> tuple[str, int] | None:
    """Return the fence character and run length ``line`` opens, else None.

    A backtick fence's info string may not contain a backtick, so a line
    that starts with inline code (three backticks, code, three backticks)
    opens nothing. A tilde fence's info string may contain anything.
    """
    match = _FENCE_OPENER.match(line)
    if match is None:
        return None
    run, info = match.groups()
    if run[0] == _BACKTICK and _BACKTICK in info:
        return None
    return run[0], len(run)


def _closes_fence(line: str, char: str, length: int) -> bool:
    """Return True if ``line`` closes a fence opened by ``length`` ``char``."""
    match = _FENCE_CLOSER.match(line)
    if match is None:
        return False
    run = match.group(1)
    return run[0] == char and len(run) >= length


def scan_markdown(
    text: str, matcher: Matcher, exempt: frozenset[int] = frozenset()
) -> list[Hit]:
    """Return ``(line, text)`` for matching lines outside fenced code blocks.

    Lines in ``exempt`` are skipped.
    """
    hits: list[Hit] = []
    fence: tuple[str, int] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if number in exempt:
            continue
        if fence is not None:
            if _closes_fence(line, *fence):
                fence = None
            continue
        fence = _fence_opener(line)
        if fence is not None:
            continue
        if matcher(line):
            hits.append((number, line))
    return hits


def scan_comments(
    text: str, comments: tuple[re.Pattern[str], ...], matcher: Matcher
) -> list[Hit]:
    """Return ``(line, text)`` for matching lines inside any ``comments`` match."""
    lines = text.splitlines()
    hits: set[Hit] = set()
    for comment in comments:
        for match in comment.finditer(text):
            first = text.count("\n", 0, match.start()) + 1
            for offset, segment in enumerate(match.group().split("\n")):
                if matcher(segment):
                    hits.add((first + offset, lines[first + offset - 1]))
    return sorted(hits)


def scan_file(path: str, text: str, matcher: Matcher) -> list[Hit]:
    """Dispatch on file type: Python, CSS/HTML/JS comments, or markdown."""
    suffix = Path(path).suffix
    if suffix == ".py":
        return scan_python(text, matcher)
    if suffix in WEB_COMMENTS:
        return scan_comments(text, WEB_COMMENTS[suffix], matcher)
    return scan_markdown(text, matcher)


def _error_line(error: Exception) -> int | None:
    """Return the line a parse error points at, if it carries one."""
    if isinstance(error, SyntaxError):
        return error.lineno
    # TokenError's args are (message, (line, column)).
    position = error.args[1] if len(error.args) > 1 else None
    return position[0] if isinstance(position, tuple) else None


def check_path(
    root: Path, path: str, scan: Scanner
) -> tuple[list[Hit], Diagnostic | None]:
    """Scan one tracked file: return its hits and, if it was not scanned, why.

    ``scan`` is the rule's whole-file scan. The diagnostic is None when the
    file was scanned. A path missing from the working tree (a staged
    deletion) is skipped without failing the run; a file that cannot be
    read, a file that is not UTF-8, or a Python file that does not parse,
    is not checked and fails it. A UTF-8 byte order mark is dropped before
    scanning. ``ast.parse`` raises ValueError rather than SyntaxError for a
    NUL byte on Python 3.10 and 3.11.
    """
    try:
        text = (root / path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return [], Diagnostic(f"{path}: {_MISSING_FILE}", fatal=False)
    except OSError as error:
        reason = _UNREADABLE.format(reason=error.strerror)
        return [], Diagnostic(f"{path}: {reason}", fatal=True)
    except UnicodeDecodeError:
        return [], Diagnostic(f"{path}: {_NOT_UTF8}", fatal=True)
    try:
        return scan(path, text), None
    except (SyntaxError, ValueError, tokenize.TokenError) as error:
        line = _error_line(error)
        where = path if line is None else f"{path}:{line}"
        return [], Diagnostic(f"{where}: {_SYNTAX_ERROR}", fatal=True)


def tracked_files(root: Path, include: Callable[[str], bool]) -> list[str]:
    """Return the repository-relative tracked paths ``include`` accepts."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return sorted(p for p in result.stdout.split("\0") if p and include(p))


def _use_utf8_output() -> None:
    """Write UTF-8 whatever the console's code page is.

    A hit line can carry any character (for the English-only check, every
    one carries Japanese). On a console with a legacy code page (Windows
    cp1252) printing one raised UnicodeEncodeError, so the run ended in a
    traceback with no report. Characters a stream still cannot take are
    written as backslash escapes, never dropped.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def run(
    argv: list[str] | None,
    doc: str,
    tracked: Callable[[Path], list[str]],
    scan: Scanner,
) -> int:
    """Run one check as a command: 1 on any hit or fatal diagnostic, else 0.

    ``doc`` is the check's module docstring (its first line is the
    ``--help`` description), ``tracked`` lists the files it scans under a
    root, and ``scan`` is its whole-file scan. Each hit is printed as
    ``path:line: text``; diagnostics go to stderr.
    """
    _use_utf8_output()
    parser = argparse.ArgumentParser(description=doc.split("\n", 1)[0])
    parser.add_argument(
        "--list", action="store_true", help="print the scanned file set and exit"
    )
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="repository root to scan"
    )
    args = parser.parse_args(argv)

    paths = tracked(args.root)
    if args.list:
        print("\n".join(paths))
        return 0

    failed = False
    for path in paths:
        hits, diagnostic = check_path(args.root, path, scan)
        for number, line in hits:
            print(f"{path}:{number}: {line.strip()}")
        if diagnostic is not None:
            print(diagnostic.message, file=sys.stderr)
            failed = failed or diagnostic.fatal
        failed = failed or bool(hits)
    return 1 if failed else 0
