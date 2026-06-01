# osint-pipeline-demo

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20480442.svg)](https://doi.org/10.5281/zenodo.20480442)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An asynchronous Python reference pipeline for high-throughput OSINT data
collection — combining `aiohttp` connection pooling, per-source token-bucket
rate limiting, regex-based field normalisation with SHA-256 content
addressing, and batched PostgreSQL writes using `ON CONFLICT DO NOTHING` for
idempotent re-runs.

Described in [`paper/paper.pdf`](paper/paper.pdf): *An Asynchronous Python
Reference Pipeline for High-Throughput OSINT Data Collection: Design,
Benchmarks, and Idempotent Deduplication.*

---

## What this gives you

- **Async fan-out** with bounded worker concurrency via `asyncio.Semaphore`
- **Per-source token-bucket rate limiter** so each upstream's documented limit is respected
- **Content-addressed deduplication** via SHA-256 over canonically-serialised fields
- **Batched PostgreSQL inserts** via `UNNEST` + `ON CONFLICT (content_hash) DO NOTHING` — single round-trip per chunk, real `RETURNING`-based dedup count
- **Exponential backoff with jitter** on transient 5xx and connection errors
- **Optional Selenium pool** for JS-rendered sources (lazily initialised; not loaded if no source needs it)
- **Structured JSON logging** for pipeline-shipped log aggregation
- **Reproducible benchmarks** against a local mock server (no upstream API hammering during measurement)

---

## Real measured throughput

| Strategy | Workers | Wall (s) | Req/s | Speedup vs sync |
|---|---|---|---|---|
| `sync_baseline` | 1 | 5.14 | 19.46 | — |
| `async_5` | 5 | 1.04 | 95.89 | **4.93×** |
| `async_10` | 10 | 0.54 | 186.17 | **9.57×** |
| `async_20` | 20 | 0.28 | 351.11 | **18.04×** |

These numbers are from `benchmarks/run_benchmarks.py` against a local
mock server (50 ms upstream latency, 100 requests). Re-run on your machine:

```bash
python -m benchmarks.run_benchmarks --requests 100 --latency-ms 50
```

![benchmark output](paper/figures/benchmark.png)

---

## Test suite

30 tests, including 4 live-PostgreSQL integration tests. Run the unit subset:

```bash
python -m pytest tests/
```

![pytest output](paper/figures/pytest.png)

To run the integration tests too, start Postgres on port 5433 (so it doesn't
clash with a system Postgres on 5432) and re-run:

```bash
docker run -d --rm --name osint_pg \
  -e POSTGRES_USER=osint -e POSTGRES_PASSWORD=osint -e POSTGRES_DB=osint \
  -p 5433:5432 \
  -v "$(pwd)/docker/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" \
  postgres:16-alpine

PIPELINE_TEST_POSTGRES=1 \
  PIPELINE_DATABASE_URL=postgresql://osint:osint@localhost:5433/osint \
  python -m pytest tests/
```

---

## End-to-end run against real data

Run the pipeline against the public NIST NVD CVE feed (no auth required):

```bash
PIPELINE_DATABASE_URL=postgresql://osint:osint@localhost:5433/osint \
PIPELINE_SOURCES_FILE=config/sources_demo.yaml \
python -m src.pipeline
```

![pipeline run + dedup demo](paper/figures/pipeline_run.png)

The first run inserts 20 records. A second run against the same source
inserts 0 and detects 20 duplicates via the `content_hash` UNIQUE
constraint — proving the idempotency contract end-to-end.

---

## Repository layout

```
.
├── src/
│   ├── config.py           # pydantic-settings tunables, sources.yaml loader
│   ├── rate_limiter.py     # async token-bucket per source
│   ├── normaliser.py       # regex extractors + SHA-256 content hash
│   ├── storage.py          # asyncpg, batched UNNEST INSERT with ON CONFLICT
│   ├── collector.py        # aiohttp fan-out, exponential backoff retry
│   ├── selenium_pool.py    # optional headless Chrome pool
│   ├── pipeline.py         # orchestrator + JSON logging
│   └── cli.py              # `python -m src.cli` entry
├── config/
│   ├── sources.yaml        # 3 public sources: NVD, GitHub events, OpenCorporates
│   └── sources_demo.yaml   # NVD-only single-source demo
├── docker/
│   ├── docker-compose.yml  # postgres:16-alpine + pipeline service
│   ├── Dockerfile          # pipeline runtime image
│   └── init.sql            # records table with content_hash UNIQUE + GIN
├── tests/                  # 30 tests across 5 modules
├── benchmarks/
│   ├── run_benchmarks.py   # real benchmark harness (local mock + sync vs async)
│   └── results.csv         # current run output
├── paper/
│   ├── paper.tex           # IEEE 4-page paper
│   ├── paper.pdf
│   └── figures/            # 3 real terminal screenshots
└── scripts/
    └── render_terminal.py  # ANSI-aware terminal-to-PNG (used to generate figures)
```

---

## Configured sources

| Source | URL | Rate limit |
|---|---|---|
| NVD CVE 2.0 | `services.nvd.nist.gov/rest/json/cves/2.0` | 0.15 req/s (5 / 30 s without API key) |
| GitHub Events | `api.github.com/events` | 0.015 req/s (60 / hour unauth) |
| OpenCorporates | `api.opencorporates.com/v0.4/companies/search` | 0.5 req/s |

Each source has a list of named regex extractors that produce a record per
match. See [`config/sources.yaml`](config/sources.yaml) for the live config.

---

## Ethical use

The pipeline:

- **Respects published rate limits** via token-bucket pacing, defaulting to
  the most conservative tier each provider documents
- **Identifies itself** via a `User-Agent` header that points back to this
  repo
- **Stores no PII** by design — extractors are field-name-positive
- **Is for defensive research and educational use** consistent with
  [10.5281/zenodo.16924934](https://doi.org/10.5281/zenodo.16924934)

Do not use this pipeline against private targets, authentication-required
endpoints, or any source where the terms-of-service prohibit automated
access.

---

## Citing this work

```bibtex
@software{bhutto2026osintpipeline,
  author    = {Bhutto, Ali Murtaza},
  title     = {osint-pipeline-demo},
  year      = {2026},
  doi       = {10.5281/zenodo.20480442},
  url       = {https://github.com/thunderstornX/osint-pipeline-demo},
  orcid     = {0009-0007-2787-943X}
}
```

> The DOI above is the **concept DOI** — it always resolves to the latest release. Version 1.0.0 is archived at [10.5281/zenodo.20480443](https://doi.org/10.5281/zenodo.20480443).
Related research:
- [Legal and Ethical Framework for OSINT Investigations](https://doi.org/10.5281/zenodo.16924934)
- [OSINT Tools Framework](https://doi.org/10.5281/zenodo.16921792)

---

## License

MIT © 2026 Ali Murtaza Bhutto
