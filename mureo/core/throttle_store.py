"""``ThrottleStore`` Protocol — pluggable API quota throttling.

Abstracts the per-key rate limiter used by MCP tool handlers when
calling out to ad platforms. Today ``mureo.mcp.server`` maintains a
``dict[str, Throttler]`` of name-keyed token buckets (see
``_PLUGIN_TOOL_THROTTLERS``) and awaits ``throttler.acquire()`` before
each tool invocation. This Protocol exposes the same "gate by name"
shape so the underlying implementation can be swapped for a no-op in
tests or for a cross-process backend (file lock, Redis) in deployments
that share an API quota across several MCP processes.

The default in-process implementation (added in a follow-up commit)
delegates to ``mureo.throttle.Throttler`` instances, preserving the
existing throttling behaviour for callers that do not inject a custom
store.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ThrottleStore(Protocol):
    """Per-key rate-limit gate.

    Contract:
    - ``acquire(key)`` is an awaitable that blocks until the caller is
      permitted to issue one unit of work tagged ``key``. The rate at
      which work is permitted is fixed at store-construction time per
      key; callers do not negotiate ``max_qps`` here. Implementations
      that are unaware of ``key`` may treat it as opaque and share a
      single bucket across all keys.
    - There is no ``release`` — the existing ``Throttler`` model is a
      token bucket that replenishes by wall-clock time, not by callers
      returning a permit. Implementations that *do* require release-side
      bookkeeping should wrap themselves in an async context manager
      rather than extending this Protocol.
    """

    async def acquire(self, key: str) -> None: ...
