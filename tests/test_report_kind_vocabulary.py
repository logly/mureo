"""Every report kind a shipped skill instructs is a kind the tool accepts (#671).

``mureo_state_report_set``'s ``report`` was an ``enum`` of three while nine
skills instructed nine kinds. The dispatcher runs JSON-Schema BEFORE the
handler (#277, re-verified in #660), so six shipped skills told an agent to
do something the tool refused, and the agent got a generic jsonschema
message naming none of it.

This module is the pin that keeps the two sides from drifting again. It does
not restate the vocabulary: it EXTRACTS the kinds the skills instruct and
checks them against the schema an agent is actually validated by, so a new
skill that reaches for ``report="quarterly"`` fails here rather than in a
customer's run.

Three claims, in the order they matter:

1. every kind a shipped SKILL.md instructs is accepted by the tool;
2. the vocabulary (:data:`~mureo.core.report_kinds.REPORT_KINDS`) names the
   skill that writes each kind, so the table cannot rot into a list of
   kinds nothing produces;
3. the browser's copy of the kind order is the same list — the read side
   has to know the vocabulary too, or a kind is writable and invisible.

The packaged copy and the repo-root mirror are both scanned: they are kept
byte-identical (``tests/test_report_structure_skills.py``), and a kind
instructed in only one of them is exactly the drift that convention exists
to prevent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mureo.core.report_kinds import REPORT_KINDS

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED_SKILLS = _ROOT / "mureo" / "_data" / "skills"
_MIRROR_SKILLS = _ROOT / "skills"

#: How a skill instructs a kind: ``Call `mureo_state_report_set` with
#: `report="daily"``. One form, deliberately — the pin can only see what it
#: can extract.
_INSTRUCTED_KIND = re.compile(r'report="([a-z_]+)"')


def _instructed_kinds(tree: Path) -> dict[str, set[str]]:
    """``{skill directory: {kind, ...}}`` for every SKILL.md under ``tree``."""
    found: dict[str, set[str]] = {}
    for skill_md in sorted(tree.glob("*/SKILL.md")):
        body = skill_md.read_text(encoding="utf-8")
        kinds = set(_INSTRUCTED_KIND.findall(body))
        if kinds:
            found[skill_md.parent.name] = kinds
    return found


def _report_set_enum() -> list[str]:
    """The ``report`` values the dispatcher's schema pass lets through."""
    from mureo.mcp.tools_mureo_context import TOOLS

    tool = next(t for t in TOOLS if t.name == "mureo_state_report_set")
    return list(tool.inputSchema["properties"]["report"]["enum"])


# ---------------------------------------------------------------------------
# The acceptance condition
# ---------------------------------------------------------------------------


def test_every_kind_a_shipped_skill_instructs_is_accepted_by_the_tool() -> None:
    """The failure #671 reports: a skill's own instructions, refused.

    Stated over the schema rather than over a constant, because the schema
    is what runs — the enum is the gate an agent meets.
    """
    accepted = set(_report_set_enum())
    instructed = _instructed_kinds(_PACKAGED_SKILLS)
    assert instructed, "no skill instructs a report kind — the scan is broken"
    refused = {
        skill: sorted(kinds - accepted)
        for skill, kinds in instructed.items()
        if kinds - accepted
    }
    assert not refused, (
        "these skills instruct a report kind mureo_state_report_set refuses: "
        f"{refused}"
    )


def test_the_two_skill_trees_instruct_the_same_kinds() -> None:
    """The packaged copy is what ships; the repo-root mirror is what a
    contributor edits. A kind added to one only is a kind half the product
    knows about."""
    assert _instructed_kinds(_PACKAGED_SKILLS) == _instructed_kinds(_MIRROR_SKILLS)


# ---------------------------------------------------------------------------
# The vocabulary and the skills that fill it
# ---------------------------------------------------------------------------


def test_the_vocabulary_is_the_tool_enum() -> None:
    """One list, stated once. The enum is generated from it, so a kind
    cannot be added to the vocabulary and left out of the schema."""
    assert _report_set_enum() == list(REPORT_KINDS)


def test_the_vocabulary_names_the_skill_that_writes_each_kind() -> None:
    """Both directions, because either gap is a drift:

    - a kind a skill instructs that the table does not name;
    - a kind in the table that no skill writes (a vocabulary entry nothing
      can fill is a view waiting for a report that never comes).
    """
    instructed = _instructed_kinds(_PACKAGED_SKILLS)
    by_kind = {
        kind: skill for skill, kinds in instructed.items() for kind in sorted(kinds)
    }
    assert by_kind == dict(REPORT_KINDS)


@pytest.mark.parametrize("kind,skill", sorted(REPORT_KINDS.items()))
def test_each_named_skill_exists_and_instructs_its_kind(kind: str, skill: str) -> None:
    """Named by directory, so the table points at something real."""
    body = (_PACKAGED_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    assert f'report="{kind}"' in body


# ---------------------------------------------------------------------------
# One vocabulary, two languages
# ---------------------------------------------------------------------------


def test_the_browser_kind_order_matches_the_python_vocabulary() -> None:
    """``REPORT_KINDS`` (Python) and ``REPORT_KINDS`` (reports_format.js) are
    the same list in two languages — same members, same order.

    Order is part of it: it is the tie-break the "latest report" pick falls
    back to for a report that carries no ``generated_at``. A drift would
    make the write side accept a kind the view has no place for, which is
    #670's failure reached by a different road.

    (Same shape as ``test_report_summary.py``'s totals-vocabulary pin.)
    """
    js = (_ROOT / "mureo" / "_data" / "web" / "reports_format.js").read_text(
        encoding="utf-8"
    )
    block = js.split("const REPORT_KINDS = [", 1)
    assert len(block) == 2, "REPORT_KINDS missing from reports_format.js"
    kinds = tuple(re.findall(r'"([a-z_]+)"', block[1].split("]", 1)[0]))
    assert kinds == tuple(REPORT_KINDS)


def test_the_renderer_binds_the_pick_rather_than_re_deciding_it() -> None:
    """The "latest report" block chooses one of the stored kinds, and that
    choice lives in ``reports_format.js`` where the JS suite can execute it.
    A second copy in ``dashboard.js`` — which has no runner — is how the
    three-kind ``daily || weekly || goal`` pick survived six new kinds."""
    js = (_ROOT / "mureo" / "_data" / "web" / "dashboard_reports.js").read_text(
        encoding="utf-8"
    )
    assert "latestReport = REPORTS_FORMAT.latestReport" in js
    assert "function latestReport(" not in js
    assert "reports.daily || reports.weekly || reports.goal" not in js
    assert "obj.daily || obj.weekly || obj.goal" not in js
