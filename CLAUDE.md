# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**WikiStreams**는 전 세계 Wikimedia(Wikipedia, Wikidata) 실시간 편집 스트림을 수집·분석하여 트렌드를 파악하는 홈랩 데이터 파이프라인입니다.

**전체 데이터 흐름:**
```
Wikimedia SSE Stream
  → Producer (Python)      # 이벤트 수집 + Wikidata 레이블 보강
  → Apache Kafka           # 메시지 버스
  → ClickHouse             # 실시간 적재 및 분석
  → Grafana                # 대시보드 시각화
  → Reporter (Python)      # 일일 트렌드 요약 → Discord
```

**사용 기술:**
- Python 3.11+, Apache Kafka (KRaft), ClickHouse, Grafana, Loki
- Claude Haiku API (Reporter), SQLite (Wikidata 캐시)
- Docker Compose (전체 인프라 IaC)

---

## 빠른 시작 (Quick Start)

### 1. 사전 요구사항

- Docker + Docker Compose
- `.env` 파일 생성 (아래 참조)

### 2. `.env` 설정

프로젝트 루트에 `.env` 파일을 생성합니다:

```bash
# Reporter에서 Claude API 호출 시 사용
ANTHROPIC_API_KEY="sk-ant-..."

# 리포트를 전송할 Discord Webhook URL
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."

# Reporter 프롬프트 스타일: 'default' 또는 'doro' (기본값: default)
# PROMPT_STYLE=doro
```

Reporter 없이 파이프라인만 사용한다면 `ANTHROPIC_API_KEY`와 `DISCORD_WEBHOOK_URL`은 생략해도 됩니다.

### 3. 전체 서비스 실행

```bash
docker compose up -d
```

초기 실행 시 이미지 빌드 + ClickHouse 초기화에 수십 초 소요됩니다.

### 4. 접속 주소

| 서비스 | 주소 | 용도 |
|---|---|---|
| Grafana | http://localhost:3000 | 대시보드 (Analytics + 모니터링) |
| ClickHouse HTTP | http://localhost:8123 | 직접 SQL 쿼리 |
| Kafka | localhost:9092 | 메시지 브로커 |

---

## 주요 명령어

### 인프라

```bash
# 전체 서비스 시작
docker compose up -d

# 특정 서비스만 재시작 (코드 변경 후)
docker compose build reporter && docker compose up -d reporter

# 서비스 로그 확인
docker compose logs -f reporter
docker compose logs -f producer

# 전체 중지
docker compose down
```

### Reporter — 즉시 실행

스케줄(매일 09:00 KST) 없이 리포트를 바로 발송합니다:

# 1단계: 데이터 수집 + Claude 호출 → JSON 저장 (비용 발생)
docker exec reporter python -c "
from reporter.main import build_and_save
build_and_save()
"

# 2단계: 저장된 JSON → Discord 전송 (API 호출 없음, 몇 초면 완료)
docker exec reporter python -c "
from reporter.main import publish_saved
publish_saved()
"

# 특정 날짜 재발송
docker exec reporter python -c "
from reporter.main import publish_saved
publish_saved('2026-03-01')
"

# 기존처럼 한번에 (스케줄러 동작 그대로)
docker exec reporter python -c "
from reporter.main import run_report
run_report()
"

### Reporter — 프롬프트 스타일 전환

`PROMPT_STYLE` 환경변수로 Claude에게 전달할 시스템 프롬프트를 교체합니다:

```bash
# .env 파일에서 설정
echo 'PROMPT_STYLE=doro' >> .env
docker compose up -d reporter   # 재시작 필요

# 또는 일회성 실행
docker exec -e PROMPT_STYLE=doro reporter python -c "
from reporter.main import run_report
run_report()
"
```

현재 사용 가능한 스타일:
- `default` — 한국어 뉴스 에디터 (객관적·간결)
- `doro` — 도로롱 캐릭터 (아가씨 말투 + 광기)

새 스타일 추가: `src/reporter/prompts/{이름}.py` 파일에 `SYSTEM_PROMPT`와 `build_user_message()` 정의 후 `PROMPT_STYLE={이름}` 설정.

### 테스트

```bash
# 단위 테스트 (외부 의존성 없음, 빠름)
PYTHONPATH=src /Users/yebin/Library/Python/3.11/bin/pytest tests/unit/ -v

# 특정 모듈만
PYTHONPATH=src pytest tests/unit/reporter/test_builder.py

# 통합 테스트 (Kafka, ClickHouse 실행 중 필요)
PYTHONPATH=src pytest tests/integration/ -m integration

# 전체
PYTHONPATH=src pytest tests/
```

