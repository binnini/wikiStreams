# WikiStreams 비기능 요구사항 (NFR)

> 작성일: 2026-03-05
> 목적: SLI/SLO/SLA 도출을 위한 선행 산출물
> 범위: WikiStreams 홈랩 데이터 파이프라인 전체 (Producer → Kafka → ClickHouse → Reporter/Grafana)

---

## 1. 배경 및 컴포넌트 정의

WikiStreams는 다음 5개 컴포넌트로 구성된다. 각 컴포넌트는 독립적으로 배포·운영되며, Docker Compose 단일 호스트 환경에서 실행된다.

| ID | 컴포넌트 | 역할 | 실행 형태 |
|----|----------|------|-----------|
| C1 | Producer | Wikimedia SSE 구독 → Kafka 발행 | 상시 실행 (무중단) |
| C2 | DLQ Consumer | 실패 이벤트 재처리 (최대 3회) | 상시 실행 |
| C3 | ClickHouse | 이벤트 저장 및 분석 쿼리 제공 | 상시 실행 |
| C4 | Reporter | 일일 트렌드 분석 → Discord 발송 | 스케줄 실행 (09:00 KST) |
| C5 | Grafana | 실시간 대시보드 제공 | 상시 실행 |

---

## 2. 외부 의존성 (통제 불가 범위)

아래 외부 서비스 장애는 WikiStreams의 NFR 달성 의무 범위 밖이다.

| 의존성 | 사용 컴포넌트 | 장애 영향 |
|--------|-------------|-----------|
| Wikimedia SSE API | C1 Producer | 이벤트 수집 중단 (재연결 자동 시도) |
| Wikidata REST API | C1 Producer | 레이블 보강 불가 (캐시로 부분 완화) |
| Anthropic Claude API | C4 Reporter | 리포트 생성 불가 |
| Discord Webhook | C4 Reporter | 리포트 발송 불가 |
| Google News RSS | C4 Reporter | 뉴스 섹션 누락 (부분 발송 가능) |

---

## 3. 비기능 요구사항

### 3.1 가용성 (Availability)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-A1 | C1 Producer | 연속 무중단 실행. 장애 발생 시 60초 이내 자동 재연결 | 지수 백오프 최대값 60초 (코드 기준) |
| NFR-A2 | C3 ClickHouse | 24시간 × 7일 쿼리 가능 상태 유지 | Grafana 대시보드 상시 접근 요구 |
| NFR-A3 | C4 Reporter | 매일 09:00 KST 기준 리포트 발송 시도 보장 | 스케줄러 정상 동작 |
| NFR-A5 | C5 Grafana | 대시보드 HTTP 접근 가능 상태 유지 | 모니터링 목적 |

### 3.2 성능 (Performance)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-P1 | C1 Producer | 배치당 처리 완료 시간 ≤ 10초 | `BATCH_TIMEOUT_SECONDS = 10.0` |
| NFR-P2 | C1 Producer | 배치 크기 500개 이벤트 처리 지원 | `BATCH_SIZE = 500` |
| NFR-P3 | C3 ClickHouse | Grafana 패널 쿼리 응답 ≤ 10초 (일반 쿼리 기준) | 대시보드 사용성 |
| NFR-P4 | C4 Reporter | 리포트 전체 생성·발송 완료 ≤ 5분 (Claude API 응답 포함) | 09:00 KST 발송 허용 오차 내 |

### 3.3 신뢰성 (Reliability)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-R1 | C1 Producer | 이벤트 DLQ 유입 비율 ≤ 1% (정상 운영 시) | 데이터 손실 허용 임계 |
| NFR-R2 | C2 DLQ Consumer | DLQ 이벤트 최대 3회 재처리 시도 | `DLQ_MAX_RETRIES = 3` |
| NFR-R3 | C1 Producer | Wikimedia SSE 연결 끊김 시 자동 재연결 (지수 백오프 2s → 60s) | `_RETRY_BASE_DELAY`, `_RETRY_MAX_DELAY` |
| NFR-R4 | C4 Reporter | Claude API 또는 Discord 실패 시 오류 로그 기록 및 다음 스케줄에 재시도 | 리포트 누락 최소화 |

### 3.4 데이터 품질 (Data Quality)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-D1 | C3 ClickHouse | 적재된 최신 이벤트의 타임스탬프가 현재 시각 기준 5분 이내 (정상 수집 중) | 실시간 대시보드 신선도 |
| NFR-D2 | C1 Producer | Wikidata Q-ID 이벤트에 대한 레이블 보강 시도 (캐시 미스 시 API 조회) | 분석 품질 |
| NFR-D3 | C1 Producer | Wikidata 레이블 캐시 TTL: 정상 엔티티 30일, missing 엔티티 24시간 | `CACHE_TTL_SECONDS`, `CACHE_MISSING_TTL_SECONDS` |

### 3.5 복구성 (Recoverability)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-RC1 | 전체 파이프라인 | 단일 컴포넌트 재시작 시 다른 컴포넌트에 영향 없이 독립 복구 | Docker Compose 독립 컨테이너 구조 |
| NFR-RC2 | C1 Producer | 재시작 후 Kafka 오프셋 기반으로 중단 지점부터 재개 (메시지 중복 허용, 유실 불허) | Kafka 컨슈머 오프셋 |
| NFR-RC3 | C3 ClickHouse | 컨테이너 재시작 후 데이터 영속성 보장 (볼륨 마운트) | Docker volume 설정 |

### 3.6 유지보수성 (Maintainability)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-M1 | 전체 | 코드 변경 후 단일 컴포넌트만 재빌드·재시작 가능 | `docker compose build {service} && up -d {service}` |
| NFR-M2 | 전체 | 모든 컴포넌트 로그는 Loki에 집계되어 Grafana에서 조회 가능 | 운영 가시성 |
| NFR-M3 | C4 Reporter | 프롬프트 스타일 변경 시 코드 수정 없이 환경변수(`PROMPT_STYLE`)로 전환 가능 | `prompts/__init__.py` 동적 로드 |

---

## 4. 비고 — 의도적으로 제외한 항목

| 항목 | 제외 이유 |
|------|-----------|
| 수평 확장 (Scale-out) | 단일 호스트 홈랩 환경, 현재 요구 없음 |
| 보안 인증/인가 | 로컬 네트워크 한정, 외부 노출 없음 |
| 데이터 백업·복구 RTO/RPO | 홈랩 특성상 데이터 손실 허용 범위 별도 정의 불필요 |
| 99.9% 이상 고가용성 | 단일 호스트 구조상 물리적으로 달성 불가 |
