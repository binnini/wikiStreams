# WikiStreams 서비스 수준 협약 (SLA)

> 작성일: 2026-03-06
> 최종 수정: 2026-03-13 (아키텍처 경량화 완료 반영 — Redpanda + QuestDB + Slack 기준)
> 상태: **v2 baseline 수집 중** (~2026-03-17 SLO 수치 확정 예정)
> 선행 산출물: NFR.md, SLI.md, SLO.md
> 적용 범위: WikiStreams 홈랩 데이터 파이프라인 운영자(개인)

---

## 1. SLA 개요

### 1.1 목적

SLO.md에 정의된 서비스 수준 목표를 기반으로, 서비스 운영자(본인)가 자기 자신에게 약속하는 **책임 범위, 위반 처리 절차, 보고 주기**를 명시한다.

이 SLA는 외부 고객과의 계약이 아닌 **홈랩 운영 규율(self-imposed discipline)**이며, 운영 품질 추적과 개선의 기준점으로 활용한다.

### 1.2 당사자

| 역할 | 내용 |
|------|------|
| 서비스 제공자 | WikiStreams 운영자 (개인) |
| 서비스 사용자 | 운영자 본인, Grafana 대시보드 열람자 |

### 1.3 서비스 범위

| 서비스 | 범위 |
|--------|------|
| 실시간 이벤트 수집 | Wikimedia SSE → Redpanda → QuestDB 파이프라인 |
| 대시보드 | Grafana Analytics, SLO, Producer Performance 대시보드 |
| 일일 리포트 | Slack 리포트 (매일 09:00 KST) |
| 알림 | Slack SLO 위반 알림 + resource-monitor 이상 감지 알림 |
| Datalake | 일일 Parquet → S3 (01:00 UTC) |

---

## 2. 서비스 가용성 약속

### 2.1 가용성 목표

| 서비스 | SLO | 월간 허용 다운타임 |
|--------|-----|-------------------|
| QuestDB (쿼리 가능) | 99% | 7.2시간 / 30일 |
| 일일 Slack 리포트 | 90% (월 27회 이상) | 3회 누락 허용 |

### 2.2 외부 의존성 제외

아래 외부 서비스 장애로 인한 SLO 위반은 가용성 계산에서 제외한다:

- Wikimedia SSE API 장애 (이벤트 수집 중단)
- Wikidata REST API 장애 (레이블 보강 불가)
- Anthropic Claude API 장애 (리포트 생성 불가)
- Slack Webhook 장애 (리포트/알림 발송 불가)
- Google News RSS 장애 (뉴스 섹션 누락)
- S3 Compatible Storage 장애 (백업 불가)

외부 장애 여부는 해당 서비스의 공식 상태 페이지 또는 로그 패턴으로 판단한다.

---

## 3. 성능 약속

| 항목 | SLO | v2 실측 |
|------|-----|---------|
| QuestDB 쿼리 응답 p99 | ≤ 200ms | 4~30ms ✅ |
| 배치 처리 소요 시간 p95 | ≤ 2초 | 0.72s ✅ |
| Producer 처리량 | ≥ 800 events/min (95% 시간대) | ~1,000/min ✅ |
| Wikidata 캐시 히트율 | ≥ 80% (90% 시간대) | 94% ✅ |

---

## 4. SLO 위반 처리 절차

### 4.1 위반 감지

| 방법 | 내용 |
|------|------|
| **자동 감지** | Grafana Alert Rule → Slack 알림 (SLI-D1, SLI-R1, SLI-P7, SLI-CAP1, SLI-CAP2) |
| **이상 감지** | resource-monitor z-score 기반 → Slack 알림 (CPU/메모리 급증) |
| **수동 확인** | 월 1회 SLO 대시보드 검토 (에러 버짓 잔량, 30일 달성률) |

### 4.2 대응 우선순위

| 심각도 | 조건 | 대응 목표 시간 |
|--------|------|----------------|
| **critical** | QuestDB 메모리 > 80% / 데이터 신선도 lag > 5분 | 30분 이내 확인 및 조치 시작 |
| **warning** | SLO 위반 감지 (D1, R1, P7, CAP2, A3) | 당일 내 원인 파악 |
| **info** | 에러 버짓 소진률 75% 초과 | 주간 리뷰 시 검토 |

### 4.3 위반 처리 흐름

```
Slack 알림 수신
  → Grafana SLO 대시보드 확인 (어떤 SLI인지 파악)
  → 원인 분석 (docker compose logs, QuestDB 쿼리, resource-monitor)
  → 조치 (서비스 재시작 / 설정 변경 / 운영자 개입)
  → DEV_LOG.md에 장애 내용 기록
  → 월간 SLO 리뷰 시 재발 방지책 검토
```

