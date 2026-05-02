"""
Async token-bucket rate limiter, one bucket per source name.

The bucket refills at ``rate`` tokens per second up to a ``capacity``
ceiling.  ``acquire()`` blocks asynchronously until a token is available,
so concurrent callers serialise without busy-waiting.

Used by the collector to respect each source's documented rate-limit
policy (NIST NVD: 5 req/30s without an API key; GitHub Events: 60 req/h
unauthenticated; OpenCorporates: documented in their ToS).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """Single-source token bucket. Not thread-safe; single-event-loop only."""

    rate: float           # tokens per second
    capacity: float       # max tokens held
    _tokens: float = 0.0
    _last_refill: float = 0.0

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError(f"rate must be positive, got {self.rate}")
        if self.capacity <= 0:
            raise ValueError(f"capacity must be positive, got {self.capacity}")
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            # Time until next token = (1 - tokens) / rate
            wait_seconds = (1.0 - self._tokens) / self.rate
            await asyncio.sleep(wait_seconds)


class MultiSourceLimiter:
    """One TokenBucket per source name. Acquire by name."""

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def register(self, name: str, rate_per_second: float, burst: float | None = None) -> None:
        """Register or replace the bucket for ``name``."""
        capacity = burst if burst is not None else max(1.0, rate_per_second)
        self._buckets[name] = TokenBucket(rate=rate_per_second, capacity=capacity)

    async def acquire(self, name: str) -> None:
        bucket = self._buckets.get(name)
        if bucket is None:
            raise KeyError(f"no rate-limit bucket registered for source {name!r}")
        await bucket.acquire()
