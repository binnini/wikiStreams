# WikiStreams 프로젝트 평가 결과

> 작성일: 2026-02-27
> 기준 문서: `docs/EVALUATION_KITS.md`
> 아키텍처: Kappa Architecture (Stream-only)
> 데이터 흐름: `Wikimedia SSE → Producer → Kafka → Druid → Superset`

---

## 1. Data Source System Evaluation

### 데이터 원천의 본질적인 특징

**원천:** Wikimedia SSE(Server-Sent Events) 스트림 (`https://stream.wikimedia.org/v2/stream/recentchange`)

Wikimedia의 실시간 편집 이벤트를 지속적으로 발행하는 **외부 공개 스트리밍 API**이다. IoT 디바이스 스웜과 유사하게 데이터가 끊임없이 흘러들어오는 구조이며, 연결이 끊기면 데이터 유실이 발생한다. 이에 맞게 Kafka와 지수 백오프(Exponential Backoff) 재연결 로직을 도입한 스트리밍 아키텍처를 채택하였다.

**현황:** `collector.py`에서 `httpx_sse` 라이브러리로 SSE 스트림을 구독하며, HTTP 오류 시 10초 간격으로 재연결을 시도한다.

---

### 데이터 보존 기간

Wikimedia SSE 스트림은 **일시적(ephemeral)**이다. 연결이 끊기는 순간 해당 시간대의 이벤트는 복구할 수 없으며, 백필(Backfill)이 불가능하다. 따라서 파이프라인은 스트림이 항상 살아있어야 한다는 전제 하에 설계되었다.

**현황:** `collector.py`에 지수 백오프 재연결 로직이 구현되어 있고, `sender.py`에 DLQ가 있으나, 스트림 자체가 끊긴 구간의 이벤트는 복구할 수 없다. Docker Compose의 `restart: on-failure` 정책이 유일한 안전망이다.

**개선 필요:** 스트림 중단 감지 시 알림(Alerting) 체계 도입이 필요하다.

---

### 데이터 생성 속도

Wikipedia와 Wikidata는 전 세계 편집자들이 24시간 기여하는 플랫폼으로, **초당 수 건~수십 건** 수준의 이벤트가 지속적으로 발생한다. 한국 시간 기준 낮 시간대에 스파이크가 있으며, 단순 Python 스크립트와 단일 Kafka 브로커로 처리 가능한 수준이다.

**현황:** `batch_size=500`, `batch_timeout=10s` 설정으로 배치 처리. 현재 Kafka 브로커 1대, Druid MiddleManager 1대 수준으로 현재 부하를 충분히 감당한다.

**미검증:** `docs/TODO.md`에 `k6`/`Locust`를 이용한 확장성 검증 리포트 작성이 Pending 상태로 남아 있다. 실제 처리 한계는 측정되지 않았다.

---

### 데이터 일관성 및 품질

Wikimedia API는 공개 외부 서비스이므로 스키마 변경, 필드 누락, 타입 불일치 등이 언제든 발생할 수 있다.

**현황 (구현 완료):**
- `src/producer/models.py`에 Pydantic v2 기반의 `WikimediaEvent` 스키마 검증 모델 구현
- 필수 필드: `title`, `server_name`, `type`, `namespace`, `timestamp`, `user`, `bot`
- 검증 실패 이벤트는 즉시 DLQ(`wikimedia.recentchange.dlq`)로 격리
- `extra="allow"` 설정으로 미정의 필드도 보존하여 미래 호환성 확보

---

### 에러 발생 빈도

SSE 스트림 특성상 네트워크 타임아웃, 연결 재설정 등이 주기적으로 발생한다.

**현황:**
- HTTP 오류: `collector.py`에서 캐치 후 지수 백오프 재연결
- JSON 파싱 오류: 경고 로그 후 해당 이벤트 스킵
- Kafka 전송 실패: `sender.py`에서 DLQ 라우팅, DLQ도 실패 시 CRITICAL 로그
- Grafana Error Monitor 대시보드에서 에러율 실시간 모니터링 가능

---

### 데이터 중복 여부

