# WikiStreams 프로젝트 평가 결과

> 작성일: 2026-03-12
> 기준 문서: `docs/EVALUATION_KITS.md`
> 아키텍처: Kappa Architecture (Stream-only)
> 데이터 흐름: `Wikimedia SSE → Producer → Redpanda → QuestDB Consumer → QuestDB (TTL 5d) → Grafana / Reporter → Slack / S3 Exporter → S3`
> 이전 평가: `docs/evaluation_result/EVALUATION_RESULT_260303.md` (2026-03-03)

---

## 이전 평가 대비 주요 변경사항

| 항목 | 260303 | 260312 |
|------|--------|--------|
| 메시지 버스 | Apache Kafka (KRaft) | **Redpanda** (-802 MiB RAM) |
| OLAP 엔진 | ClickHouse | **QuestDB 9.3.3** (ILP + REST, TTL 5d) |
| 로그 수집 | Grafana Alloy + Loki | **제거** (-257 MiB RAM) |
| 알림 채널 | Discord | **Slack** (Reporter + Resource Monitor) |
| Datalake | 없음 | **S3 Exporter 신규** (Parquet/Snappy, Hive 파티션) |
| SLO 체계 | 비공식 | **11개 SLO 정의·대시보드·알림** (QuestDB 기반) |
| SLO 지표 저장 | Loki (P1/P7) | **`producer_slo_metrics` QuestDB 테이블** |
| 리소스 메트릭 저장 | 없음 (메모리만) | **`resource_metrics` QuestDB 테이블** |
| 캐시 TTL (missing) | 24시간 | **3시간** (빠른 재시도) |
| QuestDB 메모리 제한 | 없음 | **1,100 MiB `mem_limit`** |
| 단위 테스트 | 미기재 | **276개** (외부 의존성 없음) |
| 스택 전체 RAM | 4,043 MiB | **947 MiB** (-77%) |
| 배포 환경 | 미기재 | **AWS EC2 t4g.small** (Graviton3, ARM64, 2 GiB) |

---

## 1. Data Source System Evaluation

### 데이터 원천의 본질적인 특징

**원천:** Wikimedia SSE(Server-Sent Events) 스트림 (`https://stream.wikimedia.org/v2/stream/recentchange`)

IoT 스웜과 유사하게 끊임없이 이벤트가 흘러드는 **외부 공개 스트리밍 API**다. 연결이 끊기면 해당 구간의 이벤트는 복구 불가능하므로 Redpanda + Exponential Backoff 재연결 구조를 채택하였다.

**현황:** `collector.py`의 `WikimediaCollector` 클래스가 SSE 구독, 배치 버퍼링, 재연결을 89줄로 처리. 이전 평가에서 완료된 리팩토링 구조를 그대로 유지한다.

---

### 데이터 보존 기간

Wikimedia SSE 스트림은 **일시적(ephemeral)**이다. 연결이 끊기면 해당 구간 이벤트는 복구 불가능하며 백필이 불가능하다.

**현황:**
- Exponential Backoff 재연결 (2s → 60s 상한)
- Docker Compose `restart: on-failure` 자동 복구
- QuestDB `wikimedia_events` 테이블: **TTL 5일** 자동 삭제
- S3 Exporter: 매일 01:00 UTC QuestDB 데이터를 Parquet으로 **S3 장기 보관** (이전 평가 대비 신규)

**여전히 미구현:** 스트림 중단 시 처리량 급감 알림. Resource Monitor가 컨테이너 자원 이상을 감지하나, 데이터 유입 자체 중단(Events/min 급감)을 감지하는 파이프라인 레벨 알림은 없다. 단, QuestDB 기반 SLO 대시보드에서 P5(처리량) 시각화로 수동 확인은 가능하다.

---

### 데이터 생성 속도

전 세계 24시간 편집 이벤트, **~1,000 events/min** 수준. 단일 Python Producer + Redpanda 단일 브로커로 처리 가능한 볼륨이다.

**현황:** `batch_size=500`, `batch_timeout=10s`. SLO P5 처리량 목표(≥800/min) 대비 실측 ~1,000/min으로 여유 있다. Redpanda 도입으로 Kafka 대비 메모리 -802 MiB, CPU 오버헤드 감소.

---

### 데이터 일관성 및 품질

**구현 완료:**
- `models.py`: Pydantic v2 `WikimediaEvent` 스키마 검증, 실패 시 DLQ 격리
- `extra="allow"`: 미정의 필드 보존, 미래 호환성 확보
- QuestDB Consumer: `type=log`(관리 이벤트), `domain=canary`(헬스체크) 사전 드롭

