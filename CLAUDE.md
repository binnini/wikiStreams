# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**WikiStreams**는 전 세계 Wikimedia(Wikipedia, Wikidata) 실시간 편집 스트림을 수집·분석하여 트렌드를 파악하는 홈랩 데이터 파이프라인입니다.

**전체 데이터 흐름:**
```
Wikimedia SSE Stream
  → Producer (Python)        # 이벤트 수집 + Wikidata 레이블 보강 (SQLite 캐시)
  → Redpanda (Kafka-compat)  # 메시지 버스
  → QuestDB                  # 시계열 DB (TTL 5일)
  → Grafana                  # 대시보드 + SLO 모니터링 + 알림
  → Reporter (Python)        # 매일 09:00 KST 트렌드 요약 → Slack
  → S3 Exporter (Python)     # 매일 01:00 UTC Parquet → S3 Datalake
```

**사용 기술:**
- Python 3.11+, Redpanda (Kafka 호환), QuestDB 9.3.3, Grafana, Loki, Grafana Alloy
- Claude Haiku API (Reporter), SQLite (Wikidata 캐시 + Resource Monitor 베이스라인)
- PyArrow, Parquet(Snappy), AWS S3 (Datalake)
- Docker Compose (전체 인프라 IaC), AWS EC2 t3.small

---

## 빠른 시작 (Quick Start)

### 1. 사전 요구사항

- Docker + Docker Compose
- `.env` 파일 생성 (아래 참조)

### 2. `.env` 설정

```bash
# Reporter에서 Claude API 호출 시 사용
ANTHROPIC_API_KEY="sk-ant-..."

# 리포트 및 이상 감지 알림을 전송할 Slack Webhook URL
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
SLACK_ALERT_WEBHOOK_URL="https://hooks.slack.com/services/..."

# Reporter 프롬프트 스타일: 'default' 또는 'doro' (기본값: default)
# PROMPT_STYLE=doro
```

Reporter·알림 없이 파이프라인만 사용한다면 API 키와 Webhook은 생략 가능합니다.

### 3. 전체 서비스 실행

```bash
docker compose up -d
```

### 4. 접속 주소

| 서비스 | 주소 | 용도 |
|---|---|---|
| Grafana | http://localhost:3000 | 대시보드 (Analytics + SLO 모니터링) |
| QuestDB | http://localhost:9000 | SQL 콘솔 직접 쿼리 |
| Redpanda | localhost:9092 | Kafka 호환 메시지 브로커 |

---

## 주요 명령어

### 인프라

```bash
# 전체 서비스 시작
docker compose up -d

# 특정 서비스만 재빌드 후 재시작
docker compose build reporter && docker compose up -d reporter

# 서비스 로그 확인
docker compose logs -f reporter
docker compose logs -f producer
docker compose logs -f resource-monitor

# 전체 중지
docker compose down
```

### Reporter — 즉시 실행

```bash
# 1단계: 데이터 수집 + Claude 호출 → JSON 저장 (비용 발생)
docker exec reporter python -c "
from reporter.main import build_and_save
build_and_save()
"

# 2단계: 저장된 JSON → Slack 전송
docker exec reporter python -c "
from reporter.main import publish_saved
publish_saved()
"

# 특정 날짜 재발송
docker exec reporter python -c "
from reporter.main import publish_saved
publish_saved('2026-03-01')
"

# 한 번에 실행 (스케줄러 동작 그대로)
docker exec reporter python -c "
from reporter.main import run_report
run_report()
"
```

### Reporter — 프롬프트 스타일 전환

```bash
# .env 파일에서 설정
echo 'PROMPT_STYLE=doro' >> .env
docker compose up -d reporter   # 재시작 필요

# 일회성 실행
docker exec -e PROMPT_STYLE=doro reporter python -c "
from reporter.main import run_report
run_report()
"
```

현재 사용 가능한 스타일:
- `default` — 한국어 뉴스 에디터 (객관적·간결)
- `doro` — 도로롱 캐릭터 (아가씨 말투 + 광기)

새 스타일 추가: `src/reporter/prompts/{이름}.py`에 `SYSTEM_PROMPT`와 `build_user_message()` 정의 후 `PROMPT_STYLE={이름}` 설정.

### S3 Datalake

```bash
# S3 Exporter 활성화 (별도 profile)
docker compose --profile s3 up -d s3-exporter

# 특정 날짜 백필
docker exec -e EXPORT_DATE=2026-03-01 s3-exporter python main.py --once

# DuckDB로 과거 데이터 조회
duckdb -c "SELECT server_name, count(*) FROM read_parquet('s3://bucket/events/**/*.parquet') GROUP BY 1"
```

