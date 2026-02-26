# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**WikiStreams** is a real-time data pipeline that monitors Wikimedia (Wikipedia, Wikidata) edit streams, enriches events with Wikidata labels/descriptions, and visualizes trends via Apache Superset. It uses a Kappa Architecture (stream-only, no batch layer) with all infrastructure managed via Docker Compose.

**Data Flow:**
```
Wikimedia SSE Stream → Producer (Python) → Apache Kafka → Apache Druid → Apache Superset
```

The Producer enriches events: if an event title is a Wikidata Q-ID (e.g. `Q12345`), it fetches the label and description from the Wikidata API and caches results in a local SQLite DB.

## Commands

### Infrastructure
```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down
```

### Testing
```bash
# All tests
PYTHONPATH=src pytest tests/

# Unit tests only (no external dependencies)
PYTHONPATH=src pytest tests/unit/

# Integration tests (requires running Kafka/Druid)
PYTHONPATH=src pytest tests/integration/ -m integration

# Single test file
PYTHONPATH=src pytest tests/unit/producer/test_enricher.py

# Single test
PYTHONPATH=src pytest tests/unit/producer/test_enricher.py::test_function_name
```

### Code Quality
```bash
# Format (auto-fix)
black .

# Check formatting without fixing
black --check .

# Lint
flake8 .
```

## Architecture

### Source Code (`src/producer/`)

All pipeline logic lives here. Modules are orchestrated by `main.py`:

- **`config.py`** — Central settings via `pydantic-settings`. All configuration flows through the `Settings` class. Priority: system env vars → `.env` file → code defaults. Key settings: `KAFKA_BROKER`, `KAFKA_TOPIC`, `KAFKA_DLQ_TOPIC`, `DATABASE_PATH`, `CACHE_TTL_SECONDS` (86400), `BATCH_SIZE` (500), `BATCH_TIMEOUT_SECONDS` (10.0).
- **`collector.py`** — Connects to Wikimedia SSE stream, batches events (500 events or 10s timeout), implements exponential backoff on network errors.
- **`enricher.py`** — Detects Q-IDs in event titles; checks SQLite cache first, then batch-fetches from Wikidata API for cache misses; adds `wikidata_label` and `wikidata_description` fields.
- **`cache.py`** — Thread-local SQLite connections. Table: `wikidata_cache(q_id, label, description, timestamp)`. TTL-based expiry: entries older than `CACHE_TTL_SECONDS` are treated as cache misses (lazy expiry).
- **`sender.py`** — Future-based Kafka publishing. On send failure, routes failed events to the DLQ topic (`KAFKA_DLQ_TOPIC`) with error metadata. Falls back to CRITICAL log if DLQ send also fails.

**When changing configuration**, update `src/producer/config.py` and add env vars there.
**When changing infrastructure**, update `docker-compose.yml` and `druid/ingestion-spec.json` together.

### Tests (`tests/`)

Three tiers with explicit isolation:
- **`tests/unit/`** — Fully mocked, no external dependencies. Uses `pytest-mock`, `tmp_path` fixtures.
- **`tests/integration/`** — Real SQLite + mocked Wikidata API (`test_enrichment_cache.py`), real Kafka broker (`test_producer_kafka_integration.py`), full Producer→Kafka→Druid flow (`test_e2e_pipeline.py`).

**E2E test isolation**: Each E2E test creates unique Kafka topics and Druid datasources, and tears them down after. Use the `e2e_context` fixture in `tests/conftest.py` for any new E2E tests.

### Infrastructure (`docker-compose.yml`)

15 services in total. Key services and ports:
- `kafka-kraft` :9092 — Message broker (KRaft mode, no Zookeeper for Kafka)
- `druid-router` :8888 — Unified Druid query interface
- `druid-broker` :8082 — Druid query layer
- `superset` :8088 — Visualization
- `grafana` :3000 — Monitoring dashboards
- `loki` :3100 — Log aggregation

Druid ingestion config is in `druid/ingestion-spec.json` — subscribes to the `wikimedia.recentchange` Kafka topic with hourly segment granularity.

### Monitoring (`monitoring/`)

Four Grafana dashboards auto-provisioned at startup:
- **Error Monitor** — System-wide error logs via Loki
- **Producer Performance** — Throughput (Events/Min) and Cache Hit Rate
- **Druid Monitor** — Query latency and segment handoff
- **Resources Monitor** — Per-container CPU/Memory via `docker-stats-logger` sidecar

### Superset Dashboard Management

Dashboards are managed as code. The source of truth is `superset/dashboards/wikimedia_dashboard.zip`, which is auto-imported on container startup via `superset/init_superset.sh`. Superset uses UUID-based deduplication (same UUID = overwrite).

**To update a dashboard**: Edit in Superset UI → Export as `.zip` → replace `superset/dashboards/wikimedia_dashboard.zip` → commit.
**Warning**: UI changes not exported will be lost on container restart.

## Roadmap (Pending Items)

- **DLQ Consumer**: DLQ routing is implemented; a consumer service for retry/reprocessing is pending.
- **Cache TTL (missing entities)**: Basic TTL is implemented; differential TTL for Wikidata `"missing"` responses is pending.
- **AsyncIO refactoring**: Current pipeline is synchronous; migrating to `asyncio`/`aiokafka` would improve throughput.
- **CI optimization**: Split into Smoke Tests (PR) and Full E2E (merge) stages.