**이전 대비 개선:** ClickHouse의 `kafka_skip_broken_messages = 1000`(조용한 데이터 손실 가능성)이 QuestDB 전환으로 제거됨. QuestDB Consumer가 명시적으로 이벤트를 처리하므로 손실 경로가 줄었다.

---

### 에러 발생 빈도 및 대응

| 오류 유형 | 대응 |
|---------|------|
| HTTP 오류 (SSE 연결 실패) | 지수 백오프 + 자동 재연결 |
| JSON 파싱 오류 | 경고 로그 후 스킵 |
| Pydantic 검증 실패 | DLQ 라우팅 |
| Redpanda 전송 실패 | DLQ 라우팅 (3회 재시도) |
| QuestDB ILP 전송 실패 | 500건 배치 or 5초 타임아웃, 재시도 |

---

### 데이터 중복 여부

SSE 재연결 시 이벤트 중복 수신 가능성 존재. **명시적 중복 제거 로직 미구현** 상태 (이전 평가와 동일).

**평가:** QuestDB MergeTree에서도 중복 방지 기본 보장이 없다. Reporter의 `fetcher.py`는 Q-ID 기반 **크로스 랭귀지 중복 제거**(`_deduplicate_by_qid`)를 분석 레이어에서 수행하여 집계 품질을 보완하고 있다.

---

### 지연 도착(Late-arriving) 데이터

SSE 스트림 특성상 발행 즉시 수신 구조이므로 지연 도착 문제는 미미하다. Watermark 개념 미적용.

**이전 대비:** Kafka Materialized View의 오프셋 관리 복잡성이 Redpanda + 별도 QuestDB Consumer 구조로 교체되어 인제스천 경로가 명확해졌다.

---

### 스키마 구조

| 필드 | 타입 | 비고 |
|------|------|------|
| `ts` | TIMESTAMP | QuestDB 지정 시간 컬럼 (PARTITION BY DAY) |
| `event_time` | TIMESTAMP | 원본 이벤트 타임스탬프 |
| `title` | VARCHAR | Q-ID 포함 가능 |
| `server_name` | VARCHAR | 위키 서버 (예: en.wikipedia.org) |
| `wiki_type` | VARCHAR | edit/new/categorize |
| `namespace` | INT | 위키 네임스페이스 |
| `user` | VARCHAR | 편집자 (IP 포함 가능) |
| `bot` | BOOLEAN | 봇 여부 |
| `comment` | VARCHAR | 편집 요약 |
| `wikidata_label` | VARCHAR | Enrichment 필드 |
| `wikidata_description` | VARCHAR | Enrichment 필드 |

단일 소스, 단일 스트림. 조인 불필요. QuestDB는 시계열 특화 DB로 PARTITION BY DAY + TTL 5일 설정으로 분석 쿼리 패턴에 최적화.

---

### 스키마 변경 대처

Pydantic 모델이 Data Contract 역할을 하며, `extra="allow"`로 신규 필드 추가에 유연하게 대응. QuestDB 스키마는 `questdb_consumer` 초기 기동 시 자동 생성(코드 관리).

**미구현:** 공식 Schema Registry 미도입. 필수 필드 제거/타입 변경 시 DLQ 급증 → 자동 대응 프로세스 없음.

---

### 데이터 수집 주기

실시간 스트리밍(Continuous). 이벤트 발생 즉시 수집 → Redpanda → QuestDB Consumer → QuestDB 자동 인제스천.

---

### 원천 시스템 성능 영향도

읽기 전용 SSE 구독. Wikidata API는 배치(50개 청크) + SQLite **30일 캐시**로 호출 최소화 (missing/빈 레이블은 3시간 TTL). Reporter의 Wikipedia REST API 및 Google News RSS 호출은 동기식 I/O 기반.

---

### 업스트림 의존 관계

```
Wikimedia SSE ──→ Producer ──→ Redpanda ──→ QuestDB Consumer ──→ QuestDB
                      ↑                                               ↓
              Wikidata API (Enrichment)              Grafana / Reporter / S3 Exporter
                                                              ↑
                                          Wikipedia REST API / Google News RSS
```

Wikidata API 다운 시 Enrichment 실패 → DLQ 라우팅, 주 파이프라인 지속 (Degraded Mode). Wikimedia SSE 다운 시 수집 중단.

---

### 데이터 품질 검사

