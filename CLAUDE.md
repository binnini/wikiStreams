# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**WikiStreams** is a real-time data pipeline that monitors Wikimedia (Wikipedia, Wikidata) edit streams, enriches events with Wikidata labels/descriptions, and visualizes trends via Grafana. It uses a Kappa Architecture (stream-only, no batch layer) with all infrastructure managed via Docker Compose.

**Data Flow:**
```
Wikimedia SSE Stream → Producer (Python) → Apache Kafka → ClickHouse → Grafana
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

# Integration tests (requires running Kafka/ClickHouse)
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
**When changing infrastructure**, update `docker-compose.yml` and `clickhouse/init-db.sql` together.

### Tests (`tests/`)

Two tiers with explicit isolation:
- **`tests/unit/`** — Fully mocked, no external dependencies. Uses `pytest-mock`, `tmp_path` fixtures.
- **`tests/integration/`** — Real SQLite + mocked Wikidata API (`test_enrichment_cache.py`), real Kafka broker (`test_producer_kafka_integration.py`), full Producer→Kafka→ClickHouse flow (`test_e2e_pipeline.py`).

**E2E test isolation**: Each E2E test sends a uniquely-identified event to the real `wikimedia.recentchange` topic and polls ClickHouse HTTP API until the event appears.

### Infrastructure (`docker-compose.yml`)

8 services in total. Key services and ports:
- `kafka-kraft` :9092 — Message broker (KRaft mode, no ZooKeeper)
- `clickhouse` :8123 — HTTP query interface, :9000 Native TCP
- `grafana` :3000 — Analytics dashboards + monitoring
- `loki` :3100 — Log aggregation

ClickHouse schema is defined in `clickhouse/init-db.sql` — Kafka engine table subscribes to `wikimedia.recentchange`, Materialized View streams data into the `wikimedia.events` MergeTree table.

### Monitoring (`monitoring/`)

Four Grafana dashboards auto-provisioned at startup:
- **Error Monitor** — System-wide error logs via Loki
- **Producer Performance** — Throughput (Events/Min) and Cache Hit Rate
- **Resources Monitor** — Per-container CPU/Memory via `docker-stats-logger` sidecar
- **WikiStreams Analytics** — Edit trends, top wikis, edit type distribution, top pages (ClickHouse)

### Grafana Dashboard Management

Dashboards are managed as code in `monitoring/dashboards/`. They are auto-provisioned via `monitoring/grafana-dashboards.yaml` on container startup.

**To update a dashboard**: Edit in Grafana UI → Export as JSON → replace the corresponding `.json` file in `monitoring/dashboards/` → commit.

## Roadmap (Pending Items)

- **AsyncIO refactoring**: Current pipeline is synchronous; migrating to `asyncio`/`aiokafka` would improve throughput.
- **CI optimization**: Split into Smoke Tests (PR) and Full E2E (merge) stages.
- **Promtail macOS fix**: `/var/lib/docker/containers` mount does not work on macOS Docker Desktop; switch to Docker socket API-only log collection.
