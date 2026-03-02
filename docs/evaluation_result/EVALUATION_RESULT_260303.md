# WikiStreams 프로젝트 평가 결과

> 작성일: 2026-03-03
> 기준 문서: `docs/EVALUATION_KITS.md`
> 아키텍처: Kappa Architecture (Stream-only)
> 데이터 흐름: `Wikimedia SSE → Producer → Kafka → ClickHouse → Grafana / Reporter → Discord`
> 이전 평가: `docs/evaluation_result/EVALUATION_RESULT_260207.md` (2026-02-27)

---

## 이전 평가 대비 주요 변경사항

| 항목 | 260207 | 260303 |
|------|--------|--------|
| OLAP 엔진 | Apache Druid | **ClickHouse** |
| 시각화 | Superset | **Grafana** |
| 로그 수집 | Promtail | **Grafana Alloy** |
| Reporter | 없음 | **신규** (Claude Haiku + Discord) |
| Resource Monitor | 없음 | **신규** (EMA z-score 이상 감지) |
| `collector.py` 규모 | 1,137줄 (SRP 위반) | **89줄** (리팩토링 완료) |
| 이상 감지 알림 | 미구현 | **Discord 알림 구현** |
| 보고서 저장 | 없음 | **JSON 영속화** (build/publish 분리) |
| ClickHouse TTL | 해당 없음 | **90일 자동 삭제** |

---

## 1. Data Source System Evaluation

### 데이터 원천의 본질적인 특징

**원천:** Wikimedia SSE(Server-Sent Events) 스트림 (`https://stream.wikimedia.org/v2/stream/recentchange`)

IoT 스웜과 유사하게 끊임없이 이벤트가 흘러드는 **외부 공개 스트리밍 API**다. 연결이 끊기면 해당 구간의 이벤트는 복구 불가능하므로, 이에 맞게 Kafka + Exponential Backoff 재연결 구조를 채택하였다.

**현황:** `collector.py`의 `WikimediaCollector` 클래스가 SSE 구독, 배치 버퍼링, 재연결을 89줄로 처리. 이전 평가에서 지적된 1,137줄 단일 모듈 문제가 `WikimediaCollector` 클래스 분리로 해소되었다.

---

### 데이터 보존 기간

Wikimedia SSE 스트림은 **일시적(ephemeral)**이다. 연결이 끊기면 해당 구간 이벤트는 복구 불가능하며, 백필(Backfill)이 불가능하다.

**현황:**
- Exponential Backoff 재연결 (2s → 60s 상한)
- Docker Compose `restart: on-failure` 자동 복구
- Kafka에 적재된 이후 데이터는 ClickHouse에 **90일 TTL**로 관리됨

**여전히 미구현:** 스트림 중단 시 알림(Alerting). Resource Monitor가 컨테이너 자원 이상을 감지하나, 데이터 유입 자체의 중단(처리량 급감)을 감지하는 파이프라인 레벨 알림은 없다.

---

### 데이터 생성 속도

전 세계 24시간 편집 이벤트, **초당 수 건~수십 건** 수준. 현재 단일 Python 스크립트 + 단일 Kafka 브로커로 처리 가능한 볼륨이다.

**현황:** `batch_size=500`, `batch_timeout=10s`. ClickHouse 단일 노드로 현재 부하를 충분히 감당한다. 확장성 검증 리포트는 여전히 미작성 상태(Pending).

---

### 데이터 일관성 및 품질

**구현 완료:**
- `models.py`: Pydantic v2 `WikimediaEvent` 스키마 검증, 실패 시 DLQ 격리
- `extra="allow"`: 미정의 필드 보존, 미래 호환성 확보
- ClickHouse `kafka_skip_broken_messages = 1000`: Kafka 엔진 레벨에서 파싱 불가 메시지 자동 스킵

**평가:** `kafka_skip_broken_messages = 1000`은 파이프라인 안정성을 높이나, 스킵된 메시지를 DLQ로 라우팅하지 않으므로 **조용한 데이터 손실(Silent data loss)** 가능성이 있다.

---

### 에러 발생 빈도 및 대응