### 코드 품질

```bash
black .          # 자동 포맷
black --check .  # 포맷 검사만
flake8 .         # 린트
```

---

## 아키텍처 상세

### Producer (`src/producer/`)

Wikimedia SSE 스트림을 구독하여 Kafka에 발행합니다. `main.py`가 오케스트레이션:

- **`config.py`** — `pydantic-settings` 기반 중앙 설정. 우선순위: 시스템 환경변수 → `.env` → 코드 기본값. 핵심 설정: `KAFKA_BROKER`, `KAFKA_TOPIC`, `KAFKA_DLQ_TOPIC`, `DATABASE_PATH`, `CACHE_TTL_SECONDS`(86400), `BATCH_SIZE`(500).
- **`collector.py`** — Wikimedia SSE 연결, 500개 or 10초 단위 배치, 지수 백오프(2s→60s) 재연결.
- **`enricher.py`** — 이벤트 타이틀이 Wikidata Q-ID(`Q12345`)이면 SQLite 캐시 조회 → 미스 시 Wikidata API 일괄 조회(50개 청크). `wikidata_label`, `wikidata_description` 필드 추가.
- **`cache.py`** — Thread-local SQLite. `wikidata_cache(q_id, label, description, timestamp, is_missing)`. TTL 기반 lazy expiry: 정상 엔티티 30일, missing 엔티티 24시간.
- **`sender.py`** — Future 기반 Kafka 발행. 실패 이벤트는 DLQ 토픽(`wikimedia.recentchange.dlq`)으로 라우팅.
- **`models.py`** — `WikimediaEvent` Pydantic 모델. 스키마 불일치 이벤트는 파이프라인 초입에서 DLQ 격리.

### DLQ Consumer (`src/dlq_consumer/`)

DLQ 토픽의 실패 이벤트를 최대 3회 재시도합니다. 초과 시 CRITICAL 로그 후 폐기.

### Reporter (`src/reporter/`)

매일 09:00 KST에 ClickHouse 데이터를 분석하여 Discord로 5개 Embed 리포트를 발송합니다.

파이프라인 순서:
```
fetch_report_data()          # ClickHouse 쿼리 + Wikipedia API
  → build_report()           # Claude Haiku: Top5 선정 + 섹션 생성 + 뉴스 키워드 추출
  → fetch_thumbnail()        # Wikipedia REST API: 1위 문서 썸네일
  → fetch_news_with_keywords()  # Google News RSS: 주제별 최대 3건
  → publish_report()         # Discord Webhook: 5 Embed 발송
```

모듈별 역할:
- **`fetcher.py`** — ClickHouse 통계 쿼리(편집 수, 활성 편집자, 봇 비율 등), Q-ID 기반 중복 제거(`ThreadPoolExecutor`), 스파이크·다국어 감지, Google News 스크래핑, Wikipedia Featured Article API.
- **`builder.py`** — Claude Haiku 호출. `_build_context()`로 데이터 요약 → `build_user_message()`로 프롬프트 구성 → JSON 파싱 → `selected_indices`로 Top5 재구성.
- **`prompts/`** — 프롬프트 패키지. `PROMPT_STYLE` 환경변수로 스타일 선택.
  - `default.py`: 기본 한국어 뉴스 에디터 프롬프트.
  - `doro.py`: 도로롱 캐릭터 프롬프트.
  - `__init__.py`: `importlib`으로 동적 로드.
- **`publisher.py`** — Discord Embed 5카드 구성 (헤드라인 → 숫자 브리핑 → Top5 문서 → 논쟁/반달리즘 → 교양코너).
- **`config.py`** — `ANTHROPIC_API_KEY`, `DISCORD_WEBHOOK_URL`, `PROMPT_STYLE`, `REPORT_HOUR_KST`(9).

### 인프라 (`docker-compose.yml`)

8개 서비스:

| 컨테이너 | 포트 | 역할 |
|---|---|---|
| `kafka-kraft` | 9092 | 메시지 브로커 (KRaft, ZooKeeper 불필요) |
| `clickhouse` | 8123, 9000 | OLAP DB (Kafka 테이블 엔진 내장) |
| `grafana` | 3000 | 대시보드 |
| `loki` | 3100 | 로그 집계 |
| `promtail` | — | 로그 수집 → Loki |
| `docker-stats-logger` | — | 컨테이너 CPU/메모리 로그 |
| `producer` | — | Wikimedia 이벤트 수집 |
| `dlq-consumer` | — | DLQ 재시도 소비자 |
| `reporter` | — | 일일 Discord 리포트 |

