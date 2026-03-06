# WikiStreams 서비스 수준 지표 (SLI)

> 작성일: 2026-03-05
> 목적: NFR.md의 각 요구사항을 실제로 측정 가능한 지표로 변환
> 선행 산출물: NFR.md
> 후행 산출물: SLO.md

---

## 1. 측정 분류 기준

| 분류 | 의미 |
|------|------|
| **자동 측정** | Grafana/Loki/ClickHouse 쿼리로 상시 관측 가능 |
| **수동 측정** | 쿼리 또는 로그를 사람이 직접 조회해야 확인 가능 |
| **계측 불가** | 현재 코드·인프라에 측정 수단 없음 → 계측 보강 필요 |

---

## 2. 가용성 (Availability) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-A1 | NFR-A1 | Producer 재연결 소요 시간 | 연결 끊김 로그 ~ 재연결 성공 로그 간 초 | Loki | 수동 측정 |
| SLI-A2 | NFR-A2 | ClickHouse 쿼리 가용성 | 단위 시간당 ClickHouse 쿼리 성공 비율 (%) | ClickHouse `system.query_log` | 자동 측정 |
| SLI-A3 | NFR-A3 | Reporter 일일 발송 성공 여부 | 하루 1회 "Publish complete" 로그 존재 여부 (0 또는 1) | Loki | 자동 측정 |

**SLI-A1 측정 방법 (Loki)**

연결 끊김 시 `collector.py`가 아래 형식으로 기록:
```
❌ HTTPX 오류 발생: ... — N초 후 재연결 시도...
✅ Wikimedia SSE 스트림에 성공적으로 연결되었습니다.
```
두 로그의 타임스탬프 차이가 재연결 소요 시간. 수동으로 Grafana Loki 패널에서 조회.

**SLI-A2 측정 쿼리 (ClickHouse)**
```sql
SELECT
    countIf(type = 'QueryFinish') * 100.0 / count() AS success_rate_pct
FROM system.query_log
WHERE event_time >= now() - INTERVAL 24 HOUR
  AND query NOT LIKE '%system.query_log%'
```

**SLI-A3 측정 쿼리 (Loki LogQL)**
```logql
count_over_time({container="reporter"} |= "Publish complete" [1d])
```
값이 1이면 성공, 0이면 미발송.

---

## 3. 성능 (Performance) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-P1 | NFR-P1 | 배치 처리 소요 시간 | 배치 콜백 시작 ~ Kafka flush 완료까지 초 | Loki (`batch_processing_seconds`) | 자동 측정 |
| SLI-P2 | NFR-P2 | 배치 크기 | 배치당 처리 이벤트 수 | Loki (`batch_size`) | 자동 측정 |
| SLI-P3 | NFR-P3 | ClickHouse 쿼리 응답 시간 | 쿼리 실행 시간 p99 (초) | ClickHouse `system.query_log` | 자동 측정 |
| SLI-P4 | NFR-P4 | Reporter 파이프라인 소요 시간 | "Starting report build" ~ "Publish complete" 로그 간 초 | Loki | 수동 측정 |
| SLI-P5 | NFR-P5 | Producer 지속 처리량 | 단위 시간당 Kafka 발행 이벤트 수 (events/min) | Grafana (기존 패널) | 자동 측정 |
| SLI-P7 | NFR-P7 | Wikidata 캐시 히트율 | 전체 Wikidata 조회 중 캐시에서 응답한 비율 (%) | Grafana (기존 패널) | 자동 측정 |

**SLI-P1 측정 방법 (Loki)**

`main.py`의 `process_batch()`에 `time.perf_counter()` 기반 로그 추가 완료 (2026-03-06):
```
batch_processing_seconds=0.004 batch_size=3 valid=3
```
Loki logfmt으로 `batch_processing_seconds` 필드 파싱 후 `quantile_over_time(0.95, ...)` 집계.

**SLI-P2 측정 방법 (Loki)**

`collector.py`의 `_process_buffer()`에 배치 크기 로그 추가 완료 (2026-03-06):
```
batch_size=3 sse_received_total=72
```
Loki logfmt으로 `batch_size` 필드 파싱.

**SLI-P3 측정 쿼리 (ClickHouse)**
```sql
SELECT
    quantile(0.99)(query_duration_ms) / 1000.0 AS p99_seconds,
    quantile(0.50)(query_duration_ms) / 1000.0 AS p50_seconds
FROM system.query_log
WHERE type = 'QueryFinish'
  AND event_time >= now() - INTERVAL 1 HOUR
  AND query NOT LIKE '%system.%'
```