| 오류 유형 | 대응 |
|---------|------|
| HTTP 오류 (SSE 연결 실패) | 지수 백오프 + 자동 재연결 |
| JSON 파싱 오류 | 경고 로그 후 스킵 |
| Pydantic 검증 실패 | DLQ 라우팅 |
| Kafka 전송 실패 | DLQ 라우팅 (3회 재시도) |
| ClickHouse 파싱 오류 | `kafka_skip_broken_messages = 1000` 자동 스킵 |

---

### 데이터 중복 여부

SSE 재연결 시 이벤트 중복 수신 가능성 존재. **명시적 중복 제거 로직 미구현** 상태 (이전 평가와 동일).

**평가:** ClickHouse MergeTree에서는 중복 방지 기본 보장이 없다. Reporter의 집계 쿼리 정확도에 영향을 줄 수 있다. Reporter `fetcher.py`는 Q-ID 기반 **크로스 랭귀지 중복 제거**(`_deduplicate_by_qid`)를 분석 레이어에서 수행하고 있어 집계 품질을 보완하고 있다.

---

### 지연 도착(Late-arriving) 데이터

SSE 스트림 특성상 발행 즉시 수신 구조이므로 지연 도착 문제는 미미하다. Watermark 개념 미적용.

**변경:** 이전의 Druid `useEarliestOffset: true` / `auto.offset.reset: latest` 혼재 문제가 ClickHouse Kafka 엔진 단일 구조로 해소됨. ClickHouse Kafka 테이블은 `clickhouse-consumer` 그룹으로 오프셋을 일관되게 관리한다.

---

### 스키마 구조

| 필드 | 타입 | 비고 |
|------|------|------|
| `event_time` | DateTime | `Delta+ZSTD` 압축 |
| `title` | String | Q-ID 포함 가능 |
| `server_name` | LowCardinality(String) | 카디널리티 최적화 |
| `wiki_type` | LowCardinality(String) | edit/new/categorize |
| `namespace` | Int32 | 위키 네임스페이스 |
| `user` | String | 편집자 (IP 포함 가능) |
| `bot` | UInt8 | 봇 여부 |
| `comment` | String | 편집 요약 (revert 감지용) |
| `wikidata_label` | String | Enrichment 필드 |
| `wikidata_description` | String | Enrichment 필드 |

단일 소스, 단일 스트림. 조인 불필요. ClickHouse `LowCardinality(String)` 타입 활용으로 쿼리 성능 최적화가 설계에 반영되어 있다.

---

### 스키마 변경 대처

Pydantic 모델이 Data Contract 역할을 하며, `extra="allow"`로 신규 필드 추가에 유연하게 대응. ClickHouse 인제스천 스키마는 `init-db.sql`로 코드 관리.

**미구현:** 공식 Schema Registry 미도입. 필수 필드 제거/타입 변경 시 DLQ 급증 → 자동 대응 프로세스 없음.

---

### 데이터 수집 주기

실시간 스트리밍(Continuous). 이벤트 발생 즉시 수집 → Kafka → ClickHouse 자동 인제스천.

---

### 원천 시스템 성능 영향도

읽기 전용 SSE 구독. Wikidata API는 배치(50개 청크) + SQLite 30일 캐시로 호출 최소화. Reporter의 `_fetch_qid`, `_fetch_ko_description`는 `ThreadPoolExecutor(max_workers=10)`로 병렬 처리하나 여전히 동기 I/O 기반이다.

---

### 업스트림 의존 관계

```
Wikimedia SSE ──→ Producer ──→ Kafka ──→ ClickHouse ──→ Grafana
                      ↑                                      ↓
              Wikidata API (Enrichment)                    Reporter
                                                              ↑
                                          Wikipedia REST API / Google News RSS
```

Wikidata API 다운 시 Enrichment 실패 → DLQ 라우팅, 주 파이프라인 지속 (Degraded Mode). Wikimedia SSE 다운 시 수집 중단.

---

### 데이터 품질 검사

**구현 완료:**
- Pydantic 스키마 검증 + DLQ 격리
- Grafana Error Monitor: DLQ Events/min, DLQ Total 시각화
- Grafana Producer Performance: 처리량(Events/min) 모니터링

**Resource Monitor 신규 추가:**
- EMA(지수이동평균) + z-score 기반 이상 감지 (임계값 기본 2.5σ)
- 컨테이너 CPU/메모리/블록 I/O 이상 시 Discord 알림 자동 발송
- `min_samples=30` 학습 기간 이후부터 감지 활성화

