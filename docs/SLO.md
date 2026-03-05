# WikiStreams 서비스 수준 목표 (SLO)

> 작성일: 2026-03-06
> 상태: **초기 목표값** (관측 기간 완료 후 수치 검증 예정)
> 선행 산출물: NFR.md, SLI.md
> 후행 산출물: SLA.md
> 측정 기간: 30일 롤링 윈도우

---

## 1. SLO 개요

### 1.1 목적

실측 데이터 없이 NFR.md 요구사항에서 도출한 **초기 목표값**이다.
1~4주 관측 기간(Stage 4) 완료 후 baseline 데이터를 반영하여 수치를 검증·조정한다.

### 1.2 측정 기간

| 항목 | 값 |
|------|----|
| 롤링 윈도우 | 30일 |
| 최소 관측 기간 (SLO 확정 전) | 4주 |
| 리뷰 주기 | 월 1회 |

### 1.3 에러 버짓 계산 기준

```
에러 버짓(분) = 30일 × 24h × 60min × (1 - SLO 목표)
에러 버짓 소진률(%) = 실제 위반 시간 / 에러 버짓 × 100
```

소진률 75% 초과 시 Discord 경고 알림 발송.

### 1.4 외부 의존성 제외

아래 외부 서비스 장애로 인한 SLI 위반은 에러 버짓 소진에서 제외한다 (NFR.md §2 기준):
- Wikimedia SSE API 장애
- Wikidata REST API 장애
- Anthropic Claude API 장애
- Discord Webhook 장애
- Google News RSS 장애
- S3 Compatible Storage 장애

---

## 2. 가용성 (Availability) SLO

### SLO-A2: ClickHouse 쿼리 가용성

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-A2 |
| 연결 NFR | NFR-A2 |
| **목표** | **쿼리 성공률 ≥ 99% (30일 롤링)** |
| 측정 쿼리 | `system.query_log` `QueryFinish` 비율 |
| 측정 도구 | ClickHouse → Grafana SLO 대시보드 |

**에러 버짓**: 30일 × 1% = 432분 (7.2시간)

**SLO 달성 조건**: 30일 중 ClickHouse 쿼리 성공률이 99% 이상 유지되는 시간이 전체의 99% 이상.

---

### SLO-A3: Reporter 일일 발송 성공률

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-A3 |
| 연결 NFR | NFR-A3 |
| **목표** | **월간 발송 성공 ≥ 27회 / 30일 (= 90%)** |
| 측정 도구 | Loki: `count_over_time({container="reporter"} \|= "Publish complete" [1d])` |

**에러 버짓**: 30일 중 3회 누락 허용.

**비고**: Claude API 또는 Discord 장애로 인한 누락은 에러 버짓에서 제외.

---

## 3. 성능 (Performance) SLO

### SLO-P1: 배치 처리 소요 시간

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-P1 |
| 연결 NFR | NFR-P1 |
| **목표** | **p95 ≤ 5초 (캐시 히트 기준, 30일 롤링)** |
| 측정 도구 | Loki: `batch_processing_seconds` logfmt 필드 |
| 계측 현황 | 2026-03-06 계측 추가 완료 |

**비고**: Wikidata API 신규 호출(캐시 미스) 구간은 외부 의존성으로 별도 처리.
초기 관측 기간 중 실제 p95 분포 확인 후 목표값 조정 예정.

---

### SLO-P3: ClickHouse 쿼리 응답 시간

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-P3 |
| 연결 NFR | NFR-P3 |
| **목표** | **p99 ≤ 1초 (1시간 기준, 30일 롤링)** |
| 측정 쿼리 | `system.query_log` `quantile(0.99)(query_duration_ms)` |
| 측정 도구 | ClickHouse → Grafana SLO 대시보드 |

**에러 버짓**: p99가 1초를 초과하는 쿼리 비율 ≤ 1%.

---

### SLO-P5: Producer 지속 처리량

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-P5 |
| 연결 NFR | NFR-P5 |
| **목표** | **≥ 300 events/min (5분 이동 평균, 30일 롤링의 95% 시간대)** |
| 측정 도구 | ClickHouse `wikimedia.events` count / interval |

**비고**: Wikimedia SSE 스트림 자체 처리량이 낮은 시간대(심야 UTC)에는 300 미달이 자연스러울 수 있음. 관측 기간 중 시간대별 패턴 파악 후 재조정.

---

### SLO-P7: Wikidata 캐시 히트율

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-P7 |
| 연결 NFR | NFR-P7 |
| **목표** | **≥ 80% (10분 이동 평균, 30일 롤링의 90% 시간대)** |
| 측정 도구 | Grafana Producer Performance 대시보드 |

**에러 버짓**: 30일 중 캐시 히트율 80% 미만인 시간대 ≤ 72시간 (10%).

---

## 4. 신뢰성 (Reliability) SLO

### SLO-R1: 이벤트 DLQ 유입 비율

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-R1 |
| 연결 NFR | NFR-R1 |
| **목표** | **DLQ 유입 비율 ≤ 1% (5분 이동 창 기준, 30일 롤링의 99% 시간대)** |
| 측정 도구 | Loki: DLQ 라우팅 로그 / 전체 전송 로그 비율 |

**에러 버짓**: DLQ 비율 1% 초과 시간 ≤ 7.2시간 / 30일.

---

## 5. 데이터 품질 (Data Quality) SLO