**SLI-P4 측정 방법 (Loki)**

`reporter/main.py`의 로그 순서:
```
INFO ... Starting report build       ← 시작
INFO ... Publish complete            ← 완료 (또는 ERROR ... Failed to run report)
```
두 로그의 타임스탬프 차이가 파이프라인 소요 시간. 수동 조회.

**SLI-P5 측정 쿼리 (ClickHouse)**
```sql
SELECT
    count() / dateDiff('minute', min(event_time), max(event_time)) AS events_per_min
FROM wikimedia.events
WHERE event_time >= now() - INTERVAL 5 MINUTE
```
Grafana Producer Performance 대시보드 `Events/Min` 패널과 동일 지표. 이미 자동 집계 중.

**SLI-P7 측정 방법 (Grafana)**

Grafana Producer Performance 대시보드 `Cache Hit Rate Trend` 패널에서 실시간 확인. Loki에서 enricher 캐시 히트/미스 로그를 집계하여 비율 산출.

---

## 4. 신뢰성 (Reliability) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-R1 | NFR-R1 | DLQ 유입 비율 | DLQ 라우팅 이벤트 수 / 전체 처리 이벤트 수 × 100 (%) | Loki | 자동 측정 |
| SLI-R2 | NFR-R2 | DLQ 재처리 시도 횟수 | DLQ 컨슈머의 재시도 로그 카운트 | Loki | 자동 측정 |
| SLI-R3 | NFR-R3 | 재연결 소요 시간 | SLI-A1과 동일 | Loki | 수동 측정 |
| SLI-R4 | NFR-R4 | Reporter 오류 후 다음 발송 성공 여부 | ERROR 로그 발생 후 익일 SLI-A3 = 1 여부 | Loki | 수동 측정 |
| SLI-R5 | NFR-R5 | 파이프라인 완전성 | SSE 수신 이벤트 수 대비 ClickHouse 적재 이벤트 수 비율 (%) | Loki (`sse_received_total`) + ClickHouse | 자동 측정 (부분) |

**SLI-R1 측정 방법 (Loki)**

`sender.py`가 아래 형식으로 기록:
```
INFO  ... {N}개의 이벤트를 'wikimedia.recentchange'으로 전송했습니다.
WARN  ... ⚠️ {M}개의 이벤트를 DLQ로 라우팅했습니다.
```

Loki LogQL (근사치):
```logql
# DLQ 이벤트 수 (분당)
sum(rate({container="producer"} |= "DLQ로 라우팅" | regexp `(?P<count>\d+)개` | unwrap count [5m]))

# 전체 이벤트 수 (분당) — 전송 성공 + DLQ 합산
```
정확한 비율은 Grafana 패널에서 두 값을 나누어 계산.

**SLI-R5 측정 방법**

`collector.py`에 SSE 수신 누적 카운터 추가 완료 (2026-03-06):
```
batch_size=3 sse_received_total=72
```
`sse_received_total`은 프로세스 재시작 시 초기화되므로, ClickHouse `count()`와의 절대값 비교는 불가. 대신 배치 단위 유입량 대비 ClickHouse 적재량의 상대적 추이로 유실 여부를 관찰. 정확한 비율 측정을 위한 대조 기준은 관측 기간 중 수립 예정.

---

## 5. 데이터 품질 (Data Quality) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-D1 | NFR-D1 | 데이터 신선도 (Lag) | `now() - max(event_time)` (초) | ClickHouse | 자동 측정 |
| SLI-D2 | NFR-D2 | Wikidata 레이블 보강률 | Q-ID 이벤트 중 `wikidata_label != ''` 비율 (%) | ClickHouse | 자동 측정 |
| SLI-D3 | NFR-D3 | 캐시 TTL 준수 | 설정값(`CACHE_TTL_SECONDS`, `CACHE_MISSING_TTL_SECONDS`) 일치 여부 | 코드 검증 | 수동 측정 |

**SLI-D1 측정 쿼리 (ClickHouse)**
```sql
SELECT dateDiff('second', max(event_time), now()) AS lag_seconds
FROM wikimedia.events
```

**SLI-D2 측정 쿼리 (ClickHouse)**
```sql
SELECT
    countIf(wikidata_label != '') * 100.0 / count() AS enrichment_rate_pct
FROM wikimedia.events
WHERE event_time >= now() - INTERVAL 24 HOUR
  AND title LIKE 'Q%'
```

---

