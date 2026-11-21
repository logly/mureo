"""Read the shipped docs and the shipped tool surface for the doc pins.

Not a test module (no ``test_`` prefix, so pytest does not collect it).

``tests/test_doc_claims.py`` and the ``tests/test_doc_*.py`` modules that
compare the docs' reference tables with the code all need the same few
things: where the repository is, how a document is read, and which tools
mureo itself ships, under which name prefixes. Keeping them here gives
every pin one definition of the shipped surface, so a family added to it is
counted by all of them at once.

The markdown reading is deliberately small: GitHub-flavoured pipe tables
(the only table form the docs use) and inline code spans. Lines inside a
fenced code block are never read as a table or a heading.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from mcp.types import Tool

from mureo.chatgpt_ads.handlers import ALL_TOOLS as CHATGPT_ADS_TOOLS
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

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Every built-in tool family ``mureo.mcp.server`` composes into its tool
#: list, ungated. A family added to the server without being added here
#: fails ``test_family_list_covers_every_built_in_tool`` in
#: ``tests/test_doc_claims.py``. ChatGPT Ads is served through the plugin path
#: but ships in every install with a fixed tool list (#993), so it is part of
#: the shipped surface the docs describe; Amazon's tools come from a
#: per-machine manifest and are not.
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
    CHATGPT_ADS_TOOLS,
)

#: Name prefixes of the shipped tool families. A table cell's code span that
#: starts with one of these is read as a tool name.
_FAMILY_PREFIXES = (
    "google_ads_",
    "meta_ads_",
    "search_console_",
    "rollback_",
    "analysis_",
    "creative_studio_",
    "chatgpt_ads_",
    "mureo_",
)

#: The tool reference, read by the tool-table and reference-table pins.
_MCP_SERVER_DOC = "docs/mcp-server.md"

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_SEPARATOR_CELL = re.compile(r":?-+:?")
# GFM splits a row on every pipe that is not backslash-escaped, inside a code
# span too: an unescaped pipe in `a | b` starts a new cell when rendered.
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_CODE_SPAN = re.compile(r"`([^`]+)`")


class Table(NamedTuple):
    """One pipe table: the heading it sits under, its header and body rows."""

    heading: str
    header: list[str]
    rows: list[list[str]]


def _doc_text(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


def _shipped_tools() -> dict[str, Tool]:
    return {tool.name: tool for family in _TOOL_FAMILIES for tool in family}


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip().replace("\\|", "|") for cell in _UNESCAPED_PIPE.split(body)]


def _is_separator(line: str) -> bool:
    if not line.lstrip().startswith("|"):
        return False
    return all(_SEPARATOR_CELL.fullmatch(cell) for cell in _split_row(line))


def fenced_lines(markdown: str) -> list[tuple[str, bool]]:
    """Each line of ``markdown`` with whether it belongs to a fenced code block.

    The opening and closing fence lines count as part of the block.
    """
    out: list[tuple[str, bool]] = []
    fence: str | None = None
    for line in markdown.splitlines():
        match = _FENCE.match(line)
        if fence is None and match:
            fence = match.group(1)
            out.append((line, True))
            continue
        if fence is not None:
            closes = (
                match is not None
                and match.group(1)[0] == fence[0]
                and len(match.group(1)) >= len(fence)
                and not match.group(2).strip()
            )
            fence = None if closes else fence
            out.append((line, True))
            continue
        out.append((line, False))
    return out


def markdown_tables(markdown: str) -> list[Table]:
    """Every pipe table in ``markdown``, in document order.

    A table is a row line followed by a separator row (``|---|:--:|``); its
    body runs until the first line that does not start with a pipe. Cells
    keep their markdown (backticks included); ``\\|`` is unescaped.
    """
    lines = ["" if fenced else line for line, fenced in fenced_lines(markdown)]
    tables: list[Table] = []
    heading = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        heading_match = _HEADING.match(line)
        if heading_match:
            heading = heading_match.group(1)
        if (
            line.lstrip().startswith("|")
            and index + 1 < len(lines)
            and _is_separator(lines[index + 1])
        ):
            rows: list[list[str]] = []
            index += 2
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                rows.append(_split_row(lines[index]))
                index += 1
            tables.append(Table(heading, _split_row(line), rows))
            continue
        index += 1
    return tables


def code_spans(cell: str) -> list[str]:
    """The text of each inline code span in ``cell``, backticks stripped."""
    return _CODE_SPAN.findall(cell)
