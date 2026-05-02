"""
End-to-end pipeline: collector -> normaliser -> storage.

Wires the modules and emits structured JSON log lines suitable for
ingestion by a downstream log shipper (Filebeat, Vector, etc.).

Run as a module: ``python -m src.pipeline``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass

from src.collector import HTTPCollector
from src.config import PipelineSettings, SourceConfig, load_sources
from src.normaliser import normalise
from src.rate_limiter import MultiSourceLimiter
from src.storage import Storage, StorageStats

log = logging.getLogger("osint_pipeline")


@dataclass
class RunSummary:
    duration_seconds: float
    fetches_attempted: int
    fetches_succeeded: int
    records_normalised: int
    records_inserted: int
    records_duplicate: int


def _configure_logging() -> None:
    """Emit one JSON object per log record. Avoids adding any logging
    handlers when called more than once."""
    if logging.getLogger().handlers:
        return

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


async def run_pipeline(settings: PipelineSettings, sources: list[SourceConfig]) -> RunSummary:
    """Execute one full pipeline pass against the given sources."""
    rate_limiter = MultiSourceLimiter()
    for src in sources:
        rate_limiter.register(src.name, src.rate_limit_per_second)

    storage = Storage(dsn=settings.database_url, batch_size=settings.batch_size)
    started = time.monotonic()

    fetches_attempted = len(sources)
    fetches_succeeded = 0
    all_records = []

    async with storage.lifecycle(), HTTPCollector(settings, rate_limiter) as collector:
        async for fetch in collector.fetch_all(sources):
            fetches_succeeded += 1
            log.info("fetch ok source=%s status=%s bytes=%d attempt=%d",
                     fetch.source, fetch.status, len(fetch.body), fetch.attempt)
            source = next(s for s in sources if s.name == fetch.source)
            records = normalise(source, fetch.body)
            all_records.extend(records)

        stats: StorageStats = await storage.insert_batch(all_records)

    duration = time.monotonic() - started
    summary = RunSummary(
        duration_seconds=duration,
        fetches_attempted=fetches_attempted,
        fetches_succeeded=fetches_succeeded,
        records_normalised=len(all_records),
        records_inserted=stats.inserted,
        records_duplicate=stats.duplicates,
    )
    log.info("pipeline done duration=%.2fs ok=%d/%d records=%d inserted=%d dup=%d",
             summary.duration_seconds, summary.fetches_succeeded, summary.fetches_attempted,
             summary.records_normalised, summary.records_inserted, summary.records_duplicate)
    return summary


def main() -> int:
    _configure_logging()
    settings = PipelineSettings()
    sources = load_sources(settings.sources_file)
    summary = asyncio.run(run_pipeline(settings, sources))
    print(json.dumps(summary.__dict__, default=str))
    return 0 if summary.fetches_succeeded > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