SSE 스트림은 연결 재시도 시 이벤트 중복 수신 가능성이 있다. 각 편집 이벤트는 고유한 `id` 필드를 가지나, 현재 파이프라인에서 명시적인 중복 제거(Deduplication) 로직은 구현되어 있지 않다.

**개선 필요:** Druid는 `rollup=false` 설정으로 모든 이벤트를 그대로 저장하므로, 재연결 시 중복 이벤트가 분석 결과에 영향을 줄 수 있다. 고유 ID 기반 Kafka 메시지 키 설정 또는 Druid 레벨 중복 필터링 검토가 필요하다.

---

### 지연 도착(Late-arriving) 데이터

SSE 스트림 특성상 발행 즉시 수신되는 구조이므로 지연 도착 문제는 미미하다. 다만 Consumer(Druid) 측에서 Kafka 오프셋 처리 지연이 발생할 수 있다.

**현황:** Druid 인제스천 스펙에서 `auto.offset.reset: latest`와 `useEarliestOffset: true`가 혼재하여 명확한 정책 정의가 필요하다. Watermark 개념은 현재 적용되지 않았다.

---

### 스키마 구조

Wikimedia RecentChange 이벤트의 주요 필드:

| 필드 | 타입 | 설명 |
|------|------|------|
| `title` | str | 편집된 문서 제목 (Q-ID 포함 가능) |
| `server_name` | str | 위키 서버명 (예: `ko.wikipedia.org`) |
| `type` | str | 이벤트 유형 (`edit`, `new`, `categorize` 등) |
| `namespace` | int | 위키 네임스페이스 |
| `timestamp` | int | Unix 타임스탬프 |
| `user` | str | 편집자 이름 |
| `bot` | bool | 봇 편집 여부 |
| `wikidata_label` | str? | 파이프라인 추가 필드 |
| `wikidata_description` | str? | 파이프라인 추가 필드 |

단일 소스의 단일 스트림이며, 조인이 필요 없다. Wikidata 레이블 조회만 별도 API 호출 후 필드 추가(Enrichment) 방식으로 처리된다.

---

### 스키마 변경 대처

현재 스키마 레지스트리(Confluent Schema Registry 등)는 도입되어 있지 않다. Pydantic 모델이 사실상 스키마 계약(Data Contract) 역할을 한다.

**현황:** `extra="allow"` 설정으로 새 필드가 추가되어도 파이프라인이 깨지지 않는다. 그러나 기존 필수 필드가 제거되거나 타입이 변경되면 DLQ로 라우팅되며, 이는 적절한 방어 전략이다.

**개선 필요:** 스키마 변경 발생 시 DLQ 급증 알림 → 자동 대응 프로세스 미비.

---

### 데이터 수집 주기

실시간 스트리밍(Continuous Streaming). 이벤트 발생 즉시 수집하는 구조로, 대시보드는 최신 데이터를 반영한다.

---

### Stateful 시스템 여부

Wikimedia SSE는 이벤트 스트림이므로 Stateful 시스템이 아니다. CDC(Change Data Capture) 개념이 아닌 순수 이벤트 로그 방식이다.

---

### 다운스트림 데이터 제공

Wikimedia Foundation에서 운영하는 공개 API. Rate Limit나 인증 없이 사용 가능하나, `User-Agent` 헤더 명시 가이드라인을 준수한다 (`wikiStreams-project/0.3`). 공식 SLA는 보장되지 않으므로 장애 시 파이프라인 중단에 대비해야 한다.

---

### 원천 시스템 성능 영향도

읽기 전용 스트림 구독(SSE) 방식이므로 Wikimedia 운영 서버에 부하를 주지 않는다.

Wikidata API 호출(`enricher.py`)은 배치당 최대 50개의 Q-ID를 묶어 1번의 API 호출로 처리(Batch API)하며, SQLite 캐시(30일 TTL)로 반복 호출을 최소화한다.

---

### 업스트림 의존 관계

```
Wikimedia SSE ──→ Producer ──→ Kafka ──→ Druid ──→ Superset
                      ↑
              Wikidata API (Enrichment)
```

