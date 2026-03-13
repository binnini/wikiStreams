# WikiStreams 서비스 수준 지표 (SLI)

> 작성일: 2026-03-05
> 최종 수정: 2026-03-13 (Loki/Alloy 제거 반영 — QuestDB producer_slo_metrics 이관)
> 목적: NFR.md의 각 요구사항을 실제로 측정 가능한 지표로 변환
> 선행 산출물: NFR.md
> 후행 산출물: SLO.md

---

## 1. 측정 분류 기준

| 분류 | 의미 |
|------|------|
| **자동 측정** | Grafana/QuestDB 쿼리로 상시 관측 가능 |
| **수동 측정** | docker logs 또는 쿼리를 사람이 직접 조회해야 확인 가능 |
| **계측 불가** | 현재 코드·인프라에 측정 수단 없음 → 계측 보강 필요 |

> **참고**: Loki/Alloy는 2026-03-12 제거됨. SLO 핵심 지표(P1/P7/R1)는 QuestDB `producer_slo_metrics`로 이관. 일반 애플리케이션 로그는 `docker compose logs`로만 접근 가능.

---

## 2. 가용성 (Availability) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-A1 | NFR-A1 | Producer 재연결 소요 시간 | 연결 끊김 로그 ~ 재연결 성공 로그 간 초 | docker logs (수동) | 수동 측정 |
| SLI-A2 | NFR-A2 | QuestDB 쿼리 가용성 | 단위 시간당 QuestDB REST API 쿼리 성공 비율 (%) | QuestDB REST API + `pytest -m slo` | 자동 측정 |
| SLI-A3 | NFR-A3 | Reporter 일일 발송 성공 여부 | 하루 1회 "Publish complete" 로그 존재 여부 (0 또는 1) | docker logs (수동) | 수동 측정 |

**SLI-A1 측정 방법 (docker logs)**

연결 끊김 시 `collector.py`가 아래 형식으로 기록:
```
❌ HTTPX 오류 발생: ... — N초 후 재연결 시도...
✅ Wikimedia SSE 스트림에 성공적으로 연결되었습니다.
```
두 로그의 타임스탬프 차이가 재연결 소요 시간. `docker compose logs producer`로 수동 확인.

**SLI-A2 측정 방법 (QuestDB REST API)**

QuestDB는 `system.query_log`를 제공하지 않으므로 직접 쿼리 시도 성공/실패로 측정:
```python
# test_slo_a2_questdb_availability (tests/integration/test_slo.py)
# 10회 쿼리 시도 후 성공 비율 산출
GET http://localhost:9000/exec?query=SELECT+count(1)+FROM+wikimedia_events&fmt=json
```
HTTP 200 응답 + `"error"` 키 부재 = 성공. `pytest -m slo` 또는 Grafana Infinity 플러그인으로 자동 폴링.

**SLI-A3 측정 방법 (docker logs)**
```bash
docker compose logs reporter | grep "Publish complete"
```
당일 로그에 존재하면 발송 성공. 수동 확인 또는 일별 cron 스크립트로 자동화 가능.

---

## 3. 성능 (Performance) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-P1 | NFR-P1 | 배치 처리 소요 시간 | 배치 콜백 시작 ~ Redpanda flush 완료까지 초 | QuestDB `producer_slo_metrics` | 자동 측정 |
| SLI-P2 | NFR-P2 | 배치 크기 | 배치당 처리 이벤트 수 | QuestDB `producer_slo_metrics` | 자동 측정 |
| SLI-P3 | NFR-P3 | QuestDB 쿼리 응답 시간 | 쿼리 실행 시간 p99 (ms) | QuestDB REST API 클라이언트 측 타이밍 + `pytest -m slo` | 자동 측정 |
| SLI-P4 | NFR-P4 | Reporter 파이프라인 소요 시간 | "Starting report build" ~ "Publish complete" 로그 간 초 | docker logs (수동) | 수동 측정 |
| SLI-P5 | NFR-P5 | Producer 지속 처리량 | 단위 시간당 Redpanda 발행 이벤트 수 (events/min) | QuestDB (`wikimedia_events` count) | 자동 측정 |
| SLI-P7 | NFR-P7 | Wikidata 캐시 히트율 | 전체 Wikidata 조회 중 캐시에서 응답한 비율 (%) | QuestDB `producer_slo_metrics` | 자동 측정 |

**SLI-P1 측정 쿼리 (QuestDB `producer_slo_metrics`)**
```sql
SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY batch_processing_seconds) AS p95
FROM producer_slo_metrics
WHERE timestamp > dateadd('d', -1, now())
```
`pytest -m slo` (test_slo_p1)로 자동 검증.

**SLI-P2 측정 쿼리 (QuestDB `producer_slo_metrics`)**
```sql
SELECT percentile_cont(0.50) WITHIN GROUP (ORDER BY batch_size) AS p50
FROM producer_slo_metrics
WHERE timestamp > dateadd('d', -1, now())
```

