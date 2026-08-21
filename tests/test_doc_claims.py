"""Shipped docs must state the tool total the registry actually exposes.

Four shipped documents quote mureo's MCP tool count. #648/#661 grew the tool
list and updated three of them; ``docs/architecture.md`` kept saying 221
through the releases that followed, because **no test reads the docs** (#677).
A stale number there does not read to an operator as "the doc is out of date"
— it reads as "my install is missing tools", with nothing anywhere to correct
that reading.

``tests/test_mcp_server.py`` pins the count on the code side, so the code
cannot drift silently. This module pins the prose the same way, so the next
tool addition fails the suite until *every* document is updated instead of
relying on the author remembering all four.

The total is summed from the per-family ``TOOLS`` constants rather than read
off ``handle_list_tools()``: the served list also carries whatever provider
plugins the machine happens to have installed, and it honours the
``MUREO_DISABLE_*`` gates. The docs describe mureo's own shipped surface,
which is neither of those.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mureo.mcp.tools_analysis import TOOLS as ANALYSIS_TOOLS
from mureo.mcp.tools_analytics_registry import TOOLS as ANALYTICS_REGISTRY_TOOLS
from mureo.mcp.tools_batch import TOOLS as BATCH_TOOLS
from mureo.mcp.tools_change_import import TOOLS as CHANGE_IMPORT_TOOLS
from mureo.mcp.tools_creative_studio import TOOLS as CREATIVE_STUDIO_TOOLS
from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS
from mureo.mcp.tools_learning import TOOLS as LEARNING_TOOLS
from mureo.mcp.tools_learning_preflight import TOOLS as LEARNING_PREFLIGHT_TOOLS
from mureo.mcp.tools_meta_ads import TOOLS as META_ADS_TOOLS
from mureo.mcp.tools_mureo_context import TOOLS as MUREO_CONTEXT_TOOLS
from mureo.mcp.tools_rollback import TOOLS as ROLLBACK_TOOLS
from mureo.mcp.tools_search_console import TOOLS as SEARCH_CONSOLE_TOOLS

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Every built-in tool family ``mureo.mcp.server`` composes into its tool
#: list, ungated. A family added to the server without being added here
#: fails ``test_family_list_covers_every_built_in_tool`` below.
_TOOL_FAMILIES = (
    GOOGLE_ADS_TOOLS,
    META_ADS_TOOLS,
    SEARCH_CONSOLE_TOOLS,
    ROLLBACK_TOOLS,
    BATCH_TOOLS,
    CHANGE_IMPORT_TOOLS,
    ANALYSIS_TOOLS,
    MUREO_CONTEXT_TOOLS,
    ANALYTICS_REGISTRY_TOOLS,
    LEARNING_TOOLS,
    LEARNING_PREFLIGHT_TOOLS,
    CREATIVE_STUDIO_TOOLS,
)

#: Each shipped surface that states the total, paired with the pattern that
#: locates the claim in *that* document's wording. Deliberately not one
#: generic ``(\d+) tools``: ``docs/mcp-server.md`` also sizes each family in
#: the same sentence ("2 rollback tools", "3 batch tools", …), and a pattern
#: that swept those up would compare a family count against the total. A
#: rewording that drops the shape stops matching, which fails the coverage
#: test rather than silently leaving that document unchecked. A document
#: added later that repeats the number has to be listed here to be guarded.
_CLAIMS = (
    ("README.md", re.compile(r"exposes \*\*(\d+) MCP tools\*\*")),
    ("README.ja.md", re.compile(r"\*\*(\d+) の MCP ツール\*\*")),
    ("docs/mcp-server.md", re.compile(r"exposes (\d+) tools")),
    ("docs/architecture.md", re.compile(r"the (\d+) individual MCP tools")),
)


def _tool_names() -> frozenset[str]:
    return frozenset(tool.name for family in _TOOL_FAMILIES for tool in family)


def _shipped_tool_count() -> int:
    return sum(len(family) for family in _TOOL_FAMILIES)


def _doc_text(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


def _stated_counts(rel: str, pattern: re.Pattern[str]) -> list[int]:
    return [int(match.group(1)) for match in pattern.finditer(_doc_text(rel))]


def test_the_documented_total_counts_distinct_tools() -> None:
    """A duplicate name across families would inflate the number the docs
    quote while the server exposed fewer tools than it added up to."""
    names = _tool_names()
    assert len(names) == _shipped_tool_count()


def test_family_list_covers_every_built_in_tool() -> None:
    """The families above must still be all of them.

    A new family wired into the server but not listed here would leave the
    docs' total too low with this pin still green — the exact way #677
    happened, one layer down. Plugin-provided tools are excluded (they are
    per-machine, and the docs say so); a subset assertion, not equality, so
    a run with a ``MUREO_DISABLE_*`` gate set does not fail on the family
    it correctly left out.
    """
    from mureo.mcp import server as mcp_server

    built_in = {tool.name for tool in mcp_server._ALL_TOOLS} - set(
        mcp_server._PLUGIN_NAMES
    )
    missing = sorted(built_in - _tool_names())
    assert missing == [], f"served but counted by no family here: {missing}"


def test_every_shipped_doc_states_the_tool_count() -> None:
    """Coverage guard: a claim is found by its wording, so a document that
    reworded past the pattern would silently stop being checked — and this
    pin would pass by matching nothing at all."""
    unmatched = [rel for rel, pattern in _CLAIMS if not _stated_counts(rel, pattern)]
    assert unmatched == [], f"no tool-count claim found in: {unmatched}"


def test_shipped_docs_state_the_tool_count_the_registry_exposes() -> None:
    """The defect: three documents said 224 while ``docs/architecture.md``
    said 221 and the registry exposed 224 (#677)."""
    expected = _shipped_tool_count()
    stale = [
        (rel, stated)
        for rel, pattern in _CLAIMS
        for stated in _stated_counts(rel, pattern)
        if stated != expected
    ]
    assert stale == [], f"docs state a stale tool count (registry: {expected}): {stale}"
