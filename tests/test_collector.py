"""HTTP collector retry / backoff behaviour, mocked via aioresponses."""

from __future__ import annotations

import pytest
from aioresponses import aioresponses

from src.collector import CollectorError, HTTPCollector
from src.config import PipelineSettings, SourceConfig
from src.rate_limiter import MultiSourceLimiter


def _src(url: str) -> SourceConfig:
    return SourceConfig(
        name="t", url=url, rate_limit_per_second=100, use_selenium=False, extractors=[],
    )


def _settings(retries: int = 2, base_delay: float = 0.01) -> PipelineSettings:
    return PipelineSettings(
        workers=5,
        retry_max_attempts=retries,
        retry_base_delay_seconds=base_delay,
        request_timeout_seconds=2.0,
    )


def _limiter(name: str = "t") -> MultiSourceLimiter:
    lim = MultiSourceLimiter()
    lim.register(name, rate_per_second=100)
    return lim


async def test_fetch_succeeds_on_first_try() -> None:
    url = "https://example.invalid/ok"
    with aioresponses() as m:
        m.get(url, status=200, body=b'{"ok":true}')
        async with HTTPCollector(_settings(), _limiter()) as c:
            results = [r async for r in c.fetch_all([_src(url)])]
    assert len(results) == 1
    assert results[0].status == 200
    assert results[0].attempt == 1
    assert b'"ok":true' in results[0].body


async def test_retries_on_5xx_then_succeeds() -> None:
    url = "https://example.invalid/flaky"
    with aioresponses() as m:
        m.get(url, status=503)
        m.get(url, status=200, body=b"ok")
        async with HTTPCollector(_settings(retries=2), _limiter()) as c:
            results = [r async for r in c.fetch_all([_src(url)])]
    assert len(results) == 1
    assert results[0].status == 200
    assert results[0].attempt == 2


async def test_gives_up_after_max_attempts() -> None:
    url = "https://example.invalid/dead"
    with aioresponses() as m:
        # All attempts return 503
        m.get(url, status=503)
        m.get(url, status=503)
        m.get(url, status=503)
        async with HTTPCollector(_settings(retries=2), _limiter()) as c:
            results = [r async for r in c.fetch_all([_src(url)])]
    # Collector swallows CollectorError into a logged warning; iterator
    # yields nothing for failed sources.
    assert results == []


async def test_returns_4xx_without_retry() -> None:
    """Client errors (4xx) are NOT retried -- they're the caller's fault."""
    url = "https://example.invalid/forbidden"
    with aioresponses() as m:
        m.get(url, status=404, body=b"not found")
        async with HTTPCollector(_settings(retries=3), _limiter()) as c:
            results = [r async for r in c.fetch_all([_src(url)])]
    assert len(results) == 1
    assert results[0].status == 404
    assert results[0].attempt == 1


async def test_fanout_yields_each_completed_source() -> None:
    urls = [f"https://example.invalid/{i}" for i in range(5)]
    with aioresponses() as m:
        for u in urls:
            m.get(u, status=200, body=b"ok")
        async with HTTPCollector(_settings(), _limiter()) as c:
            results = [r async for r in c.fetch_all([_src(u) for u in urls])]
    assert len(results) == 5
    # Order is undefined (asyncio.as_completed); just check we got each URL once.
    fetched_urls = sorted(r.url for r in results)
    assert fetched_urls == sorted(urls)


async def test_using_outside_context_manager_raises() -> None:
    c = HTTPCollector(_settings(), _limiter())
    with pytest.raises(RuntimeError):
        # Calling _fetch_once before __aenter__
        await c._fetch_once(_src("https://example.invalid/x"))