**SLI-P3 측정 방법 (클라이언트 측 타이밍)**

QuestDB는 `system.query_log`를 제공하지 않으므로 클라이언트 측 `time.perf_counter()`로 측정:
```python
# test_slo_p3_query_latency (tests/integration/test_slo.py)
# Reporter 실제 쿼리 패턴 10회 반복, p99 산출
sql = "SELECT count(1) AS total, sum(CASE WHEN bot = true THEN 1 ELSE 0 END) AS bot_count " \
      "FROM wikimedia_events WHERE timestamp > dateadd('d', -1, now())"
```
Grafana 패널 로드 시간(PostgreSQL 와이어 프로토콜 → QuestDB 8812포트)으로도 관측 가능.

**SLI-P4 측정 방법 (docker logs)**

`reporter/main.py`의 로그 순서:
```
INFO ... Starting report build       ← 시작
INFO ... Publish complete            ← 완료 (또는 ERROR ... Failed to run report)
```
두 로그의 타임스탬프 차이가 파이프라인 소요 시간. `docker compose logs reporter`로 수동 조회.

**SLI-P5 측정 쿼리 (QuestDB)**
```sql
SELECT count(1) AS cnt
FROM wikimedia_events
WHERE timestamp > dateadd('mi', -5, now())
```
결과 `cnt / 5` = events/min. Grafana Producer Performance 대시보드 `Events/Min` 패널 + `pytest -m slo` (test_slo_p5)로 자동 집계 중.

**SLI-P7 측정 쿼리 (QuestDB `producer_slo_metrics`)**
```sql
SELECT avg((total_enriched - new_api_calls) * 100.0 / total_enriched) AS cache_hit_rate
FROM producer_slo_metrics
WHERE timestamp > dateadd('mi', -10, now())
  AND total_enriched > 0
```
공식: `(total_enriched - new_api_calls) / total_enriched × 100`. Grafana SLO 대시보드에서 실시간 확인.

---

## 4. 신뢰성 (Reliability) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-R1 | NFR-R1 | DLQ 유입 비율 | DLQ 라우팅 이벤트 수 / 전체 처리 이벤트 수 × 100 (%) | QuestDB `producer_slo_metrics` | 자동 측정 |
| ~~SLI-R2~~ | ~~NFR-R2~~ | ~~DLQ 재처리 시도 횟수~~ | ~~DLQ 컨슈머 재시도 로그 카운트~~ | ~~폐기~~ | ~~C2 제거로 폐기 (2026-03-07)~~ |
| SLI-R3 | NFR-R3 | 재연결 소요 시간 | SLI-A1과 동일 | docker logs (수동) | 수동 측정 |
| SLI-R4 | NFR-R4 | Reporter 오류 후 다음 발송 성공 여부 | ERROR 로그 발생 후 익일 SLI-A3 = 1 여부 | docker logs (수동) | 수동 측정 |
| SLI-R5 | NFR-R5 | 파이프라인 완전성 | SSE 수신 이벤트 수 대비 QuestDB 적재 이벤트 수 비율 (%) | docker logs + QuestDB | 수동 측정 |

**SLI-R1 측정 쿼리 (QuestDB `producer_slo_metrics`)**
```sql
SELECT sum(dlq_count) * 100.0 / sum(batch_size) AS dlq_rate
FROM producer_slo_metrics
WHERE timestamp > dateadd('mi', -5, now())
```
`pytest -m slo` (test_slo_r1)으로 자동 검증.

**SLI-R5 측정 방법**

`collector.py`에 SSE 수신 누적 카운터(`sse_received_total`)가 기록됨. `docker compose logs producer`에서 확인 가능.
`sse_received_total`은 프로세스 재시작 시 초기화되므로, QuestDB `count(1)`와의 절대값 비교는 불가. 배치 단위 유입량 대비 QuestDB 적재량의 상대적 추이로 유실 여부 관찰.

---

## 5. 데이터 품질 (Data Quality) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-D1 | NFR-D1 | 데이터 신선도 (Lag) | `now() - max(timestamp)` (초) | QuestDB + `pytest -m slo` | 자동 측정 |
| SLI-D2 | NFR-D2 | Wikidata 레이블 보강률 | Q-ID 이벤트 중 `wikidata_label != ''` 비율 (%) | QuestDB + `pytest -m slo` | 자동 측정 |
| SLI-D3 | NFR-D3 | 캐시 TTL 준수 | 설정값(`CACHE_TTL_SECONDS`, `CACHE_MISSING_TTL_SECONDS`) 일치 여부 | 코드 검증 | 수동 측정 |

**SLI-D1 측정 쿼리 (QuestDB)**
```sql
SELECT max(timestamp) AS latest FROM wikimedia_events
```
`now(UTC) - latest` 차이(초)를 클라이언트에서 계산. `pytest -m slo` (test_slo_d1) 자동 검증.

