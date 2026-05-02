"""Token-bucket rate-limiter behaviour."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.rate_limiter import MultiSourceLimiter, TokenBucket


def test_token_bucket_rejects_zero_rate() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=0, capacity=1)


def test_token_bucket_rejects_zero_capacity() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=1, capacity=0)


async def test_token_bucket_first_acquire_is_immediate() -> None:
    bucket = TokenBucket(rate=10, capacity=1)
    started = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - started
    assert elapsed < 0.05, f"first acquire blocked for {elapsed:.3f}s"


async def test_token_bucket_serialises_at_configured_rate() -> None:
    """At 10/s with capacity 1, two consecutive acquires should be ~100ms apart."""
    bucket = TokenBucket(rate=10, capacity=1)
    await bucket.acquire()
    started = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - started
    # Allow generous slack for the event loop on a busy machine, but bound it.
    assert 0.06 < elapsed < 0.30, (
        f"second acquire elapsed {elapsed:.3f}s, expected ~0.1s")


async def test_multi_source_limiter_isolates_buckets() -> None:
    """Each source bucket is independent: throttling one must not affect others."""
    limiter = MultiSourceLimiter()
    limiter.register("fast", rate_per_second=100, burst=1)
    limiter.register("slow", rate_per_second=2, burst=1)

    # First acquires drain each bucket's single token.
    await limiter.acquire("slow")
    started_slow = time.monotonic()
    await limiter.acquire("slow")  # waits ~0.5s for next token
    slow_elapsed = time.monotonic() - started_slow

    # The fast bucket has refilled by now and should be immediate.
    started_fast = time.monotonic()
    await limiter.acquire("fast")
    fast_elapsed = time.monotonic() - started_fast

    assert slow_elapsed > 0.30, f"slow bucket failed to throttle: {slow_elapsed}"
    assert fast_elapsed < 0.05, f"fast bucket was incorrectly throttled: {fast_elapsed}"


async def test_unregistered_source_raises() -> None:
    limiter = MultiSourceLimiter()
    with pytest.raises(KeyError):
        await limiter.acquire("does-not-exist")


async def test_concurrent_acquires_serialise() -> None:
    """Five concurrent acquires at 5/s, capacity 1: 1 free, 4 throttled at 0.2s each."""
    limiter = MultiSourceLimiter()
    limiter.register("test", rate_per_second=5, burst=1)

    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire("test") for _ in range(5)))
    elapsed = time.monotonic() - started

    # First is free; remaining 4 wait ~0.2s each = ~0.8s total.
    assert 0.6 < elapsed < 1.5, f"concurrent acquires elapsed {elapsed:.3f}s"
