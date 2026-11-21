"""The tool tables in ``AGENTS.md`` must name the tools mureo ships.

``AGENTS.md`` lists every tool by family, written by hand, while the tools
live in code, so a renamed, removed or added tool changes the code and
leaves the tables naming a tool that no longer exists or missing one that
does. Nothing in the code reads these tables, so only a test that reads the
document notices (#1043).

The shipped surface is the per-family ``TOOLS`` constants
(``tests/_doc_surface.py``), never ``handle_list_tools()``: the served list
also carries the machine's own plugins and honours the ``MUREO_DISABLE_*``
gates, and the document describes neither.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from mcp.types import Tool

from tests._doc_surface import (
    _FAMILY_PREFIXES,
    _doc_text,
    _shipped_tools,
    code_spans,
    markdown_tables,
)

pytestmark = pytest.mark.unit

_AGENTS_DOC = "AGENTS.md"

#: ``AGENTS.md`` headings with a tool table, and what turns a dotted name in
#: that table (``campaigns.list``) into the tool id. The core table already
#: uses full tool ids.
_AGENTS_SECTIONS = {
    "Google Ads": "google_ads_",
    "Meta Ads": "meta_ads_",
    "Search Console": "search_console_",
    "ChatGPT Ads": "chatgpt_ads_",
    "mureo Core Tools (platform-independent)": "",
}


def _agents_names(prefix: str, cell: str) -> list[str]:
    names: list[str] = []
    for span in code_spans(cell):
        if "." in span:
            names.append(prefix + span.replace(".", "_"))
        elif span.startswith(_FAMILY_PREFIXES):
            names.append(span)
    return names


def agents_tool_names(markdown: str) -> dict[str, list[str]]:
    """Tool ids named in each ``AGENTS.md`` tool table, keyed by heading."""
    found: dict[str, list[str]] = {}
    for table in markdown_tables(markdown):
        prefix = _AGENTS_SECTIONS.get(table.heading)
        if prefix is None or "Tools" not in table.header:
            continue
        column = table.header.index("Tools")
        names = found.setdefault(table.heading, [])
        for row in table.rows:
            if column < len(row):
                names.extend(_agents_names(prefix, row[column]))
    return found


def unknown_agents_tools(markdown: str, tools: Mapping[str, Tool]) -> list[str]:
    """Names in the ``AGENTS.md`` tool tables that are not shipped tools."""
    named = {n for names in agents_tool_names(markdown).values() for n in names}
    return sorted(named - set(tools))


def test_agents_doc_has_every_tool_table() -> None:
    """Coverage guard: each family heading still carries a readable table."""
    found = agents_tool_names(_doc_text(_AGENTS_DOC))
    empty = [heading for heading in _AGENTS_SECTIONS if not found.get(heading)]
    assert empty == [], f"{_AGENTS_DOC} tool tables not found: {empty}"


def test_agents_doc_lists_every_shipped_tool() -> None:
    found = agents_tool_names(_doc_text(_AGENTS_DOC))
    named = {name for names in found.values() for name in names}
    missing = sorted(set(_shipped_tools()) - named)
    assert missing == [], f"{_AGENTS_DOC} does not list: {missing}"


def test_agents_doc_names_only_shipped_tools() -> None:
    unknown = unknown_agents_tools(_doc_text(_AGENTS_DOC), _shipped_tools())
    assert unknown == [], f"{_AGENTS_DOC} names tools mureo lacks: {unknown}"


def test_unknown_agents_tools_reports_a_name_that_does_not_exist() -> None:
    snippet = (
        "### Google Ads\n\n"
        "| Category | Tools |\n"
        "|----------|-------|\n"
        "| Campaigns | `campaigns.get`, `campaigns.gone`, `ad_group_ad` |\n"
    )
    tools = {
        "google_ads_campaigns_get": Tool(
            name="google_ads_campaigns_get", inputSchema={"type": "object"}
        )
    }
    assert unknown_agents_tools(snippet, tools) == ["google_ads_campaigns_gone"]