**SLI-D2 측정 쿼리 (QuestDB)**
```sql
SELECT
    count(1) AS total,
    sum(CASE WHEN wikidata_label <> '' THEN 1 ELSE 0 END) AS labeled
FROM wikimedia_events
WHERE timestamp > dateadd('h', -24, now())
  AND title LIKE 'Q%'
  AND server_name = 'www.wikidata.org'
```
`labeled / total × 100` = 보강률(%). `pytest -m slo` (test_slo_d2) 자동 검증.

---

## 6. ~~유지보수성 (Maintainability) SLI~~

~~SLI-M4 (NFR-M4): Loki 로그 보존 기간 측정~~ → **Loki/Alloy 제거(2026-03-12)로 폐기**. NFR-M4와 함께 비활성화.

---

## 7. 복구성 (Recoverability) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-RC1 | NFR-RC1 | 컴포넌트 독립 복구 | 단일 컨테이너 재시작 시 타 컨테이너 에러 로그 발생 여부 | docker logs (수동) | 수동 측정 |
| SLI-RC2 | NFR-RC2 | 재시작 후 이벤트 연속성 | 재시작 전후 QuestDB 이벤트 카운트 갭 | QuestDB | 수동 측정 |
| SLI-RC3 | NFR-RC3 | 데이터 영속성 | 컨테이너 재시작 전후 `count(1)` 동일 여부 | QuestDB | 수동 측정 |
| SLI-RC4 | NFR-RC4 | RPO (백업 주기 준수) | 마지막 S3 업로드 완료 타임스탬프 ~ 현재 시각 간격 | S3 Exporter 로그 (docker logs) | 수동 측정 |
| SLI-RC5 | NFR-RC5 | RTO (복원 소요 시간) | 장애 감지 ~ 서비스 복원 완료까지 소요 시간 (분) | 수동 기록 | **계측 불가** |

**SLI-RC2, RC3 측정 쿼리 (QuestDB)**
```sql
-- 재시작 전후 비교용
SELECT count(1) AS total_events, max(timestamp) AS latest
FROM wikimedia_events
```

---

## 8. 용량 (Capacity) SLI

| SLI ID | 연결 NFR | 지표 이름 | 측정값 | 측정 도구 | 분류 |
|--------|----------|-----------|--------|-----------|------|
| SLI-CAP1 | NFR-CAP1 | QuestDB 메모리 사용량 | 컨테이너 RSS (MiB) vs mem_limit 1100m의 80% | Grafana (resource-monitor) + `pytest -m slo` | 자동 측정 |
| SLI-CAP2 | NFR-CAP2 | Producer CPU 사용률 | 컨테이너 CPU 사용률 (%) | Grafana (resource-monitor) | 자동 측정 |
| SLI-CAP3 | NFR-CAP3 | 전체 컨테이너 합산 메모리 사용량 | 전체 컨테이너 `mem_mb` 합계 (MB) | Grafana (resource-monitor) | 자동 측정 |

**SLI-CAP1, SLI-CAP2 측정 방법 (Grafana)**

`resource-monitor` 서비스가 10초 간격으로 `mem_pct`, `cpu_pct`를 수집. Grafana Resources 대시보드에서 실시간 확인 및 이상 감지(z-score ≥ 3.0) Slack 알림 연동.

SLI-CAP1은 추가로 `docker stats questdb`로 RSS(MiB)를 직접 조회 가능. `pytest -m slo` (test_slo_cap1)에서 880 MiB 임계값 자동 검증.

---

## 9. 계측 현황 요약

| SLI ID | 연결 NFR | 상태 | 비고 |
|--------|----------|------|------|
| SLI-P1 | NFR-P1 | **완료** (2026-03-06, QuestDB 이관 2026-03-12) | `producer_slo_metrics.batch_processing_seconds` |
| SLI-P2 | NFR-P2 | **완료** (2026-03-06, QuestDB 이관 2026-03-12) | `producer_slo_metrics.batch_size` |
| SLI-R2 | NFR-R2 | **폐기** (2026-03-07) | DLQ Consumer 제거로 불필요 |
| SLI-M4 | NFR-M4 | **폐기** (2026-03-12) | Loki/Alloy 제거로 불필요 |
| SLI-R5 | NFR-R5 | **부분 완료** | `sse_received_total` docker logs 확인, QuestDB 대조 기준 관측 중 |
| SLI-A2, P3, D1, D2, CAP1 | 각 NFR | **완료** (2026-03-10) | `pytest -m slo` SLO 테스트로 자동 검증 |
| SLI-RC4 | NFR-RC4 | **부분 완료** | S3 Exporter 운영 중(2026-03-11~), 완료 타임스탬프 로그 확인 필요 |
| SLI-RC5 | NFR-RC5 | **미완료** | 복원 runbook 실행 시 소요 시간 수동 기록 체계 마련 필요 |

미완료 SLI는 **SLO 범위에서 제외**하며, 보강 완료 후 다음 리뷰 주기에 SLO 포함 여부를 결정합니다.
