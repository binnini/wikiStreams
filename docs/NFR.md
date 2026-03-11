# WikiStreams 비기능 요구사항 (NFR)

> 작성일: 2026-03-05
> 최종 수정: 2026-03-10 (아키텍처 경량화 완료 — Redpanda + QuestDB 기준으로 재작성)
> 목적: SLI/SLO/SLA 도출을 위한 선행 산출물
> 범위: WikiStreams 홈랩 데이터 파이프라인 전체 (Producer → Redpanda → QuestDB → Reporter/Grafana)

---

## 1. 배경 및 컴포넌트 정의

WikiStreams는 다음 6개 컴포넌트로 구성된다. 각 컴포넌트는 독립적으로 배포·운영되며, Docker Compose 단일 호스트 환경에서 실행된다.

| ID | 컴포넌트 | 역할 | 실행 형태 |
|----|----------|------|-----------|
| C1 | Producer | Wikimedia SSE 구독 → Redpanda 발행 | 상시 실행 (무중단) |
| ~~C2~~ | ~~DLQ Consumer~~ | ~~실패 이벤트 재처리 (최대 3회)~~ | ~~제거됨 (2026-03-07): Producer에서 사전 필터(_should_skip)로 대체~~ |
| C3 | QuestDB | 이벤트 저장 및 분석 쿼리 제공 (TTL 5일) | 상시 실행 |
| C4 | Reporter | 일일 트렌드 분석 → Discord 발송 | 스케줄 실행 (09:00 KST) |
| C5 | Grafana | 실시간 대시보드 제공 | 상시 실행 |
| C6 | S3 Exporter | 이벤트 데이터 오프호스트 백업 저장소 (일일 Parquet → S3) | 스케줄 실행 (01:00 UTC, profiles: s3) |

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
| S3 Compatible Storage | C6 S3 Exporter | 백업 저장 불가 → RPO 보장 불가 (파이프라인 동작 자체는 유지) |

---

## 3. 비기능 요구사항

### 3.1 가용성 (Availability)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-A1 | C1 Producer | 연속 무중단 실행. 장애 발생 시 60초 이내 자동 재연결 | 지수 백오프 최대값 60초 (코드 기준) |
| NFR-A2 | C3 QuestDB | 24시간 × 7일 쿼리 가능 상태 유지 | Grafana 대시보드 상시 접근 요구 |
| NFR-A3 | C4 Reporter | 매일 09:00 KST 기준 리포트 발송 시도 보장 | 스케줄러 정상 동작 |
| NFR-A5 | C5 Grafana | 대시보드 HTTP 접근 가능 상태 유지 | 모니터링 목적 |

### 3.2 성능 (Performance)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-P1 | C1 Producer | 배치당 처리 완료 시간 ≤ 5초 (Wikidata 캐시 히트 기준, enrich → Kafka 발행 완료) | 캐시 히트율 정상 시 달성 가능 목표; API 레이턴시 의존 구간은 외부 의존성으로 별도 처리 |
| NFR-P2 | C1 Producer | 배치 크기 500개 이벤트 처리 지원 | `BATCH_SIZE = 500` (Wikidata API 50개 청크 × 10회 일괄 조회 효율 최적화) |
| NFR-P3 | C3 QuestDB | Grafana 패널 쿼리 응답 ≤ 1초 (일반 쿼리 기준) | 대시보드 사용성 |
| NFR-P4 | C4 Reporter | 리포트 전체 생성·발송 완료 ≤ 30초 (Claude API 응답 포함) | 09:00 KST 발송 허용 오차 내 |
| NFR-P5 | C1 Producer | 지속 처리량 ≥ 800 events/min (정상 수집 중) | 실측 p5=1,166 기준 상향 (SLO-P5 2차 조정); 처리량 부족 시 Redpanda 레그 누적 |
| NFR-P7 | C1 Producer | Wikidata 캐시 히트율 ≥ 80% (정상 운영 기준) | 캐시 히트율 저하 시 Wikidata API 호출 급증 → 배치 처리 지연 (NFR-P1 연동) |

### 3.3 신뢰성 (Reliability)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-R1 | C1 Producer | 이벤트 DLQ 유입 비율 ≤ 1% (정상 운영 시) | `_should_skip()` 필터로 log/canary 사전 드롭; 진짜 실패만 DLQ 라우팅 |
| ~~NFR-R2~~ | ~~C2 DLQ Consumer~~ | ~~DLQ 이벤트 최대 3회 재처리 시도~~ | ~~C2 제거로 폐기 (2026-03-07)~~ |
| NFR-R3 | C1 Producer | Wikimedia SSE 연결 끊김 시 자동 재연결 (지수 백오프 2s → 60s) | `_RETRY_BASE_DELAY`, `_RETRY_MAX_DELAY` |
| NFR-R4 | C4 Reporter | Claude API 또는 Discord 실패 시 오류 로그 기록 및 다음 스케줄에 재시도 | 리포트 누락 최소화 |
| NFR-R5 | C1 Producer + C3 | SSE → QuestDB 파이프라인 완전성: 이벤트 유실률 ≤ 2% | DLQ 비율(R1)과 별개 — SSE 연결 끊김·QuestDB 적재 누락 포함한 엔드투엔드 유실 허용 임계 |

