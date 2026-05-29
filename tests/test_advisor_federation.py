"""Tests for ``mureo.learning.federation``.

Pins the retrieval-pattern client logic:
- A vector-search ``tools/call`` is dispatched with ``{query, top_k}``.
- The response is parsed as a list of fragments (text + similarity).
- Per-source timeout / exception isolation never breaks the flow.
- Concurrent fan-out via ``asyncio.gather`` keeps wall-time bounded.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from mureo.learning.federation import (
    Fragment,
    consult_advisors,
    search_one,
)
from mureo.learning.insight_sources import InsightSource


def _patch_open(session: Any) -> Any:
    """Return a patcher whose replacement for ``_open_session`` is a
    proper ``@asynccontextmanager`` yielding ``session``.
    """

    @asynccontextmanager
    async def _fake(_src: InsightSource) -> AsyncIterator[Any]:
        yield session

    return patch("mureo.learning.federation._open_session", new=_fake)


def _patch_open_raises(exc: BaseException) -> Any:
    @asynccontextmanager
    async def _fake(_src: InsightSource) -> AsyncIterator[Any]:
        raise exc
        yield  # pragma: no cover

    return patch("mureo.learning.federation._open_session", new=_fake)


def _patch_open_slow(delay: float) -> Any:
    @asynccontextmanager
    async def _fake(_src: InsightSource) -> AsyncIterator[Any]:
        await asyncio.sleep(delay)
        yield MagicMock()

    return patch("mureo.learning.federation._open_session", new=_fake)


def _src(name: str = "acme", **overrides: Any) -> InsightSource:
    base: dict[str, Any] = dict(
        name=name,
        transport="stdio",
        tool="vector_search",
        command="acme-mcp",
        timeout_sec=2,
        top_k=3,
    )
    base.update(overrides)
    return InsightSource(**base)


def _fake_tool_call_result(payload: Any, *, is_error: bool = False) -> MagicMock:
    """Build a mock ``CallToolResult`` whose ``content`` carries one
    text block holding the JSON payload — the shape the parser expects.
    """
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload) if not isinstance(payload, str) else payload
    result = MagicMock()
    result.isError = is_error
    result.content = [block]
    return result


@pytest.mark.asyncio
class TestSearchOne:
    async def test_forwards_query_and_top_k(self) -> None:
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_fake_tool_call_result([{"text": "hit", "similarity": 0.91}])
        )
        with _patch_open(session):
            fragments = await search_one(_src(), query="CV declining", top_k=3)
        session.call_tool.assert_awaited_once_with(
            "vector_search", {"query": "CV declining", "top_k": 3}
        )
        assert fragments == (Fragment(text="hit", similarity=0.91, metadata={}),)

    async def test_parses_fragments_with_metadata(self) -> None:
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_fake_tool_call_result(
                [
                    {
                        "text": "A",
                        "similarity": 0.7,
                        "tags": ["budget"],
                        "case_id": "c1",
                    },
                    {"text": "B", "similarity": 0.5},
                ]
            )
        )
        with _patch_open(session):
            fragments = await search_one(_src(), query="q", top_k=2)
        assert len(fragments) == 2
        assert fragments[0].metadata == {"tags": ["budget"], "case_id": "c1"}
        assert fragments[1].similarity == 0.5

    async def test_is_error_response_returns_empty(self) -> None:
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_fake_tool_call_result("oops", is_error=True)
        )
        with _patch_open(session):
            fragments = await search_one(_src(), query="q", top_k=3)
        assert fragments == ()

    async def test_non_list_payload_returns_empty(self) -> None:
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_fake_tool_call_result({"not": "a list"})
        )
        with _patch_open(session):
            fragments = await search_one(_src(), query="q", top_k=3)
        assert fragments == ()

    async def test_timeout_returns_empty(self) -> None:
        with _patch_open_slow(10):
            fragments = await search_one(_src(timeout_sec=0.05), query="q", top_k=3)
        assert fragments == ()

    async def test_exception_returns_empty(self) -> None:
        with _patch_open_raises(RuntimeError("network down")):
            fragments = await search_one(_src(), query="q", top_k=3)
        assert fragments == ()

    async def test_cancelled_propagates(self) -> None:
        with _patch_open_slow(100):
            task = asyncio.create_task(
                search_one(_src(timeout_sec=10), query="q", top_k=3)
            )
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
class TestConsultAdvisors:
    async def test_fans_out_concurrently(self) -> None:
        sources = (_src("a"), _src("b"))

        async def _fake_search(
            source: InsightSource,
            *,
            query: str,
            top_k: int | None = None,
        ) -> tuple[Fragment, ...]:
            await asyncio.sleep(0.05)
            return (Fragment(text=f"{source.name}-hit", similarity=0.9, metadata={}),)

        with patch(
            "mureo.learning.federation.search_one",
            new=AsyncMock(side_effect=_fake_search),
        ):
            t0 = asyncio.get_running_loop().time()
            results = await consult_advisors(sources, query="q")
            elapsed = asyncio.get_running_loop().time() - t0

        assert set(results.keys()) == {"a", "b"}
        assert elapsed < 0.2  # would be ~0.1 if sequential

    async def test_one_failure_isolates(self) -> None:
        sources = (_src("ok"), _src("bad"))

        async def _fake_search(
            source: InsightSource,
            *,
            query: str,
            top_k: int | None = None,
        ) -> tuple[Fragment, ...]:
            if source.name == "bad":
                return ()
            return (Fragment(text="OK", similarity=0.8, metadata={}),)

        with patch(
            "mureo.learning.federation.search_one",
            new=AsyncMock(side_effect=_fake_search),
        ):
            results = await consult_advisors(sources, query="q")
        assert results["ok"][0].text == "OK"
        assert results["bad"] == ()

    async def test_empty_sources_returns_empty_dict(self) -> None:
        results = await consult_advisors((), query="q")
        assert results == {}


@pytest.mark.asyncio
class TestFragmentPayloadCaps:
    """Untrusted advisor responses must not balloon the agent's
    context — pin the size / count / per-fragment caps."""

    async def test_megabyte_response_dropped(self) -> None:
        huge = json.dumps([{"text": "x" * (2 * 1024 * 1024), "similarity": 0.5}])
        block = MagicMock()
        block.type = "text"
        block.text = huge
        result = MagicMock()
        result.isError = False
        result.content = [block]
        session = AsyncMock()
        session.call_tool = AsyncMock(return_value=result)
        with _patch_open(session):
            fragments = await search_one(_src(), query="q", top_k=3)
        assert fragments == ()

    async def test_fragment_count_capped(self) -> None:
        # Many small fragments — well below the byte cap so the byte
        # check passes, but the count cap should still kick in.
        items = [{"text": f"f{i}", "similarity": 0.5} for i in range(200)]
        session = AsyncMock()
        session.call_tool = AsyncMock(return_value=_fake_tool_call_result(items))
        with _patch_open(session):
            fragments = await search_one(_src(), query="q", top_k=3)
        assert len(fragments) == 50  # _MAX_FRAGMENTS

    async def test_individual_fragment_text_truncated(self) -> None:
        # One mid-sized fragment that stays under the byte cap but
        # individually exceeds the per-fragment text cap.
        item = {"text": "z" * 20000, "similarity": 0.9}
        session = AsyncMock()
        session.call_tool = AsyncMock(return_value=_fake_tool_call_result([item]))
        with _patch_open(session):
            fragments = await search_one(_src(), query="q", top_k=3)
        assert len(fragments) == 1
        assert len(fragments[0].text) == 4 * 1024  # _MAX_FRAGMENT_TEXT_CHARS

    async def test_boolean_similarity_rejected(self) -> None:
        # bool subclasses int — naive isinstance(x, (int, float)) would
        # accept True/False as 1.0/0.0. Pin that we reject it explicitly
        # so a hostile advisor cannot smuggle a Fragment with
        # similarity=1.0 by sending ``"similarity": true``.
        item = {"text": "ok", "similarity": True}
        session = AsyncMock()
        session.call_tool = AsyncMock(return_value=_fake_tool_call_result([item]))
        with _patch_open(session):
            fragments = await search_one(_src(), query="q", top_k=3)
        assert fragments == ()
