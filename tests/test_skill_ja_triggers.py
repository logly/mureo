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

That exemption is about *triggers only*. This module used to also pin the
``skills/`` ↔ ``mureo/_data/skills/`` byte-identity over the same filtered
list, which quietly left every foundation skill unpinned there (#672). The
byte-identity pin now lives in one place that covers both trees in full —
``tests/test_plugin_manifests.py::test_skill_copies_are_byte_identical``.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mureo.core.skills.parser import parse_skill_md

REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = REPO_ROOT / "mureo" / "_data" / "skills"

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
