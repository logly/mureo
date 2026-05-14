"""Regression tests — every shipped ``skills/*/SKILL.md`` parses cleanly.

These tests guard the contract that the parser (P1-08) accepts every
SKILL.md currently shipped at the repository root under ``skills/``.
None of the 16 in-tree files declare a ``capabilities`` block in
Phase 1, so every parsed entry must report empty capability frozensets.
This sentinel catches accidental drift if someone adds ``capabilities``
without going through the dedicated migration PR (planner tracks this
as a follow-up P1-09).

Marks: every test is ``@pytest.mark.integration`` — touches the real
on-disk SKILL.md files shipped with the repo.

NOTE: the parser import is expected to FAIL during the RED phase — the
module ``mureo.core.skills.parser`` does not exist yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mureo.core.skills.parser import parse_skill_md  # noqa: E402 — RED-phase

# Repo root is three parents above this test file:
# tests/core/skills/test_existing_skills_parse.py
#                       └── parents[3] == repo root
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_SKILLS_DIR: Path = _REPO_ROOT / "skills"
_SHIPPED_SKILL_FILES: tuple[Path, ...] = tuple(sorted(_SKILLS_DIR.glob("*/SKILL.md")))


# A failsafe — if the test layout changes and we can't find the skills
# directory, every parametrized case below would silently be 0 cases,
# turning this regression test into a no-op. Fail loudly instead.
assert len(_SHIPPED_SKILL_FILES) >= 1, (
    f"expected at least one SKILL.md under {_SKILLS_DIR}; "
    f"found {len(_SHIPPED_SKILL_FILES)}"
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "skill_path",
    _SHIPPED_SKILL_FILES,
    ids=[p.parent.name for p in _SHIPPED_SKILL_FILES],
)
def test_shipped_skill_md_parses(skill_path: Path) -> None:
    """Every shipped ``skills/*/SKILL.md`` parses without raising."""
    entry = parse_skill_md(skill_path)

    # Sanity: parser returned a SkillEntry-shaped object.
    assert entry.name, "parsed skill must have a non-empty name"
    assert entry.description, "parsed skill must have a non-empty description"
    # Name on disk matches frontmatter ``name``.
    assert entry.name == skill_path.parent.name, (
        f"frontmatter name {entry.name!r} does not match directory name "
        f"{skill_path.parent.name!r}"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "skill_path",
    _SHIPPED_SKILL_FILES,
    ids=[p.parent.name for p in _SHIPPED_SKILL_FILES],
)
def test_shipped_skill_md_has_no_capabilities_yet(skill_path: Path) -> None:
    """Sentinel — until the P1-09 migration PR lands, no shipped
    SKILL.md should declare ``capabilities``. If this assertion ever
    starts failing, route the change through the dedicated migration PR
    instead of bundling it with parser changes.
    """
    entry = parse_skill_md(skill_path)

    assert entry.required_capabilities == frozenset(), (
        f"{skill_path.parent.name}: unexpected required_capabilities "
        f"{entry.required_capabilities!r} — content drift, route through "
        "the P1-09 frontmatter-migration PR"
    )
    assert entry.advisory_mode_capabilities == frozenset(), (
        f"{skill_path.parent.name}: unexpected advisory_mode_capabilities "
        f"{entry.advisory_mode_capabilities!r} — content drift, route through "
        "the P1-09 frontmatter-migration PR"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "skill_path",
    _SHIPPED_SKILL_FILES,
    ids=[p.parent.name for p in _SHIPPED_SKILL_FILES],
)
def test_shipped_skill_md_metadata_captured_in_extra(skill_path: Path) -> None:
    """Every shipped SKILL.md carries a ``metadata`` block (containing
    ``version``, ``openclaw``, etc.). The parser must surface it
    verbatim in ``extra`` for forward compatibility, and must NOT leak
    reserved keys (``name`` / ``description`` / ``capabilities``) into
    ``extra``.
    """
    entry = parse_skill_md(skill_path)

    # Reserved keys are stripped from extra.
    assert "name" not in entry.extra
    assert "description" not in entry.extra
    assert "capabilities" not in entry.extra

    # The shipped files all ship ``metadata`` — make that the regression
    # contract for this PR.
    assert "metadata" in entry.extra, (
        f"{skill_path.parent.name}: expected a top-level 'metadata' key "
        f"in extra (forward-compat preservation), got keys "
        f"{sorted(entry.extra.keys())}"
    )