Wikidata API가 다운되면 Enrichment 실패 이벤트가 DLQ로 라우팅되어 주 파이프라인은 계속 동작한다(Degraded Mode). Wikimedia SSE가 다운되면 수집 자체가 중단된다.

---

### 데이터 품질 검사

**현황:**
- 스키마 검증(Pydantic): 필수 필드 누락, 타입 불일치 시 DLQ 격리
- Grafana Error Monitor: DLQ Events/min, DLQ Total 시각화
- Grafana Producer Performance: Events/min 처리량 모니터링

**개선 필요:** 이상 감지(Anomaly Detection) — 평소 처리량 대비 급감 시 자동 알림 미구현.

---

## 2. Storage System Evaluation

### 읽기/쓰기 속도 적합성

| 스토리지 | 역할 | 쓰기 패턴 | 읽기 패턴 | 적합성 |
|--------|------|---------|---------|------|
| **Kafka** | 메시지 버퍼 | 실시간 고속 스트림 쓰기 | 순차 오프셋 읽기 | ✅ 최적 |
| **Apache Druid** | OLAP 분석 엔진 | 실시간 세그먼트 인제스천 | 시계열 집계 쿼리 | ✅ 최적 |
| **SQLite** | Wikidata 캐시 | Upsert (INSERT OR REPLACE) | Key-value 조회 | ⚠️ 단일 프로세스 제한 |

Kafka와 Druid는 현재 워크로드에 적합하다. SQLite는 단일 Producer 인스턴스에서는 충분하나, Scale-out 시 병목이 된다.

---

### 다운스트림 병목 여부

현재 아키텍처에서 잠재적 병목 지점:

1. **Wikidata API 호출 (동기식 I/O):** `enricher.py`의 API 호출이 배치 처리를 블로킹. 10초 타임아웃 설정에 의존하는 구조이며, API 지연이 길어지면 전체 배치 처리 지연으로 이어진다.
2. **SQLite 단일 연결:** Producer 인스턴스가 1개일 때는 문제없으나, Scale-out 불가.

**현황:** `TODO.md`에 AsyncIO 리팩토링(`asyncio` + `httpx` + `aiokafka`)이 Pending 상태로 남아 있다.

---

### 스토리지 기술 적합성

- **Kafka (KRaft 모드):** 메시지 큐로서 올바르게 사용. 순차 쓰기와 오프셋 기반 읽기 패턴에 최적화된 방식으로 활용.
- **Druid:** 시계열 OLAP 워크로드에 적합. 세그먼트 기반 저장, 쿼리 시 인덱스 활용. `segmentGranularity: HOUR`로 시간별 세그먼트 생성.
- **SQLite:** 캐시 목적으로는 적절하나, 스레드-로컬 연결(Thread-local) 방식으로 멀티스레드 안전성 확보. Scale-out에는 적합하지 않음(Anti-pattern for distributed systems).

---

### 확장성

| 컴포넌트 | 현재 설정 | 확장 경로 |
|---------|---------|---------|
| Kafka | 1 브로커, 단일 노드 | 파티션 수 증가, 브로커 추가 |
| Druid | MiddleManager 1개, TaskCount 1 | TaskCount/MiddleManager 증설 |
| SQLite | 단일 파일 DB | Redis로 교체 (TODO.md에 명시) |
| Producer | 단일 컨테이너 | Scale-out 시 Redis 캐시 공유 필요 |

현재 홈랩(WSL2) 환경에 맞게 최소 사양으로 구성되어 있으며, 클라우드 배포 시 수평 확장(Scale-out) 전략이 필요하다.

---

### SLA 충족 여부

**목표:** 실시간 대시보드를 통한 Wikimedia 편집 트렌드 모니터링

- Druid 인제스천 지연: 초~수십 초 (Kafka → Druid 실시간 인제스천)
- Superset 쿼리 응답: 초 단위 (Druid OLAP 특성)
- 파이프라인 재시작: Docker `restart: on-failure`로 자동 복구

**미보장:** 공식 SLA 문서 없음. 홈랩 환경이므로 99.9% 가용성 보장 불가.

---

### 메타데이터 캡처

**현황:**
- DLQ 메시지에 `error`, `failed_at`, `source_topic`, `retry_count` 메타데이터 포함
- Grafana 대시보드로 파이프라인 상태 시각화

