"""``ThrottleStore`` Protocol and default in-process implementation.

The Protocol abstracts the per-key rate limiter used by MCP tool
handlers when calling out to ad platforms. Today ``mureo.mcp.server``
maintains a ``dict[str, Throttler]`` of name-keyed token buckets and
awaits ``throttler.acquire()`` before each tool invocation. This
Protocol exposes the same "gate by name" shape so the underlying
implementation can be swapped for a no-op in tests or for a
cross-process backend (file lock, Redis) in deployments that share an
API quota across several MCP processes.

``ProcessLocalThrottleStore`` is the default implementation — a thin
per-process registry of ``mureo.throttle.Throttler`` instances. It
mirrors today's MCP server pattern: each unique ``key`` lazily
materialises its own token bucket; repeated calls with the same key
reuse the same bucket so rate limits are enforced across the process.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mureo.throttle import PLUGIN_THROTTLE, ThrottleConfig, Throttler


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


# ---------------------------------------------------------------------------
# Default implementation — per-key Throttler dict in process memory
# ---------------------------------------------------------------------------


class ProcessLocalThrottleStore:
    """Maintain one :class:`mureo.throttle.Throttler` per key in process
    memory. Each Throttler is constructed lazily on first acquire using
    ``default_config`` (falling back to ``PLUGIN_THROTTLE`` if omitted),
    matching today's MCP-server fallback for tools without a declared
    throttle hint.

    asyncio is single-threaded so the ``key not in self.throttlers``
    check followed by ``self.throttlers[key] = ...`` is race-free in
    practice (no ``await`` between the check and the insert).
    """

    def __init__(self, default_config: ThrottleConfig | None = None) -> None:
        self.default_config = (
            default_config if default_config is not None else PLUGIN_THROTTLE
        )
        self.throttlers: dict[str, Throttler] = {}

    def register(self, key: str, config: ThrottleConfig) -> None:
        """Pre-install a :class:`Throttler` with a custom ``config`` for
        ``key``. Subsequent calls to ``acquire(key)`` reuse this instance
        instead of materialising a new one from ``default_config``.

        Mirrors the existing MCP server pattern that pre-builds
        per-tool-name buckets from ``derive_semantics`` output
        (``mureo.mcp.server._PLUGIN_TOOL_THROTTLERS``); the lazy path
        through ``acquire`` remains the fallback for keys that have not
        been registered.
        """
        self.throttlers[key] = Throttler(config)

    async def acquire(self, key: str) -> None:
        throttler = self.throttlers.get(key)
        if throttler is None:
            throttler = Throttler(self.default_config)
            self.throttlers[key] = throttler
        await throttler.acquire()
