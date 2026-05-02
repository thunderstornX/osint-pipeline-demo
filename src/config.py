"""
Pipeline configuration: pydantic-settings reads tunables from
environment variables (or a `.env` file in the working directory) and
the source/source-pattern configuration from the YAML files in
``config/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceFieldExtractor(BaseModel):
    """A single named regex extractor applied to a fetched payload."""
    name: str
    regex: str


class SourceConfig(BaseModel):
    """One configured public data source."""
    name: str
    url: str
    rate_limit_per_second: float = Field(gt=0, le=100)
    use_selenium: bool = False
    extractors: list[SourceFieldExtractor] = Field(default_factory=list)


class SourcesFile(BaseModel):
    sources: list[SourceConfig]


class PipelineSettings(BaseSettings):
    """Runtime tunables -- environment variables override defaults."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PIPELINE_",
                                       env_file_encoding="utf-8")

    workers: Annotated[int, Field(ge=1, le=200)] = 10
    selenium_drivers: Annotated[int, Field(ge=1, le=20)] = 3
    batch_size: Annotated[int, Field(ge=1, le=10_000)] = 500
    retry_max_attempts: Annotated[int, Field(ge=0, le=10)] = 3
    retry_base_delay_seconds: Annotated[float, Field(gt=0, le=60)] = 0.5
    request_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 20.0
    user_agent: str = "osint-pipeline-demo/1.0 (+https://github.com/thunderstornX/osint-pipeline-demo)"

    database_url: str = "postgresql://osint:osint@localhost:5432/osint"
    sources_file: Path = Path("config/sources.yaml")

    @field_validator("sources_file")
    @classmethod
    def _resolve(cls, v: Path) -> Path:
        return v.expanduser().resolve()


def load_sources(path: Path) -> list[SourceConfig]:
    raw = yaml.safe_load(path.read_text())
    return SourcesFile(**raw).sources
