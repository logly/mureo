"""External insight-source federation client.

Translates an :class:`mureo.learning.insight_sources.InsightSource`
into a concrete MCP client session and extracts the Markdown content
returned by the configured remote tool.

Design constraints:

- **Per-source error isolation.** A single misbehaving source (slow,
  crashed, malformed response, network error) must never block the
  diagnostic flow. Every failure mode in this module returns ``None``
  with a warning log, and :func:`fetch_all` filters those out.

- **Per-source timeout.** ``InsightSource.timeout_sec`` caps each
  ``tools/call`` round-trip via :func:`asyncio.wait_for`. The default
  of 10s is long enough for a slow remote, short enough to keep the
  diagnostic UX responsive when the operator's network is down.

- **Concurrent fan-out.** :func:`fetch_all` uses
  :func:`asyncio.gather` so the wall-time of N sources is bounded by
  the slowest, not their sum.

- **No SDK leak.** The SDK imports stay local to this module so a
  test that just exercises config parsing
  (:mod:`mureo.learning.insight_sources`) does not pull in the
  network-capable client modules.

The text-extraction policy is deliberately strict: only ``type ==
"text"`` content blocks are kept. Image / resource / structured-data
blocks are dropped silently rather than rendered as placeholders that
would pollute the agent's prompt with non-Markdown noise.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mureo.learning.insight_sources import InsightSource

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _open_session(source: InsightSource) -> AsyncIterator[ClientSession]:
    """Open an MCP client session for ``source`` via the right
    transport, perform the protocol initialize, and yield the
    session. The context exits clean up the transport.

    This wrapper exists so :func:`fetch_from_source` can be unit-tested
    by patching just this one function instead of mocking three
    separate transport helpers.
    """
    if source.transport == "stdio":
        # ``command`` is guaranteed non-None by ``InsightSource``
        # post-init validation. ``env`` and ``headers`` are passed
        # as ``None`` (not empty dict) when unset so the SDK's
        # "inherit / default" semantics apply — a future SDK that
        # distinguishes ``{}`` from ``None`` would otherwise break.
        params = StdioServerParameters(
            command=source.command or "",
            args=list(source.args),
            env=dict(source.env) if source.env else None,
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
        return
    if source.transport == "sse":
        async with (
            sse_client(
                source.url or "",
                headers=dict(source.headers) if source.headers else None,
            ) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
        return
    if source.transport == "http":
        # streamablehttp_client yields a (read, write, _close) tuple
        # on newer SDK versions; we only need the first two for
        # ClientSession.
        async with streamablehttp_client(
            source.url or "",
            headers=dict(source.headers) if source.headers else None,
        ) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:  # noqa: SIM117
                await session.initialize()
                yield session
        return
    # Defence-in-depth: ``InsightSource.__post_init__`` already
    # refuses unknown transports, so a config-built source can
    # never reach this branch. Kept so a hand-built source (e.g.
    # in a future test fixture) fails loudly rather than silently
    # returning ``None``.
    raise ValueError(f"unknown transport for source {source.name!r}")


def _extract_text(result: Any) -> str:
    """Concatenate every ``type == "text"`` block in ``result.content``.

    Each block's trailing whitespace is stripped before joining
    with a blank-line separator so blocks render as one Markdown
    paragraph break regardless of whether the remote server emits
    each block with or without a trailing newline. Single-block
    responses round-trip unchanged (the strip only removes
    trailing whitespace; leading content is preserved).
    """
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text.rstrip())
    return "\n\n".join(parts)


async def fetch_from_source(source: InsightSource) -> str | None:
    """Fetch insights from one external MCP server.

    Returns the Markdown text on success, ``None`` on any failure
    mode (timeout, network error, ``isError`` response, malformed
    content). The error path always logs a WARNING that names the
    source so an operator inspecting the log can act on it.
    """
    try:
        async with _open_session(source) as session:
            # ``asyncio.wait_for`` is the canonical timeout layer —
            # it raises ``asyncio.TimeoutError`` which we map to a
            # clear "timed out" warning. The SDK's own
            # ``read_timeout_seconds`` is intentionally not set so
            # there is no second timer that could fire first with
            # an SDK-specific exception type masquerading as a
            # generic failure.
            result = await asyncio.wait_for(
                session.call_tool(source.tool, arguments={}),
                timeout=source.timeout_sec,
            )
    except asyncio.TimeoutError:
        logger.warning(
            "insight source %r: timed out after %.1fs",
            source.name,
            source.timeout_sec,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — per-source isolation
        # ``except Exception`` (not ``BaseException``) is
        # deliberate: ``asyncio.CancelledError`` inherits from
        # ``BaseException`` in 3.8+, so it correctly propagates and
        # the outer task group can still cancel cleanly. Only
        # operational failures (network / subprocess / protocol)
        # are caught here.
        logger.warning(
            "insight source %r: fetch failed (%s): %s",
            source.name,
            type(exc).__name__,
            exc,
        )
        return None

    if getattr(result, "isError", False):
        logger.warning(
            "insight source %r: remote tool returned an error result",
            source.name,
        )
        return None

    text = _extract_text(result)
    if not text:
        logger.warning("insight source %r: response had no text content", source.name)
        return None
    return text


async def fetch_all(
    sources: tuple[InsightSource, ...],
) -> dict[str, str]:
    """Fetch insights from every source concurrently.

    Returns ``{source_name: insight_text}`` keyed by
    :attr:`InsightSource.name`. Sources that failed (returned
    ``None``) are omitted, so the caller can iterate without
    re-checking for blanks.

    Cancellation safety: ``asyncio.gather`` with default
    ``return_exceptions=False`` would cancel the rest of the task
    group on any unhandled exception. The per-source error trap in
    :func:`fetch_from_source` makes that unreachable in practice, but
    we still pass ``return_exceptions=True`` as a belt-and-suspenders
    guard so a future refactor can't accidentally introduce a global
    failure mode.
    """
    if not sources:
        return {}
    coros = [fetch_from_source(s) for s in sources]
    results = await asyncio.gather(*coros, return_exceptions=True)
    out: dict[str, str] = {}
    for source, result in zip(sources, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "insight source %r: unexpected exception escaped (%s): %s",
                source.name,
                type(result).__name__,
                result,
            )
            continue
        if result:
            out[source.name] = result
    return out


__all__ = [
    "fetch_all",
    "fetch_from_source",
]