### SLO 데이터 수집 (로컬)

```bash
# EC2에서 데이터 수집 후 로컬로 다운로드 (SSH config: wikistreams)
./scripts/fetch_slo_data.sh

# 특정 기간 지정 (최대 5일, QuestDB TTL 한계)
./scripts/fetch_slo_data.sh --days 3
```

### 테스트

```bash
# 단위 테스트 (외부 의존성 없음, 빠름)
PYTHONPATH=src /Users/yebin/Library/Python/3.11/bin/pytest tests/unit/ -v

# 특정 모듈만
PYTHONPATH=src pytest tests/unit/producer/test_cache.py -v

# 통합 테스트 (Redpanda, QuestDB 실행 중 필요)
PYTHONPATH=src pytest tests/integration/ -m integration

# SLO 검증 테스트 (운영 환경에서)
PYTHONPATH=src pytest tests/integration/test_slo.py -v -m slo

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

Wikimedia SSE 스트림을 구독하여 Redpanda에 발행합니다. `main.py`가 오케스트레이션:

- **`config.py`** — `pydantic-settings` 기반 중앙 설정. 핵심 설정: `KAFKA_BROKER`(redpanda:9092), `KAFKA_TOPIC`, `BATCH_SIZE`(500), `BATCH_TIMEOUT_SECONDS`(10.0), `CACHE_TTL_SECONDS`(2592000 = 30일), `CACHE_MISSING_TTL_SECONDS`(10800 = 3시간), `CACHE_EMPTY_LABEL_TTL_SECONDS`(10800 = 3시간).
- **`collector.py`** — Wikimedia SSE 연결, 500개 or 10초 단위 배치, 지수 백오프(2s→60s) 재연결.
- **`enricher.py`** — 이벤트 타이틀이 Wikidata Q-ID(`Q12345`)이면 SQLite 캐시 조회 → 미스 시 Wikidata API 일괄 조회(50개 청크). `wikidata_label`, `wikidata_description` 필드 추가.
- **`cache.py`** — Thread-local SQLite. `wikidata_cache(q_id, label, description, timestamp, is_missing)`. 3-way TTL: 정상 엔티티 30일, missing/빈 레이블 엔티티 3시간.
- **`sender.py`** — Future 기반 Redpanda 발행. 실패 이벤트는 DLQ 토픽(`wikimedia.recentchange.dlq`)으로 라우팅.
- **`models.py`** — `WikimediaEvent` Pydantic 모델. 스키마 불일치 이벤트는 파이프라인 초입에서 DLQ 격리.

### QuestDB Consumer (`src/questdb_consumer/`)

Redpanda → QuestDB ILP(InfluxDB Line Protocol)로 이벤트를 적재합니다.
- `type=log`(관리 이벤트), `domain=canary`(헬스체크) 이벤트를 사전 드롭(`_should_skip()`).
- 500개 배치 or 5초 타임아웃으로 QuestDB ILP(포트 9009) 전송.
- 테이블 TTL 5일, 파티션 by DAY, 메모리 제한 1100 MiB.

### Resource Monitor (`src/resource_monitor/`)

컨테이너 CPU·메모리·I/O를 10초마다 수집하여 이상 감지 후 Slack 알림을 발송합니다.

- **`collector.py`** — `docker stats` API로 메트릭 수집.
- **`baseline.py`** — EMA + Welford online variance로 rolling 베이스라인 유지 (SQLite 저장).
- **`detector.py`** — z-score(warning ≥3.0, critical ≥4.0) + 절댓값 가드(CPU 20%, 메모리 70%, I/O 50MB/s) 이중 조건.
- **`alerter.py`** — Slack Webhook 발송. 컨테이너·메트릭별 cooldown 1시간.
- **`config.py`** — `SLACK_ALERT_WEBHOOK_URL`, `ANOMALY_THRESHOLD`(3.0), `CRITICAL_Z_SCORE`(4.0), `MIN_SAMPLES`(720 = 2시간분).

### Reporter (`src/reporter/`)

매일 09:00 KST에 QuestDB 데이터를 분석하여 Slack으로 리포트를 발송합니다.

파이프라인 순서:
```
fetch_report_data()           # QuestDB 쿼리 + Wikipedia API
  → build_report()            # Claude Haiku: Top5 선정 + 섹션 생성 + 뉴스 키워드 추출
  → fetch_thumbnail()         # Wikipedia REST API: 1위 문서 썸네일
  → fetch_news_with_keywords() # Google News RSS: 주제별 최대 3건
  → publish_report()          # Slack Webhook 발송
