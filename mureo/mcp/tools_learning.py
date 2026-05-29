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
from typing import Any

from mcp.types import TextContent, Tool

from mureo.core.knowledge_store import _OPERATOR_SCAFFOLD
from mureo.core.runtime_context import get_runtime_context
from mureo.learning.context_builder import build_query
from mureo.learning.federation import Fragment, consult_advisors
from mureo.learning.insight_sources import load_insight_sources

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


_NO_ADVISORS_MESSAGE = (
    "(No external advisor sources configured. Set up "
    "~/.mureo/insight_sources.json with the MCP servers you want "
    "mureo to consult — see docs/insight-federation.md.)"
)


_ADVISORS_RETURNED_NOTHING = (
    "(All configured advisors returned no matching fragments for "
    "this question. Proceed with local /learn history and "
    "STATE.json / STRATEGY.md only.)"
)


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
    Tool(
        name="mureo_consult_advisor",
        description=(
            "Consult external advisor MCP servers (vector search) for "
            "fragments relevant to a specific question. mureo enriches "
            "the question with the local campaign state (metrics, "
            "recent action log, STRATEGY.md) before forwarding it to "
            "every server configured in ~/.mureo/insight_sources.json. "
            "Each server returns top-k snippets with similarity "
            "scores; the agent reasons over them. Use this when "
            "/learn history is thin or when you need a second "
            "opinion from a shared knowledge base (consulting cos, "
            "industry benchmarks, OSS communities, internal wikis)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The specific diagnostic question to search "
                        "for. Concrete > generic — 'why is CPA up "
                        "30% on Brand-Search?' beats 'tips for "
                        "Google Ads'."
                    ),
                },
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Optional campaign id. When supplied, mureo "
                        "attaches the campaign's name / status / "
                        "budget and the last few action-log entries "
                        "to the query so the advisor's vector "
                        "search has richer context to match against."
                    ),
                },
            },
            "required": ["question"],
        },
    ),
]


_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch entry point used by ``mureo.mcp.server``.

    Mirrors the shape of every other ``tools_*`` module's
    ``handle_tool`` so the server can dispatch uniformly.

    Raises:
        ValueError: ``name`` is not a tool exported by this module.
    """
    if name == "mureo_learning_insights_get":
        return await _handle_learning_insights_get(arguments)
    if name == "mureo_consult_advisor":
        return await _handle_consult_advisor(arguments)
    raise ValueError(f"Unknown tool: {name}")


async def _handle_learning_insights_get(
    arguments: dict[str, Any],  # noqa: ARG001
) -> list[TextContent]:
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


async def _handle_consult_advisor(
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Fan out to external advisor servers and aggregate fragments.

    Step 1: load ``~/.mureo/insight_sources.json``. If no advisors are
    configured, return guidance (the agent should fall back to local
    insights only).

    Step 2: build a context-rich query from the operator's question +
    the local campaign state.

    Step 3: ``consult_advisors`` fans out to every advisor concurrently
    (each per-source error is isolated, so one bad source can't break
    the others).

    Step 4: format the merged result into a single markdown payload
    the agent can reason over. Per-source headings + similarity
    scores let the agent weigh fragments without server-side help.
    """
    question = str(arguments.get("question", "")).strip()
    campaign_id_raw = arguments.get("campaign_id")
    campaign_id = (
        str(campaign_id_raw).strip()
        if isinstance(campaign_id_raw, str) and campaign_id_raw.strip()
        else None
    )

    if not question:
        return [
            TextContent(
                type="text",
                text="(mureo_consult_advisor requires a non-empty 'question'.)",
            )
        ]

    config = load_insight_sources()
    if not config.sources:
        return [TextContent(type="text", text=_NO_ADVISORS_MESSAGE)]

    ctx = get_runtime_context()
    query = build_query(
        state_store=ctx.state_store,
        question=question,
        campaign_id=campaign_id,
    )
    results = await consult_advisors(config.sources, query=query)
    body = _format_advisor_response(results)
    return [TextContent(type="text", text=body)]


def _format_advisor_response(
    results: dict[str, tuple[Fragment, ...]],
) -> str:
    """Render the per-advisor fragments dict as markdown.

    Empty advisors are skipped silently; when every advisor returned
    nothing, the caller-facing string is the ``_ADVISORS_RETURNED_NOTHING``
    sentinel so the agent doesn't quote an empty block into its
    analysis.
    """
    sections: list[str] = []
    for name, fragments in results.items():
        if not fragments:
            continue
        lines = [f"## {name}"]
        for frag in fragments:
            lines.append(f"- (similarity {frag.similarity:.2f}) {_sanitize(frag.text)}")
        sections.append("\n".join(lines))
    if not sections:
        return _ADVISORS_RETURNED_NOTHING
    return "\n\n---\n\n".join(sections)


def _sanitize(text: str) -> str:
    """Collapse advisor-supplied text into a single Markdown-safe line.

    Advisor fragments are untrusted: a hostile response can contain
    newlines, ``---`` section separators, or ``## headings`` that would
    spoof per-source boundaries when the operator-side agent reads the
    aggregated payload. We:

    1. Flatten whitespace so the fragment occupies a single line and
       cannot smuggle a real heading-at-line-start.
    2. Break up consecutive ``#`` runs so even an LLM reader scanning
       for ``## name`` patterns mid-line will not mistake the
       fragment text for a section header attributing content to a
       different advisor.
    """
    flattened = " ".join(text.split())
    # Defang heading and rule markers without losing the visible word.
    return flattened.replace("##", "# #").replace("---", "—")


__all__ = ["TOOLS", "handle_tool"]
