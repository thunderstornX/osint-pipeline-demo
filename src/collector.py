"""
Async HTTP collector with connection pooling, exponential backoff retry,
and rate-limit-aware acquisition.

The collector is parametrised by:

* ``workers`` -- size of the asyncio.Semaphore controlling in-flight requests
* ``rate_limiter`` -- ``MultiSourceLimiter`` registered with one bucket per source
* ``settings`` -- backoff base/cap, max attempts, request timeout

It exposes a single coroutine, ``fetch_all(sources)``, which yields raw
``(source, body_bytes)`` pairs. The orchestrator (``pipeline.py``) is
responsible for normalising and persisting them.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import AsyncIterator

import aiohttp

from src.config import PipelineSettings, SourceConfig
from src.rate_limiter import MultiSourceLimiter

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    source: str
    url: str
    status: int
    body: bytes
    attempt: int     # 1-based; tracks how many tries succeeded


class CollectorError(Exception):
    """Raised when a fetch ultimately fails after all retries."""


class HTTPCollector:
    """async HTTP collector. Use as an async context manager so the
    underlying ``aiohttp.ClientSession`` is closed cleanly on exit."""

    def __init__(self, settings: PipelineSettings, rate_limiter: MultiSourceLimiter) -> None:
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(settings.workers)

    async def __aenter__(self) -> "HTTPCollector":
        timeout = aiohttp.ClientTimeout(total=self._settings.request_timeout_seconds)
        connector = aiohttp.TCPConnector(limit=self._settings.workers, ttl_dns_cache=300)
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"User-Agent": self._settings.user_agent},
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _fetch_once(self, source: SourceConfig) -> FetchResult:
        """Fetch a source's URL once with retry. Raises CollectorError on failure."""
        if self._session is None:
            raise RuntimeError("HTTPCollector must be used as an async context manager")

        last_exc: Exception | None = None
        max_attempts = self._settings.retry_max_attempts + 1  # initial + retries
        for attempt in range(1, max_attempts + 1):
            await self._rate_limiter.acquire(source.name)
            try:
                async with self._semaphore:
                    async with self._session.get(source.url) as resp:
                        body = await resp.read()
                        # Retry on transient server errors
                        if 500 <= resp.status < 600:
                            last_exc = CollectorError(
                                f"HTTP {resp.status} from {source.url} (attempt {attempt})")
                            if attempt < max_attempts:
                                await self._sleep_backoff(attempt)
                                continue
                            # Final attempt also 5xx -- give up.
                            break
                        return FetchResult(
                            source=source.name, url=source.url,
                            status=resp.status, body=body, attempt=attempt,
                        )
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt < max_attempts:
                    await self._sleep_backoff(attempt)
                    continue
                break

        raise CollectorError(
            f"failed to fetch {source.url} after {max_attempts} attempts: {last_exc!r}"
        )

    async def _sleep_backoff(self, attempt: int) -> None:
        """Exponential backoff with jitter: base * 2**(attempt-1) +/- 25%."""
        base = self._settings.retry_base_delay_seconds
        delay = base * (2 ** (attempt - 1))
        jitter = delay * random.uniform(-0.25, 0.25)
        await asyncio.sleep(max(0.0, delay + jitter))

    async def fetch_all(self, sources: list[SourceConfig]) -> AsyncIterator[FetchResult]:
        """Fan out across sources, yielding results as each completes."""
        tasks = [asyncio.create_task(self._fetch_once(s)) for s in sources]
        for completed in asyncio.as_completed(tasks):
            try:
                yield await completed
            except CollectorError as exc:
                log.warning("collector failure: %s", exc)
