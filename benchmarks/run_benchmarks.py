#!/usr/bin/env python3
"""
Reproducible throughput benchmark for the pipeline.

Runs a local aiohttp mock server with a controlled per-request latency
(default 50 ms), then issues N requests using:

  * sync_baseline  -- sequential requests.get() one at a time
  * async_5/10/20  -- aiohttp with 5/10/20-worker concurrency

For each strategy we record wall time, throughput (requests/second), peak
RSS during the run (resource.getrusage), and any failures. Results are
written to ``benchmarks/results.csv`` and printed as a summary table.

Why a mock server?
------------------
Running the benchmark against real public APIs would (a) hammer rate-limited
endpoints, violating provider ToS, (b) introduce network jitter that
contaminates the comparison, and (c) make results un-reproducible. A
local mock with a fixed sleep gives a stable baseline that is unambiguous
about what is being measured: the pipeline's HTTP-fan-out efficiency, not
the upstream API's variability.

Usage
-----
    python -m benchmarks.run_benchmarks [--requests 100] [--latency-ms 50]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import resource
import statistics
import sys
import time
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import aiohttp
from aiohttp import web

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_CSV = REPO_ROOT / "benchmarks" / "results.csv"


@dataclass
class BenchResult:
    strategy: str
    requests: int
    workers: int
    wall_seconds: float
    requests_per_second: float
    peak_rss_kb: int
    failures: int


# ---------------------------------------------------------------------------
# Mock server: every GET sleeps for `latency` seconds then returns a tiny JSON
# payload. Emulates a slow upstream API without external dependencies.
# ---------------------------------------------------------------------------
async def _make_mock_app(latency_seconds: float) -> web.Application:
    counter = {"n": 0}

    async def handler(_: web.Request) -> web.Response:
        counter["n"] += 1
        await asyncio.sleep(latency_seconds)
        return web.json_response({"id": counter["n"], "ok": True})

    app = web.Application()
    app.router.add_get("/", handler)
    return app


@asynccontextmanager
async def _mock_server(port: int, latency_seconds: float) -> AsyncIterator[str]:
    app = await _make_mock_app(latency_seconds)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Sync baseline (urllib, one at a time) -- run in a thread so the mock server
# can keep serving on the same event loop.
# ---------------------------------------------------------------------------
def _sync_baseline(url: str, count: int) -> tuple[int, int]:
    """Returns (success, failure) counts."""
    success = failures = 0
    for _ in range(count):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                resp.read()
                if 200 <= resp.status < 300:
                    success += 1
                else:
                    failures += 1
        except Exception:
            failures += 1
    return success, failures


async def _async_runner(url: str, count: int, workers: int) -> tuple[int, int]:
    """Issue `count` requests concurrent-bounded to `workers` workers."""
    success = failures = 0
    sem = asyncio.Semaphore(workers)
    timeout = aiohttp.ClientTimeout(total=10)
    connector = aiohttp.TCPConnector(limit=workers)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async def fetch_one() -> bool:
            async with sem:
                try:
                    async with session.get(url) as resp:
                        await resp.read()
                        return 200 <= resp.status < 300
                except Exception:
                    return False

        outcomes = await asyncio.gather(*(fetch_one() for _ in range(count)))
    success = sum(1 for ok in outcomes if ok)
    failures = count - success
    return success, failures


def _peak_rss_kb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _summarise(strategy: str, count: int, workers: int,
               wall: float, success: int, failures: int) -> BenchResult:
    rps = success / wall if wall > 0 else 0.0
    return BenchResult(
        strategy=strategy, requests=count, workers=workers,
        wall_seconds=round(wall, 4),
        requests_per_second=round(rps, 2),
        peak_rss_kb=_peak_rss_kb(),
        failures=failures,
    )


async def _run_all(count: int, latency_ms: float) -> list[BenchResult]:
    results: list[BenchResult] = []
    latency_seconds = latency_ms / 1000.0

    async with _mock_server(port=18080, latency_seconds=latency_seconds) as url:
        # Sync baseline: in a thread so it doesn't block the event loop
        # (the mock server is on the same loop).
        print(f"[sync_baseline]  count={count} latency={latency_ms}ms ...", flush=True)
        started = time.monotonic()
        success, failures = await asyncio.to_thread(_sync_baseline, url, count)
        results.append(_summarise(
            "sync_baseline", count, 1, time.monotonic() - started, success, failures))

        for workers in (5, 10, 20):
            label = f"async_{workers}"
            print(f"[{label}] count={count} workers={workers} ...", flush=True)
            started = time.monotonic()
            success, failures = await _async_runner(url, count, workers)
            results.append(_summarise(
                label, count, workers, time.monotonic() - started, success, failures))

    return results


def _write_csv(results: list[BenchResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["strategy", "requests", "workers", "wall_seconds",
                          "requests_per_second", "peak_rss_kb", "failures"])
        for r in results:
            writer.writerow([r.strategy, r.requests, r.workers, r.wall_seconds,
                             r.requests_per_second, r.peak_rss_kb, r.failures])


def _print_table(results: list[BenchResult]) -> None:
    cols = ["strategy", "requests", "workers", "wall_s", "req/s", "RSS_kb", "failed"]
    print()
    print("{:<16} {:>9} {:>8} {:>9} {:>8} {:>9} {:>7}".format(*cols))
    print("-" * 76)
    for r in results:
        print("{:<16} {:>9} {:>8} {:>9.2f} {:>8.2f} {:>9} {:>7}".format(
            r.strategy, r.requests, r.workers,
            r.wall_seconds, r.requests_per_second, r.peak_rss_kb, r.failures))

    # Speedup of fastest async strategy vs sync baseline
    sync = next((r for r in results if r.strategy == "sync_baseline"), None)
    fastest_async = max((r for r in results if r.strategy.startswith("async_")),
                        key=lambda r: r.requests_per_second, default=None)
    if sync and fastest_async and sync.requests_per_second > 0:
        speedup = fastest_async.requests_per_second / sync.requests_per_second
        print()
        print(f"  Fastest async strategy: {fastest_async.strategy} "
              f"@ {fastest_async.requests_per_second:.1f} req/s")
        print(f"  Sync baseline:          {sync.requests_per_second:.2f} req/s")
        print(f"  Measured speedup:       {speedup:.2f}x")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline throughput benchmark")
    parser.add_argument("--requests", type=int, default=100,
                        help="Number of requests per strategy (default: 100)")
    parser.add_argument("--latency-ms", type=float, default=50.0,
                        help="Mock-server per-request latency (default: 50)")
    parser.add_argument("--output", default=str(RESULTS_CSV))
    args = parser.parse_args(argv)

    results = asyncio.run(_run_all(args.requests, args.latency_ms))
    _write_csv(results, Path(args.output))
    _print_table(results)
    print(f"\nResults written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