**여전히 미구현:** 데이터 처리량(Events/min) 급감 자체에 대한 알림. Resource Monitor는 컨테이너 자원 이상을 감지하지만, 데이터 볼륨 이상은 감지하지 않는다.

---

## 2. Storage System Evaluation

### 읽기/쓰기 속도 적합성

| 스토리지 | 역할 | 쓰기 패턴 | 읽기 패턴 | 적합성 |
|---------|------|---------|---------|------|
| **Kafka** | 메시지 버퍼 | 실시간 고속 스트림 쓰기 | 순차 오프셋 읽기 | ✅ 최적 |
| **ClickHouse** | OLAP 분석 엔진 | Kafka Engine 자동 인제스천 | 시계열 집계 쿼리 | ✅ 최적 |
| **SQLite** | Wikidata 캐시 | Upsert | Key-value 조회 | ⚠️ Scale-out 불가 |
| **JSON 파일** | Reporter 저장소 | 일 1회 덮어쓰기 | 로드 후 Discord 발송 | ✅ 목적에 적합 |

**이전 대비 개선:** Druid(복잡한 설정, Zookeeper 의존성) → ClickHouse(단순, Kafka Engine 내장, SQL 친화적)로 전환하여 운영 복잡도가 크게 낮아졌다.

---

### 다운스트림 병목 여부

**잠재적 병목:**
1. **Wikidata API 동기식 I/O**: `enricher.py`의 API 호출이 배치 처리를 블로킹. AsyncIO 리팩토링은 여전히 Pending.
2. **Reporter의 동기식 외부 API 호출**: `fetch_report_data()`에서 Wikipedia REST API, Google News RSS 호출이 동기식. `ThreadPoolExecutor`로 병렬 처리하나 비동기 대비 효율 낮음.
3. **SQLite 단일 연결**: Producer 1개 인스턴스에서는 문제없으나 Scale-out 불가.

---

### 스토리지 기술 적합성

- **Kafka (KRaft)**: 메시지 큐 목적에 적합. ZooKeeper 없는 KRaft 모드로 운영 단순화.
- **ClickHouse**: OLAP 워크로드 최적. `LowCardinality` 타입, `Delta+ZSTD` 압축, 월별 파티셔닝, `MergeTree` 정렬 키(`event_time, server_name, wiki_type`)가 Reporter 집계 쿼리 패턴에 잘 맞다.
- **Kafka Engine + Materialized View**: Kafka → ClickHouse 인제스천이 별도 Consumer 없이 DB 내부에서 처리됨. 단순하고 효율적인 패턴.
- **JSON 파일 스토리지**: Reporter 빌드/발행 분리(`build_and_save` / `publish_saved`)를 위한 간단한 영속화 계층. 목적에 적합.

---

### 확장성

| 컴포넌트 | 현재 설정 | 확장 경로 |
|---------|---------|---------|
| Kafka | 1 브로커, 단일 노드 | 파티션 수 증가, 브로커 추가 |
| ClickHouse | 단일 노드 | 샤드 + 복제(ReplicatedMergeTree) 전환 |
| SQLite | 단일 파일 DB | Redis로 교체 (여전히 Pending) |
| Producer | 단일 컨테이너 | Scale-out 시 분산 캐시 필요 |

---

### SLA 충족 여부

- Kafka → ClickHouse 인제스천 지연: 초~수십 초 (Materialized View 자동 처리)
- Reporter 쿼리 응답: 초 단위 (ClickHouse OLAP 특성)
- 홈랩 환경이므로 공식 SLA 미정의. `restart: always/on-failure`로 자동 복구.

---

### 메타데이터 캡처

**구현 완료:**
- DLQ 메시지: `error`, `failed_at`, `source_topic`, `retry_count` 메타데이터 포함
- Reporter JSON: `generated_at`, `prompt_style` 포함
- Grafana 대시보드: 파이프라인 상태 시각화

**미구현:** 공식 데이터 카탈로그, 스키마 변경 이력 추적, 데이터 리니지 자동 추적.

---

### 스토리지 유형 및 스키마 정책

| 스토리지 | 유형 | 스키마 정책 |
|---------|------|----------|
| Kafka | 메시지 큐 | 스키마 없음 (JSON raw) |
| ClickHouse | OLAP DW | 강제 적용 (`init-db.sql`로 코드 관리) |
| SQLite | Key-Value 캐시 | 고정 스키마 |
| JSON 파일 | 파일 스토리지 | dataclass 기반 구조화 |

