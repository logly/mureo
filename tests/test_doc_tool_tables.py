"""The tool tables in ``docs/mcp-server.md`` must match the tools mureo ships.

``docs/mcp-server.md`` lists every tool with its required parameters. It is
written by hand, while the tools and their ``inputSchema`` live in code, so
a renamed tool, a new tool or a parameter that became required changes the
code and leaves the tables describing a tool that no longer exists or a
call that is now refused. Nothing in the code reads these tables, so only a
test that reads the document notices (#1043). ``AGENTS.md``'s tool tables
are pinned in ``tests/test_doc_agents_tables.py``.

The shipped surface is the per-family ``TOOLS`` constants
(``tests/_doc_surface.py``), never ``handle_list_tools()``: the served list
also carries the machine's own plugins and honours the ``MUREO_DISABLE_*``
gates, and the docs describe neither.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from mcp.types import Tool

from tests._doc_surface import (
    _FAMILY_PREFIXES,
    _MCP_SERVER_DOC,
    Table,
    _doc_text,
    _shipped_tools,
    code_spans,
    markdown_tables,
)

pytestmark = pytest.mark.unit

#: The parameter each platform's tools fall back to from the configured
#: credentials. ``docs/mcp-server.md`` lists it in the "Required Parameters"
#: column although the schema does not require it, and says so above the
#: tables, so it is not compared with ``required``.
_CREDENTIAL_FALLBACK = {"google_ads_": "customer_id", "meta_ads_": "account_id"}

#: Tools whose "Required Parameters" cell is prose that states a condition
#: the flat ``required`` list cannot express. They are read by
#: ``prose_cell_mismatches``; every other cell is compared exactly.
_PROSE_REQUIRED_CELLS = {
    "search_console_sites_get": "names an optional parameter beside (none)",
    "search_console_sitemaps_list": "names an optional parameter beside (none)",
    "analysis_anomalies_check": "names the nested keys `current` must carry",
    "analysis_exclusion_impact_preview": "either/or between two argument sets",
    "mureo_state_display_set": "a parameter required only once a section is set",
    "mureo_outcome_evaluate": "a parameter required unless another is given",
    "chatgpt_ads_conversions_report": "a parameter required unless a flag is false",
}

_EMPTY_CELLS = frozenset({"", "--", "—", "-", "none"})
#: How a segment of a Required cell opens, after an optional "and ", when it
#: names alternatives.
_ALTERNATIVES = ("one of ", "exactly one of ", "at least one of ")
# A parameter name, or a dotted path into a nested object (`current.cost`).
# Any other code span in a prose cell is not read as a parameter.
_PARAMETER_PATH = re.compile(r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*")


def _cell_names(cell: str) -> tuple[set[str], set[str]]:
    """(required names, alternative names) a Required cell states.

    Cells are comma-separated names; a segment that opens with "one of" or
    "at least one of" names alternatives, none of which the schema can
    require on its own.
    """
    plain = cell.strip().strip("*").strip("()").strip()
    if plain.lower() in _EMPTY_CELLS:
        return set(), set()
    required: set[str] = set()
    alternatives: set[str] = set()
    for segment in cell.split(","):
        opening = segment.strip().removeprefix("and ")
        names = alternatives if opening.startswith(_ALTERNATIVES) else required
        names.update(code_spans(segment))
    return required, alternatives


def _cells_per_tool(names: list[str], cell: str) -> dict[str, str]:
    """A row naming N tools carries N `` / ``-separated cells, or one shared."""
    parts = cell.split(" / ")
    if len(names) > 1 and len(parts) == len(names):
        return dict(zip(names, parts, strict=True))
    return {name: cell for name in names}


def _tool_tables(markdown: str) -> Iterator[Table]:
    return (t for t in markdown_tables(markdown) if t.header[:1] == ["Tool"])


def _row_tool_names(row: list[str]) -> list[str]:
    if not row[0].startswith("`"):
        return []
    return [n for n in code_spans(row[0]) if n.startswith(_FAMILY_PREFIXES)]


def tool_rows(markdown: str) -> list[tuple[str, str | None]]:
    """(tool name, its Required cell or ``None``) for every tool-table row."""
    found: list[tuple[str, str | None]] = []
    for table in _tool_tables(markdown):
        required_col = next(
            (i for i, head in enumerate(table.header) if "required" in head.lower()),
            None,
        )
        for row in table.rows:
            names = _row_tool_names(row)
            if required_col is None or required_col >= len(row):
                found.extend((name, None) for name in names)
                continue
            cells = _cells_per_tool(names, row[required_col])
            found.extend((name, cells[name]) for name in names)
    return found


def unreadable_tool_rows(markdown: str) -> list[str]:
    """Tool-table rows the reader would skip or misread: no tool name in the
    first cell, or a cell count that differs from the header's."""
    return [
        f"{table.heading}: {row[0]}"
        for table in _tool_tables(markdown)
        for row in table.rows
        if not _row_tool_names(row) or len(row) != len(table.header)
    ]


