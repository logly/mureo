"""Tests for ``mureo.core.throttle_store`` — structural Protocol contract.

RED-phase tests for the new ``ThrottleStore`` Protocol that abstracts
API quota throttling. Today the MCP server holds a ``dict[str,
Throttler]`` of named token buckets and awaits ``throttler.acquire()``
before each tool invocation; this Protocol exists so alternate backends
(cross-process file lock, Redis-backed shared throttle, no-op in tests)
can be swapped in without touching the MCP tool handlers.

This commit pins the Protocol shape only — concrete default
implementations land in a separate commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mureo.core.throttle_store import ThrottleStore


@dataclass
class _FakeThrottleStore:
    """Minimal no-op implementation used to exercise the Protocol shape."""

    acquired: list[str] = field(default_factory=list)

    async def acquire(self, key: str) -> None:
        self.acquired.append(key)


@pytest.mark.unit
def test_protocol_is_runtime_checkable() -> None:
    assert isinstance(_FakeThrottleStore(), ThrottleStore)


@pytest.mark.unit
def test_incomplete_implementation_is_rejected() -> None:
    class _MissingAcquire:
        async def something_else(self) -> None:
            pass

    assert not isinstance(_MissingAcquire(), ThrottleStore)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fake_records_acquire() -> None:
    store = _FakeThrottleStore()
    await store.acquire("google_ads:dev-token-abc")
    await store.acquire("meta_ads:bm-token-xyz")
    assert store.acquired == ["google_ads:dev-token-abc", "meta_ads:bm-token-xyz"]
