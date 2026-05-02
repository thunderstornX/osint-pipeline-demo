"""Config + sources.yaml loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import (
    PipelineSettings,
    SourceConfig,
    SourceFieldExtractor,
    SourcesFile,
    load_sources,
)


def test_settings_defaults_are_sensible() -> None:
    s = PipelineSettings()
    assert s.workers == 10
    assert s.selenium_drivers == 3
    assert s.batch_size == 500
    assert s.retry_max_attempts == 3
    assert "osint-pipeline-demo" in s.user_agent


def test_settings_workers_validated() -> None:
    with pytest.raises(Exception):
        PipelineSettings(workers=0)
    with pytest.raises(Exception):
        PipelineSettings(workers=999)


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_WORKERS", "25")
    monkeypatch.setenv("PIPELINE_BATCH_SIZE", "1000")
    s = PipelineSettings()
    assert s.workers == 25
    assert s.batch_size == 1000


def test_load_sources_parses_demo_file(sources_yaml_path: Path) -> None:
    sources = load_sources(sources_yaml_path)
    assert len(sources) == 3
    names = {s.name for s in sources}
    assert names == {"nvd_recent_cves", "github_public_events", "opencorporates_recent"}
    nvd = next(s for s in sources if s.name == "nvd_recent_cves")
    assert nvd.url.startswith("https://services.nvd.nist.gov")
    assert nvd.rate_limit_per_second > 0
    assert any(e.name == "cve_id" for e in nvd.extractors)


def test_source_rate_limit_must_be_positive() -> None:
    with pytest.raises(Exception):
        SourceConfig(name="x", url="https://example.invalid",
                     rate_limit_per_second=0, extractors=[])


def test_sources_file_round_trip() -> None:
    """Construct a SourcesFile programmatically and verify each source survives."""
    sf = SourcesFile(sources=[SourceConfig(
        name="x",
        url="https://example.invalid",
        rate_limit_per_second=1.0,
        extractors=[SourceFieldExtractor(name="k", regex=r"k=(\w+)")],
    )])
    assert sf.sources[0].name == "x"
    assert sf.sources[0].extractors[0].name == "k"