---

### 데이터 거버넌스 / 법령 준수

- Wikimedia CC BY-SA 공개 데이터. 특별한 데이터 주권 이슈 없음.
- 편집자 IP 주소가 `user` 필드에 포함될 수 있으나 PII 마스킹 미구현 (이전 평가와 동일).
- **ClickHouse TTL 90일**: 데이터 수명 주기 관리가 스키마 레벨에서 자동화되어 있다. 이전 평가 대비 개선.

---

## 3. Data Ingestion System Evaluation

### 데이터 재사용 가능성

Kafka 토픽(`wikimedia.recentchange`) 하나를 ClickHouse Kafka Engine이 소비. 추가 Consumer Group을 붙여 다른 분석 목적에 재사용 가능한 구조.

---

### 내결함성

**구현된 내결함성:**
- Collector: HTTP 오류 시 지수 백오프(2s→60s) 재연결
- Sender: Kafka 전송 실패 시 DLQ 라우팅 (3회 재시도)
- DLQ Consumer: 재처리 로직, 3회 초과 시 CRITICAL 로그 후 폐기
- Docker: `restart: on-failure` / `restart: always` 자동 재시작

**미구현:**
- Wikimedia 서버 점검 등 완전 중단 시 누락 이벤트 복구 불가
- Kafka offset commit 실패 시 Exactly-once 미보장 (at-least-once 수준)

---

### 수집 목적지 및 파이프라인

```
Wikimedia SSE
  → [Producer: batch(500/10s)] → Kafka(wikimedia.recentchange)
                                    ↓
                          [Kafka Engine Table]     [DLQ Topic] → DLQ Consumer
                                    ↓
                         [Materialized View]
                                    ↓
                        ClickHouse(wikimedia.events)  ← TTL 90일
                                    ↓
                         Grafana / Reporter
```

이전 대비: Druid Supervisor → ClickHouse Kafka Engine + Materialized View로 인제스천 구조가 단순화. 별도 Druid Coordinator/Overlord 관리 불필요.

---

### 데이터 접근 빈도

- **ClickHouse**: Reporter가 일 1회 대량 집계 쿼리, Grafana가 실시간 조회
- **SQLite 캐시**: 배치마다 Q-ID 조회 (초~수십 초 단위)
- **JSON 파일**: 빌드 후 1회 저장, 발행 시 1회 로드
- **Reporter reports/ 볼륨**: 날짜별 JSON 보관, 특정 날짜 재발송 가능

---

### 데이터 포맷

| 구간 | 포맷 |
|------|------|
| Wikimedia SSE | JSON (UTF-8) |
| Kafka 메시지 | JSON (UTF-8) |
| ClickHouse 인제스천 | `JSONEachRow` (`kafka_format`) |
| DLQ 메시지 | JSON + metadata wrapper |
| Reporter 저장소 | JSON (dataclasses.asdict) |

JSON 전체 파이프라인으로 일관성 있음. 바이너리 포맷(Avro/Protobuf) 및 Schema Registry 미도입.

---

### 스트리밍 vs 배치 평가

| 항목 | 평가 |
|------|------|
| 스트리밍 선택 근거 | 편집 이벤트는 발생 즉시 의미 있는 데이터. 배치 대비 Grafana 실시간성 확보 |
| 스트리밍 비용 | Docker Compose 자체 운영으로 관리형 서비스 대비 비용 낮음 |
| Exactly-once | 미보장 (at-least-once). ClickHouse Kafka Engine 자체도 at-least-once |
| 도구 선택 | Kafka(KRaft) + Python Producer: 홈랩 규모에 적합, 운영 부담 수용 가능 수준 |
| Reporter 배치 처리 | 일 1회 집계 쿼리 → Claude Haiku 호출 → Discord 발송. 비용 효율적 |

---

## 4. Data Transformation System Evaluation

### 변환 비용 및 ROI