**구현 완료:**
- Pydantic 스키마 검증 + DLQ 격리
- Grafana SLO 대시보드: DLQ 비율(R1), 처리량(P5), 캐시 히트율(P7), 배치 처리 시간(P1) 시각화
- Grafana Producer Performance 대시보드: 처리량(Events/min) 모니터링
- Resource Monitor: EMA z-score 기반 CPU/메모리/I/O 이상 감지 → Slack 알림 (warning z≥3.0, critical z≥4.0)
- 절댓값 가드: CPU 20%, 메모리 70%, I/O 50MB/s 이중 조건

**여전히 미구현:** Events/min 급감 자동 알림 (컨테이너 이상이 아닌 데이터 볼륨 이상 감지).

---

## 2. Storage System Evaluation

### 읽기/쓰기 속도 적합성

| 스토리지 | 역할 | 쓰기 패턴 | 읽기 패턴 | 적합성 |
|---------|------|---------|---------|------|
| **Redpanda** | 메시지 버퍼 | 실시간 고속 스트림 쓰기 | 순차 오프셋 읽기 | ✅ 최적 |
| **QuestDB** | 시계열 OLAP | ILP 배치 인제스천 | 시계열 집계 쿼리 | ✅ 최적 |
| **SQLite** | Wikidata 캐시 + Resource Monitor 베이스라인 | Upsert | Key-value 조회 | ⚠️ Scale-out 불가 |
| **JSON 파일** | Reporter 저장소 | 일 1회 덮어쓰기 | 로드 후 Slack 발송 | ✅ 목적에 적합 |
| **S3 (Parquet)** | Datalake 장기 보관 | 일 1회 Parquet 업로드 | DuckDB 등 애드혹 쿼리 | ✅ 콜드 아카이브 최적 |

**이전 대비 개선:**
- ClickHouse(-1,756 MiB) → QuestDB: 메모리 대폭 절감 + ILP 인제스천으로 Consumer 구조 단순화
- Kafka(-802 MiB) → Redpanda: Kafka 호환 유지하며 메모리/CPU 오버헤드 감소
- S3 Datalake 추가: TTL 5일 이후 데이터 영구 보관 경로 확보

---

### 다운스트림 병목 여부

**잠재적 병목:**
1. **Wikidata API 동기식 I/O**: `enricher.py`의 API 호출이 배치 처리를 블로킹. AsyncIO 리팩토링은 여전히 Pending.
2. **Reporter의 동기식 외부 API 호출**: Wikipedia REST API, Google News RSS 호출이 동기식.
3. **SQLite 단일 연결**: Producer 1개 인스턴스에서는 문제없으나 Scale-out 불가.
4. **QuestDB mmap 특성**: OS 페이지 캐시(mmap) 기반 — 콜드 리드(72h+ 조회)는 swap-backed page fault로 느려질 수 있으나 OOM이 아닌 성능 저하 수준에서 머문다. `mem_limit: 1100m` + Docker 기본 `memswap = 2× limit` (2,200m 총 사용 가능)으로 안정적.

---

### 스토리지 기술 적합성

- **Redpanda (KRaft)**: 메시지 큐 목적에 적합. Kafka 호환 유지하며 JVM 오버헤드 없이 경량 운영.
- **QuestDB**: 시계열 OLAP 워크로드 최적. ILP 고속 인제스천, SAMPLE BY 시계열 집계, TTL + PARTITION BY DAY. p99 쿼리 52ms → 9~16ms로 개선.
- **S3 (Parquet/Snappy)**: 장기 보관 콜드 데이터. Hive 파티셔닝으로 DuckDB 등 다양한 쿼리 엔진에서 재사용 가능.
- **JSON 파일 스토리지**: Reporter 빌드/발행 분리(`build_and_save` / `publish_saved`)를 위한 간단한 영속화 계층.

---

### 확장성

| 컴포넌트 | 현재 설정 | 확장 경로 |
|---------|---------|---------|
| Redpanda | 1 브로커, 단일 노드 | 파티션 수 증가, 브로커 추가 |
| QuestDB | 단일 노드, mem_limit 1,100m | 엔터프라이즈 클러스터 전환 |
| SQLite | 단일 파일 DB | Redis로 교체 (여전히 Pending) |
| Producer | 단일 컨테이너 | Scale-out 시 분산 캐시 필요 |
| S3 Datalake | Parquet/Snappy, Hive 파티셔닝 | EMR/Athena 연결로 대규모 분석 확장 가능 |

---

### SLA 충족 여부

