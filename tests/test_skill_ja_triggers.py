"""Japanese trigger coverage for the bundled operational skills (#396).

Operators phrase requests in Japanese, but skill firing is driven by the
``description`` frontmatter. Descriptions written only in English lower
the match confidence for natural Japanese asks ("CPAが急に悪化した" vs
"Use when the user reports a sudden CPA spike"), which showed up as
near-zero real-world usage for several workflow skills. The newer skills
(ad-fatigue-check, audience-review, ...) already enumerate Japanese
trigger phrases; this suite pins that EVERY user-triggered operational
skill does.

Foundation skills (``_mureo-*`` prefix) are exempt: they are loaded as
PREREQUISITEs by other skills, never fired from a user utterance.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mureo.core.skills.parser import parse_skill_md

REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = REPO_ROOT / "mureo" / "_data" / "skills"
_MIRROR = REPO_ROOT / "skills"

# Hiragana, katakana, and CJK unified ideographs — any hit means the
# description carries at least one Japanese trigger phrase.
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def _operational_skill_dirs() -> list[Path]:
    return sorted(
        p
        for p in _PACKAGED.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "SKILL.md").exists()
    )


def _skill_ids() -> list[str]:
    return [p.name for p in _operational_skill_dirs()]


@pytest.mark.unit
class TestOperationalSkillJapaneseTriggers:
    def test_discovers_a_plausible_skill_population(self) -> None:
        """Structural anchor: the packaged tree holds the operational
        skills (20 at the time of writing) — an empty glob must fail
        loudly instead of vacuously passing the suite."""
        assert len(_operational_skill_dirs()) >= 15

    @pytest.mark.parametrize("skill_dir", _operational_skill_dirs(), ids=_skill_ids())
    def test_description_contains_japanese_trigger(self, skill_dir: Path) -> None:
        parsed = parse_skill_md(skill_dir / "SKILL.md")
        description = parsed.description
        assert description
        assert _JAPANESE.search(description), (
            f"{skill_dir.name}: description has no Japanese trigger phrases — "
            "operators ask in Japanese, so English-only descriptions risk the "
            "skill never firing (#396). Follow the enumeration style of "
            "ad-fatigue-check / audience-review."
        )

    @pytest.mark.parametrize("skill_dir", _operational_skill_dirs(), ids=_skill_ids())
    def test_packaged_and_mirror_copies_stay_identical(self, skill_dir: Path) -> None:
        """The repo-root ``skills/`` mirror must match the packaged copy
        byte-for-byte, so a trigger edit cannot land on one side only."""
        mirror = _MIRROR / skill_dir.name / "SKILL.md"
        assert mirror.exists(), f"missing mirror for {skill_dir.name}"
        packaged_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert (
            mirror.read_text(encoding="utf-8") == packaged_text
        ), f"{skill_dir.name}: skills/ mirror differs from mureo/_data/skills/"
