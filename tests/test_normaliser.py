"""Normaliser determinism + extractor behaviour."""

from __future__ import annotations

import hashlib

from src.config import SourceConfig, SourceFieldExtractor
from src.normaliser import normalise


def _src(name: str = "demo", extractors: list[tuple[str, str]] | None = None) -> SourceConfig:
    return SourceConfig(
        name=name,
        url="https://example.invalid/data",
        rate_limit_per_second=1.0,
        use_selenium=False,
        extractors=[SourceFieldExtractor(name=n, regex=r) for n, r in (extractors or [])],
    )


def test_no_extractors_hashes_full_payload() -> None:
    src = _src(extractors=[])
    raw = b'{"hello":"world"}'
    records = normalise(src, raw)
    assert len(records) == 1
    assert records[0].source == "demo"
    expected_hash = hashlib.sha256(raw).hexdigest()
    assert records[0].content_hash == expected_hash


def test_extractors_zip_into_rows() -> None:
    src = _src(extractors=[
        ("cve", r'"id":"(CVE-\d{4}-\d+)"'),
        ("severity", r'"severity":"(LOW|MEDIUM|HIGH|CRITICAL)"'),
    ])
    raw = (
        b'[{"id":"CVE-2024-0001","severity":"HIGH"},'
        b'{"id":"CVE-2024-0002","severity":"MEDIUM"}]'
    )
    records = normalise(src, raw)
    assert len(records) == 2
    assert records[0].fields == {"cve": "CVE-2024-0001", "severity": "HIGH"}
    assert records[1].fields == {"cve": "CVE-2024-0002", "severity": "MEDIUM"}


def test_same_payload_same_hash() -> None:
    """Determinism: same input bytes + same extractors -> same hash."""
    src = _src(extractors=[("k", r'"k":"([^"]+)"')])
    raw = b'{"k":"value"}'
    h1 = normalise(src, raw)[0].content_hash
    h2 = normalise(src, raw)[0].content_hash
    assert h1 == h2


def test_field_order_does_not_change_hash() -> None:
    """Hash uses sort_keys, so {a,b} == {b,a}."""
    src1 = _src(extractors=[("a", r'"a":"([^"]+)"'), ("b", r'"b":"([^"]+)"')])
    src2 = _src(extractors=[("b", r'"b":"([^"]+)"'), ("a", r'"a":"([^"]+)"')])
    raw = b'{"a":"1","b":"2"}'
    assert normalise(src1, raw)[0].content_hash == normalise(src2, raw)[0].content_hash


def test_no_matches_returns_empty_list() -> None:
    src = _src(extractors=[("k", r'"NEVER_MATCHES":"([^"]+)"')])
    records = normalise(src, b'{"k":"value"}')
    assert records == []


def test_raw_excerpt_is_capped_at_256_chars() -> None:
    src = _src(extractors=[])
    long_payload = b"x" * 1000
    records = normalise(src, long_payload)
    assert len(records[0].raw_excerpt) == 256


def test_decodes_bytes_with_replacement_on_invalid_utf8() -> None:
    src = _src(extractors=[("k", r'"k":"([^"]+)"')])
    raw = b'\xff\xfe{"k":"value"}'  # invalid UTF-8 prefix
    records = normalise(src, raw)
    assert len(records) == 1
    assert records[0].fields == {"k": "value"}
