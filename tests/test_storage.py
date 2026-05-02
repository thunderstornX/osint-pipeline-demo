"""Storage tests: dedup behaviour against a real PostgreSQL.

Skipped unless PIPELINE_TEST_POSTGRES=1 is set in the environment so that
laptop developers without docker-compose up can still run the rest of
the suite cleanly.

Run locally:
    docker-compose -f docker/docker-compose.yml up -d postgres
    PIPELINE_TEST_POSTGRES=1 \
        PIPELINE_DATABASE_URL=postgresql://osint:osint@localhost:5432/osint \
        pytest tests/test_storage.py -v
"""

from __future__ import annotations

import os

import pytest

from src.normaliser import NormalisedRecord
from src.storage import Storage


pytestmark = pytest.mark.skipif(
    os.environ.get("PIPELINE_TEST_POSTGRES") != "1",
    reason="PIPELINE_TEST_POSTGRES=1 required (live DB integration test)",
)


def _record(name: str, content_hash: str) -> NormalisedRecord:
    return NormalisedRecord(
        source=name,
        fields={"k": content_hash[:8]},
        content_hash=content_hash,
        raw_excerpt="raw",
    )


@pytest.fixture
async def storage() -> Storage:  # type: ignore[misc]
    dsn = os.environ.get("PIPELINE_DATABASE_URL",
                         "postgresql://osint:osint@localhost:5432/osint")
    s = Storage(dsn=dsn, batch_size=100)
    await s.connect()
    # Clear table for isolation
    async with s._pool.acquire() as conn:  # type: ignore[union-attr]
        await conn.execute("TRUNCATE records RESTART IDENTITY")
    try:
        yield s
    finally:
        await s.close()


async def test_insert_one_record(storage: Storage) -> None:
    h = "a" * 64
    stats = await storage.insert_batch([_record("src", h)])
    assert stats.attempted == 1
    assert stats.inserted == 1
    assert stats.duplicates == 0
    assert await storage.count() == 1


async def test_dedup_on_repeat_insert(storage: Storage) -> None:
    h = "b" * 64
    rec = _record("src", h)
    first = await storage.insert_batch([rec])
    second = await storage.insert_batch([rec])
    assert first.inserted == 1
    assert second.inserted == 0
    assert second.duplicates == 1
    assert await storage.count() == 1


async def test_mixed_duplicates_in_one_batch(storage: Storage) -> None:
    h1, h2 = "1" * 64, "2" * 64
    # Pre-seed one record
    await storage.insert_batch([_record("src", h1)])
    # Now batch with one duplicate (h1) and one new (h2)
    stats = await storage.insert_batch([_record("src", h1), _record("src", h2)])
    assert stats.attempted == 2
    assert stats.inserted == 1   # only h2
    assert stats.duplicates == 1
    assert await storage.count() == 2


async def test_empty_batch_is_a_no_op(storage: Storage) -> None:
    stats = await storage.insert_batch([])
    assert stats.attempted == 0
    assert stats.inserted == 0
    assert await storage.count() == 0
