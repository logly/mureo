"""Token-bucket rate limiter with optional rolling hourly cap.

Provides a :class:`Throttler` that enforces per-second token-bucket semantics
and an optional hourly request cap.  Pre-configured instances for Google Ads
and Meta Ads are exported as module-level constants.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass

# Alias so tests can patch deterministically
asyncio_sleep = asyncio.sleep


@dataclass(frozen=True)
class ThrottleConfig:
    """Immutable rate-limit configuration.

    Attributes:
        rate: Tokens refilled per second.
        burst: Maximum bucket capacity (also the initial token count).
        hourly_limit: Rolling-hour request cap.  ``None`` disables the cap.
    """

    rate: float
    burst: int
    hourly_limit: int | None = None

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError(f"rate must be positive, got {self.rate}")
        if self.burst <= 0:
            raise ValueError(f"burst must be positive, got {self.burst}")
        if self.hourly_limit is not None and self.hourly_limit <= 0:
            raise ValueError(f"hourly_limit must be positive, got {self.hourly_limit}")


# ---------------------------------------------------------------------------
# Preset configurations
# ---------------------------------------------------------------------------

# Google Ads: dynamic rate limits (not published). Conservative defaults.
# See https://developers.google.com/google-ads/api/docs/best-practices/rate-limits
GOOGLE_ADS_THROTTLE = ThrottleConfig(rate=10.0, burst=5)

# Meta Ads: Standard access = 9,000 pts / 300s, 100 QPS mutations.
# See https://developers.facebook.com/docs/marketing-api/overview/rate-limiting
META_ADS_THROTTLE = ThrottleConfig(rate=20.0, burst=10, hourly_limit=50_000)

# Search Console: Conservative defaults.
# See https://developers.google.com/webmaster-tools/limits
SEARCH_CONSOLE_THROTTLE = ThrottleConfig(rate=5.0, burst=5)


# ---------------------------------------------------------------------------
# Throttler
# ---------------------------------------------------------------------------


class Throttler:
    """Async token-bucket throttler with optional hourly cap.

    The throttler is safe to share across multiple coroutines — an internal
    :class:`asyncio.Lock` serialises token accounting.  When a token is not
    immediately available the caller is suspended (via ``asyncio.sleep``)
    outside the lock so that other coroutines can proceed.
    """

    def __init__(self, config: ThrottleConfig) -> None:
        self._rate: float = config.rate
        self._burst: int = config.burst
        self._hourly_limit: int | None = config.hourly_limit

        self._tokens: float = float(config.burst)
        self._last_refill: float = time.monotonic()

        self._lock: asyncio.Lock = asyncio.Lock()

        # Timestamps of requests within the rolling hour window.
        self._hourly_window: deque[float] = deque()

    # -- public API ---------------------------------------------------------

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        while True:
            wait_time = 0.0
            async with self._lock:
                # 1. Hourly-limit gate
                if self._hourly_limit is not None:
                    self._prune_hourly()
                    if len(self._hourly_window) >= self._hourly_limit:
                        oldest = self._hourly_window[0]
                        wait_time = 3600.0 - (time.monotonic() - oldest) + 0.01

                if wait_time == 0.0:
                    # 2. Token bucket
                    self._refill()
                    if self._tokens >= 1.0:
                        self._tokens -= 1.0
                        if self._hourly_limit is not None:
                            self._hourly_window.append(time.monotonic())
                        return  # Token acquired
                    wait_time = max((1.0 - self._tokens) / self._rate, 0.001)

            # Sleep *outside* the lock so other coroutines can proceed.
            await asyncio_sleep(wait_time)

    # -- internal helpers ---------------------------------------------------

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(
                float(self._burst),
                self._tokens + elapsed * self._rate,
            )
            self._last_refill = now

    def _prune_hourly(self) -> None:
        """Remove entries older than 3600 seconds from the hourly window."""
        cutoff = time.monotonic() - 3600.0
        while self._hourly_window and self._hourly_window[0] < cutoff:
            self._hourly_window.popleft()