- Redpanda → QuestDB 인제스천 지연: ~9s (SLO D1 ≤30s 대비 ✅)
- QuestDB p99 쿼리 응답: 9~16ms (SLO P3 ≤200ms 대비 ✅)
- Reporter 쿼리 응답: 초 단위
- 홈랩 환경이므로 공식 SLA 미정의. `restart: always/on-failure`로 자동 복구.

---

### 메타데이터 캡처

**구현 완료:**
- DLQ 메시지: `error`, `failed_at`, `source_topic`, `retry_count` 메타데이터 포함
- Reporter JSON: `generated_at`, `prompt_style` 포함
- S3 Parquet: Hive 파티셔닝(`year/month/day`) 메타데이터 자동 구조화
- `producer_slo_metrics`: `ts`, `batch_size`, `valid`, `batch_processing_seconds`, `cache_hit_rate_pct` 시계열 기록
- `resource_metrics`: `ts`, `container`, `cpu_pct`, `mem_pct`, `mem_mb`, `block_read_mb`, `block_write_mb` 기록

**미구현:** 공식 데이터 카탈로그, 스키마 변경 이력 추적, 데이터 리니지 자동 추적.

---

### 스토리지 유형 및 스키마 정책

| 스토리지 | 유형 | 스키마 정책 |
|---------|------|----------|
| Redpanda | 메시지 큐 | 스키마 없음 (JSON raw) |
| QuestDB | 시계열 OLAP | 강제 적용 (Consumer 초기화 코드로 관리) |
| SQLite | Key-Value 캐시 | 고정 스키마 |
| JSON 파일 | 파일 스토리지 | dataclass 기반 구조화 |
| S3 Parquet | Data Lake | Schema-on-read (PyArrow 스키마 정의) |

---

### 데이터 거버넌스 / 법령 준수

- Wikimedia CC BY-SA 공개 데이터. 특별한 데이터 주권 이슈 없음.
- 편집자 IP 주소가 `user` 필드에 포함될 수 있으나 PII 마스킹 미구현 (이전 평가와 동일).
- **QuestDB TTL 5일**: 데이터 수명 주기 관리가 스키마 레벨에서 자동화.
- **S3 Parquet 장기 보관**: TTL 만료 데이터를 Datalake에 영구 보관함으로써 분석 연속성 확보.

---

## 3. Data Ingestion System Evaluation

### 데이터 재사용 가능성

Redpanda 토픽(`wikimedia.recentchange`) 하나를 QuestDB Consumer가 소비. 추가 Consumer Group을 붙여 다른 분석 목적에 재사용 가능한 구조.

---

### 내결함성

**구현된 내결함성:**
- Collector: HTTP 오류 시 지수 백오프(2s→60s) 재연결
- Sender: Redpanda 전송 실패 시 DLQ 라우팅 (3회 재시도)
- QuestDB Consumer: 500건 배치 or 5초 타임아웃, `type=log`/`domain=canary` 사전 드롭
- Docker: `restart: on-failure` / `restart: always` 자동 재시작

**미구현:**
- Wikimedia 서버 완전 중단 시 누락 이벤트 복구 불가
- Exactly-once 미보장 (at-least-once 수준)

---

### 수집 목적지 및 파이프라인

```
Wikimedia SSE
  → [Producer: batch(500/10s)] → Redpanda(wikimedia.recentchange)
                                            ↓
                                  [QuestDB Consumer]    [DLQ Topic]
                                            ↓
                                  QuestDB(wikimedia_events)  ← TTL 5d
                                            ↓
                              Grafana / Reporter / S3 Exporter
                                                        ↓
                                              S3 Datalake (Parquet)
```

이전 대비: ClickHouse Kafka Engine + Materialized View → 별도 Python QuestDB Consumer로 전환. ILP(포트 9009) 고속 인제스천을 활용하며, `_should_skip()` 로직으로 노이즈 이벤트를 Consumer 레벨에서 드롭.

---

### 데이터 접근 빈도

- **QuestDB**: Reporter가 일 1회 대량 집계 쿼리, Grafana가 실시간 조회(10s~30s refresh)
- **SQLite 캐시**: 배치마다 Q-ID 조회 (초~수십 초 단위)
- **S3 Parquet**: 일 1회 쓰기, 애드혹 쿼리 시 읽기 (콜드 데이터)
- **Reporter reports/ 볼륨**: 날짜별 JSON 보관, 특정 날짜 재발송 가능

---

### 데이터 포맷

