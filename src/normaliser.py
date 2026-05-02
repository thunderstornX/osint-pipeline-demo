"""
Normalise raw collector payloads into canonical records.

Each ``SourceConfig`` carries a list of named regex extractors applied to
the raw response body (or a JSON-stringified payload). Field values are
trimmed and joined into a stable record dict, then content-hashed with
SHA-256. The hash is the deduplication key in the storage layer.

Hash determinism: the same input bytes + same extractor list produce the
same hash, regardless of dict insertion order. This is enforced by sorting
the keys when serialising before hashing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from src.config import SourceConfig


@dataclass(frozen=True)
class NormalisedRecord:
    source: str
    fields: dict[str, str]
    content_hash: str
    raw_excerpt: str          # first 256 chars of raw payload (debugging)


def _stable_serialise(fields: dict[str, str]) -> bytes:
    """Sort keys so the same fields produce the same hash regardless of order."""
    return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()


def normalise(source: SourceConfig, raw: bytes | str) -> list[NormalisedRecord]:
    """Apply the source's extractors to a single raw payload.

    Returns a list because some sources (e.g. NVD) return multiple records
    per response. If a payload yields no extractor matches, an empty list
    is returned.
    """
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw

    # Compile each extractor once
    compiled = [(e.name, re.compile(e.regex)) for e in source.extractors]

    if not compiled:
        # No extractors: hash the entire payload as a single record.
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return [NormalisedRecord(
            source=source.name,
            fields={"raw": text[:1024]},
            content_hash=digest,
            raw_excerpt=text[:256],
        )]

    # Build per-extractor match lists, then zip into rows by index.
    matches_per_field: list[list[str]] = []
    for _, pattern in compiled:
        matches_per_field.append([m.strip() for m in pattern.findall(text)])

    if not any(matches_per_field):
        return []

    row_count = max(len(m) for m in matches_per_field)
    records: list[NormalisedRecord] = []
    for i in range(row_count):
        fields: dict[str, str] = {}
        for (name, _), matches in zip(compiled, matches_per_field):
            if i < len(matches):
                fields[name] = matches[i]
        if not fields:
            continue
        digest = hashlib.sha256(_stable_serialise(fields)).hexdigest()
        records.append(NormalisedRecord(
            source=source.name,
            fields=fields,
            content_hash=digest,
            raw_excerpt=text[:256],
        ))
    return records
