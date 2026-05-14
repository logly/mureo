"""Skill discovery, parsing, and capability matching (Issue #89 P1-08).

This package introduces the skill layer that pairs declarative skill
metadata (shipped as ``SKILL.md`` files with YAML frontmatter) with the
provider registry from P1-07.

Public surface
--------------
- :class:`SkillEntry` — frozen dataclass capturing one parsed skill.
- :class:`SkillMatch` — three-bucket classification of skills against a
  single provider.
- :class:`ProviderMatch` — symmetric three-bucket classification of
  providers against a single skill.
- :class:`SkillParseError` — raised on any decode / YAML / validation
  failure inside :func:`parse_skill_md`.
- :class:`SkillDiscoveryWarning` — :class:`UserWarning` subclass emitted
  when discovery skips a malformed plugin, file, or duplicate.
- :func:`parse_skill_md` — read one ``SKILL.md`` from disk into a
  :class:`SkillEntry`.
- :func:`discover_skills` — entry-points + built-in directory scan with
  per-plugin fault isolation.
- :func:`match_skills` — pure function: ``(skills, provider) ->
  SkillMatch``.
- :func:`providers_for_skill` — pure function: ``(skill, registry) ->
  ProviderMatch``.
- :data:`SKILLS_ENTRY_POINT_GROUP` — re-exported from
  :mod:`mureo.core.providers.registry` for convenience.

Foundation rule
---------------
This subpackage may only import from
:mod:`mureo.core.providers.{base,capabilities,registry}`. No imports
from the four domain Protocol modules; the matcher treats providers
structurally via :class:`ProviderEntry`.
"""

from __future__ import annotations

from mureo.core.providers.registry import SKILLS_ENTRY_POINT_GROUP
from mureo.core.skills.discovery import (
    SkillDiscoveryWarning,
    clear_skills_cache,
    discover_skills,
)
from mureo.core.skills.matcher import (
    ProviderMatch,
    SkillMatch,
    match_skills,
    providers_for_skill,
)
from mureo.core.skills.models import SkillEntry
from mureo.core.skills.parser import SkillParseError, parse_skill_md

__all__ = [
    "SKILLS_ENTRY_POINT_GROUP",
    "ProviderMatch",
    "SkillDiscoveryWarning",
    "SkillEntry",
    "SkillMatch",
    "SkillParseError",
    "clear_skills_cache",
    "discover_skills",
    "match_skills",
    "parse_skill_md",
    "providers_for_skill",
]