| 구간 | 포맷 |
|------|------|
| Wikimedia SSE | JSON (UTF-8) |
| Redpanda 메시지 | JSON (UTF-8) |
| QuestDB 인제스천 | ILP (InfluxDB Line Protocol, 포트 9009) |
| DLQ 메시지 | JSON + metadata wrapper |
| Reporter 저장소 | JSON (dataclasses.asdict) |
| S3 Datalake | Parquet (Snappy 압축, Hive 파티셔닝) |

JSON 수집 → ILP 인제스천 → Parquet 아카이빙. 바이너리 포맷(Avro/Protobuf) 및 Schema Registry 미도입.

---

### 스트리밍 vs 배치 평가

| 항목 | 평가 |
|------|------|
| 스트리밍 선택 근거 | 편집 이벤트는 발생 즉시 의미 있는 데이터. Grafana 실시간 대시보드 가치 |
| 스트리밍 비용 | Docker Compose 자체 운영, 월 ~$15(t4g.small + EBS) |
| Exactly-once | 미보장 (at-least-once). Redpanda + QuestDB Consumer 모두 at-least-once |
| 도구 선택 | Redpanda: JVM 없이 Kafka 호환 + 경량. 홈랩 규모에서 최적 선택 |
| Reporter 배치 처리 | 일 1회 집계 쿼리 → Claude Haiku 호출 → Slack 발송. 비용 효율적 |
| S3 Exporter 배치 | 일 1회 Parquet 변환 → S3. 24개 시간 청크 처리로 메모리 효율적 |

---

## 4. Data Transformation System Evaluation

### 변환 비용 및 ROI

| 변환 단계 | 비용 | ROI |
|---------|------|-----|
| 스키마 검증 (Pydantic) | CPU 미미 | 데이터 품질 보장 → 높음 |
| Wikidata Enrichment | 네트워크 I/O + SQLite | Q-ID → 가독성 레이블 변환 → 높음 |
| QuestDB SAMPLE BY 집계 | DB 컴퓨팅 | 실시간 대시보드 분석 → 높음 |
| Claude Haiku 호출 | API 비용 (일 1회) | 트렌드 서사화 + Top5 다양성 선정 → 높음 |
| Q-ID 기반 중복 제거 | 병렬 API 호출 | 다국어 편집 집계 정확도 향상 → 높음 |
| EMA z-score 이상 감지 | CPU 미미 | 컨테이너 이상 선제 감지 → 높음 |
| Parquet 변환 (Snappy) | PyArrow 컴퓨팅 | Datalake 장기 보관 + 범용 분석 → 높음 |
| SLO 지표 QuestDB 기록 | ILP 쓰기 미미 | SLO 대시보드 + 알림 기반 → 높음 |

모든 변환이 명확한 목적과 ROI를 가진다.

---

### 변환의 단순성 및 독립성

단일 책임 원칙(SRP)이 전체 코드베이스에 일관되게 적용됨.

| 모듈 | 책임 |
|------|------|
| `collector.py` | SSE 연결 + 배치 버퍼링 (89줄) |
| `models.py` | 스키마 검증 |
| `enricher.py` | Wikidata 레이블 Enrichment |
| `cache.py` | SQLite 캐시 (3-way TTL: 정상 30일 / missing 3시간 / 빈 레이블 3시간) |
| `sender.py` | Redpanda 발행 + DLQ 라우팅 |
| `fetcher.py` | QuestDB 쿼리 + 외부 API 데이터 수집 |
| `builder.py` | Claude Haiku 호출 + JSON 파싱 |
| `publisher.py` | Slack 메시지 구성 + 전송 |
| `storage.py` | 보고서 JSON 저장/로드 |
| `detector.py` | z-score 이상 감지 로직 |
| `alerter.py` | Slack 알림 전송 + 쿨다운 |
| `baseline.py` | EMA + Welford online variance (SQLite 영속화) |
| `s3_exporter/main.py` | QuestDB → Parquet → S3 (24개 청크) |

---

### 비즈니스 규칙 구현