def unknown_tool_rows(markdown: str, tools: Mapping[str, Tool]) -> list[str]:
    """Tool-table rows that name a tool mureo does not ship."""
    return sorted({name for name, _ in tool_rows(markdown) if name not in tools})


def _compared_rows(
    markdown: str, tools: Mapping[str, Tool]
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """(name, cell, schema) for every shipped tool whose cell is not prose."""
    for name, cell in tool_rows(markdown):
        if cell is not None and name in tools and name not in _PROSE_REQUIRED_CELLS:
            yield name, cell, tools[name].inputSchema


def _documented_required(name: str, cell: str) -> set[str]:
    names = _cell_names(cell)[0]
    for prefix, fallback in _CREDENTIAL_FALLBACK.items():
        if name.startswith(prefix):
            names.discard(fallback)
    return names


def required_mismatches(markdown: str, tools: Mapping[str, Tool]) -> list[str]:
    """Rows whose Required cell differs from the tool's schema ``required``."""
    problems: list[str] = []
    for name, cell, schema in _compared_rows(markdown, tools):
        documented = _documented_required(name, cell)
        expected = set(schema.get("required", []))
        if documented != expected:
            problems.append(
                f"{name}: doc {sorted(documented)} != schema {sorted(expected)}"
            )
    return problems


def unknown_parameter_names(markdown: str, tools: Mapping[str, Tool]) -> list[str]:
    """Rows whose Required cell names something the schema has no property
    for: a required name, an alternative or the credential fallback."""
    problems: list[str] = []
    for name, cell, schema in _compared_rows(markdown, tools):
        required, alternatives = _cell_names(cell)
        unknown = sorted((required | alternatives) - set(schema.get("properties", {})))
        if unknown:
            problems.append(f"{name}: not a parameter {unknown}")
    return problems


def _schema_alternatives(schema: Mapping[str, Any]) -> set[str]:
    """Names of a top-level ``anyOf`` / ``oneOf`` whose every branch is a
    ``required`` list; empty when the schema has no such alternatives."""
    branches = [*schema.get("anyOf", []), *schema.get("oneOf", [])]
    if not all(isinstance(branch.get("required"), list) for branch in branches):
        return set()
    return {required for branch in branches for required in branch["required"]}


def alternative_mismatches(markdown: str, tools: Mapping[str, Tool]) -> list[str]:
    """Rows whose alternatives differ from the schema's ``anyOf`` / ``oneOf``."""
    problems: list[str] = []
    for name, cell, schema in _compared_rows(markdown, tools):
        expected = _schema_alternatives(schema)
        documented = _cell_names(cell)[1]
        if expected and documented != expected:
            problems.append(
                f"{name}: doc alternatives {sorted(documented)} "
                f"!= schema {sorted(expected)}"
            )
    return problems


def _property_names(schema: Mapping[str, Any]) -> set[str]:
    """Every property name in ``schema``, nested objects and array items too."""
    names: set[str] = set()
    for key, sub in schema.get("properties", {}).items():
        names |= {key, *_property_names(sub)}
    items = schema.get("items")
    if isinstance(items, dict):
        names |= _property_names(items)
    return names


def prose_cell_mismatches(markdown: str, tools: Mapping[str, Tool]) -> list[str]:
    """Prose cells that leave out a required name or name a non-parameter."""
    problems: list[str] = []
    for name, cell in tool_rows(markdown):
        if cell is None or name not in _PROSE_REQUIRED_CELLS or name not in tools:
            continue
        schema = tools[name].inputSchema
        spans = code_spans(cell)
        unnamed = sorted(set(schema.get("required", [])) - set(spans))
        known = _property_names(schema)
        unknown = [
            span
            for span in spans
            if _PARAMETER_PATH.fullmatch(span) and not set(span.split(".")) <= known
        ]
        if unnamed or unknown:
            problems.append(f"{name}: unnamed {unnamed}, not a parameter {unknown}")
    return problems


def test_every_shipped_tool_name_has_a_family_prefix() -> None:
    """A family with a new prefix would have its rows skipped by the reader."""
    stray = [n for n in _shipped_tools() if not n.startswith(_FAMILY_PREFIXES)]
    assert stray == [], f"tool names outside every family prefix: {stray}"


def test_mcp_server_doc_tabulates_every_shipped_tool() -> None:
    """Coverage guard: every shipped tool has a row, so a reworded table
    fails here instead of passing by matching nothing."""
    tabulated = {name for name, _ in tool_rows(_doc_text(_MCP_SERVER_DOC))}
    missing = sorted(set(_shipped_tools()) - tabulated)
    assert missing == [], f"{_MCP_SERVER_DOC} has no row for: {missing}"


def test_every_tool_row_has_a_required_cell() -> None:
    """Coverage guard: a renamed Required column fails here instead of
    switching the comparisons off."""
    rows = tool_rows(_doc_text(_MCP_SERVER_DOC))
    assert rows
    assert [name for name, cell in rows if cell is None] == []


def test_mcp_server_doc_has_no_unreadable_tool_row() -> None:
    unreadable = unreadable_tool_rows(_doc_text(_MCP_SERVER_DOC))
    assert unreadable == [], f"{_MCP_SERVER_DOC} rows not read: {unreadable}"


def test_mcp_server_doc_rows_name_shipped_tools() -> None:
    unknown = unknown_tool_rows(_doc_text(_MCP_SERVER_DOC), _shipped_tools())
    assert unknown == [], f"{_MCP_SERVER_DOC} lists tools mureo lacks: {unknown}"


def test_mcp_server_doc_required_parameters_match_the_schemas() -> None:
    mismatches = required_mismatches(_doc_text(_MCP_SERVER_DOC), _shipped_tools())
    assert mismatches == [], f"{_MCP_SERVER_DOC} Required column: {mismatches}"


def test_mcp_server_doc_required_cells_name_parameters() -> None:
    unknown = unknown_parameter_names(_doc_text(_MCP_SERVER_DOC), _shipped_tools())
    assert unknown == [], f"{_MCP_SERVER_DOC} Required column: {unknown}"


def test_some_shipped_schema_declares_alternatives() -> None:
    """Coverage guard: the alternatives check reads at least one schema."""
    assert any(_schema_alternatives(t.inputSchema) for t in _shipped_tools().values())


def test_mcp_server_doc_alternatives_match_the_schemas() -> None:
    mismatches = alternative_mismatches(_doc_text(_MCP_SERVER_DOC), _shipped_tools())
    assert mismatches == [], f"{_MCP_SERVER_DOC} alternatives: {mismatches}"


def test_mcp_server_doc_prose_cells_match_the_schemas() -> None:
    mismatches = prose_cell_mismatches(_doc_text(_MCP_SERVER_DOC), _shipped_tools())
    assert mismatches == [], f"{_MCP_SERVER_DOC} prose cells: {mismatches}"


def test_prose_required_cells_are_still_prose() -> None:
    """Each exception names a tabulated tool whose cell still does not parse
    to its schema; one that does is no longer needed and must go."""
    tools = _shipped_tools()
    cells = dict(tool_rows(_doc_text(_MCP_SERVER_DOC)))
    stale = []
    for name in _PROSE_REQUIRED_CELLS:
        cell = cells.get(name)
        if (
            cell is None
            or name not in tools
            or _documented_required(name, cell)
            == set(tools[name].inputSchema.get("required", []))
        ):
            stale.append(name)
    assert stale == [], f"exceptions no longer needed: {stale}"


def _snippet_tools() -> dict[str, Tool]:
    schema = {
        "type": "object",
        "properties": {"customer_id": {}, "campaign_id": {}, "add": {}, "drop": {}},
        "required": ["campaign_id"],
        "anyOf": [{"required": ["add"]}, {"required": ["drop"]}],
    }
    tool = Tool(name="google_ads_campaigns_get", inputSchema=schema)
    return {tool.name: tool}


_SNIPPET_HEADER = (
    "| Tool | Description | Required Parameters |\n"
    "|------|-------------|---------------------|\n"
)


def test_unknown_tool_rows_reports_a_row_for_a_missing_tool() -> None:
    snippet = (
        f"{_SNIPPET_HEADER}"
        "| `google_ads_campaigns_get` | Get | `customer_id`, `campaign_id` |\n"
        "| `google_ads_campaigns_gone` | Gone | `customer_id` |\n"
    )
    assert unknown_tool_rows(snippet, _snippet_tools()) == ["google_ads_campaigns_gone"]


def test_unreadable_tool_rows_reports_skipped_and_split_rows() -> None:
    snippet = (
        f"### Campaigns\n\n{_SNIPPET_HEADER}"
        "| `google_ads_campaigns_get` | Get | `campaign_id` |\n"
        "| **`google_ads_campaigns_bogus`** | x | -- |\n"
        "| `google_ads_campaigns_get` | `a | b` | `campaign_id` |\n"
    )
    assert unreadable_tool_rows(snippet) == [
        "Campaigns: **`google_ads_campaigns_bogus`**",
        "Campaigns: `google_ads_campaigns_get`",
    ]


def test_required_mismatches_reports_a_wrong_required_cell() -> None:
    snippet = (
        "| Tool | Required Parameters | Description |\n"
        "|------|---------------------|-------------|\n"
        "| `google_ads_campaigns_get` | `customer_id`, `name` | Get |\n"
    )
    assert required_mismatches(snippet, _snippet_tools()) == [
        "google_ads_campaigns_get: doc ['name'] != schema ['campaign_id']"
    ]


def test_unknown_parameter_names_reports_a_misspelt_alternative() -> None:
    snippet = (
        f"{_SNIPPET_HEADER}| `google_ads_campaigns_get` | Get | "
        "`customer_id`, `campaign_id`, at least one of `add` / `dorp` |\n"
    )
    assert unknown_parameter_names(snippet, _snippet_tools()) == [
        "google_ads_campaigns_get: not a parameter ['dorp']"
    ]


def test_alternative_mismatches_reports_missing_alternatives() -> None:
    snippet = (
        f"{_SNIPPET_HEADER}"
        "| `google_ads_campaigns_get` | Get | `customer_id`, `campaign_id` |\n"
    )
    assert alternative_mismatches(snippet, _snippet_tools()) == [
        "google_ads_campaigns_get: doc alternatives [] != schema ['add', 'drop']"
    ]


def test_prose_cell_mismatches_reports_a_renamed_nested_key() -> None:
    schema = {
        "type": "object",
        "properties": {"current": {"properties": {"cost": {}}}},
        "required": ["current"],
    }
    tools = {"analysis_anomalies_check": Tool(name="x", inputSchema=schema)}
    snippet = (
        f"{_SNIPPET_HEADER}| `analysis_anomalies_check` | Check | "
        "`current` (`current.costs` required, `-1` allowed) |\n"
    )
    assert prose_cell_mismatches(snippet, tools) == [
        "analysis_anomalies_check: unnamed [], not a parameter ['current.costs']"
    ]


def test_cell_names_reads_the_cell_shapes_the_doc_uses() -> None:
    assert _cell_names("*(none)*") == (set(), set())
    assert _cell_names("`a`, one of `b` / `c`, `d`") == ({"a", "d"}, {"b", "c"})
    assert _cell_names("`a`, and one of `b` / `c`") == ({"a"}, {"b", "c"})
    assert _cell_names("`a`, at least one of `b` / `c`") == ({"a"}, {"b", "c"})
    assert _cell_names("exactly one of `a` / `b`") == (set(), {"a", "b"})
