#!/usr/bin/env python3
"""Fail when shipped text records how a change came about.

Comments, docstrings, docs and CHANGELOG entries explain why the code has
its shape. They do not record who asked for a change, who decided,
approved or rejected it, what a review found and under which label, which
workflow role or phase wrote it, or which internal document or plan label
it came from. A reader of the public repository cannot see any of those
sources, and the sentence stops being true the moment the process changes.
A public issue or PR number is the only attribution.

What is flagged: a line of prose that matches one of the patterns below
(``ROLE_ACTION``, ``WORKFLOW_ROLE``, ...). Prose is extracted the same way
as for ``check_english_only.py`` (see ``shipped_text.py``): Python
comments, docstrings and attribute docstrings; markdown lines outside
fenced code blocks; ``/* */``, ``<!-- -->`` and line-start ``//`` comments
in CSS, HTML and JavaScript; and the name of a ``test_`` function or a
``Test`` class, read with underscores as spaces. Python string literals are
not scanned. There is no allowlist and no inline opt-out: a hit is fixed by
rewriting the sentence to state the fact or the reason.

Known limitation: single-letter review labels such as ``H1`` or ``M2``
cannot be matched without false positives (they collide with headings,
product codes and coordinates), so they are caught in review, not by this
script.

Scanned files: the English-only check's set (``CHANGELOG.md`` is in it),
minus ``AGENTS.md`` and ``CONTRIBUTING.md`` (they describe the review
process and this rule) and this script and its test (they carry the
patterns).

Usage::

    python scripts/check_comment_provenance.py          # exit 1 on any hit
    python scripts/check_comment_provenance.py --list   # print the scanned files

Run it as ``python scripts/check_comment_provenance.py`` (it imports ``shipped_text`` from
its own directory, so ``python -m`` and ``-P``/``-I`` runs do not resolve it).

Each hit is printed as ``path:line: text``; a file that cannot be checked
gets one line on stderr, with the same rules as the English-only check.
Standard library only, so it can run before the package is installed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import shipped_text
from shipped_text import WEB_COMMENTS, Diagnostic, Hit

__all__ = [
    "PATTERNS",
    "REPO_ROOT",
    "Diagnostic",
    "Hit",
    "check_path",
    "is_provenance",
    "is_scanned",
    "main",
    "scan_comments",
    "scan_file",
    "scan_markdown",
    "scan_python",
    "tracked_files",
]

REPO_ROOT = shipped_text.REPO_ROOT

_ROLE = (
    r"(?:the\s+)?(?:owner|ceo|cto|boss|president|founder|maintainer|reviewer"
    r"|implementer|sub-?agent|main\s+loop|orchestrator|verifier)(?:'s)?"
)
_VERB = (
    r"(?:asked|said|wanted|requested|told|decided|rejected|reported|flagged"
    r"|noted|found|confirmed|approved|chose|picked|preferred|instructed"
    r"|decision|request|report|instruction)"
)
_I = re.IGNORECASE

# A person or role and what they did: "the owner asked", "CTO decision".
ROLE_ACTION = re.compile(rf"\b{_ROLE}\s+{_VERB}\b", _I)
# The reviewing role named as an actor.
WORKFLOW_ROLE = re.compile(r"\bthe\s+reviewer\b", _I)
# A review's output cited as the source.
REVIEW_FINDING = re.compile(r"\breview\s+findings?\b", _I)
# A named review pass cited as the source.
REVIEW_PASS = re.compile(r"\b(?:full|capture|security|code)[-\s]review\b", _I)
# A numbered review round cited as the source.
ROUND_REVIEW = re.compile(r"\bround[-\s][0-9]+\s+review\b", _I)
# A review credited with what it found.
REVIEW_VERB = re.compile(r"\breview\s+(?:flagged|caught|found|insisted)\b", _I)
# The internal design document cited as the source.
DESIGN_DOC = re.compile(r"\bdesign\s+doc\b", _I)
# An internal planning document cited as the source.
ACCEPTANCE_CRITERIA = re.compile(r"\bacceptance\s+criteria\b", _I)
# A person or title credited in the passive: "approved by the owner".
ROLE_PASSIVE = re.compile(
    r"\b(?:asked|requested|decided|approved|rejected)\s+by\s+(?:the\s+)?"
    r"(?:owner|maintainer|founder|president|ceo|cto)\b",
    _I,
)
# A test-first workflow phase, spaced or hyphenated.
WORKFLOW_PHASE = re.compile(r"\b(?:red|green)[-\s]phase\b", _I)
# The test-first cycle written as arrows; case-sensitive.
TDD_CYCLE = re.compile(r"\bRED\s*(?:->|→|=>)\s*GREEN\b")
# The implementing role as a bare noun.
IMPLEMENTER = re.compile(r"\bimplementers?\b", _I)
# A conversation cited as the reason.
CONVERSATION = re.compile(r"\bas\s+(?:discussed|agreed)\b", _I)
# A request cited as the reason.
WERE_ASKED = re.compile(r"\bwe\s+were\s+asked\b", _I)
# A document or person cited as the authority.
PER_SOURCE = re.compile(
    r"\bper\s+(?:the\s+)?(?:spec|brief|handoff|review|owner|ceo|cto)\b", _I
)
# The internal hand-off document; case-sensitive, "OAuth handoff" is product text.
HANDOFF_DOC = re.compile(r"\bHANDOFF\b")
# The internal hand-off document, named with its author.
PLANNER_HANDOFF = re.compile(r"\bplanner\s+handoff\b", _I)
# A hand-over between people or sessions.
HANDOVER = re.compile(r"\bhandover\b", _I)
# An internal plan label such as P1-05 or P2-2; case-sensitive.
PLAN_LABEL = re.compile(r"\bP[0-9]-[0-9]{1,2}\b")
# An executive title; case-sensitive.
EXECUTIVE = re.compile(r"\b(?:CEO|CTO)\b")

PATTERNS: tuple[re.Pattern[str], ...] = (
    ROLE_ACTION,
    WORKFLOW_ROLE,
    REVIEW_FINDING,
    REVIEW_PASS,
    ROUND_REVIEW,
    REVIEW_VERB,
    DESIGN_DOC,
    ACCEPTANCE_CRITERIA,
    ROLE_PASSIVE,
    WORKFLOW_PHASE,
    TDD_CYCLE,
    IMPLEMENTER,
    CONVERSATION,
    WERE_ASKED,
    PER_SOURCE,
    HANDOFF_DOC,
    PLANNER_HANDOFF,
    HANDOVER,
    PLAN_LABEL,
    EXECUTIVE,
)

# They describe the review process and this rule, or carry the patterns.
_NOT_SCANNED = frozenset(
    {
        "AGENTS.md",
        "CONTRIBUTING.md",
        "scripts/check_comment_provenance.py",
        "tests/test_check_comment_provenance.py",
    }
)


def is_provenance(text: str) -> bool:
    """Return True if ``text`` matches any of :data:`PATTERNS`."""
    return any(pattern.search(text) for pattern in PATTERNS)


def _is_provenance_name(name: str) -> bool:
    return is_provenance(name.replace("_", " "))


def is_scanned(path: str) -> bool:
    """Return True if the repository-relative ``path`` is in the checked set."""
    return shipped_text.is_scanned(path) and path not in _NOT_SCANNED


def scan_python(source: str) -> list[Hit]:
    """Return ``(line, text)`` for provenance in comments, docstrings and test names."""
    return shipped_text.scan_python(source, is_provenance, _is_provenance_name)


def scan_markdown(text: str) -> list[Hit]:
    """Return ``(line, text)`` for provenance outside fenced code blocks."""
    return shipped_text.scan_markdown(text, is_provenance)


def scan_comments(text: str, comments: tuple[re.Pattern[str], ...]) -> list[Hit]:
    """Return ``(line, text)`` for provenance inside any ``comments`` match."""
    return shipped_text.scan_comments(text, comments, is_provenance)


def scan_file(path: str, text: str) -> list[Hit]:
    """Dispatch on file type: Python, CSS/HTML/JS comments, or markdown."""
    suffix = Path(path).suffix
    if suffix == ".py":
        return scan_python(text)
    if suffix in WEB_COMMENTS:
        return scan_comments(text, WEB_COMMENTS[suffix])
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