| 비즈니스 규칙 | 구현 위치 |
|-------------|---------|
| Q-ID 이벤트만 Enrichment | `enricher.py` (정규식) |
| 캐시 미스 시에만 API 호출 | `enricher.py` + `cache.py` |
| 정상 엔티티 캐시 30일 TTL | `cache.py` |
| missing/빈 레이블 엔티티 캐시 3시간 TTL | `cache.py` |
| 검증 실패 이벤트 DLQ 격리 | `main.py` |
| 한국어 우선 → 영어 fallback | `enricher.py` |
| 봇 제외 실제 편집만 Top5 집계 | `fetcher.py` QuestDB 쿼리 |
| Q-ID 기반 크로스 랭귀지 중복 제거 | `fetcher.py` `_deduplicate_by_qid()` |
| `type=log` / `domain=canary` 이벤트 드롭 | `questdb_consumer/_should_skip()` |
| 스파이크: 최근 15분 vs 이전 60분 비율 | `fetcher.py` QuestDB 쿼리 |
| 전일 대비 순위 변화(rank_change) | `fetcher.py` |
| Claude가 Top5 주제 다양성 선정 | `builder.py` `selected_indices` |
| 설명 없는 문서: Claude가 보완 | `builder.py` `descriptions` |
| 컨테이너 이상: 720 샘플(2시간) 이후 감지 | `detector.py` |
| 알림 쿨다운 1시간 (반복 알림 방지) | `alerter.py` |
| QuestDB 이벤트 TTL 5일 | QuestDB Consumer 스키마 초기화 |
| Parquet Hive 파티셔닝 (year/month/day) | `s3_exporter/main.py` |
| SLO 지표 배치마다 QuestDB 기록 | `producer/main.py` → `producer_slo_metrics` |

---

## 5. Undercurrents (횡단 관심사)

### 5-1. Security

| 항목 | 상태 | 비고 |
|------|------|------|
| 최소 권한 원칙 | ⚠️ 부분 | Grafana `GF_AUTH_ANONYMOUS_ENABLED=true` — EC2 내부망 전용(SSH 터널링)이므로 허용 범위 |
| 환경변수 기반 시크릿 관리 | ✅ | API Key, Webhook URL을 `.env`로 관리 |
| 데이터 암호화 | ❌ | 전송/저장 중 암호화 미적용 |
| PII 마스킹 | ❌ | `user` 필드에 IP 주소 포함 가능, 마스킹 없음 |
| Docker socket 마운트 | ⚠️ | `resource-monitor`가 `/var/run/docker.sock` 마운트 — 컨테이너 탈출 위험, 홈랩 허용 범위 |
| QuestDB 인증 | ⚠️ | HTTP 포트(9000, 8812) 내부망 전용. EC2 Security Group으로 외부 차단 |
| S3 접근 권한 | ✅ | IAM Role 기반 (EC2 인스턴스 프로파일) |
| Grafana 외부 공개 | ⚠️ | 현재 SSH 터널링으로만 접근. 공개 시 Cloudflare Tunnel 권장 |

**전반 평가:** EC2 인스턴스가 SSH 터널링으로만 접근되므로 이전 평가 대비 외부 노출 위험이 낮다. 외부 공개 전 Grafana 인증 활성화 필수.

---

### 5-2. Data Management

| 항목 | 상태 | 비고 |
|------|------|------|
| 데이터 품질 (Accuracy) | ✅ | Pydantic 검증 + DLQ |
| 데이터 품질 (Completeness) | ✅ | QuestDB Consumer 명시적 처리로 조용한 손실 경로 제거 |
| 데이터 품질 (Timeliness) | ✅ | 실시간 스트리밍, lag ~9s |
| Data Lineage | ⚠️ | DLQ 메타데이터로 부분 추적, 공식 리니지 도구 없음 |
| Data Lifecycle | ✅ | QuestDB TTL 5일 + S3 Parquet 장기 보관 (이중 계층) |
| Data Modeling | ✅ | 시계열 쿼리 패턴에 맞는 QuestDB PARTITION BY DAY + 정렬 설계 |
| Metadata | ⚠️ | DLQ/Reporter JSON/S3 파티션에 부분 메타데이터, 공식 카탈로그 없음 |
| Ethics & Privacy | ❌ | IP 주소 PII 마스킹 미구현 |

---

### 5-3. DataOps

**자동화:**
- GitHub Actions CI: Lint(flake8) + 포맷(black) + 단위 테스트 (PR/push 자동 실행)
- GitHub Actions CI: 통합/E2E 테스트 (main 브랜치 push 시 자동 실행)
- Docker Compose `restart: always/on-failure`: 서비스 자동 복구
- APScheduler: Reporter 일 09:00 KST 자동 발송, S3 Exporter 일 01:00 UTC 자동 실행

