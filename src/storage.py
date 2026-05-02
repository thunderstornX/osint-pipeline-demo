"""
PostgreSQL storage layer with batched inserts and content-addressed dedup.

The schema (see ``docker/init.sql``) declares
``content_hash CHAR(64) UNIQUE``. We INSERT with ``ON CONFLICT (content_hash)
DO NOTHING`` so that re-runs are idempotent: the same payload normalised
twice produces the same SHA-256 and the second insert is a no-op without
raising an exception.

The connection pool is async (asyncpg) and configurable via env vars.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import asyncpg

from src.normaliser import NormalisedRecord

log = logging.getLogger(__name__)


# Single-statement bulk insert via unnest, with RETURNING so we can
# count exactly how many rows survived ON CONFLICT DO NOTHING.
_BULK_INSERT_SQL = """
    WITH ins AS (
        INSERT INTO records (source, content_hash, fields, raw_excerpt)
        SELECT * FROM UNNEST($1::text[], $2::text[], $3::jsonb[], $4::text[])
        ON CONFLICT (content_hash) DO NOTHING
        RETURNING 1
    )
    SELECT COUNT(*) FROM ins
"""


@dataclass
class StorageStats:
    attempted: int = 0
    inserted: int = 0      # rows actually persisted (post-dedup)
    duplicates: int = 0    # rows skipped because content_hash already existed


class Storage:
    """Thin async wrapper around an asyncpg pool."""

    def __init__(self, dsn: str, batch_size: int = 500) -> None:
        self._dsn = dsn
        self._batch_size = batch_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self, min_size: int = 1, max_size: int = 10) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn, min_size=min_size, max_size=max_size,
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator["Storage"]:
        await self.connect()
        try:
            yield self
        finally:
            await self.close()

    async def insert_batch(self, records: list[NormalisedRecord]) -> StorageStats:
        """Insert a batch with ON CONFLICT DO NOTHING and return real counts.

        Splits the input into chunks of ``self._batch_size`` so the
        UNNEST array length stays modest on very large runs.
        """
        if self._pool is None:
            raise RuntimeError("Storage.connect() must be called before insert_batch")

        stats = StorageStats(attempted=len(records))
        if not records:
            return stats

        async with self._pool.acquire() as conn:
            for chunk_start in range(0, len(records), self._batch_size):
                chunk = records[chunk_start:chunk_start + self._batch_size]
                sources = [r.source for r in chunk]
                hashes = [r.content_hash for r in chunk]
                fields = [json.dumps(r.fields, sort_keys=True) for r in chunk]
                excerpts = [r.raw_excerpt for r in chunk]
                inserted_now = await conn.fetchval(
                    _BULK_INSERT_SQL, sources, hashes, fields, excerpts,
                )
                stats.inserted += int(inserted_now or 0)

        stats.duplicates = stats.attempted - stats.inserted
        return stats

    async def count(self) -> int:
        if self._pool is None:
            raise RuntimeError("Storage.connect() must be called before count")
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM records")