### 4.4 장애 기록 기준

아래 조건 중 하나라도 해당하면 `docs/DEV_LOG.md`에 장애 항목 추가:
- SLO 위반 지속 시간 ≥ 30분
- 일일 리포트 누락
- QuestDB 데이터 손실 발생
- 에러 버짓 소진률 100% 도달

---

## 5. 데이터 보존 및 복구 약속

### 5.1 데이터 보존

| 데이터 | 보존 기간 | 저장 위치 |
|--------|----------|-----------|
| QuestDB 이벤트 | 5일 (TTL) | Docker volume `questdb_data` |
| Parquet Datalake | 무기한 | AWS S3 (`events/year=YYYY/month=MM/day=DD/`) |
| Wikidata SQLite 캐시 | 30일 TTL (정상 엔티티) | Docker volume `producer_cache` |
| Slack 리포트 JSON | 무기한 | `./reports/` 디렉토리 |

### 5.2 복구 목표

| 지표 | 목표 | 현재 상태 |
|------|------|-----------|
| RPO (Recovery Point Objective) | ≤ 1일 | S3 Exporter 운영 중 (2026-03-11~). 일 1회 백업. |
| RTO (Recovery Time Objective) | ≤ 30분 | S3 복원 + 컨테이너 재시작 포함. runbook 미작성. |

**비고**: 호스트 장애 시 당일 QuestDB 데이터(최대 1일치)는 손실 가능. 역사 데이터는 S3 Parquet으로 복구 가능 (DuckDB로 직접 조회 가능).

---

## 6. 보고 및 리뷰

### 6.1 월간 SLO 리뷰

매월 1일에 아래 항목을 검토한다:

1. **SLO 달성률** — Grafana SLO 대시보드에서 30일 롤링 윈도우 기준 각 SLO 달성 여부 확인
2. **에러 버짓 현황** — 각 SLO별 에러 버짓 소진률 기록
3. **주요 위반 사례** — DEV_LOG.md에서 해당 월 장애 항목 검토
4. **외부 의존성 제외 판정** — 위반 사례 중 외부 장애 기인 건 분리
5. **SLO 목표 재조정 여부** — 3개월 연속 달성 시 목표 강화, 2개월 연속 미달 시 목표 완화 또는 개선 과제 등록

### 6.2 SLO 목표 조정 기준

| 조건 | 조치 |
|------|------|
| 3개월 연속 목표 초과 달성 | SLO 목표 상향 조정 (다음 리뷰 시) |
| 2개월 연속 목표 미달 | 원인 분석 후 목표 하향 조정 또는 개선 과제 TODO 등록 |
| 외부 환경 변화 (Wikimedia 처리량 급증 등) | 관측 2주 후 임시 SLO 조정 가능 |

### 6.3 SLA 갱신 주기

| 이벤트 | SLA 갱신 필요 여부 |
|--------|-------------------|
| S3 복원 runbook 작성 완료 | 필요 (RTO 조항 구체화) |
| SLO 목표 수치 변경 | 필요 (§3 성능 약속 업데이트) |
| 신규 SLI 계측 추가 및 SLO 편입 | 필요 |
| 아키텍처 주요 변경 | 필요 |

---

## 7. 현재 SLO 적용 상태

| SLO ID | 상태 | 비고 |
|--------|------|------|
| SLO-A2 | 적용 중 | v2 baseline 장기 수집 중 (~2026-03-17) |
| SLO-A3 | 적용 중 | Claude/Slack 장애 제외 조건 적용 |
| SLO-P1 | 적용 중 | v2 실측 p95=0.72s ✅ |
| SLO-P3 | 적용 중 | v2 실측 p99=4~30ms ✅ |
| SLO-P5 | 적용 중 | v2 실측 ~1,000/min ✅ |
| SLO-P7 | 적용 중 | v2 실측 94% ✅ |
| SLO-R1 | 적용 중 | near-zero ✅ |
| SLO-D1 | 적용 중 | v2 실측 ~9s ✅; Grafana 알림 연동 완료 |
| SLO-D2 | 적용 중 | v2 실측 79~88% ⚠️ 목표 재검토 예정 |
| SLO-CAP1 | 적용 중 | v2 실측 285~500 MiB ✅; Grafana critical 알림 연동 완료 |
| SLO-CAP2 | 적용 중 | v2 실측 1~7% ✅ |
| SLO-RC4 (RPO) | **부분 적용** | S3 Exporter 운영 중 (일 1회 백업). runbook 미작성. |
| SLO-RC5 (RTO) | **미적용** | runbook 작성 후 활성화 |