**Observability:**
- **Grafana 대시보드 4종**: Producer Performance, WikiStreams Analytics, WikiStreams SLO, Resources Monitor
- **SLO 대시보드 (11개)**: A2/A3/P1/P3/P5/P7/R1/D1/D2/CAP1/CAP2 — 전부 QuestDB 기반 (이전 Loki 의존 제거)
- **Resource Monitor**: EMA(Welford online variance) z-score 기반 CPU/메모리/I/O 이상 감지 → Slack 알림
- **이전 Loki/Alloy 제거**: CPU 57.3% 절감, Swap 700 MiB → 205 MiB

**Incident Response:**
- Resource Monitor: 이상 감지 즉시 Slack 알림 (쿨다운 1시간, 반복 알림 방지)
- SLO 알림: Grafana Alerting으로 SLO 위반 시 알림 가능
- MTTD: Grafana 대시보드 + Slack 알림으로 선제 감지 가능
- MTTR: `docker compose build <service> && up -d`로 서비스 재배포 단순함

**여전히 미구현:**
- 데이터 처리량(Events/min) 급감 자동 알림
- CI Smoke(PR) / Full E2E(merge) 이원화

---

### 5-4. Data Architecture

**설계 원칙 준수 평가:**

| 원칙 | 상태 | 비고 |
|------|------|------|
| 조직 규모·스킬셋에 맞는 도구 선택 | ✅ | 4단계 경량화로 월 $15 단일 호스트에서 현업 수준 파이프라인 구현 |
| 모듈형 설계 (컴포넌트 교체 가능) | ✅ | Producer/Reporter/Monitor/S3Exporter 독립 배포 |
| 비용·운영 간소화 균형 | ✅ | 스택 RAM -77%(4,043→947 MiB), CPU -57.3% 달성 |
| 전 구간 설계 일관성 | ✅ | SSE → Redpanda → QuestDB → Grafana/Slack/S3 흐름 일관 |
| 데이터 계층 분리 | ✅ | Hot(QuestDB 5일) + Cold(S3 Parquet 영구) 이중 계층 확보 |

**특기 사항:** 4단계 경량화(Kafka→Redpanda, ClickHouse→QuestDB, Loki/Alloy 제거)를 통해 t4g.small(2 GiB RAM)에서 안정 운영 가능한 아키텍처를 완성했다. SLO 지표를 QuestDB로 통합하여 외부 로그 수집 스택 없이도 완전한 Observability를 구현한 점이 핵심 설계 결정이다.

---

### 5-5. Orchestration

| 항목 | 상태 |
|------|------|
| 고가용성 | ⚠️ 단일 노드 Docker Compose (홈랩 수용 범위) |
| 스케줄링 | ✅ APScheduler (Reporter 09:00 KST, S3 Exporter 01:00 UTC) + Docker `restart` 정책 |
| 데이터 의존성 관리 | ⚠️ 명시적 DAG 없음, 서비스 간 `depends_on`으로 제한적 관리 |
| 장애 시 Failover | ⚠️ `restart: on-failure` 단순 재시작, 복잡한 Failover 전략 없음 |

**전반 평가:** 홈랩 파이프라인으로서 현재 복잡도에서는 Airflow/Dagster 불필요. 서비스 수(현재 7개)가 추가되거나 의존 관계가 복잡해지면 재평가 필요.

---

### 5-6. Software Engineering

| 항목 | 상태 | 비고 |
|------|------|------|
| **단위 테스트** | ✅ 완료 | **276개** (Producer, Reporter, Resource Monitor, S3 Exporter 전 모듈, 외부 의존성 없음) |
| **통합 테스트** | ✅ 완료 | Redpanda, SQLite, Wikipedia API 실제 연동 |
| **E2E 테스트** | ✅ 완료 | Producer→Redpanda→QuestDB 전체 흐름 |
| **SLO 검증 테스트** | ✅ 완료 | `pytest -m slo` (운영 환경 전용) |
| **CI 파이프라인** | ✅ 완료 | GitHub Actions (Lint + Unit + Integration/E2E) |
| **IaC** | ✅ 완료 | Docker Compose + QuestDB 스키마 자동 초기화 + Grafana provisioning YAML |
| **포맷/린트** | ✅ 완료 | black + flake8 CI 강제 |
| **오픈소스 활용** | ✅ 완료 | 상용 서비스 미사용, 전 스택 오픈소스 |
| **AsyncIO** | ❌ Pending | 동기식 I/O 병목 (enricher, fetcher) |

---

## 6. 종합 평가 요약

### 구현 완료 항목