**미구현:**
- 공식 데이터 카탈로그(Data Catalog) 미도입
- 스키마 변경 이력(Schema Evolution History) 추적 없음
- 데이터 리니지(Data Lineage) 자동 추적 미구현

---

### 스토리지 유형

| 스토리지 | 유형 | 쿼리 지원 |
|--------|------|---------|
| Kafka | 메시지 큐 (임시 버퍼) | 오프셋 기반 순차 읽기 |
| Druid | OLAP 데이터 웨어하우스 | 복잡한 시계열 SQL 집계 |
| SQLite | 로컬 Key-Value 캐시 | 단순 SELECT/UPSERT |

Druid가 스토리지와 컴퓨팅을 결합한 형태로, Superset을 통한 즉각적인 분석이 가능하다.

---

### 스키마 정책

- **Kafka:** 스키마 없음 (JSON raw). 스키마 레지스트리 미도입.
- **Druid:** 강제 적용 스키마. `ingestion-spec.json`에 정의된 dimension/metric만 저장됨 (`extra="allow"` 필드는 Druid에서 무시됨).
- **SQLite 캐시:** 고정 스키마 (`q_id, label, description, timestamp, is_missing`).

**개선 필요:** Kafka 레벨 스키마 레지스트리 미도입으로 스키마 변경 시 Druid 인제스천 스펙과 수동으로 맞춰야 하는 리스크 존재.

---

### 데이터 거버넌스

Wikimedia 공개 데이터를 수집하는 프로젝트로 개인정보 이슈는 제한적이나:
- 편집자 IP 주소가 포함될 수 있음 (`user` 필드에 익명 IP 표기 가능)
- 현재 PII(개인식별정보) 마스킹 로직 없음

---

### 법령 준수 및 데이터 주권

Wikimedia 데이터는 CC BY-SA 라이선스 하에 공개된 퍼블릭 도메인. 특별한 데이터 주권 이슈 없음. 단, 클라우드 배포 시 리전 설정 검토 필요.

---

## 3. Data Ingestion System Evaluation

### 데이터 사용 사례 및 재사용

현재 Kafka 토픽(`wikimedia.recentchange`) 하나를 Druid가 단독 소비. 추후 다른 분석 목적(예: ML 피처 엔지니어링, 별도 집계 서비스)이 생긴다면 동일 Kafka 토픽에 Consumer Group을 추가하여 재사용 가능한 구조이다.

---

### 안정적 수집 여부

**구현된 내결함성:**
- Collector: HTTP 오류 시 지수 백오프 + 자동 재연결
- Sender: Kafka 전송 실패 시 DLQ 라우팅 (3회 재시도)
- DLQ Consumer: 재처리 로직 (`src/dlq_consumer/consumer.py`)
- Docker: `restart: on-failure` 자동 재시작

**미구현:**
- 스트림 완전 중단(Wikimedia 서버 점검 등) 시 누락 이벤트 복구 불가
- Kafka offset commit 실패 시 멱등성(Idempotency) 보장 미검증

---

### 수집 목적지

```
Wikimedia SSE → [Producer: Batch(500 events / 10s)] → Kafka → Druid → Superset
                                                          ↓
                                                     DLQ Topic → DLQ Consumer
```

메인 데이터는 Kafka를 거쳐 Druid(시계열 OLAP)에 저장. 실패 이벤트는 DLQ 토픽에 보관 후 재처리.

---

### 데이터 접근 빈도

- **Druid:** 실시간 인제스천 → Superset 대시보드에서 분 단위 조회
- **SQLite 캐시:** 배치 처리마다 Q-ID 조회 (초~수십 초 단위)
- **DLQ:** 재처리 목적으로 비정기 접근

---

### 데이터 도착 크기

배치당 최대 500개 이벤트. 이벤트 하나의 크기는 JSON 직렬화 기준 약 500B~2KB 수준. 배치당 최대 ~1MB로 네트워크 대역폭 부담이 없다.

---

### 데이터 포맷