### SLO-D1: 데이터 신선도

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-D1 |
| 연결 NFR | NFR-D1 |
| **목표** | **lag ≤ 30초 (30일 롤링의 99% 시간대)** |
| 측정 쿼리 | `SELECT dateDiff('second', max(event_time), now()) FROM wikimedia.events` |
| 측정 도구 | ClickHouse → Grafana SLO 대시보드 |

**에러 버짓**: lag > 30초인 시간 ≤ 7.2시간 / 30일.

**Grafana 알림**: lag > 30초 2분 지속 시 Discord 경고 (SLI-D1 알림 규칙).

---

### SLO-D2: Wikidata 레이블 보강률

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-D2 |
| 연결 NFR | NFR-D2 |
| **목표** | **Q-ID 이벤트 중 레이블 보강 성공률 ≥ 90% (24시간 기준)** |
| 측정 쿼리 | `countIf(wikidata_label != '') / count()` WHERE `title LIKE 'Q%'` |
| 측정 도구 | ClickHouse → Grafana SLO 대시보드 |

**비고**: Wikidata API 장애 또는 신규 엔티티 비율에 따라 변동 가능. 초기 관측 후 재조정 예정.

---

## 6. 용량 (Capacity) SLO

### SLO-CAP1: ClickHouse 메모리 사용률

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-CAP1 |
| 연결 NFR | NFR-CAP1 |
| **목표** | **메모리 사용률 ≤ 80% (30일 롤링의 99% 시간대)** |
| 측정 도구 | Grafana resource-monitor `mem_pct` |

**에러 버짓**: 메모리 80% 초과 시간 ≤ 7.2시간 / 30일.

**Grafana 알림**: 80% 초과 5분 지속 시 Discord critical 알림.

---

### SLO-CAP2: Producer CPU 사용률

| 항목 | 값 |
|------|----|
| 연결 SLI | SLI-CAP2 |
| 연결 NFR | NFR-CAP2 |
| **목표** | **CPU 사용률 ≤ 70% (30일 롤링의 95% 시간대)** |
| 측정 도구 | Grafana resource-monitor `cpu_pct` |

**에러 버짓**: CPU 70% 초과 시간 ≤ 36시간 / 30일 (5%).

---

## 7. SLO 제외 항목

아래 SLI는 현재 계측 불가 상태이므로 SLO 범위에서 제외한다.
계측 보강 완료 후 다음 리뷰 주기에 SLO에 포함 여부를 결정한다.

| SLI ID | 제외 이유 | 보강 필요 작업 |
|--------|-----------|----------------|
| SLI-P2 | 배치 크기 로그 추가됨(2026-03-06), 관측 데이터 부족 | 1~2주 관측 후 SLO 수치 설정 |
| SLI-P6 | Kafka 컨슈머 레그 Grafana 미연동 | JMX Exporter 또는 polling 스크립트 추가 |
| SLI-R5 | SSE 수신 카운터 추가됨(2026-03-06), ClickHouse 대조 기준 미정 | 관측 후 유실률 baseline 파악 |
| SLI-RC4 | S3 백업 미구현 | S3 Datalake 도입 후 추가 |
| SLI-RC5 | 복원 runbook 미작성 | runbook 작성 및 복원 테스트 후 추가 |
| SLI-CAP3 | 호스트 디스크 모니터링 미구현 | node-exporter 또는 df 스크립트 추가 |

---

## 8. SLO 요약표

| SLO ID | SLI | 목표 | 에러 버짓 (30일) | 알림 |
|--------|-----|------|-----------------|------|
| SLO-A2 | SLI-A2 | ClickHouse 쿼리 성공률 ≥ 99% | 432분 | — |
| SLO-A3 | SLI-A3 | 월 발송 ≥ 27회 | 3회 누락 | 당일 미발송 |
| SLO-P1 | SLI-P1 | 배치 처리 p95 ≤ 5s | — | — |
| SLO-P3 | SLI-P3 | 쿼리 응답 p99 ≤ 1s | — | — |
| SLO-P5 | SLI-P5 | 처리량 ≥ 300 events/min (95% 시간대) | 36시간 | — |
| SLO-P7 | SLI-P7 | 캐시 히트율 ≥ 80% (90% 시간대) | 72시간 | < 80% 10분 지속 |
| SLO-R1 | SLI-R1 | DLQ 비율 ≤ 1% (99% 시간대) | 7.2시간 | > 1% 3분 지속 |
| SLO-D1 | SLI-D1 | 데이터 lag ≤ 30s (99% 시간대) | 7.2시간 | > 30s 2분 지속 |
| SLO-D2 | SLI-D2 | 레이블 보강률 ≥ 90% | — | — |
| SLO-CAP1 | SLI-CAP1 | ClickHouse 메모리 ≤ 80% (99% 시간대) | 7.2시간 | > 80% 5분 지속 (critical) |
| SLO-CAP2 | SLI-CAP2 | Producer CPU ≤ 70% (95% 시간대) | 36시간 | > 70% 10분 지속 |

---

## 9. 다음 단계

| 단계 | 내용 | 예상 완료 |
|------|------|----------|
| Stage 4 (진행 중) | 1~4주 관측. SLO 대시보드에서 각 SLI baseline 수집 | 2026-04-06 이전 |
| SLO 검증 리뷰 | 관측 데이터 기반 목표 수치 조정 | 관측 완료 후 |
| SLA.md 확정 | SLO 기반 책임 범위 및 위반 처리 최종화 | SLO 확정 후 |
