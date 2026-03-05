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
| SLI-P1 | NFR-P1 | 배치 처리 소요 시간 | 배치 콜백 시작 ~ Kafka flush 완료까지 초 | — | **계측 불가** |
| SLI-P2 | NFR-P2 | 배치 크기 | 배치당 처리 이벤트 수 | — | **계측 불가** |
| SLI-P3 | NFR-P3 | ClickHouse 쿼리 응답 시간 | 쿼리 실행 시간 ≤ 1(초) | ClickHouse `system.query_log` | 자동 측정 |
| SLI-P4 | NFR-P4 | Reporter 파이프라인 소요 시간 | "Starting report build" ~ "Publish complete" 로그 간 초 | Loki | 수동 측정 |

**SLI-P1, SLI-P2 계측 공백**

`main.py`의 `process_batch()`와 `collector.py`의 `_process_buffer()`에 타이밍 로그가 없음. 측정하려면 두 함수에 `time.perf_counter()` 기반 로그 추가 필요.

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

---

## 4. 신뢰성 (Reliability) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-R1 | NFR-R1 | DLQ 유입 비율 | DLQ 라우팅 이벤트 수 / 전체 처리 이벤트 수 × 100 (%) | Loki | 자동 측정 |
| SLI-R2 | NFR-R2 | DLQ 재처리 시도 횟수 | DLQ 컨슈머의 재시도 로그 카운트 | Loki | 자동 측정 |
| SLI-R3 | NFR-R3 | 재연결 소요 시간 | SLI-A1과 동일 | Loki | 수동 측정 |
| SLI-R4 | NFR-R4 | Reporter 오류 후 다음 발송 성공 여부 | ERROR 로그 발생 후 익일 SLI-A3 = 1 여부 | Loki | 수동 측정 |

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

## 6. 복구성 (Recoverability) SLI

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

## 7. 계측 공백 요약

SLO/SLA 수립 전 아래 항목에 대한 계측 보강이 필요합니다.

| SLI ID | 연결 NFR | 필요 보강 내용 |
|--------|----------|----------------|
| SLI-P1 | NFR-P1 | `process_batch()` 시작·종료 시 `time.perf_counter()` 로그 추가 |
| SLI-P2 | NFR-P2 | `_process_buffer()` 호출 시 배치 크기 로그 추가 |
| SLI-RC4 | NFR-RC4 | S3 백업 구현 후 백업 완료 타임스탬프 로그 기록 |
| SLI-RC5 | NFR-RC5 | 복원 runbook 실행 시 소요 시간 수동 기록 체계 마련 |

계측 불가 SLI는 **SLO 범위에서 제외하거나**, 보강 완료 후 SLO에 포함합니다.
