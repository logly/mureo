"""Skills treat a namespaced built-in variant as the built-in (#825).

A provider whose tools are ``<builtin_platform>_<suffix>_<operation>`` with
the same operation set and input schemas as the built-in
``<builtin_platform>_<operation>`` tools is the built-in platform reached
through a different credential source. ``_mureo-shared`` defines that rule
once; every skill that names a built-in tool carries a one-line note pointing
at it, so the hard-coded tool names are not read as "built-in only".

Pinned in BOTH the packaged copy (``mureo/_data/skills``) and the repo-root
mirror (``skills/``).

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_TREES = (_ROOT / "mureo" / "_data" / "skills", _ROOT / "skills")

_BUILTIN_TOOL = re.compile(r"(meta_ads_|google_ads_|search_console_|amazon_ads_)")

_NOTE = (
    "Tool names below refer to the built-in platforms; a namespaced variant "
    "(see `_mureo-shared` → Namespaced built-in variants) is used with its "
    "prefix substituted."
)

_SECTION = "## Namespaced built-in variants"


def _flatten(text: str) -> str:
    """Join wrapped blockquote / paragraph lines into single spaces."""
    lines = (line.lstrip("> ").strip() for line in text.splitlines())
    return " ".join(line for line in lines if line)


def _skills_naming_builtin_tools() -> list[Path]:
    found = [
        path
        for tree in _TREES
        for path in sorted(tree.glob("*/SKILL.md"))
        if _BUILTIN_TOOL.search(path.read_text(encoding="utf-8"))
    ]
    assert found, "expected at least one skill naming a built-in tool"
    return found


@pytest.mark.parametrize(
    "skill",
    _skills_naming_builtin_tools(),
    ids=lambda p: p.parent.relative_to(_ROOT).as_posix(),
)
def test_skill_naming_builtin_tools_carries_variant_note(skill: Path) -> None:
    text = skill.read_text(encoding="utf-8")
    assert _NOTE in _flatten(text), f"{skill} names built-in tools without the note"


@pytest.mark.parametrize(
    "skill",
    _skills_naming_builtin_tools(),
    ids=lambda p: p.parent.relative_to(_ROOT).as_posix(),
)
def test_variant_note_sits_near_the_top(skill: Path) -> None:
    """The note precedes the first ``##`` section, so it frames every mention."""
    text = skill.read_text(encoding="utf-8")
    first_section = text.find("\n## ")
    head = text if first_section == -1 else text[:first_section]
    assert _NOTE in _flatten(head), f"{skill}: note must precede the first section"


@pytest.mark.parametrize("tree", _TREES, ids=lambda t: t.relative_to(_ROOT).as_posix())
def test_shared_skill_defines_namespaced_variants(tree: Path) -> None:
    text = (tree / "_mureo-shared" / "SKILL.md").read_text(encoding="utf-8")
    assert _SECTION in text
    section = text.split(_SECTION, 1)[1].split("\n## ", 1)[0]
    flat = _flatten(section)
    # The shape, the matching criteria and where the rule is derived from.
    assert "<builtin_platform>_<suffix>_<operation>" in flat
    assert "input schemas" in flat
    assert "live tool list" in flat
    # A non-matching provider stays on the plugin path.
    assert "Plugin platforms" in flat
    # Both present: pick the configured one, never both for one account.
    assert "credentials are configured" in flat
    assert "never call both" in flat