```

모듈별 역할:
- **`fetcher.py`** — QuestDB 통계 쿼리, Q-ID 기반 중복 제거, 스파이크·다국어 감지, Google News 스크래핑, Wikipedia Featured Article API.
- **`builder.py`** — Claude Haiku 호출. `selected_indices`로 Top5 재구성.
- **`prompts/`** — `PROMPT_STYLE` 환경변수로 스타일 선택. `importlib`으로 동적 로드.
- **`publisher.py`** — Slack 메시지 구성 및 발송.
- **`storage.py`** — 리포트 JSON 저장/로드 (`/app/reports/YYYY-MM-DD.json`).
- **`config.py`** — `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`, `PROMPT_STYLE`, `REPORT_HOUR_KST`(9).

### S3 Exporter (`src/s3_exporter/`)

매일 01:00 UTC에 QuestDB 데이터를 Parquet으로 변환하여 S3에 업로드합니다.
- 출력: `s3://{bucket}/events/year=YYYY/month=MM/day=DD/events.parquet`
- Hive 파티셔닝, Snappy 압축, 24개 시간 청크 처리.
- MinIO 지원 (로컬 개발).

### 인프라 (`docker-compose.yml`)

9개 서비스:

| 컨테이너 | 포트 | 역할 |
|---|---|---|
| `redpanda` | 9092 | 메시지 브로커 (Kafka 호환, KRaft) |
| `questdb` | 9000, 8812, 9009 | OLAP 시계열 DB |
| `grafana` | 3000 | 대시보드 + 알림 |
| `loki` | 3100 | 로그 집계 (retention 30일) |
| `alloy` | — | 로그 수집 → Loki (Docker socket API) |
| `questdb-consumer` | — | Redpanda → QuestDB ILP 적재 |
| `producer` | — | Wikimedia 이벤트 수집 |
| `resource-monitor` | — | CPU/메모리 이상 감지 + Slack 알림 |
| `reporter` | — | 일일 Slack 리포트 |
| `s3-exporter` | — | Parquet → S3 (optional, `--profile s3`) |

QuestDB 스키마는 questdb-consumer가 최초 기동 시 자동 생성.

**설정 변경 시**: 해당 모듈의 `config.py` 수정 + `.env` 환경변수 추가.
**인프라 변경 시**: `docker-compose.yml` 수정.

### 모니터링 (`monitoring/`)

Grafana 대시보드 4종 (컨테이너 시작 시 자동 프로비저닝):

- **Error Monitor** — 전체 컨테이너 에러 로그 (Loki)
- **Producer Performance** — 처리량(Events/Min), 캐시 적중률, 배치 처리 시간
- **Resources Monitor** — 컨테이너별 CPU/메모리 (`resource-monitor`)
- **WikiStreams SLO** — SLI/SLO 현황 (가용성·성능·신뢰성·데이터품질·용량)

**대시보드 업데이트**: Grafana UI에서 편집 → JSON 내보내기 → `monitoring/dashboards/` 파일 교체 → 커밋.

### 테스트 구조 (`tests/`)

```
tests/
├── unit/                    # 276개 단위 테스트 (완전한 mock, 외부 의존성 없음)
│   ├── producer/            # cache, collector, enricher, models, sender, main
│   ├── reporter/            # fetcher, builder, publisher, prompts, main
│   ├── resource_monitor/    # baseline, collector, detector, alerter
│   └── s3_exporter/         # main
└── integration/
    ├── test_enrichment_cache.py            # 실제 SQLite
    ├── test_producer_kafka_integration.py  # 실제 Redpanda
    ├── test_e2e_pipeline.py                # Producer→Redpanda→QuestDB 전체 흐름
    ├── test_reporter_integration.py        # 실제 Wikipedia API, Google News RSS
    └── test_slo.py                         # SLO 검증 (pytest -m slo, 운영 환경 전용)
```

핵심 테스트 패턴:
- httpx 모킹: `mocker.patch("module.httpx.Client", return_value=mock_cm)` — context manager mock
- Kafka 모킹: `mocker.patch("producer.sender.KafkaProducer")`
- Claude API 모킹: `mocker.patch("reporter.builder.anthropic.Anthropic")`
- SQLite 격리: `tmp_path` fixture + `monkeypatch`로 설정 경로 교체

---

## 설정 레퍼런스