| 변환 단계 | 비용 | ROI |
|---------|------|-----|
| 스키마 검증 (Pydantic) | CPU 미미 | 데이터 품질 보장 → 높음 |
| Wikidata Enrichment | 네트워크 I/O + SQLite | Q-ID → 가독성 레이블 변환 → 높음 |
| ClickHouse 집계 | DB 컴퓨팅 | 실시간 대시보드 분석 → 높음 |
| Claude Haiku 호출 | API 비용 (일 1회) | 트렌드 서사화 + Top5 다양성 선정 → 높음 |
| Q-ID 기반 중복 제거 | 병렬 API 호출 | 다국어 편집 집계 정확도 향상 → 높음 |
| EMA z-score 이상 감지 | CPU 미미 | 컨테이너 이상 선제 감지 → 높음 |

모든 변환이 명확한 목적과 ROI를 가진다.

---

### 변환의 단순성 및 독립성

단일 책임 원칙(SRP)이 전체 코드베이스에 일관되게 적용됨.

| 모듈 | 책임 |
|------|------|
| `collector.py` | SSE 연결 + 배치 버퍼링 (**이전 1,137줄 → 89줄 리팩토링 완료**) |
| `models.py` | 스키마 검증 |
| `enricher.py` | Wikidata 레이블 Enrichment |
| `cache.py` | SQLite 캐시 |
| `sender.py` | Kafka 전송 + DLQ 라우팅 |
| `fetcher.py` | ClickHouse 쿼리 + 외부 API 데이터 수집 |
| `builder.py` | Claude Haiku 호출 + JSON 파싱 |
| `publisher.py` | Discord Embed 구성 + 전송 |
| `storage.py` | 보고서 JSON 저장/로드 |
| `detector.py` | z-score 이상 감지 로직 |
| `alerter.py` | Discord 알림 전송 + 쿨다운 |
| `baseline.py` | EMA + 분산 계산 (SQLite 영속화) |

---

### 비즈니스 규칙 구현

| 비즈니스 규칙 | 구현 위치 |
|-------------|---------|
| Q-ID 이벤트만 Enrichment | `enricher.py` (정규식) |
| 캐시 미스 시에만 API 호출 | `enricher.py` + `cache.py` |
| 정상 엔티티 캐시 30일 TTL | `cache.py` |
| 미존재 엔티티 캐시 24시간 TTL | `cache.py` |
| 검증 실패 이벤트 DLQ 격리 | `main.py` |
| DLQ 3회 재시도 후 폐기 | `dlq_consumer/consumer.py` |
| 한국어 우선 → 영어 fallback | `enricher.py` |
| 봇 제외 실제 편집만 Top5 집계 | `fetcher.py` ClickHouse 쿼리 |
| Q-ID 기반 크로스 랭귀지 중복 제거 | `fetcher.py` `_deduplicate_by_qid()` |
| 스파이크: 최근 15분 vs 이전 60분 비율 | `fetcher.py` ClickHouse 쿼리 |
| 전일 대비 순위 변화(rank_change) | `fetcher.py` |
| Claude가 Top5 주제 다양성 선정 | `builder.py` `selected_indices` |
| 설명 없는 문서: Claude가 보완 | `builder.py` `descriptions` |
| 컨테이너 이상: 30 샘플 이후 감지 | `detector.py` |
| 알림 쿨다운 (반복 알림 방지) | `alerter.py` |
| ClickHouse 이벤트 90일 TTL | `init-db.sql` |

---

## 5. Undercurrents (횡단 관심사)

### 5-1. Security

| 항목 | 상태 | 비고 |
|------|------|------|
| 최소 권한 원칙 | ⚠️ 부분 | Grafana `GF_AUTH_ANONYMOUS_ENABLED=true` + `Admin` 권한 — 홈랩이므로 허용 범위이나 외부 노출 시 위험 |
| 환경변수 기반 시크릿 관리 | ✅ | API Key, Webhook URL을 `.env`로 관리 |
| 데이터 암호화 | ❌ | 전송/저장 중 암호화 미적용 |
| PII 마스킹 | ❌ | `user` 필드에 IP 주소 포함 가능, 마스킹 없음 |
| Docker socket 마운트 | ⚠️ | `resource-monitor` 컨테이너가 `/var/run/docker.sock` 마운트 — 컨테이너 탈출 위험, 홈랩 허용 범위 |
| ClickHouse 인증 | ⚠️ | `override-users.xml`로 관리 중이나 외부 포트(8123, 9000) 노출 |