ClickHouse 스키마는 `clickhouse/init-db.sql`에 정의. Kafka 테이블 엔진이 `wikimedia.recentchange` 토픽을 구독하고, Materialized View가 `wikimedia.events` MergeTree에 자동 저장.

**설정 변경 시**: `src/producer/config.py` 수정 + `.env` 환경변수 추가.
**인프라 변경 시**: `docker-compose.yml` + `clickhouse/init-db.sql` 함께 수정.

### 모니터링 (`monitoring/`)

Grafana 대시보드 4종 (컨테이너 시작 시 자동 프로비저닝):

- **Error Monitor** — 전체 컨테이너 에러 로그 (Loki)
- **Producer Performance** — 처리량(Events/Min), 캐시 적중률, DLQ 현황
- **Resources Monitor** — 컨테이너별 CPU/메모리 (`docker-stats-logger` 사이드카)
- **WikiStreams Analytics** — 편집 트렌드, 상위 위키, 편집 유형, 실시간 트렌딩 문서

**대시보드 업데이트 방법**: Grafana UI에서 편집 → JSON으로 내보내기 → `monitoring/dashboards/` 파일 교체 → 커밋.

### 테스트 구조 (`tests/`)

```
tests/
├── unit/
│   ├── producer/        # enricher, cache, sender, collector, models, main
│   ├── dlq_consumer/    # DLQ 재시도 로직
│   └── reporter/        # fetcher, builder, publisher, prompts, main
└── integration/
    ├── test_enrichment_cache.py          # 실제 SQLite
    ├── test_producer_kafka_integration.py # 실제 Kafka
    ├── test_e2e_pipeline.py               # Producer→Kafka→ClickHouse 전체 흐름
    └── test_reporter_integration.py       # 실제 Wikipedia API, Google News RSS
```

- 단위 테스트: 완전한 mock, 외부 의존성 없음. `pytest-mock`, `tmp_path` 사용.
- E2E 테스트 격리: 고유 이벤트를 실제 토픽에 발행 → ClickHouse HTTP API 폴링으로 확인.

---

## 설정 레퍼런스

### Producer (`src/producer/config.py`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `KAFKA_BROKER` | `kafka-kraft:9092` | Kafka 브로커 주소 |
| `KAFKA_TOPIC` | `wikimedia.recentchange` | 메인 토픽 |
| `KAFKA_DLQ_TOPIC` | `wikimedia.recentchange.dlq` | 실패 이벤트 토픽 |
| `DATABASE_PATH` | `wikidata_cache.db` | SQLite 캐시 경로 |
| `CACHE_TTL_SECONDS` | `2592000` (30일) | 정상 Wikidata 캐시 TTL |
| `CACHE_MISSING_TTL_SECONDS` | `86400` (24시간) | missing 엔티티 캐시 TTL |
| `BATCH_SIZE` | `500` | 배치당 이벤트 수 |
| `BATCH_TIMEOUT_SECONDS` | `10.0` | 배치 타임아웃 |

### Reporter (`src/reporter/config.py`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | (필수) | Claude API 키 |
| `DISCORD_WEBHOOK_URL` | (필수) | Discord Webhook |
| `PROMPT_STYLE` | `default` | 프롬프트 스타일 (`default` / `doro`) |
| `REPORT_HOUR_KST` | `9` | 발송 시각 (KST, 0-23) |
| `CLICKHOUSE_HOST` | `clickhouse` | ClickHouse 호스트 |
| `CLICKHOUSE_PORT` | `8123` | ClickHouse HTTP 포트 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |

---

## Roadmap (Pending Items)

- **AsyncIO refactoring**: 현재 파이프라인은 동기 방식. `asyncio`/`aiokafka` 마이그레이션으로 처리량 개선 가능.
- **CI optimization**: Smoke Tests (PR) / Full E2E (merge) 단계 분리.
- **Promtail macOS fix**: `/var/lib/docker/containers` 마운트는 macOS Docker Desktop에서 불가. Docker socket API 전용 수집으로 전환 필요.
- **Reporter 스타일 런타임 전환**: 현재 환경변수로만 가능. Discord 명령어 또는 슬래시 커맨드로 실행 중 전환 지원 고려.
