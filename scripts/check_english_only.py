#!/usr/bin/env python3
"""Fail when Japanese prose appears in shipped files (#810).

The repository is public and English-only. Japanese belongs in two places:

* the ``*.ja.md`` translations (``README.ja.md``, ``docs/*.ja.md``), which
  are not scanned at all; and
* string literals that ARE Japanese data — ad-text samples, the Japanese
  column headers a report parser matches on, character classes in a
  validator. Those are allowed in Python source.

What is flagged:

* Python (``mureo/``, ``tests/``, ``scripts/``): Japanese in a comment, or in
  a docstring (the first statement of a module, class or function). Plain
  string literals are not checked.
* Markdown (top-level ``*.md``, ``docs/``, ``skills/``,
  ``mureo/_data/skills/``): any line with Japanese outside a fenced code
  block, unless the line ends with ``<!-- ja-literal -->``. One exemption:
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
code page is. Standard library only, so it can run before the package is
installed.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

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

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

Hit = tuple[int, str]


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


def _docstring_nodes(tree: ast.Module) -> list[ast.Expr]:
    nodes: list[ast.Expr] = []
    for owner in ast.walk(tree):
        if not isinstance(owner, _DOCSTRING_OWNERS) or not owner.body:
            continue
        first = owner.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            nodes.append(first)
    return nodes


def _docstring_hits(source: str) -> list[Hit]:
    lines = source.splitlines()
    hits: list[Hit] = []
    for node in _docstring_nodes(ast.parse(source)):
        end = node.end_lineno or node.lineno
        for number in range(node.lineno, end + 1):
            text = lines[number - 1]
            if JAPANESE.search(text):
                hits.append((number, text))
    return hits


def scan_python(source: str) -> list[Hit]:
    """Return ``(line, text)`` for Japanese in comments and docstrings."""
    return sorted(set(_comment_hits(source)) | set(_docstring_hits(source)))


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


def scan_markdown(text: str, exempt: frozenset[int] = frozenset()) -> list[Hit]:
    """Return ``(line, text)`` for Japanese outside fences and unmarked.

    Lines in ``exempt`` are skipped (see :func:`skill_trigger_lines`).
    """
    hits: list[Hit] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if number in exempt:
            continue
        match = _FENCE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
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
        text = (args.root / path).read_text(encoding="utf-8")
        for number, line in scan_file(path, text):
            print(f"{path}:{number}: {line.strip()}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