**전반 평가:** 홈랩 내부 환경에서는 허용 가능한 수준이나, 외부 공개 배포 전 Grafana 인증 활성화, ClickHouse 방화벽 설정, Docker socket 최소 권한 제한이 필요하다.

---

### 5-2. Data Management

| 항목 | 상태 | 비고 |
|------|------|------|
| 데이터 품질 (Accuracy) | ✅ | Pydantic 검증 + DLQ |
| 데이터 품질 (Completeness) | ⚠️ | `kafka_skip_broken_messages`로 조용한 손실 가능 |
| 데이터 품질 (Timeliness) | ✅ | 실시간 스트리밍 |
| Data Lineage | ⚠️ | DLQ 메타데이터로 부분 추적, 공식 리니지 도구 없음 |
| Data Lifecycle | ✅ | ClickHouse TTL 90일 자동 삭제 신규 구현 |
| Data Modeling | ✅ | 분석 쿼리 패턴에 맞는 ClickHouse 정렬 키 설계 |
| Metadata | ⚠️ | DLQ/Reporter JSON에 일부 메타데이터, 공식 카탈로그 없음 |
| Ethics & Privacy | ❌ | IP 주소 PII 마스킹 미구현 |

---

### 5-3. DataOps

**자동화:**
- GitHub Actions CI: Lint(flake8) + 포맷(black) + 단위 테스트 (PR/push 자동 실행)
- GitHub Actions CI: 통합/E2E 테스트 (main 브랜치 push 시 자동 실행)
- Docker Compose `restart: always/on-failure`: 서비스 자동 복구
- APScheduler: Reporter 일 1회 09:00 KST 자동 발송

**Observability:**
- **Grafana 대시보드 4종**: Error Monitor, Producer Performance, Resources Monitor, WikiStreams Analytics
- **Grafana Alloy**: 컨테이너 로그 수집 → Loki (이전 Promtail 대체, macOS 호환 문제 해소)
- **Resource Monitor**: EMA z-score 기반 CPU/메모리/블록 I/O 이상 감지 → Discord 알림

**Incident Response:**
- Resource Monitor: 이상 감지 즉시 Discord 알림 (쿨다운 포함, 반복 알림 방지)
- MTTD: Grafana 대시보드 + Discord 알림으로 선제 감지 가능
- MTTR: `docker compose build <service> && up -d`로 서비스 재배포 단순함

**여전히 미구현:**
- 데이터 처리량(Events/min) 급감 알림
- CI Smoke(PR) / Full E2E(merge) 이원화

---

### 5-4. Data Architecture

**설계 원칙 준수 평가:**

| 원칙 | 상태 | 비고 |
|------|------|------|
| 조직 규모·스킬셋에 맞는 도구 선택 | ✅ | 홈랩 수준에서 최소 복잡도 유지 |
| 모듈형 설계 (컴포넌트 교체 가능) | ✅ | Producer/Reporter/Monitor 독립 배포 |
| 비용·운영 간소화 균형 | ✅ | Druid → ClickHouse로 운영 부담 대폭 감소 |
| 전 구간 설계 일관성 | ✅ | SSE → Kafka → ClickHouse → Grafana/Discord 흐름 일관 |

**특기 사항:** ClickHouse Kafka Engine + Materialized View 패턴이 이전 Druid Supervisor 대비 코드 관리 범위를 크게 줄였다. 인제스천 파이프라인이 DB 스키마 파일 한 곳(`init-db.sql`)에서 선언적으로 관리됨.

---

### 5-5. Orchestration

| 항목 | 상태 |
|------|------|
| 고가용성 | ⚠️ 단일 노드 Docker Compose (홈랩 수용 범위) |
| 스케줄링 | ✅ APScheduler (Reporter) + Docker `restart` 정책 |
| 데이터 의존성 관리 | ⚠️ 명시적 DAG 없음, 서비스 간 `depends_on`으로 제한적 관리 |
| 장애 시 Failover | ⚠️ `restart: on-failure` 단순 재시작, 복잡한 Failover 전략 없음 |

**전반 평가:** 홈랩 파이프라인으로서 현재 복잡도에서는 Airflow/Dagster 불필요. 서비스 수가 늘면 재평가 필요.

---

### 5-6. Software Engineering

