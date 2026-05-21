"""Tests for ``mureo.core.throttle_store.ProcessLocalThrottleStore`` —
the default in-process implementation that maintains a per-key
``mureo.throttle.Throttler`` and awaits ``acquire()`` on the matching
instance.

Behavioural equivalence with today's MCP server pattern: each unique
``key`` lazily materialises its own token bucket; repeated calls with
the same key reuse the same bucket so QPS limits are enforced across
the process.
"""

from __future__ import annotations

import pytest

from mureo.core.throttle_store import ProcessLocalThrottleStore, ThrottleStore
from mureo.throttle import ThrottleConfig


@pytest.mark.unit
def test_satisfies_protocol() -> None:
    assert isinstance(ProcessLocalThrottleStore(), ThrottleStore)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_returns_without_blocking_on_first_call() -> None:
    """A token bucket with a burst of ``1`` permits the first acquire
    immediately — used to verify the wired Throttler is in fact awaited."""
    config = ThrottleConfig(rate=1000.0, burst=10)
    store = ProcessLocalThrottleStore(default_config=config)
    await store.acquire("anything")  # must return promptly


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_key_reuses_throttler() -> None:
    """Repeated acquire on the same key must hit the same Throttler so
    rate limits are enforced — observable via the internal cache."""
    config = ThrottleConfig(rate=1000.0, burst=10)
    store = ProcessLocalThrottleStore(default_config=config)
    await store.acquire("key-a")
    await store.acquire("key-a")
    assert len(store.throttlers) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_distinct_keys_get_separate_throttlers() -> None:
    config = ThrottleConfig(rate=1000.0, burst=10)
    store = ProcessLocalThrottleStore(default_config=config)
    await store.acquire("key-a")
    await store.acquire("key-b")
    assert set(store.throttlers.keys()) == {"key-a", "key-b"}


@pytest.mark.unit
def test_default_config_is_used_when_unspecified() -> None:
    """When no config is injected the store must fall back to
    ``mureo.throttle.PLUGIN_THROTTLE`` so callers that do nothing special
    see the same limits as today's MCP server."""
    from mureo.throttle import PLUGIN_THROTTLE

    store = ProcessLocalThrottleStore()
    assert store.default_config is PLUGIN_THROTTLE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_installs_custom_throttler_used_by_acquire() -> None:
    """``register(key, config)`` pre-installs a Throttler with the given
    config; subsequent ``acquire(key)`` reuses that exact instance
    (verified by identity) instead of materialising a new one from
    default_config. Mirrors today's MCP-server pattern that builds
    per-tool buckets from ``derive_semantics``."""
    default = ThrottleConfig(rate=1.0, burst=1)  # slow default
    fast = ThrottleConfig(rate=1000.0, burst=10)  # fast override
    store = ProcessLocalThrottleStore(default_config=default)
    store.register("fast-tool", fast)
    registered = store.throttlers["fast-tool"]
    # Wiring check: the Throttler was actually built from ``fast``, not
    # ``default``. Reaches into a private attribute deliberately — there
    # is no public way to read the config back from a Throttler.
    assert registered._rate == fast.rate  # type: ignore[attr-defined]
    await store.acquire("fast-tool")
    assert store.throttlers["fast-tool"] is registered
