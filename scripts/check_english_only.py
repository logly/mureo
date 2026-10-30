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

Run it as ``python scripts/check_english_only.py`` (it imports ``shipped_text`` from
its own directory, so ``python -m`` and ``-P``/``-I`` runs do not resolve it).

Each hit is printed as ``path:line: text``, in UTF-8 whatever the console's
code page is. A file that cannot be checked gets one line on stderr instead
of a traceback: a tracked path missing from the working tree is skipped
without failing the run (a staged deletion), while a file that cannot be
read, a file that is not UTF-8 or a Python file that does not parse fails
it. Standard library only, so it can run before the package is installed.
The file walk and the prose extraction live in ``shipped_text.py``; this
module supplies the Japanese matcher, the test-name rule and the two
markdown exemptions above.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import shipped_text
from shipped_text import WEB_COMMENTS, Diagnostic, Hit

__all__ = [
    "JAPANESE",
    "JA_LITERAL_MARKER",
    "REPO_ROOT",
    "Diagnostic",
    "Hit",
    "check_path",
    "is_scanned",
    "main",
    "scan_comments",
    "scan_file",
    "scan_markdown",
    "scan_python",
    "skill_trigger_lines",
    "tracked_files",
]

REPO_ROOT = shipped_text.REPO_ROOT

# Hiragana + Katakana, CJK Extension A, CJK Unified Ideographs, half-width
# Katakana. The Katakana block includes the middle dot (U+30FB) and the
# long-vowel mark (U+30FC), so those two are flagged too. The CJK
# punctuation block (U+3000-U+303F, e.g. the full stop and brackets) and
# the full-width ASCII forms (U+FF01-U+FF65) are not included.
JAPANESE = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")

JA_LITERAL_MARKER = "<!-- ja-literal -->"

is_scanned = shipped_text.is_scanned

_FRONTMATTER_DELIMITER = "---"
_YAML_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:")
_SKILL_FILE = "SKILL.md"
_TRIGGER_KEY = "description"


def _is_japanese(text: str) -> bool:
    return JAPANESE.search(text) is not None


def _is_non_ascii(name: str) -> bool:
    return not name.isascii()


def _is_unmarked_japanese(line: str) -> bool:
    return _is_japanese(line) and not line.rstrip().endswith(JA_LITERAL_MARKER)


def scan_python(source: str) -> list[Hit]:
    """Return ``(line, text)`` for Japanese prose and non-ASCII test names."""
    return shipped_text.scan_python(source, _is_japanese, _is_non_ascii)


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
    return shipped_text.scan_markdown(text, _is_unmarked_japanese, exempt)


def scan_comments(text: str, comments: tuple[re.Pattern[str], ...]) -> list[Hit]:
    """Return ``(line, text)`` for Japanese inside any ``comments`` match."""
    return shipped_text.scan_comments(text, comments, _is_japanese)


def scan_file(path: str, text: str) -> list[Hit]:
    """Dispatch on file type: Python, CSS/HTML/JS comments, or markdown."""
    suffix = Path(path).suffix
    if suffix == ".py":
        return scan_python(text)
    if suffix in WEB_COMMENTS:
        return scan_comments(text, WEB_COMMENTS[suffix])
    if Path(path).name == _SKILL_FILE:
        return scan_markdown(text, skill_trigger_lines(text))
    return scan_markdown(text)


def check_path(root: Path, path: str) -> tuple[list[Hit], Diagnostic | None]:
    """Scan one tracked file: return its hits and, if it was not scanned, why.

    See :func:`shipped_text.check_path` for the diagnostics.
    """
    return shipped_text.check_path(root, path, scan_file)


def tracked_files(root: Path) -> list[str]:
    """Return the repository-relative paths of the checked, tracked files."""
    return shipped_text.tracked_files(root, is_scanned)


def main(argv: list[str] | None = None) -> int:
    return shipped_text.run(argv, __doc__ or "", tracked_files, scan_file)


if __name__ == "__main__":
    sys.exit(main())