### 3.4 데이터 품질 (Data Quality)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-D1 | C3 QuestDB | 적재된 최신 이벤트의 타임스탬프가 현재 시각 기준 30초 이내 (정상 수집 중) | 실시간 대시보드 신선도 |
| NFR-D2 | C1 Producer | Wikidata Q-ID 이벤트에 대한 레이블 보강 시도 (캐시 미스 시 API 조회) | 분석 품질 |
| NFR-D3 | C1 Producer | Wikidata 레이블 캐시 TTL: 정상 엔티티 30일, missing 엔티티 24시간 | `CACHE_TTL_SECONDS`, `CACHE_MISSING_TTL_SECONDS` |

### 3.5 복구성 (Recoverability)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-RC1 | 전체 파이프라인 | 단일 컴포넌트 재시작 시 다른 컴포넌트에 영향 없이 독립 복구 | Docker Compose 독립 컨테이너 구조 |
| NFR-RC2 | C1 Producer | 재시작 후 Redpanda 오프셋 기반으로 중단 지점부터 재개 (메시지 중복 허용, 유실 불허) | Redpanda 컨슈머 오프셋 |
| NFR-RC3 | C3 QuestDB | 컨테이너 재시작 후 데이터 영속성 보장 (볼륨 마운트) | Docker volume 설정 |
| NFR-RC4 | C6 S3 Exporter | RPO ≤ 1일: 호스트 전체 장애 시 최대 1일 분량의 이벤트 데이터 손실 허용 (매일 01:00 UTC 백업) | S3 Exporter 운영 중 (2026-03-11). 1시간 단위 백업은 현재 미구현 |
| NFR-RC5 | C3 QuestDB + C6 | RTO ≤ 30분: S3 백업으로부터 QuestDB 데이터 복원 및 전체 서비스 재기동 완료 | runbook 미작성 — DuckDB로 S3 Parquet 직접 조회는 가능 |

### 3.6 유지보수성 (Maintainability)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-M1 | 전체 | 코드 변경 후 단일 컴포넌트만 재빌드·재시작 가능 | `docker compose build {service} && up -d {service}` |
| NFR-M2 | 전체 | 모든 컴포넌트 로그는 Loki에 집계되어 Grafana에서 조회 가능 | 운영 가시성 |
| NFR-M3 | C4 Reporter | 프롬프트 스타일 변경 시 코드 수정 없이 환경변수(`PROMPT_STYLE`)로 전환 가능 | `prompts/__init__.py` 동적 로드 |
| NFR-M4 | C5 Loki | 로그 보존 기간 ≥ 30일 | SLO 측정 롤링 기간(30일) 확보; 보존 기간 미달 시 SLI 측정 공백 발생 |

### 3.7 용량 (Capacity)

| ID | 대상 | 요구사항 | 근거 |
|----|------|----------|------|
| NFR-CAP1 | C3 QuestDB | 상시 RSS ≤ 880 MiB (mem_limit 1100m의 80%) | OOM 방지; QuestDB mmap 특성상 RSS가 page cache에 비례해 증가 → TTL 5일 + mem_limit으로 상한 제어 |
| NFR-CAP2 | C1 Producer | 상시 CPU 사용률 ≤ 70% (컨테이너 할당 기준) | CPU 포화 시 배치 처리 지연 → NFR-P1 달성 불가 |
| NFR-CAP3 | 전체 컨테이너 | 전체 컨테이너 합산 메모리 사용량을 Grafana에서 실시간 관측 가능 | 개별 컨테이너 지표만으로는 호스트 메모리 압박 여부 판단 불가; `resource-monitor`의 컨테이너별 `mem_mb` 합산으로 측정 |

---

## 4. 비고 — 의도적으로 제외한 항목

| 항목 | 제외 이유 |
|------|-----------|
| 수평 확장 (Scale-out) | 단일 호스트 홈랩 환경, 현재 요구 없음 |
| 보안 인증/인가 | AWS EC2 배포 후에도 외부 포트 미노출 (SSH 터널 접근); 서비스 간 인증은 VPC 내부 통신으로 대체 |
| 99.9% 이상 고가용성 | 단일 호스트 구조상 물리적으로 달성 불가 |
