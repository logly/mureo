"""Detect whether a host's deployed workflow skills are current (#728).

The deployed copies under a host's skills directory are written only by an
install (``mureo setup`` / the configure UI), so an upgrade can leave them on
an older mureo's format. :func:`detect_workflow_skills` compares each deployed
``SKILL.md`` with the copy this mureo ships and says whether the set is
current, stale or incomplete. Read by ``mureo upgrade``
(:mod:`mureo.cli.upgrade_cmd`) and the configure UI's status poll
(:mod:`mureo.web.status_collector`), so it lives in the CLI layer next to the
installer whose package data it reads (#863).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mureo import __version__
from mureo.cli.setup_cmd import _get_data_path

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# The three states a deployed workflow-skill set can be in (#728). Surfaced
# verbatim on the status payload as ``setup_parts.skills_state``, so the
# strings are part of the JSON contract the dashboard reads.
SKILLS_MISSING = "missing"
SKILLS_STALE = "stale"
SKILLS_CURRENT = "current"

# Frontmatter is delimited by lines containing exactly ``---``, the opener on
# line 1 — the same rule ``mureo.core.skills.parser`` enforces.
_SKILL_FRONTMATTER_DELIM = "---"

# ``version:`` anywhere inside the frontmatter block. Deliberately indifferent
# to the indentation that puts it under ``metadata:``, and unanchored at the
# end so a trailing ``# comment`` does not hide the pin: the shipped files are
# the only writers of the key, and a stricter parse would answer "unknown"
# (i.e. stale) for a file whose block was merely reordered or annotated.
_SKILL_VERSION_RE = re.compile(r"^\s*version:\s*(\S+)")

# Bytes of a SKILL.md read to find its frontmatter. Comfortably past the
# longest block mureo ships (~2 KB of description) and far short of the 64 KiB
# a whole file may be: none of the body answers "which version is this", and
# this runs once per shipped skill on every status poll.
_SKILL_HEAD_BYTES = 8192


@dataclass(frozen=True)
class SkillsStatus:
    """What a host's deployed workflow-skill set is, version included (#728).

    ``state`` is one of :data:`SKILLS_MISSING` / :data:`SKILLS_STALE` /
    :data:`SKILLS_CURRENT`. ``installed_versions`` maps each shipped skill name
    to the version its deployed copy records — ``None`` for a copy too old to
    record one — and omits the ones that are not deployed at all.
    """

    state: str
    expected_version: str
    installed_versions: dict[str, str | None] = field(default_factory=dict)

    @property
    def is_current(self) -> bool:
        return self.state == SKILLS_CURRENT

    @property
    def installed_version(self) -> str | None:
        """The single version to name in a one-line report, or ``None``."""
        return _dominant_version(self.installed_versions.values())


def _read_skill_version(skill_md: Path) -> str | None:
    """Return the mureo version a ``SKILL.md`` records about itself.

    Every shipped skill pins ``metadata.version`` to the mureo that shipped it
    (CI asserts the pin across all shipped files), and ``install_skills``
    copies the file verbatim — so the deployed copy carries the version of the
    mureo that deployed it, and that is the only thing on disk that can date it.

    Parsed line-wise instead of through :mod:`mureo.core.skills.parser`: that
    parser is the right one for loading a skill (YAML, capabilities,
    validation), and this module is a pure filesystem read on the status-poll
    path that must not pull the skills stack in behind it. Only the frontmatter
    block is looked at, so a ``version:`` line in the body cannot answer for
    the file.

    ``None`` when the file is unreadable, has no leading ``---`` block, or that
    block records no version. An unknown version is never treated as a match:
    a copy that cannot say where it came from predates the pin, which makes it
    older than every copy that can.
    """
    try:
        with skill_md.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(_SKILL_HEAD_BYTES)
    except OSError:
        return None
    lines = head.splitlines()
    if not lines or lines[0].lstrip("\ufeff").rstrip() != _SKILL_FRONTMATTER_DELIM:
        return None
    for line in lines[1:]:
        if line.rstrip() == _SKILL_FRONTMATTER_DELIM:
            return None
        match = _SKILL_VERSION_RE.match(line)
        if match is not None:
            return match.group(1).strip("\"'")
    return None


def _shipped_skill_versions() -> dict[str, str | None]:
    """The skills this mureo would install, each with its recorded version.

    Read from ``mureo/_data/skills`` on disk rather than assumed to be
    :data:`mureo.__version__`. The two agree in any released install (CI pins
    them), but they disagree for exactly one process: the one running
    ``mureo upgrade``, which holds the OLD ``__version__`` in memory while the
    NEW package data is already on disk. Comparing deployed copies against the
    source files they were copied from is right in both cases.
    """
    try:
        src = _get_data_path("skills")
        return {
            d.name: _read_skill_version(d / "SKILL.md")
            for d in sorted(src.iterdir())
            if d.is_dir() and (d / "SKILL.md").exists()
        }
    except OSError:  # unreadable package data — cannot claim anything is installed
        return {}


def _dominant_version(versions: Iterable[str | None]) -> str | None:
    """The one version worth naming in a one-line report.

    A skill set is normally all of one version, so this is that version. When
    it is not (a half-finished copy, a hand-edited file), the most common one
    describes the set better than an arbitrary member does; ties break on the
    lowest string so the answer never depends on iteration order.
    """
    counts = Counter(v for v in versions if v)
    if not counts:
        return None
    top = max(counts.values())
    return min(v for v, count in counts.items() if count == top)


def detect_workflow_skills(skills_dir: Path) -> SkillsStatus:
    """Report whether ``skills_dir`` holds a current, stale or absent skill set.

    Detected, never recalled (#423). The old status came from a flag file that
    only the configure UI's own actions wrote, so a ``mureo setup`` install read
    ✗ while present, and a hand-deleted skill read ✓ while absent — the UI
    asserting a component is there when it is not.

    Presence alone was still not the question (#728). ``pip install -U mureo``
    never rewrites the deployed copies, so a skill from 0.10.39 sat in
    ``~/.claude/skills`` of a 0.17 install for months reading ✓ — running
    workflows written against tools that had moved on. So a set that is all
    there but not all CURRENT is its own state.

    A *missing* skill still outranks a stale one: the remedy is the same either
    way (re-run the install, which overwrites), and a half-installed set
    reported as ✓ is how an operator ends up without the workflow they think
    they have — the more urgent half of the fact leads.

    A skill whose SHIPPED copy records no version is not judged: mureo cannot
    date it, and inventing staleness out of package data it failed to read
    would make the check cry wolf on the install that is actually fine.
    """
    shipped = _shipped_skill_versions()
    expected = _dominant_version(shipped.values()) or __version__
    if not shipped:
        return SkillsStatus(state=SKILLS_MISSING, expected_version=expected)
    installed: dict[str, str | None] = {}
    absent = False
    for name in shipped:
        skill_md = skills_dir / name / "SKILL.md"
        if not skill_md.exists():
            absent = True
            continue
        installed[name] = _read_skill_version(skill_md)
    if absent:
        return SkillsStatus(SKILLS_MISSING, expected, installed)
    stale = any(
        installed[name] != shipped_version
        for name, shipped_version in shipped.items()
        if shipped_version is not None
    )
    return SkillsStatus(SKILLS_STALE if stale else SKILLS_CURRENT, expected, installed)
