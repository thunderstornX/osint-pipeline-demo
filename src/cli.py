"""Thin CLI entry point. Defers to ``src.pipeline.main``."""

from __future__ import annotations

import sys

from src.pipeline import main as pipeline_main


def main() -> int:
    return pipeline_main()


if __name__ == "__main__":
    sys.exit(main())