## 6. 유지보수성 (Maintainability) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-M4 | NFR-M4 | Loki 로그 보존 기간 | 현재 시각 기준 30일 전 로그 조회 가능 여부 | Loki | 수동 측정 |

**SLI-M4 측정 방법 (Loki)**
```logql
# 30일 전 로그 존재 여부 확인
{container="producer"} | since="720h"
```
`loki-config.yaml`의 `retention_period` 설정값과 실제 조회 가능 범위를 월 1회 대조 확인.

---

## 7. 복구성 (Recoverability) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-RC1 | NFR-RC1 | 컴포넌트 독립 복구 | 단일 컨테이너 재시작 시 타 컨테이너 에러 로그 발생 여부 | Loki | 수동 측정 |
| SLI-RC2 | NFR-RC2 | 재시작 후 이벤트 연속성 | 재시작 전후 ClickHouse 이벤트 카운트 갭 | ClickHouse | 수동 측정 |
| SLI-RC3 | NFR-RC3 | 데이터 영속성 | 컨테이너 재시작 전후 `count(*)` 동일 여부 | ClickHouse | 수동 측정 |
| SLI-RC4 | NFR-RC4 | RPO (백업 주기 준수) | 마지막 백업 완료 타임스탬프 ~ 현재 시각 간격 (초) | 백업 로그 | **계측 불가** |
| SLI-RC5 | NFR-RC5 | RTO (복원 소요 시간) | 장애 감지 ~ 서비스 복원 완료까지 소요 시간 (분) | 수동 기록 | **계측 불가** |

**SLI-RC2, RC3 측정 쿼리 (ClickHouse)**
```sql
-- 재시작 전후 비교용
SELECT count() AS total_events, max(event_time) AS latest
FROM wikimedia.events
```

---

## 8. 용량 (Capacity) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-CAP1 | NFR-CAP1 | ClickHouse 메모리 사용률 | 컨테이너 메모리 사용률 (%) | Grafana (resource-monitor) | 자동 측정 |
| SLI-CAP2 | NFR-CAP2 | Producer CPU 사용률 | 컨테이너 CPU 사용률 (%) | Grafana (resource-monitor) | 자동 측정 |
| SLI-CAP3 | NFR-CAP3 | 전체 컨테이너 합산 메모리 사용량 | 전체 컨테이너 `mem_mb` 합계 (MB) | Grafana (resource-monitor) | 자동 측정 |

**SLI-CAP1, SLI-CAP2 측정 방법 (Grafana)**

`resource-monitor` 서비스가 10초 간격으로 `mem_pct`, `cpu_pct`를 수집하여 Loki에 구조화 로그로 기록. Grafana Resources 대시보드에서 실시간 확인 및 이상 감지(z-score > 2.5) 알림 연동.

**SLI-CAP3 측정 쿼리 (Loki)**
```logql
sum(avg by (target_container) (last_over_time({container="resource-monitor"} |= "DockerStats" | logfmt | unwrap mem_mb [1m])))
```
`avg by (target_container)`로 컨테이너당 1개 시리즈로 축소 후 합산. logfmt이 cpu_pct·mem_pct 등 변동 필드를 레이블로 취급해 동일 컨테이너의 샘플이 여러 시리즈로 분리되는 문제를 방지. 컨테이너 추가·제거 시 자동 반영.

---

## 9. 계측 현황 요약

| SLI ID | 연결 NFR | 상태 | 비고 |
|--------|----------|------|------|
| SLI-P1 | NFR-P1 | **완료** (2026-03-06) | `batch_processing_seconds` logfmt 로그 추가 |
| SLI-P2 | NFR-P2 | **완료** (2026-03-06) | `batch_size` logfmt 로그 추가 |
| SLI-R5 | NFR-R5 | **부분 완료** (2026-03-06) | `sse_received_total` 추가, ClickHouse 대조 기준 관측 중 |
| SLI-CAP3 | NFR-CAP3 | **완료** (2026-03-06) | `resource-monitor` `mem_mb` 합산 Loki 쿼리로 측정 가능 |
| SLI-RC4 | NFR-RC4 | **미완료** | S3 백업 구현 후 백업 완료 타임스탬프 로그 기록 |
| SLI-RC5 | NFR-RC5 | **미완료** | 복원 runbook 실행 시 소요 시간 수동 기록 체계 마련 |
미완료 SLI는 **SLO 범위에서 제외**하며, 보강 완료 후 다음 리뷰 주기에 SLO 포함 여부를 결정합니다.