| 구간 | 포맷 |
|------|------|
| Wikimedia SSE | JSON (UTF-8) |
| Kafka 메시지 | JSON (UTF-8, `value_serializer=json.dumps`) |
| Druid 인제스천 | JSON (`inputFormat: json`) |
| DLQ 메시지 | JSON with metadata wrapper |

JSON 전체 파이프라인으로 일관성 있음. Avro/Protobuf 등 바이너리 포맷 미사용 (스키마 레지스트리 없음과 일관).

---

### 원천 데이터 품질 및 다운스트림 즉시 사용 가능성

Wikimedia 이벤트 자체는 Druid에 바로 적재 가능한 구조이나, Enrichment(Wikidata 레이블 추가)가 포함된 데이터가 더 높은 분석 가치를 가진다. ELT 방식(수집 후 Druid에서 집계)을 채택.

---

### 스트리밍 변환 필요성

현재 Producer에서 경량 변환을 수행:
1. **스키마 검증** (Pydantic): 형식 오류 이벤트 DLQ 라우팅
2. **Enrichment** (Wikidata API): `wikidata_label`, `wikidata_description` 필드 추가
3. **캐시 조회/저장** (SQLite): API 호출 최소화

Flink나 Spark Streaming 수준의 복잡한 스트림 처리는 불필요. 현재 구현으로 충분하다.

---

### Streaming vs Batch 평가

| 항목 | 평가 |
|------|------|
| **스트리밍 선택 근거** | Wikimedia 편집 이벤트는 발생 즉시 의미 있는 데이터. 배치 처리 시 최소 수 분의 지연 발생. |
| **실시간 이점** | 트렌딩 토픽 모니터링, 봇 활동 실시간 감지 |
| **스트리밍 비용** | 홈랩 환경에서 Docker Compose로 운영하므로 관리형 서비스 대비 비용 낮음. 단, DevOps 부담 존재. |
| **인프라 장애 대응** | Kafka의 내구성 보장 + DLQ로 재처리 가능. Exactly-once 미보장(at-least-once 수준). |
| **도구 선택** | Kafka(KRaft) + Python Producer: 자체 관리 부담 있으나 홈랩 수준에서 적절. 관리형 서비스(MSK, Kinesis) 불필요. |

---

### 운영 인스턴스 영향도

수집 대상이 Wikimedia의 SSE 스트림(읽기 전용 구독)이므로 Wikimedia 운영 서버에 부하 없음. Wikidata API 호출은 배치 최적화 및 캐싱으로 최소화.

---

## 4. Data Transformation System Evaluation

### 변환 비용 및 ROI

| 변환 단계 | 비용 | ROI |
|---------|------|-----|
| 스키마 검증 (Pydantic) | CPU 미미 | DLQ 격리로 데이터 품질 보장 → 높음 |
| Wikidata Enrichment (API 호출) | 네트워크 I/O, 외부 API 의존 | Q-ID를 인간이 이해할 수 있는 레이블로 변환 → 높음 |
| SQLite 캐시 | 디스크 I/O | API 호출 대폭 감소 → 매우 높음 |
| Druid 롤업/집계 | Druid 컴퓨팅 | 실시간 대시보드 집계 → 높음 |

모든 변환이 명확한 목적과 ROI를 가진다.

---

### 변환의 단순성 및 독립성

단일 책임 원칙(SRP)이 잘 적용된 모듈 구조:

| 모듈 | 책임 |
|------|------|
| `collector.py` | SSE 스트림 수집 + 배치 버퍼링 |
| `models.py` | 스키마 검증 (Pydantic) |
| `enricher.py` | Wikidata 레이블 Enrichment |
| `cache.py` | SQLite 캐시 조회/저장 |
| `sender.py` | Kafka 전송 + DLQ 라우팅 |
| `main.py` | 파이프라인 오케스트레이션 |

각 모듈이 독립적으로 테스트 가능하며, 단위 테스트 커버리지가 각 모듈별로 구현되어 있다.

**개선 필요:** `collector.py`가 1,137줄로 SSE 연결 관리 / 배치 로직 / 에러 처리가 혼재 (`TODO.md` 중간 우선순위 항목). `SSEClient`, `BatchBuffer`, `RetryPolicy`로 분리가 권장된다.

