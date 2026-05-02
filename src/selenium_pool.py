"""
Async wrapper around a fixed-size pool of Selenium WebDriver instances.

Selenium's API is synchronous; we run each ``driver.get`` call inside an
``asyncio.to_thread`` so the calling coroutine isn't blocked. The pool
itself is bounded by an ``asyncio.Queue`` of drivers -- ``acquire()``
takes one out, ``release()`` puts it back.

Drivers are created lazily on first use, so simply importing this module
does NOT spawn a Chrome process. This keeps the optional-dependency
contract clean: a deployment that never enables a Selenium-backed source
pays no Selenium cost.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

log = logging.getLogger(__name__)


def _new_chrome_driver(headless: bool) -> Any:
    """Construct a single headless Chrome driver synchronously.

    Imports are local so the rest of the package can be imported without
    Selenium installed.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    return webdriver.Chrome(options=options)


class SeleniumPool:
    """Fixed-size pool of Chrome WebDriver instances."""

    def __init__(self, size: int = 3, headless: bool = True) -> None:
        if size < 1:
            raise ValueError(f"pool size must be >= 1, got {size}")
        self._size = size
        self._headless = headless
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=size)
        self._initialised = False

    async def initialise(self) -> None:
        if self._initialised:
            return
        for _ in range(self._size):
            driver = await asyncio.to_thread(_new_chrome_driver, self._headless)
            await self._queue.put(driver)
        self._initialised = True

    async def shutdown(self) -> None:
        while not self._queue.empty():
            driver = await self._queue.get()
            await asyncio.to_thread(driver.quit)
        self._initialised = False

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        if not self._initialised:
            await self.initialise()
        driver = await self._queue.get()
        try:
            yield driver
        finally:
            await self._queue.put(driver)

    async def fetch(self, url: str, timeout_seconds: float = 20.0) -> str:
        """Navigate to ``url`` and return the rendered page source."""
        async with self.acquire() as driver:
            def _go() -> str:
                driver.set_page_load_timeout(timeout_seconds)
                driver.get(url)
                return driver.page_source
            return await asyncio.to_thread(_go)
