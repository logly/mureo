"""mureo's learned-insights MCP tool surface.

A single tool — :data:`TOOLS` exposes ``mureo_learning_insights_get``
— that returns the operator-tier knowledge base for diagnostic
workflows to consult. The data flow is the read-side counterpart to
``mureo learn add``:

    /learn skill (markdown)
      → mureo learn add "<insight>"  (mureo/cli/learn_cmd.py)
      → KnowledgeStore.append_operator_knowledge()
      ↑ write side already shipped
      ↓ this module — read side
      → KnowledgeStore.read_operator_knowledge()
      → mureo_learning_insights_get  (this tool)
      → /daily-check / /rescue / /budget-rebalance / …

The tool deliberately takes no arguments: its job is to surface
every saved insight so the agent treats them as authoritative
context. A future, separate tool could expose a filtered / scoped
view if scoping turns out to be necessary; the current design
errs on the side of "give the agent everything it should know".

An empty knowledge base (no file, or only the YAML-frontmatter
scaffold) returns a guidance string rather than a blank or
scaffold-only payload — otherwise the agent would either quote an
empty section into its analysis or treat the scaffold header as
real content. The guidance also encourages the operator to start
using ``/learn``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent, Tool

from mureo.core.knowledge_store import _OPERATOR_SCAFFOLD
from mureo.core.runtime_context import get_runtime_context

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


# Sentinel returned when the knowledge base is effectively empty. The
# explicit "no insights" wording is also what
# ``test_handler_returns_guidance_when_no_insights_saved`` pins.
_NO_INSIGHTS_MESSAGE = (
    "(No insights saved yet — the operator hasn't run /learn yet. "
    "Continue with the workflow using only STRATEGY.md / STATE.json "
    "as context, and consider suggesting /learn at the end if you "
    "uncover a reusable lesson.)"
)


# Derive the scaffold's terminal heading from the single source of
# truth in ``knowledge_store._OPERATOR_SCAFFOLD`` so a future edit
# to the scaffold heading does not silently break this check. A
# parity test pins the derivation.
_SCAFFOLD_TERMINAL_HEADING = "## " + _OPERATOR_SCAFFOLD.rsplit("## ", 1)[1].strip()


def _is_scaffold_only(text: str) -> bool:
    """Return ``True`` when ``text`` is empty or contains only the
    frontmatter scaffold seeded by
    :func:`mureo.core.knowledge_store.FilesystemKnowledgeStore.append_operator_knowledge`
    on first write.

    The check has to tolerate trailing whitespace because the
    scaffold ends with a newline and the file may or may not have
    content appended after it. We treat "scaffold + only whitespace"
    as scaffold-only.
    """
    if not text or not text.strip():
        return True
    # ``rfind`` over ``find`` is deliberate: if an operator pastes a
    # transcript whose body happens to contain the literal scaffold
    # heading, the last occurrence is the true scaffold boundary and
    # everything after it is the real content. This keeps the
    # "agent sees every saved insight" contract while staying robust
    # against transcripts that re-use the heading.
    idx = text.rfind(_SCAFFOLD_TERMINAL_HEADING)
    if idx == -1:
        return False
    tail = text[idx + len(_SCAFFOLD_TERMINAL_HEADING) :]
    return not tail.strip()


TOOLS: list[Tool] = [
    Tool(
        name="mureo_learning_insights_get",
        description=(
            "Load every insight previously saved via /learn from the "
            "operator-tier knowledge base. Returns the raw Markdown so "
            "the agent can apply the lessons when forming a "
            "diagnostic answer. Read-only. Call this near the start "
            "of every diagnostic workflow (/daily-check, /rescue, "
            "/budget-rebalance, /creative-refresh, /goal-review, "
            "/competitive-scan, /search-term-cleanup) BEFORE drawing "
            "conclusions, so accumulated practitioner know-how "
            "informs the analysis instead of being ignored. Returns "
            "a guidance string when no insights have been saved yet."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]


_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


async def handle_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Dispatch entry point used by ``mureo.mcp.server``.

    Mirrors the shape of every other ``tools_*`` module's
    ``handle_tool`` so the server can dispatch uniformly.

    Raises:
        ValueError: ``name`` is not a tool exported by this module.
    """
    if name == "mureo_learning_insights_get":
        return await _handle_learning_insights_get(arguments)
    raise ValueError(f"Unknown tool: {name}")


async def _handle_learning_insights_get(
    arguments: dict[str, Any],  # noqa: ARG001
) -> Sequence[TextContent]:
    """Return the operator-tier knowledge base as a single
    ``TextContent``.

    Defers to the runtime context's ``KnowledgeStore`` so an
    alternate backend registered via
    ``mureo.runtime_context_factory`` (filesystem-backed by default;
    could be DB-backed or remote-fetch-backed under a third-party
    runtime context factory) works transparently.
    """
    store = get_runtime_context().knowledge_store
    text = store.read_operator_knowledge()
    if _is_scaffold_only(text):
        logger.debug("learning insights: knowledge base empty / scaffold-only")
        return [TextContent(type="text", text=_NO_INSIGHTS_MESSAGE)]
    return [TextContent(type="text", text=text)]


__all__ = ["TOOLS", "handle_tool"]
