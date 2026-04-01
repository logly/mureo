"""Tests for mureo.throttle — token-bucket rate limiter with optional hourly cap."""

from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import AsyncMock, patch

import pytest

from mureo.throttle import (
    GOOGLE_ADS_THROTTLE,
    META_ADS_THROTTLE,
    ThrottleConfig,
    Throttler,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_throttler(
    cfg: ThrottleConfig,
    initial_time: float = 0.0,
) -> tuple[Throttler, list[float]]:
    """Create a Throttler with a controllable time sequence.

    Returns ``(throttler, time_values)`` where *time_values* is a mutable
    list.  ``time.monotonic`` inside the throttle module will pop from the
    front of the list on each call; once exhausted it returns the last value.
    """
    throttler = Throttler(cfg)
    return throttler, []


# ---------------------------------------------------------------------------
# ThrottleConfig
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_throttle_config_frozen() -> None:
    """ThrottleConfig must be immutable (frozen dataclass)."""
    cfg = ThrottleConfig(rate=5.0, burst=3)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.rate = 99.0  # type: ignore[misc]


@pytest.mark.unit
def test_default_configs() -> None:
    """Verify preset throttle configurations."""
    assert GOOGLE_ADS_THROTTLE.rate == 10.0
    assert GOOGLE_ADS_THROTTLE.burst == 5
    assert GOOGLE_ADS_THROTTLE.hourly_limit is None

    assert META_ADS_THROTTLE.rate == 20.0
    assert META_ADS_THROTTLE.burst == 10
    assert META_ADS_THROTTLE.hourly_limit == 50_000


# ---------------------------------------------------------------------------
# Token bucket — immediate acquire
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_acquire_immediate() -> None:
    """With burst=5, five acquire() calls should complete instantly (no sleep)."""
    cfg = ThrottleConfig(rate=10.0, burst=5)
    throttler = Throttler(cfg)

    with patch("mureo.throttle.time") as mock_time:
        mock_time.monotonic.return_value = 0.0
        with patch(
            "mureo.throttle.asyncio_sleep", new_callable=AsyncMock
        ) as mock_sleep:
            for _ in range(5):
                await throttler.acquire()
            mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Token bucket — blocks when empty
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_acquire_blocks_when_empty() -> None:
    """After exhausting burst, next acquire() must sleep to wait for refill."""
    cfg = ThrottleConfig(rate=10.0, burst=2)
    throttler = Throttler(cfg)

    sleep_count = 0

    # _refill() calls monotonic() once per acquire loop iteration.
    # acquire 1: monotonic -> 0.0, elapsed=0 (same as _last_refill), tokens stay 2 -> -1 = 1
    # acquire 2: monotonic -> 0.0, elapsed=0, tokens=1 -> -1 = 0
    # acquire 3 loop 1: monotonic -> 0.0, elapsed=0, tokens=0 < 1 -> sleep
    # acquire 3 loop 2: monotonic -> 0.5, elapsed=0.5, tokens=0+5=2(cap) -> -1 = 1 -> done
    call_count = 0

    def mock_monotonic() -> float:
        nonlocal call_count
        call_count += 1
        # After any sleep has happened, advance time
        if sleep_count > 0:
            return 0.5
        return 0.0

    async def fake_sleep(duration: float) -> None:
        nonlocal sleep_count
        sleep_count += 1

    with patch("mureo.throttle.time") as mock_time:
        mock_time.monotonic.side_effect = mock_monotonic
        throttler._last_refill = 0.0

        with patch(
            "mureo.throttle.asyncio_sleep", side_effect=fake_sleep
        ) as mock_sleep:
            await throttler.acquire()
            await throttler.acquire()
            await throttler.acquire()

            assert sleep_count >= 1
            wait_arg = mock_sleep.call_args[0][0]
            assert wait_arg > 0


# ---------------------------------------------------------------------------
# Refill over time
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_refill_over_time() -> None:
    """After waiting, tokens should refill based on elapsed time."""
    cfg = ThrottleConfig(rate=10.0, burst=5)
    throttler = Throttler(cfg)

    # First 5 acquires at t=0 exhaust all tokens.
    # Then time jumps to t=1.0 for the next 5 acquires.
    phase = [0]

    def mock_monotonic() -> float:
        if phase[0] < 10:
            phase[0] += 1
            return 0.0
        return 1.0

    with patch("mureo.throttle.time") as mock_time:
        mock_time.monotonic.side_effect = mock_monotonic
        throttler._last_refill = 0.0

        with patch("mureo.throttle.asyncio_sleep", new_callable=AsyncMock):
            # Exhaust all 5 tokens at t=0
            for _ in range(5):
                await throttler.acquire()

            # At t=1.0, 10 tokens refilled but capped at burst=5
            for _ in range(5):
                await throttler.acquire()


# ---------------------------------------------------------------------------
# Hourly limit — blocks
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_hourly_limit_blocks() -> None:
    """With hourly_limit=3, fourth call must sleep."""
    cfg = ThrottleConfig(rate=100.0, burst=10, hourly_limit=3)
    throttler = Throttler(cfg)

    sleep_called = False

    # First 3 acquires at t=100. Fourth triggers hourly limit.
    # After sleep, time jumps to t=3800 so oldest entries are pruned.
    phase = [0]

    def mock_monotonic() -> float:
        phase[0] += 1
        if phase[0] <= 12:
            return 100.0
        return 3800.0

    async def fake_sleep(duration: float) -> None:
        nonlocal sleep_called
        sleep_called = True

    with patch("mureo.throttle.time") as mock_time:
        mock_time.monotonic.side_effect = mock_monotonic
        throttler._last_refill = 100.0

        with patch("mureo.throttle.asyncio_sleep", side_effect=fake_sleep):
            await throttler.acquire()
            await throttler.acquire()
            await throttler.acquire()
            await throttler.acquire()

            assert sleep_called


# ---------------------------------------------------------------------------
# No hourly limit
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_no_hourly_limit() -> None:
    """With hourly_limit=None, no hourly tracking occurs."""
    cfg = ThrottleConfig(rate=100.0, burst=100)
    throttler = Throttler(cfg)

    with patch("mureo.throttle.time") as mock_time:
        mock_time.monotonic.return_value = 0.0
        throttler._last_refill = 0.0

        with patch(
            "mureo.throttle.asyncio_sleep", new_callable=AsyncMock
        ) as mock_sleep:
            for _ in range(50):
                await throttler.acquire()
            mock_sleep.assert_not_called()

    # Verify hourly window was not used
    assert len(throttler._hourly_window) == 0


# ---------------------------------------------------------------------------
# Concurrent acquire
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_concurrent_acquire() -> None:
    """Multiple coroutines sharing one throttler should all eventually acquire."""
    cfg = ThrottleConfig(rate=10.0, burst=5)
    throttler = Throttler(cfg)

    acquired = 0
    # 10 workers, burst=5, so first 5 get tokens immediately, rest need refill.
    phase = [0]

    def mock_monotonic() -> float:
        phase[0] += 1
        if phase[0] <= 20:
            return 0.0
        return 1.0  # 1s later -> 10 tokens refill (capped to burst=5)

    with patch("mureo.throttle.time") as mock_time:
        mock_time.monotonic.side_effect = mock_monotonic
        throttler._last_refill = 0.0

        with patch("mureo.throttle.asyncio_sleep", new_callable=AsyncMock):

            async def worker() -> None:
                nonlocal acquired
                await throttler.acquire()
                acquired += 1

            tasks = [asyncio.create_task(worker()) for _ in range(10)]
            await asyncio.gather(*tasks)

    assert acquired == 10
