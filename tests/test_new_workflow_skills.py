"""Content tests for the bundled workflow skills added in this family:
``tracking-health``, ``budget-pacing``, ``monthly-report`` (PR #390) and
``experiment``, ``audience-review``, ``ad-fatigue-check``,
``incident-postmortem`` (this PR).

These are lighter than ``test_creative_generate_skill.py`` — one shared
parametrized suite over all the skills. For each skill we pin the load-
bearing invariants a future edit could silently break:

1. The packaged copy (``mureo/_data/skills``) and the repo-root mirror
   (``skills/``) stay **byte-identical**.
2. The frontmatter parses through the real discovery parser, ``name``
   matches the directory, and ``metadata.version`` tracks ``pyproject.toml``.
3. The ``Before you start`` pointer to the shared *Diagnostic preamble* is
   present (the #389 dedup convention).
4. At least three **verified-real** MCP tool names are referenced (guards
   against a rewrite drifting to a tool that does not exist).
5. Approval-gate language is present (no silent platform mutation).
6. The ``mureo_state_report_set`` persistence key is present for the skills
   that persist a report (``tracking`` / ``pacing`` / ``monthly`` /
   ``experiment`` / ``audience`` / ``fatigue``). ``incident-postmortem``
   persists no report — instead it must state it makes no ad-platform
   writes.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mureo.core.skills.parser import parse_skill_md

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = REPO_ROOT / "mureo" / "_data" / "skills"
_MIRROR = REPO_ROOT / "skills"


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# name -> at least three exact MCP tool names verified to exist in the
# tool definitions (see mureo/mcp/_tools_*.py). Every string here MUST be a
# real tool; the test asserts each appears verbatim in the skill body.
_SKILLS: dict[str, tuple[str, ...]] = {
    "tracking-health": (
        "meta_ads_pixels_list",
        "meta_ads_pixels_get",
        "meta_ads_pixels_stats",
        "google_ads_conversions_list",
        "google_ads_conversions_performance",
    ),
    "budget-pacing": (
        "google_ads_performance_report",
        "meta_ads_insights_report",
        "google_ads_budget_update",
    ),
    "monthly-report": (
        "google_ads_performance_report",
        "meta_ads_insights_report",
        "mureo_outcome_evaluate",
    ),
    "experiment": (
        "meta_ads_split_tests_create",
        "meta_ads_split_tests_get",
        "meta_ads_split_tests_end",
        "mureo_outcome_evaluate",
        "mureo_state_action_log_append",
    ),
    "audience-review": (
        "google_ads_demographic_targeting_list",
        "google_ads_audience_targeting_list",
        "meta_ads_audiences_list",
        "meta_ads_analysis_placements",
        "meta_ads_ad_sets_update",
    ),
    "ad-fatigue-check": (
        "meta_ads_insights_report",
        "meta_ads_ads_list",
        "google_ads_ad_performance_report",
        "meta_ads_ads_pause",
        "google_ads_rsa_assets_audit",
    ),
    # incident-postmortem persists no report; it may reference mureo_*
    # context tools (it makes no ad-platform writes).
    "incident-postmortem": (
        "mureo_state_get",
        "mureo_outcome_evaluate",
        "mureo_state_action_log_append",
        "mureo_strategy_set",
        "mureo_learning_insights_get",
    ),
}

# name -> the report_set persistence key it must write. Skills absent from
# this map (``incident-postmortem``) intentionally persist no report.
_REPORT_KEY: dict[str, str] = {
    "tracking-health": "tracking",
    "budget-pacing": "pacing",
    "monthly-report": "monthly",
    "experiment": "experiment",
    "audience-review": "audience",
    "ad-fatigue-check": "fatigue",
}

_NAMES = tuple(_SKILLS)

# Static invariant of the fixture itself: the "at least 3 verified tools"
# contract must survive future edits that trim entries from _SKILLS.
assert all(
    len(tools) >= 3 for tools in _SKILLS.values()
), "each skill must pin at least 3 verified tool names"


def _packaged(name: str) -> Path:
    return _PACKAGED / name / "SKILL.md"


def _mirror(name: str) -> Path:
    return _MIRROR / name / "SKILL.md"


@pytest.mark.unit
@pytest.mark.parametrize("name", _NAMES)
class TestNewWorkflowSkills:
    def test_both_copies_exist(self, name: str) -> None:
        assert _packaged(name).exists(), f"missing packaged skill: {name}"
        assert _mirror(name).exists(), f"missing repo-root mirror: {name}"

    def test_copies_are_byte_identical(self, name: str) -> None:
        """Packaged copy and repo-root mirror must not drift (true byte
        comparison — read_bytes, no newline normalization)."""
        assert (
            _packaged(name).read_bytes() == _mirror(name).read_bytes()
        ), f"{name}: packaged and mirror copies differ"

    def test_frontmatter_parses(self, name: str) -> None:
        """Loads through the real parser; name matches dir; version tracks
        pyproject.toml (so a release bump does not need this test edited)."""
        for path in (_packaged(name), _mirror(name)):
            entry = parse_skill_md(path)
            assert entry.name == name
            assert entry.description
            assert entry.extra["metadata"]["version"] == _pyproject_version()

    def test_before_you_start_pointer_present(self, name: str) -> None:
        """The #389 shared *Diagnostic preamble* pointer must be present."""
        body = _read(_packaged(name))
        assert "**Before you start**" in body
        assert "Diagnostic preamble" in body

    def test_references_at_least_three_real_tools(self, name: str) -> None:
        body = _read(_packaged(name))
        for tool in _SKILLS[name]:
            assert tool in body, f"{name}: must reference real tool {tool}"

    def test_approval_gate_language_present(self, name: str) -> None:
        """No skill may mutate platform state without an approval gate; the
        read-only report cross-links to skills that carry one."""
        assert "approval" in _read(_packaged(name)).lower()

    def test_report_set_persistence_key_present(self, name: str) -> None:
        if name not in _REPORT_KEY:
            pytest.skip(f"{name} persists no report (asserted elsewhere)")
        body = _read(_packaged(name))
        assert "mureo_state_report_set" in body
        assert f'report="{_REPORT_KEY[name]}"' in body

    def test_no_platform_writes_statement(self, name: str) -> None:
        """``incident-postmortem`` persists no report and must instead
        state, up front, that it performs no ad-platform writes. It may
        *mention* ``mureo_state_report_set`` to explain the omission, but
        must not actually persist a ``report="..."`` key."""
        if name != "incident-postmortem":
            pytest.skip("no-platform-writes contract is specific to postmortem")
        body = _read(_packaged(name)).lower()
        assert "no ad-platform writes" in body
        # Negative guard: no report_set persistence key is written.
        assert 'report="' not in body
