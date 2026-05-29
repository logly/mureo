"""Tests for ``mureo.learning.federation``.

The federation layer:

- Translates an :class:`mureo.learning.insight_sources.InsightSource`
  into a concrete MCP client session (stdio / sse / streamable-HTTP).
- Calls the configured ``tool`` and extracts text content from the
  response.
- Imposes a per-source timeout so a slow / dead remote does not stall
  the diagnostic flow.
- Isolates per-source failures: a single timeout / network error /
  malformed response logs a warning and yields ``None`` for that
  source, never raising into the caller.

We do not stand up real MCP servers in the test suite — that would
require subprocess plumbing and would be slow. Instead we patch the
small set of SDK seams the federation layer touches (``ClientSession``,
``stdio_client``, ``sse_client``, ``streamablehttp_client``) and
verify that the right helper is selected per transport, that the
right tool name is called, and that the right text is extracted.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_tool_result(text: str) -> Any:
    """Build a mock ``CallToolResult`` carrying a single text block.

    The federation layer only reads ``result.content[*].text`` (when
    ``type == "text"``), so we can get away with a minimal mock that
    pins just those attributes.
    """
    block = MagicMock()
    block.type = "text"
    block.text = text
    result = MagicMock()
    result.isError = False
    result.content = [block]
    return result


@asynccontextmanager
async def _fake_session_factory(tool_result: Any):
    """Yield a mock ``ClientSession`` whose ``call_tool`` returns
    ``tool_result``.

    Used by the patched ``ClientSession`` to short-circuit the real
    transport handshake.
    """
    session = MagicMock()
    session.initialize = AsyncMock()
    session.call_tool = AsyncMock(return_value=tool_result)
    yield session


@asynccontextmanager
async def _fake_transport_streams():
    """Yield (read, write) streams the real transport context managers
    would. The federation layer just forwards them into
    ``ClientSession``, which we are also patching, so they can be
    sentinel objects."""
    yield (object(), object())


@pytest.fixture
def stdio_source() -> Any:
    from mureo.learning.insight_sources import InsightSource

    return InsightSource(
        name="acme",
        transport="stdio",
        tool="insights_get",
        command="acme-insights-mcp",
    )


@pytest.fixture
def sse_source() -> Any:
    from mureo.learning.insight_sources import InsightSource

    return InsightSource(
        name="benchmarks",
        transport="sse",
        tool="benchmarks_get",
        url="https://benchmarks.example/mcp",
        headers={"Authorization": "Bearer xyz"},
    )


@pytest.fixture
def http_source() -> Any:
    from mureo.learning.insight_sources import InsightSource

    return InsightSource(
        name="kb",
        transport="http",
        tool="insights_get",
        url="https://kb.example/mcp",
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestFetchFromSource:
    async def test_stdio_source_uses_stdio_client_helper(
        self, stdio_source: Any
    ) -> None:
        from mureo.learning import federation

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(federation, "sse_client") as mock_sse,
            patch.object(federation, "streamablehttp_client") as mock_http,
            patch.object(
                federation,
                "_open_session",
                return_value=_fake_session_factory(
                    _make_mock_tool_result("## Insight A\n")
                ),
            ),
        ):
            mock_stdio.return_value = _fake_transport_streams()
            text = await federation.fetch_from_source(stdio_source)

        # ``_extract_text`` strips trailing whitespace from each
        # block; the source text had a trailing newline that is
        # normalised out so the agent sees a clean single section.
        assert text == "## Insight A"
        # Only the stdio helper is dispatched.
        mock_sse.assert_not_called()
        mock_http.assert_not_called()

    async def test_sse_source_uses_sse_client_helper(self, sse_source: Any) -> None:
        from mureo.learning import federation

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(federation, "sse_client") as mock_sse,
            patch.object(federation, "streamablehttp_client") as mock_http,
            patch.object(
                federation,
                "_open_session",
                return_value=_fake_session_factory(
                    _make_mock_tool_result("## Industry benchmarks\n")
                ),
            ),
        ):
            mock_sse.return_value = _fake_transport_streams()
            text = await federation.fetch_from_source(sse_source)

        assert text == "## Industry benchmarks"
        mock_stdio.assert_not_called()
        mock_http.assert_not_called()

    async def test_http_source_uses_streamable_http_client_helper(
        self, http_source: Any
    ) -> None:
        from mureo.learning import federation

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(federation, "sse_client") as mock_sse,
            patch.object(federation, "streamablehttp_client") as mock_http,
            patch.object(
                federation,
                "_open_session",
                return_value=_fake_session_factory(_make_mock_tool_result("## KB\n")),
            ),
        ):
            mock_http.return_value = _fake_transport_streams()
            text = await federation.fetch_from_source(http_source)

        assert text == "## KB"
        mock_stdio.assert_not_called()
        mock_sse.assert_not_called()

    async def test_call_tool_uses_configured_tool_name(self, stdio_source: Any) -> None:
        """The ``tool`` field on the source picks the remote tool name;
        the federation layer must NOT hardcode a name."""
        from mureo.learning import federation

        captured: dict[str, Any] = {}

        @asynccontextmanager
        async def capturing_session():
            session = MagicMock()
            session.initialize = AsyncMock()

            async def fake_call_tool(name: str, *args: Any, **kw: Any) -> Any:
                captured["name"] = name
                return _make_mock_tool_result("ok")

            session.call_tool = fake_call_tool
            yield session

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(federation, "_open_session", return_value=capturing_session()),
        ):
            mock_stdio.return_value = _fake_transport_streams()
            await federation.fetch_from_source(stdio_source)

        assert captured["name"] == "insights_get"

    async def test_text_is_concatenated_across_multiple_text_blocks(
        self, stdio_source: Any
    ) -> None:
        """A remote tool can return its insights split across several
        text blocks; we concatenate them with a single newline so the
        agent sees them as one section."""
        from mureo.learning import federation

        block_a, block_b = MagicMock(), MagicMock()
        block_a.type = "text"
        block_a.text = "## Block A\n"
        block_b.type = "text"
        # No trailing newline — the rstrip-then-join policy produces
        # the same output regardless, which is the whole point.
        block_b.text = "## Block B"
        multi = MagicMock()
        multi.isError = False
        multi.content = [block_a, block_b]

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(
                federation,
                "_open_session",
                return_value=_fake_session_factory(multi),
            ),
        ):
            mock_stdio.return_value = _fake_transport_streams()
            text = await federation.fetch_from_source(stdio_source)

        assert text == "## Block A\n\n## Block B"

    async def test_non_text_content_blocks_are_skipped(self, stdio_source: Any) -> None:
        """Image / resource blocks aren't useful as Markdown insights —
        they get dropped silently rather than rendered as ``[image]``
        placeholders that would pollute the agent's context."""
        from mureo.learning import federation

        text_block, image_block = MagicMock(), MagicMock()
        text_block.type = "text"
        text_block.text = "real insight"
        image_block.type = "image"
        mixed = MagicMock()
        mixed.isError = False
        mixed.content = [text_block, image_block]

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(
                federation,
                "_open_session",
                return_value=_fake_session_factory(mixed),
            ),
        ):
            mock_stdio.return_value = _fake_transport_streams()
            text = await federation.fetch_from_source(stdio_source)

        assert text == "real insight"

    async def test_error_response_returns_none(self, stdio_source: Any) -> None:
        """``CallToolResult.isError`` set by the remote tool itself
        (the SDK's structured error path) should not raise — we just
        skip the source with a warning, same as any other failure."""
        from mureo.learning import federation

        error_result = MagicMock()
        error_result.isError = True
        error_result.content = []

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(
                federation,
                "_open_session",
                return_value=_fake_session_factory(error_result),
            ),
        ):
            mock_stdio.return_value = _fake_transport_streams()
            text = await federation.fetch_from_source(stdio_source)

        assert text is None

    async def test_exception_during_fetch_returns_none(self, stdio_source: Any) -> None:
        """Network exceptions / subprocess crashes must be swallowed
        per source — a dead Acme MCP server should not block the
        operator's local insights from reaching the agent."""
        from mureo.learning import federation

        @asynccontextmanager
        async def boom_session():
            session = MagicMock()
            session.initialize = AsyncMock()
            session.call_tool = AsyncMock(
                side_effect=RuntimeError("connection refused")
            )
            yield session

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(federation, "_open_session", return_value=boom_session()),
        ):
            mock_stdio.return_value = _fake_transport_streams()
            text = await federation.fetch_from_source(stdio_source)

        assert text is None

    async def test_timeout_returns_none(self, stdio_source: Any) -> None:
        """A source that exceeds ``timeout_sec`` is dropped, not
        awaited indefinitely."""
        import asyncio

        from mureo.learning import federation
        from mureo.learning.insight_sources import InsightSource

        slow_source = InsightSource(
            name="slow",
            transport="stdio",
            tool="insights_get",
            command="slow-mcp",
            timeout_sec=0.05,
        )

        @asynccontextmanager
        async def stalling_session():
            session = MagicMock()
            session.initialize = AsyncMock()

            async def slow_call(*args: Any, **kw: Any) -> Any:
                await asyncio.sleep(1.0)
                return _make_mock_tool_result("late")

            session.call_tool = slow_call
            yield session

        with (
            patch.object(federation, "stdio_client") as mock_stdio,
            patch.object(federation, "_open_session", return_value=stalling_session()),
        ):
            mock_stdio.return_value = _fake_transport_streams()
            text = await federation.fetch_from_source(slow_source)

        assert text is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestFetchAll:
    async def test_fetch_all_returns_dict_keyed_by_source_name(self) -> None:
        from mureo.learning import federation
        from mureo.learning.insight_sources import InsightSource

        a = InsightSource(name="a", transport="stdio", tool="t", command="c")
        b = InsightSource(name="b", transport="stdio", tool="t", command="c")

        async def fake_fetch(src: Any) -> str:
            return f"insight from {src.name}"

        with patch.object(federation, "fetch_from_source", side_effect=fake_fetch):
            result = await federation.fetch_all((a, b))

        assert result == {"a": "insight from a", "b": "insight from b"}

    async def test_fetch_all_isolates_per_source_failures(self) -> None:
        """One source failing or returning ``None`` must not block
        others. The returned dict only contains sources that produced
        usable text."""
        from mureo.learning import federation
        from mureo.learning.insight_sources import InsightSource

        good = InsightSource(name="good", transport="stdio", tool="t", command="c")
        bad = InsightSource(name="bad", transport="stdio", tool="t", command="c")

        async def fake_fetch(src: Any) -> str | None:
            if src.name == "good":
                return "good insight"
            return None  # simulated failure

        with patch.object(federation, "fetch_from_source", side_effect=fake_fetch):
            result = await federation.fetch_all((good, bad))

        assert result == {"good": "good insight"}

    async def test_fetch_all_runs_sources_concurrently(self) -> None:
        """Sources fan out via ``asyncio.gather`` so total wall-time
        is bounded by the slowest source, not their sum."""
        import asyncio

        from mureo.learning import federation
        from mureo.learning.insight_sources import InsightSource

        sources = tuple(
            InsightSource(name=f"s{i}", transport="stdio", tool="t", command="c")
            for i in range(5)
        )

        async def slow_fetch(src: Any) -> str:
            await asyncio.sleep(0.1)
            return src.name

        import time

        start = time.monotonic()
        with patch.object(federation, "fetch_from_source", side_effect=slow_fetch):
            await federation.fetch_all(sources)
        elapsed = time.monotonic() - start

        # Sequential would be 0.5s; concurrent should be ~0.1-0.15s.
        assert elapsed < 0.4

    async def test_fetch_all_empty_sources_returns_empty_dict(self) -> None:
        from mureo.learning import federation

        result = await federation.fetch_all(())
        assert result == {}