| 항목 | 상태 | 비고 |
|------|------|------|
| **단위 테스트** | ✅ 완료 | Producer, DLQ Consumer, Reporter, Resource Monitor 전 모듈 |
| **통합 테스트** | ✅ 완료 | Kafka, ClickHouse 실제 연동 |
| **E2E 테스트** | ✅ 완료 | Producer→Kafka→ClickHouse 전체 흐름 |
| **CI 파이프라인** | ✅ 완료 | GitHub Actions (Lint + Unit + Integration/E2E) |
| **IaC** | ✅ 완료 | Docker Compose + `init-db.sql` + Grafana provisioning YAML |
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
| DLQ Consumer (재처리) | ✅ | 유지 |
| Wikidata Enrichment + TTL 캐시 | ✅ | 유지 |
| Kafka 연동 (KRaft) | ✅ | 유지 |
| **ClickHouse 실시간 인제스천** | ✅ | **Druid 대체 신규 구현** |
| **Grafana 대시보드 4종** | ✅ | **Superset 대체 신규 구현** |
| **Grafana Alloy 로그 수집** | ✅ | **Promtail 대체, macOS 호환 해소** |
| **Reporter (Claude + Discord)** | ✅ | **신규 구현** |
| **Resource Monitor (이상 감지 + 알림)** | ✅ | **신규 구현** |
| **collector.py 리팩토링** | ✅ | **1,137줄 → 89줄** |
| **ClickHouse TTL 90일** | ✅ | **신규 구현** |
| **보고서 JSON 영속화** | ✅ | **신규 구현** |
| **Q-ID 크로스 랭귀지 중복 제거** | ✅ | **신규 구현** |
| 단위 / 통합 / E2E 테스트 | ✅ | Resource Monitor 테스트 추가 |
| GitHub Actions CI | ✅ | Resource Monitor 의존성 추가 |

---

### 여전히 개선 필요한 항목

| 항목 | 우선순위 | 이유 |
|------|---------|------|
| AsyncIO 리팩토링 | 중 | 동기식 Wikidata API(enricher) + 외부 API(fetcher) 병목 |
| SQLite → Redis | 중 | Producer Scale-out 시 캐시 공유 불가 |
| 데이터 처리량 급감 알림 | 중 | Events/min 급감 시 파이프라인 이상 자동 감지 불가 |
| `kafka_skip_broken_messages` DLQ 연동 | 낮 | 조용한 데이터 손실 방지 |
| 중복 이벤트 제거 | 낮 | 재연결 시 잠재적 중복 (Reporter 레이어에서 부분 보완) |
| PII 마스킹 (`user` 필드 IP) | 낮 | 퍼블릭 배포 전 필요 |
| CI Smoke/Full E2E 이원화 | 낮 | PR 단계 빠른 피드백 개선 |
| Grafana 인증 활성화 | 낮 | 외부 공개 시 필수 |

---

### 아키텍처 성숙도 평가

```
데이터 수집    ████████████ 완성도 높음 (리팩토링 완료)
데이터 품질    █████████░░░ 검증/DLQ 구현, 처리량 급감 알림 미흡
데이터 저장    ██████████░░ ClickHouse 최적화, SQLite Scale-out 제한
데이터 변환    ████████░░░░ 동기식 I/O 병목 여전히 개선 필요
모니터링/알림  ██████████░░ Resource Monitor 신규 구현으로 크게 향상
가치 전달      ██████████░░ Reporter 신규 구현 (Claude + Discord 일일 브리핑)
테스트         ████████████ 전 계층 커버 (Resource Monitor 추가)
```

**전반 평가:** 이전 대비 완성도가 크게 향상되었다. Druid/Superset이라는 운영 부담이 높은 스택을 ClickHouse/Grafana로 교체하면서 아키텍처 단순도와 쿼리 성능이 동시에 개선됐다. Reporter와 Resource Monitor 신규 추가로 파이프라인이 단순 수집·저장을 넘어 **가치 전달(Daily Briefing)** 과 **자율 감시(Anomaly Alert)** 기능을 갖춘 시스템으로 발전하였다. 홈랩 데이터 파이프라인으로서 현 단계의 완성도는 매우 높다.

프로덕션 수준으로 끌어올리기 위한 핵심 과제는 **AsyncIO 리팩토링(성능)**, **Redis 전환(확장성)**, **처리량 이상 감지(신뢰성)** 세 가지다.
