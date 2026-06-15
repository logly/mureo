"""Test isolation for the adapter suites (google_ads / meta_ads).

Both adapters expose a synchronous Protocol over an ``async`` client and the
tests drive them with ``Mock(spec=...Client)`` whose async methods are
``AsyncMock``. Speccing a class with async methods makes unittest.mock create
``AsyncMockMixin._execute_mock_call`` coroutines that are never awaited; left to
chance garbage collection one can survive a test boundary and surface inside a
LATER async test's event loop (e.g. a Google Ads error popping up in a Meta
test), producing an order/timing-dependent FLAKY failure.

Collecting garbage at the end of every adapter test closes any such dangling
coroutine in its own scope, so it can never contaminate a subsequent test.
"""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _flush_leaked_coroutines() -> Iterator[None]:
    """Force GC after each adapter test so a never-awaited AsyncMock coroutine
    is closed in-scope rather than surviving into a later async test.

    Known source: ``test_calling_from_running_loop_raises_runtime_error`` (both
    suites) calls the adapter inside ``asyncio.run(...)``; the adapter raises on
    the running-loop check BEFORE awaiting the coroutine that ``AsyncMock``
    already built, orphaning it. The guard also covers any future test that
    reintroduces the same pattern.
    """
    yield
    gc.collect()
