"""Shared pytest fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def sources_yaml_path(repo_root: Path) -> Path:
    return repo_root / "config" / "sources.yaml"


@pytest.fixture
def has_postgres() -> bool:
    """True if a PostgreSQL is available at PIPELINE_DATABASE_URL.

    Tests that need a real DB are skipped when this is False so the suite
    still runs cleanly on a developer laptop without docker-compose up.
    """
    return os.environ.get("PIPELINE_TEST_POSTGRES") == "1"
