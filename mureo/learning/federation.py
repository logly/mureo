"""Retrieval-pattern federation client.

For each configured advisor source, fan out a single ``tools/call`` to
the server's vector-search tool with ``{query, top_k}``, parse the
returned list of fragments, and aggregate by source name.

The server side does the embedding + vector search; this module is a
thin client. No LLM lives here — reasoning happens on the operator's
machine, downstream of this module.

Per-source isolation rules:
- a single misbehaving source MUST NEVER block the others.
- per-source timeout (``InsightSource.timeout_sec``, default 10s) caps
  each call.
- any ``Exception`` from the SDK / network / server collapses the
  source to ``()``; ``asyncio.CancelledError`` (BaseException) is
  re-raised so structured concurrency / KeyboardInterrupt keep working.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mcp.client.session import ClientSession

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mureo.learning.insight_sources import InsightSource

logger = logging.getLogger(__name__)


# Caps on untrusted advisor payloads. Realistic responses sit well
# below these — they exist so a malicious / broken advisor cannot
# inject megabytes of content into the agent's context window.
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024  # 1 MiB JSON
_MAX_FRAGMENTS = 50
_MAX_FRAGMENT_TEXT_CHARS = 4 * 1024  # 4 KiB per fragment text


@dataclass(frozen=True)
class Fragment:
    """One retrieved snippet plus its similarity score and metadata.

    ``metadata`` carries advisor-supplied fields (tags, case_id,
    source URL, …) verbatim so the agent on the operator side can
    reason about them without server-side LLM help.
    """

    text: str
    similarity: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Transport dispatch
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _open_session(source: InsightSource) -> AsyncIterator[ClientSession]:
    """Open an MCP ``ClientSession`` for ``source`` and yield it.

    Each transport routes to the corresponding ``mcp.client`` helper.
    Unreachable branches (other transports rejected by
    ``InsightSource.__post_init__``) raise so any future regression in
    the schema validator surfaces immediately rather than silently
    skipping a source.
    """
    if source.transport == "stdio":
        from mcp.client.stdio import StdioServerParameters, stdio_client

        # ``env`` semantics: ``None`` (omitted in config) inherits the
        # parent env; ``{}`` (explicitly empty) yields a sealed
        # subprocess. The dict() copy preserves the {}.
        params = StdioServerParameters(
            command=source.command or "",
            args=list(source.args),
            env=dict(source.env) if source.env is not None else None,
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
        return

    if source.transport == "sse":
        from mcp.client.sse import sse_client

        async with (
            sse_client(
                source.url or "",
                headers=dict(source.headers) if source.headers is not None else None,
            ) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
        return

    if source.transport == "http":
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(
                source.url or "",
                headers=dict(source.headers) if source.headers is not None else None,
            ) as (read, write, _get_session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
        return

    # Defensive: InsightSource validation should prevent reaching here.
    raise ValueError(f"unsupported transport: {source.transport}")


# ---------------------------------------------------------------------------
# Single-source fetch
# ---------------------------------------------------------------------------


async def search_one(
    source: InsightSource,
    *,
    query: str,
    top_k: int | None = None,
) -> tuple[Fragment, ...]:
    """Call the vector-search tool on one advisor server.

    Returns the parsed fragments tuple, or ``()`` on any failure
    (timeout, exception, error response, malformed payload). Logs a
    WARNING with the source name and the failure summary so an
    operator can diagnose without the failure cascading.
    """
    effective_top_k = top_k if top_k is not None else source.top_k
    try:
        return await asyncio.wait_for(
            _search_inner(source, query=query, top_k=effective_top_k),
            timeout=source.timeout_sec,
        )
    except asyncio.CancelledError:
        # CancelledError is a BaseException — must propagate so the
        # caller's structured concurrency cleanup runs.
        raise
    except asyncio.TimeoutError:
        logger.warning(
            "advisor %s: timed out after %.1fs", source.name, source.timeout_sec
        )
        return ()
    except Exception as exc:  # noqa: BLE001
        logger.warning("advisor %s: failed (%s)", source.name, exc)
        return ()


async def _search_inner(
    source: InsightSource, *, query: str, top_k: int
) -> tuple[Fragment, ...]:
    async with _open_session(source) as session:
        result = await session.call_tool(source.tool, {"query": query, "top_k": top_k})
    if getattr(result, "isError", False):
        logger.warning("advisor %s: server returned isError", source.name)
        return ()
    return _parse_fragments(result.content, source_name=source.name)


def _parse_fragments(content: list[Any], *, source_name: str) -> tuple[Fragment, ...]:
    """Parse a list of ``TextContent`` blocks into a fragment tuple.

    Convention: the vector-search server returns ONE text block whose
    body is a JSON-encoded list of ``{text, similarity, ...}`` dicts.
    A non-text block, malformed JSON, or non-list payload yields the
    empty tuple — the source is treated as "no hits".
    """
    if not content:
        return ()
    block = content[0]
    if getattr(block, "type", None) != "text":
        return ()
    text = getattr(block, "text", None)
    if not isinstance(text, str):
        return ()
    if len(text.encode("utf-8", errors="replace")) > _MAX_RESPONSE_BYTES:
        logger.warning(
            "advisor %s: response exceeds %d bytes, dropping",
            source_name,
            _MAX_RESPONSE_BYTES,
        )
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("advisor %s: response is not valid JSON", source_name)
        return ()
    if not isinstance(payload, list):
        logger.warning(
            "advisor %s: response is not a JSON array of fragments",
            source_name,
        )
        return ()
    fragments: list[Fragment] = []
    for item in payload[:_MAX_FRAGMENTS]:
        if not isinstance(item, dict):
            continue
        frag_text = item.get("text")
        frag_sim = item.get("similarity")
        if (
            not isinstance(frag_text, str)
            or isinstance(frag_sim, bool)
            or not isinstance(frag_sim, (int, float))
        ):
            continue
        # Truncate so a 5 MiB single-fragment response cannot bypass
        # ``_MAX_RESPONSE_BYTES`` after the JSON has been parsed away.
        frag_text = frag_text[:_MAX_FRAGMENT_TEXT_CHARS]
        metadata = {k: v for k, v in item.items() if k not in {"text", "similarity"}}
        fragments.append(
            Fragment(text=frag_text, similarity=float(frag_sim), metadata=metadata)
        )
    return tuple(fragments)


# ---------------------------------------------------------------------------
# Concurrent fan-out
# ---------------------------------------------------------------------------


async def consult_advisors(
    sources: tuple[InsightSource, ...] | list[InsightSource],
    *,
    query: str,
) -> dict[str, tuple[Fragment, ...]]:
    """Run ``search_one`` for every source concurrently.

    Wall-time is bounded by the slowest source's effective timeout,
    not the sum, because all sources are launched together via
    ``asyncio.gather``. Returns a dict keyed by ``source.name`` so
    the caller can format per-advisor sections.
    """
    sources = tuple(sources)
    if not sources:
        return {}

    results = await asyncio.gather(
        *(search_one(s, query=query) for s in sources),
        return_exceptions=False,
    )
    return {s.name: r for s, r in zip(sources, results, strict=True)}


__all__ = [
    "Fragment",
    "consult_advisors",
    "search_one",
]