### Producer (`src/producer/config.py`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `KAFKA_BROKER` | `redpanda:9092` | Redpanda 브로커 주소 |
| `KAFKA_TOPIC` | `wikimedia.recentchange` | 메인 토픽 |
| `KAFKA_DLQ_TOPIC` | `wikimedia.recentchange.dlq` | 실패 이벤트 토픽 |
| `DATABASE_PATH` | `/cache/wikidata_cache.db` | SQLite 캐시 경로 |
| `CACHE_TTL_SECONDS` | `2592000` (30일) | 정상 Wikidata 캐시 TTL |
| `CACHE_MISSING_TTL_SECONDS` | `10800` (3시간) | missing 엔티티 캐시 TTL |
| `CACHE_EMPTY_LABEL_TTL_SECONDS` | `10800` (3시간) | 빈 레이블 엔티티 캐시 TTL |
| `BATCH_SIZE` | `500` | 배치당 이벤트 수 |
| `BATCH_TIMEOUT_SECONDS` | `10.0` | 배치 타임아웃 |

### Reporter (`src/reporter/config.py`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | (필수) | Claude API 키 |
| `SLACK_WEBHOOK_URL` | (필수) | Slack Webhook (리포트 발송) |
| `PROMPT_STYLE` | `default` | 프롬프트 스타일 (`default` / `doro`) |
| `REPORT_HOUR_KST` | `9` | 발송 시각 (KST, 0-23) |
| `QUESTDB_HOST` | `questdb` | QuestDB 호스트 |
| `QUESTDB_PORT` | `9000` | QuestDB HTTP 포트 |

### Resource Monitor (`src/resource_monitor/config.py`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SLACK_ALERT_WEBHOOK_URL` | (필수) | Slack Webhook (이상 감지 알림 전용) |
| `MONITOR_TARGETS` | `producer,questdb,...` | 모니터링 대상 컨테이너 |
| `ANOMALY_THRESHOLD` | `3.0` | Warning z-score 임계값 |
| `CRITICAL_Z_SCORE` | `4.0` | Critical z-score 임계값 |
| `MIN_SAMPLES` | `720` | 감지 시작 최소 샘플 수 (2시간분) |
| `ALERT_COOLDOWN_SECONDS` | `3600` | 재발송 억제 시간 |

---

## SLO 현황 (v2 baseline 수집 중, 2026-03-10~)

| SLO | 목표 | v2 실측 | 판정 |
|---|---|---|---|
| A2 쿼리 성공률 | ≥ 99% | 수집 중 | 🔄 |
| A3 Reporter 발송 | 월 ≥ 27회 | 정상 | ✅ |
| P1 배치 처리 p95 | ≤ 2s | 0.95s | ✅ |
| P3 쿼리 응답 p99 | ≤ 200ms | 4~30ms | ✅ |
| P5 처리량 | ≥ 800/min | ~1,000/min | ✅ |
| P7 캐시 히트율 | ≥ 80% | p5=89% | ✅ |
| R1 DLQ 비율 | ≤ 1% | near-zero (인프라 장애 시에만 발생) | ✅ |
| D1 데이터 lag | ≤ 30s | ~9s | ✅ |
| D2 레이블 보강률 | ≥ 80% | ~79~88% (시간대별 편차) | ⚠️ 경계 |
| CAP1 QDB 메모리 | ≤ 880 MiB | ~285~500 MiB | ✅ |
| CAP2 Producer CPU | ≤ 70% | ~1~7% | ✅ |

> D2는 Wikidata의 구조적 한계(~20% Q-ID에 en/ko 레이블 없음)로 80% 달성이 어려움. 목표값 재검토 예정 (~2026-03-17).

SLO 데이터 수집: `./scripts/fetch_slo_data.sh` → `slo_export/` 디렉터리

---

## 운영 환경 (AWS EC2)

- **인스턴스**: t3.small (2 GiB RAM), AWS Seoul
- **SSH**: `ssh wikistreams` (`~/.ssh/config`에 등록됨)
- **주의**: EC2에서 무거운 프로세스(Node.js 등) 실행 금지 — 메모리 부족으로 OOM 발생

---

## Roadmap (Pending Items)

- **v2 baseline 확정**: 2026-03-17 이후 `pytest -m slo` 실행 및 SLO 수치 재측정.
- **SLO-D2 목표 재검토**: 레이블 보강률 78~80% 경계값 원인 분석 후 목표 조정.
- **4단계 경량화**: Loki/Alloy 제거 여부 결정 (운영 안정화 후).
- **CI 최적화**: Smoke Tests (PR) / Full E2E (merge) 단계 분리.