| 항목 | 상태 | 이전 평가 대비 |
|------|------|-------------|
| 실시간 스트리밍 수집 (SSE) | ✅ | 유지 |
| 스키마 검증 (Pydantic) | ✅ | 유지 |
| Dead Letter Queue | ✅ | 유지 |
| Wikidata Enrichment + TTL 캐시 | ✅ | missing TTL 24h → 3h 개선 |
| **Redpanda 메시지 버스** | ✅ | **Kafka 대체, -802 MiB** |
| **QuestDB 시계열 DB** | ✅ | **ClickHouse 대체, -1,756 MiB** |
| **QuestDB ILP Consumer** | ✅ | **ClickHouse Kafka Engine 대체** |
| **Loki/Alloy 제거** | ✅ | **SLO 지표 QuestDB 이관, -257 MiB** |
| **S3 Exporter (Parquet Datalake)** | ✅ | **신규 구현** |
| **SLO 11개 정의·대시보드·알림** | ✅ | **신규 구현 (QuestDB 기반)** |
| **`producer_slo_metrics` 테이블** | ✅ | **신규 구현** |
| **`resource_metrics` 테이블** | ✅ | **신규 구현** |
| **Grafana 대시보드 4종** | ✅ | **Resources Monitor + SLO 대시보드 추가** |
| **알림 채널: Slack** | ✅ | **Discord 대체** |
| **EC2 t4g.small 안정 운영** | ✅ | **스택 RAM 947 MiB / 2,048 MiB (46%)** |
| Reporter (Claude Haiku + Slack) | ✅ | 유지 (Discord → Slack) |
| Resource Monitor (이상 감지 + 알림) | ✅ | min_samples 30 → 720(2h) 강화 |
| 단위 / 통합 / E2E 테스트 | ✅ | **276개** (S3 Exporter 테스트 추가) |
| GitHub Actions CI | ✅ | 유지 |

---

### 여전히 개선 필요한 항목

| 항목 | 우선순위 | 이유 |
|------|---------|------|
| AsyncIO 리팩토링 | 중 | 동기식 Wikidata API(enricher) + 외부 API(fetcher) 병목 |
| SQLite → Redis | 중 | Producer Scale-out 시 캐시 공유 불가 |
| 데이터 처리량 급감 알림 | 중 | Events/min 급감 시 파이프라인 이상 자동 감지 불가 |
| D2 SLO 목표 재검토 | 중 | 레이블 보강률 78~80% 경계 (Wikidata 구조적 한계) |
| 중복 이벤트 제거 | 낮 | 재연결 시 잠재적 중복 (Reporter 레이어에서 부분 보완) |
| PII 마스킹 (`user` 필드 IP) | 낮 | 퍼블릭 배포 전 필요 |
| CI Smoke/Full E2E 이원화 | 낮 | PR 단계 빠른 피드백 개선 |
| Grafana 인증 활성화 | 낮 | 외부 공개 시 필수 (현재 SSH 터널링으로 내부망만 접근) |

---

### 아키텍처 성숙도 평가

```
데이터 수집    ████████████ 완성도 높음 (재연결·배치·DLQ 완비)
데이터 품질    ██████████░░ 검증/DLQ 구현, 처리량 급감 알림 미흡
데이터 저장    ████████████ QuestDB TTL + S3 Datalake 이중 계층 완성
데이터 변환    ████████░░░░ 동기식 I/O 병목 여전히 개선 필요
모니터링/알림  ████████████ SLO 11개 + Resource Monitor + Slack 알림 완비
가치 전달      ████████████ Reporter(Claude+Slack) + S3 Datalake 신규 완성
테스트         ████████████ 276개 단위 테스트 + SLO 검증 테스트 완비
```

**전반 평가:** 이전 평가 대비 아키텍처 완성도가 최고 수준에 도달했다. 4단계 경량화(Kafka→Redpanda, ClickHouse→QuestDB, Loki/Alloy 제거, S3 Datalake 추가)를 통해 **월 $15(t4g.small) 단일 호스트**에서 현업 수준 파이프라인을 구현했다는 점이 핵심 성과다.

특히 Loki/Alloy를 제거하고 SLO 지표를 QuestDB로 이관한 결정은 기술 부채를 줄이면서도 Observability를 오히려 강화한 사례다. 11개 SLO를 정의하고 대시보드와 알림을 갖춘 것은 홈랩 프로젝트의 운영 성숙도를 크게 높인다.

프로덕션 수준으로 끌어올리기 위한 남은 과제는 **AsyncIO 리팩토링(성능)**, **처리량 이상 감지(신뢰성)**, **D2 SLO 목표 재조정(데이터 품질)** 세 가지다.
