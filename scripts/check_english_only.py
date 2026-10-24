#!/usr/bin/env python3
"""Fail when Japanese prose appears in shipped files (#810).

The repository is public and English-only. Japanese belongs in two places:

* the ``*.ja.md`` translations (``README.ja.md``, ``docs/*.ja.md``), which
  are not scanned at all; and
* string literals that ARE Japanese data — ad-text samples, the Japanese
  column headers a report parser matches on, character classes in a
  validator. Those are allowed in Python source.

What is flagged:

* Python (``mureo/``, ``tests/``, ``scripts/``): Japanese in a comment, in
  a docstring (the first statement of a module, class or function), or in
  an attribute docstring (PEP 257: a bare string statement right after an
  assignment), and any non-ASCII character in the name of a ``test_``
  function or a ``Test`` class (#818). Attribute docstrings are detected
  only directly in a module, class or function body, not inside an ``if``,
  ``try``, ``with`` or ``for`` block, matching PEP 257. Plain string
  literals and other identifiers are not checked.
* Markdown (top-level ``*.md``, ``docs/``, ``skills/``,
  ``mureo/_data/skills/``): any line with Japanese outside a fenced code
  block, unless the line ends with ``<!-- ja-literal -->``. Fences follow
  CommonMark: at most three spaces of indentation, a run of three or more
  backticks or tildes, no backtick in a backtick fence's info string (so a
  line that starts with inline code is prose), and a closing run of the
  same character at least as long with nothing after it. Limitation: a
  fence indented four or more spaces (for example inside a nested list
  item) is not recognised as a fence; mark such a line
  ``<!-- ja-literal -->`` or outdent the fence. One exemption:
  the ``description:`` key in the YAML frontmatter of a ``SKILL.md``, which
  carries the Japanese trigger phrases a skill fires on (#396).
* CSS and HTML under ``mureo/``: Japanese inside a ``/* */`` or ``<!-- -->``
  comment. What renders (rules, markup, text) is not checked.
* JavaScript under ``mureo/`` and ``tests/js/``: Japanese inside a ``/* */``
  block, or in a ``//`` comment that starts its line (leading whitespace
  allowed). Limitation: a ``//`` comment AFTER code on the same line is not
  checked, because telling it apart from ``//`` inside a string (a URL, say)
  needs a JavaScript tokenizer. String literals are not checked.

Usage::

    python scripts/check_english_only.py          # exit 1 on any hit
    python scripts/check_english_only.py --list   # print the scanned files

Each hit is printed as ``path:line: text``, in UTF-8 whatever the console's
code page is. A file that cannot be checked gets one line on stderr instead
of a traceback: a tracked path missing from the working tree is skipped
without failing the run (a staged deletion), while a file that cannot be
read, a file that is not UTF-8 or a Python file that does not parse fails
it. Standard library only, so it can run before the package is installed.
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
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hiragana + Katakana, CJK Extension A, CJK Unified Ideographs, half-width
# Katakana. The Katakana block includes the middle dot (U+30FB) and the
# long-vowel mark (U+30FC), so those two are flagged too. The CJK
# punctuation block (U+3000-U+303F, e.g. the full stop and brackets) and
# the full-width ASCII forms (U+FF01-U+FF65) are not included.
JAPANESE = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")

JA_LITERAL_MARKER = "<!-- ja-literal -->"

_PYTHON_DIRS = ("mureo/", "tests/", "scripts/")
_MARKDOWN_DIRS = ("docs/",)
_SKILL_DIRS = ("skills/", "mureo/_data/skills/")
_EXCLUDED_SUFFIXES = (".ja.md",)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_START_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)
_WEB_COMMENTS: dict[str, tuple[re.Pattern[str], ...]] = {
    ".css": (_BLOCK_COMMENT,),
    ".html": (re.compile(r"<!--.*?-->", re.DOTALL),),
    ".js": (_BLOCK_COMMENT, _LINE_START_COMMENT),
}
_WEB_DIRS: dict[str, tuple[str, ...]] = {
    ".css": ("mureo/",),
    ".html": ("mureo/",),
    ".js": ("mureo/", "tests/js/"),
}

_FRONTMATTER_DELIMITER = "---"
_YAML_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:")
_SKILL_FILE = "SKILL.md"
_TRIGGER_KEY = "description"

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


class Diagnostic(NamedTuple):
    """Why a tracked file was not scanned, and whether that fails the run."""

    message: str
    fatal: bool


def is_scanned(path: str) -> bool:
    """Return True if the repository-relative ``path`` is in the checked set."""
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


def _comment_hits(source: str) -> list[Hit]:
    hits: list[Hit] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and JAPANESE.search(token.string):
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


def _docstring_hits(tree: ast.Module, lines: list[str]) -> list[Hit]:
    hits: list[Hit] = []
    for node in _docstring_nodes(tree):
        end = node.end_lineno or node.lineno
        for number in range(node.lineno, end + 1):
            text = lines[number - 1]
            if JAPANESE.search(text):
                hits.append((number, text))
    return hits


def _test_name_hits(tree: ast.Module, lines: list[str]) -> list[Hit]:
    hits: list[Hit] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = _TEST_FUNCTION_PREFIX
        elif isinstance(node, ast.ClassDef):
            prefix = _TEST_CLASS_PREFIX
        else:
            continue
        if node.name.startswith(prefix) and not node.name.isascii():
            hits.append((node.lineno, lines[node.lineno - 1]))
    return hits


def scan_python(source: str) -> list[Hit]:
    """Return ``(line, text)`` for Japanese prose and non-ASCII test names."""
    tree = ast.parse(source)
    lines = _AST_LINE_BREAK.split(source)
    return sorted(
        set(_comment_hits(source))
        | set(_docstring_hits(tree, lines))
        | set(_test_name_hits(tree, lines))
    )


def skill_trigger_lines(text: str) -> frozenset[int]:
    """Return the line numbers of ``description:`` in a SKILL.md frontmatter.

    The one exemption from the markdown rule, on purpose (#396):
    ``tests/test_skill_ja_triggers.py`` requires every operational skill's
    description to carry Japanese trigger phrases, because skill firing is
    driven by that text and operators ask in Japanese. Only this key is
    exempt — its line and any continuation lines up to the next key. Every
    other frontmatter key (a Japanese ``name:`` included) and the whole body
    are checked like any other markdown.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return frozenset()
    closing = next(
        (
            i
            for i, line in enumerate(lines[1:], 1)
            if line.strip() == _FRONTMATTER_DELIMITER
        ),
        None,
    )
    if closing is None:
        return frozenset()
    exempt: set[int] = set()
    key: str | None = None
    for number, line in enumerate(lines[1:closing], start=2):
        match = _YAML_KEY.match(line)
        if match:
            key = match.group(1)
        if key == _TRIGGER_KEY:
            exempt.add(number)
    return frozenset(exempt)


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


def scan_markdown(text: str, exempt: frozenset[int] = frozenset()) -> list[Hit]:
    """Return ``(line, text)`` for Japanese outside fences and unmarked.

    Lines in ``exempt`` are skipped (see :func:`skill_trigger_lines`).
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
        if JAPANESE.search(line) and not line.rstrip().endswith(JA_LITERAL_MARKER):
            hits.append((number, line))
    return hits


def scan_comments(text: str, comments: tuple[re.Pattern[str], ...]) -> list[Hit]:
    """Return ``(line, text)`` for Japanese inside any ``comments`` match."""
    lines = text.splitlines()
    hits: set[Hit] = set()
    for comment in comments:
        for match in comment.finditer(text):
            first = text.count("\n", 0, match.start()) + 1
            for offset, segment in enumerate(match.group().split("\n")):
                if JAPANESE.search(segment):
                    hits.add((first + offset, lines[first + offset - 1]))
    return sorted(hits)


def scan_file(path: str, text: str) -> list[Hit]:
    """Dispatch on file type: Python, CSS/HTML/JS comments, or markdown."""
    suffix = Path(path).suffix
    if suffix == ".py":
        return scan_python(text)
    if suffix in _WEB_COMMENTS:
        return scan_comments(text, _WEB_COMMENTS[suffix])
    if Path(path).name == _SKILL_FILE:
        return scan_markdown(text, skill_trigger_lines(text))
    return scan_markdown(text)


def _error_line(error: Exception) -> int | None:
    """Return the line a parse error points at, if it carries one."""
    if isinstance(error, SyntaxError):
        return error.lineno
    # TokenError's args are (message, (line, column)).
    position = error.args[1] if len(error.args) > 1 else None
    return position[0] if isinstance(position, tuple) else None


def check_path(root: Path, path: str) -> tuple[list[Hit], Diagnostic | None]:
    """Scan one tracked file: return its hits and, if it was not scanned, why.

    The diagnostic is None when the file was scanned. A path missing from
    the working tree (a staged deletion) is skipped without failing the
    run; a file that cannot be read, a file that is not UTF-8, or a Python
    file that does not parse, is not checked and fails it. A UTF-8 byte
    order mark is dropped before scanning. ``ast.parse`` raises ValueError
    rather than SyntaxError for a NUL byte on Python 3.10 and 3.11.
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
        return scan_file(path, text), None
    except (SyntaxError, ValueError, tokenize.TokenError) as error:
        line = _error_line(error)
        where = path if line is None else f"{path}:{line}"
        return [], Diagnostic(f"{where}: {_SYNTAX_ERROR}", fatal=True)


def tracked_files(root: Path) -> list[str]:
    """Return the repository-relative paths of the checked, tracked files."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return sorted(p for p in result.stdout.split("\0") if p and is_scanned(p))


def _use_utf8_output() -> None:
    """Write UTF-8 whatever the console's code page is.

    Every hit line contains Japanese by definition. On a console with a
    legacy code page (Windows cp1252) printing one raised UnicodeEncodeError,
    so the run ended in a traceback with no report. Characters a stream
    still cannot take are written as backslash escapes, never dropped.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    _use_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--list", action="store_true", help="print the scanned file set and exit"
    )
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="repository root to scan"
    )
    args = parser.parse_args(argv)

    paths = tracked_files(args.root)
    if args.list:
        print("\n".join(paths))
        return 0

    failed = False
    for path in paths:
        hits, diagnostic = check_path(args.root, path)
        for number, line in hits:
            print(f"{path}:{number}: {line.strip()}")
        if diagnostic is not None:
            print(diagnostic.message, file=sys.stderr)
            failed = failed or diagnostic.fatal
        failed = failed or bool(hits)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