---

### 지원하는 비즈니스 규칙

| 비즈니스 규칙 | 구현 위치 |
|-------------|---------|
| Q-ID를 가진 이벤트만 Enrichment | `enricher.py` (정규식 `Q[0-9]+`) |
| 캐시 미스 시에만 외부 API 호출 | `enricher.py` + `cache.py` |
| 정상 엔티티: 30일 TTL | `cache.py` (`CACHE_TTL_SECONDS`) |
| 미존재 엔티티: 24시간 TTL | `cache.py` (`CACHE_MISSING_TTL_SECONDS`) |
| 검증 실패 이벤트 DLQ 격리 | `main.py` |
| 3회 재시도 후 최종 폐기 | `dlq_consumer/consumer.py` |
| 레이블 우선순위: 한국어 → 영어 | `enricher.py` |

---

## 5. 종합 평가 요약

### 구현 완료 항목

| 항목 | 상태 | 비고 |
|------|------|------|
| 실시간 스트리밍 수집 (SSE) | ✅ 완료 | Exponential Backoff 포함 |
| 스키마 검증 (Pydantic) | ✅ 완료 | WikimediaEvent, WikidataApiResponse |
| Dead Letter Queue | ✅ 완료 | 메타데이터 포함 격리 |
| DLQ Consumer (재처리) | ✅ 완료 | 3회 재시도 로직 |
| Wikidata Enrichment | ✅ 완료 | 배치 API + SQLite 캐시 |
| TTL 기반 캐시 (정상/미존재 차등) | ✅ 완료 | 30일/24시간 |
| Kafka 연동 | ✅ 완료 | KRaft 모드 |
| Druid 실시간 인제스천 | ✅ 완료 | 시간별 세그먼트 |
| Superset 대시보드 | ✅ 완료 | 코드로 관리 |
| Grafana 모니터링 (4개 대시보드) | ✅ 완료 | Loki 기반 |
| 단위 테스트 | ✅ 완료 | 모든 모듈 커버 |
| 통합/E2E 테스트 | ✅ 완료 | 자기 치유(Self-healing) 격리 |
| CI 파이프라인 | ✅ 완료 | GitHub Actions |

### 개선 필요 항목 (Pending)

| 항목 | 우선순위 | 이유 |
|------|---------|------|
| AsyncIO 리팩토링 | 중 | 동기식 Wikidata API 호출이 배치 블로킹 |
| SQLite → Redis 교체 | 중 | Scale-out 시 캐시 공유 불가 |
| `collector.py` 리팩토링 | 중 | 1,137줄 단일 모듈, SRP 위반 |
| 확장성 검증 리포트 | 낮 | 실제 처리 한계 미측정 |
| 중복 이벤트 제거 | 낮 | 재연결 시 잠재적 중복 |
| 이상 감지 알림 | 낮 | 처리량 급감 시 자동 알림 미구현 |
| CI 파이프라인 이원화 | 낮 | PR: Smoke / Merge: Full E2E |
| 클라우드 배포 (CD) | 낮 | 현재 로컬 홈랩 환경 |

### 아키텍처 성숙도 평가

```
데이터 수집    ████████████ 완성도 높음
데이터 품질    █████████░░░ 검증/DLQ 구현, 이상감지 미흡
데이터 저장    █████████░░░ Druid 적합, SQLite Scale-out 제한
데이터 변환    ████████░░░░ 동기식 I/O 병목 개선 필요
모니터링       ████████░░░░ 대시보드 있으나 자동 알림 미흡
테스트         ████████████ 단위/통합/E2E 전 계층 커버
```

전반적으로 **홈랩 수준의 실시간 데이터 파이프라인으로서 완성도가 높다.** 핵심 기능(수집, 검증, Enrichment, 저장, 시각화, 모니터링)이 모두 구현되어 있으며, 특히 DLQ 기반 에러 처리와 차등 캐시 TTL 전략이 데이터 품질 관리 측면에서 우수하다. 프로덕션 배포를 위해서는 AsyncIO 리팩토링과 분산 캐시(Redis) 전환이 주요 과제이다.
