# TODO

## 우선순위 높음

- [ ] **SLO 수립 로드맵** *(진행 중)*
  - 목표: 실측 데이터 기반 SLO.md 작성 → SLA.md 작성
  - 선행 산출물: NFR.md ✅, SLI.md ✅

  - [x] **1단계: 계측 보강 (Instrumentation Gap 해소)** *(2026-03-06 완료)*
    - [x] `process_batch()` 시작·종료 시 `time.perf_counter()` 로그 추가 → SLI-P1 (배치 처리 소요 시간) 측정 가능화
    - [x] `_process_buffer()` 호출 시 배치 크기 로그 추가 → SLI-P2 (배치 크기) 측정 가능화
    - [x] Kafka JMX Exporter 또는 `kafka-consumer-groups.sh` polling → Grafana 연동 → SLI-P6 (Kafka 컨슈머 레그) 측정 가능화
    - [x] **SLI-P6 제거**: 처리량(18 msg/sec) 대비 ClickHouse가 즉시 offset 커밋하여 lag가 항상 0 → 정보량 없음. SLI-D1(데이터 신선도)이 실질적으로 대체. `kafka-lag-monitor` 서비스 및 SLO 대시보드 SLI-P6 패널 제거.
    - [x] `collector.py`에 SSE 수신 이벤트 누적 카운터 로그 추가 → SLI-R5 (파이프라인 완전성) 측정 가능화
    - [ ] ~~S3 백업 구현 후 백업 완료 타임스탬프 로그 기록 → SLI-RC4 (RPO) 측정 가능화~~ *(2026-03-06 생략)*


  - [x] **2단계: SLO 대시보드 구현 (Grafana)** *(2026-03-06 완료)*
    - [x] `monitoring/dashboards/wikistreams-slo.json` 신규 작성
    - [x] 각 SLI 현재값 패널 (가용성·성능·신뢰성·데이터 품질·용량 5개 섹션)
      - 가용성: SLI-A2 (ClickHouse 가용성), SLI-A3 (Reporter 발송 성공)
      - 성능: SLI-P1 (배치 처리), SLI-P2 (배치 크기), SLI-P3 (쿼리 응답), SLI-P5 (처리량), SLI-P7 (캐시 히트율)
      - 신뢰성: SLI-R1 (DLQ 비율)
      - 데이터 품질: SLI-D1 (신선도), SLI-D2 (레이블 보강률)
      - 용량: SLI-CAP1 (ClickHouse 메모리), SLI-CAP2 (Producer CPU)
    - [x] **추이 패널 가독성 개선** *(2026-03-06)*: `[$__interval]` → `[5m]` 고정 윈도우, `avg(avg_over_time())` 단일 시리즈화, max 시리즈 제거, y축 고정(`min=0`)
    - [x] **SLI-A2 버그 수정** *(2026-03-06)*: `system.query_log` QueryStart 행이 분모에 포함되어 성공률이 항상 ~50%로 고정되던 문제 → `type NOT IN ('QueryStart')` 추가로 수정 (실제 값: 99.92%)

  - [x] **3단계: 알림 구현 (Grafana Alert Rule)** *(2026-03-06 완료)*
    - [x] `monitoring/grafana-contact-points.yaml` 작성 (Discord Webhook 연동)
    - [x] `monitoring/grafana-notification-policy.yaml` 작성 (라우팅 정책)
    - [x] `monitoring/grafana-alert-rules.yaml` 작성 (6개 알림 규칙)
      - SLI-D1: 데이터 신선도 lag > 30초 2분 지속 → Discord 알림
      - SLI-A3: 1시간 내 Reporter 발송 없음 → Discord 알림
      - SLI-R1: DLQ 비율 > 1% 3분 지속 → Discord 알림
      - SLI-P7: 캐시 히트율 < 80% 10분 지속 → Discord 알림
      - SLI-CAP1: ClickHouse 메모리 > 80% 5분 지속 → Discord critical 알림
      - SLI-CAP2: Producer CPU > 70% 10분 지속 → Discord 알림
    - [x] `docker-compose.yml`에 alerting 프로비저닝 볼륨 마운트 추가
    - [ ] 에러 버짓 소진률 75% 초과 시 Discord 경고 *(Grafana 계산 패널로 구현 필요)*

  - [ ] **4단계: 관측 기간 (1~4주)** *(2026-03-06 시작)*
    - [ ] SLI별 baseline 수집 (SLI-D1, SLI-P3는 1~2주 / SLI-A3, SLI-R1은 2~4주)
    - [ ] 시간대별·요일별 패턴 파악 (특히 SLI-P5: 심야 UTC 처리량 저하 확인)
    - [ ] 이상 구간 원인 분석 및 기록

  - [x] **5단계: SLO.md 작성** *(2026-03-06 초기 목표값으로 완료)*
    - [x] NFR 기반 초기 목표 수치 정의 (관측 완료 후 확정 예정)
    - [x] 에러 버짓 계산 (SLO 수치 → 허용 위반 시간/횟수)
    - [x] 외부 의존성 제외 조건 명시 (NFR.md 섹션 2 기준)

  - [x] **6단계: SLA.md 작성** *(2026-03-06 초기 협약으로 완료)*
    - [x] SLO 기반 책임 범위 및 위반 처리 정의
    - [x] 월간 리포팅 주기 및 SLO 재조정 주기 명시


- [ ] **아키텍처 경량화**
  - **배경**: 현재 컨테이너 합산 메모리 ~3,909 MiB + OS ~400 MiB = ~4,309 MiB로 t4g.medium(4 GiB) 초과.
  - **목표**: AWS t3.small(2 GiB) 마이그레이션. Kafka→Redpanda(-802 MiB) + ClickHouse→QuestDB(-1,750 MiB) 로 달성.
  - **원칙**: 단계별 완료 후 SLI 재측정 → Trade-Off 수치화 → 다음 단계 진행.

  - [ ] **전제: SLO 수립 로드맵 4단계(관측 기간) 완료**
    - 관측 기간 중 수집한 SLI baseline을 경량화 전 기준값으로 사용
    - 경량화 후 동일 SLI를 재측정하여 성능 회귀 여부 확인

  - [ ] **1단계: DLQ Consumer 제거** *(리스크 없음)*
    - 18 msg/sec 처리량에서 재처리 가치 없음 (스키마 검증 실패는 코드 수정으로 해결)
    - `docker-compose.yml`에서 `dlq-consumer` 서비스 제거
    - `src/dlq_consumer/`, 관련 테스트 제거
    - 절감: ~27 MiB

  - [ ] **2단계: Kafka → Redpanda 전환** *(핵심 경량화, t4g.medium 전제 조건)*
    - 절감: ~1,184 MiB → 전환 후 예상 총 메모리 ~3,125 MiB (t4g.medium 76%)
    - **선택 이유**: Kafka API 완전 호환 → `docker-compose.yml` 이미지 한 줄 교체만으로 완료. Producer/ClickHouse Kafka 엔진/DLQ Consumer 코드 변경 없음.
    - **Redis Streams 대비**: Redis는 sender.py·ClickHouse Kafka 엔진·DLQ 전면 재작성 필요. 150 MiB 추가 절감보다 코드 변경 리스크가 큼.
    - `docker-compose.yml`: `kafka-kraft` → `redpandadata/redpanda` 이미지 교체
    - 완료 후 SLI-P1·P2·P5·D1 재측정, 경량화 전후 수치 비교 기록
    - **진행 중 (2026-03-07)**: 스테이징 환경 구축 완료 (`feat/arch-lightening` 브랜치)
      - `docker-compose.staging.yml` + `clickhouse/init-db-staging.sql` 작성
      - 운영(Kafka)과 스테이징(Redpanda)이 동일 Wikimedia 스트림을 동시 구독 중 (섀도우 테스트)
      - SLO 4단계 관측 기간 완료 후 SLI 수치 비교 → 운영 전환 결정

  - [ ] **3단계: ClickHouse → QuestDB 전환** *(t3.small 목표의 핵심 단계)* **진행 중 (2026-03-07)**
    - 절감: ~1,750 MiB → 전환 후 예상 총 메모리 ~1,464 MiB (t3.small 72% ✅)
    - **선택 이유**: DuckDB 대비 QuestDB 채택 (2026-03-07 결정)
      - Kafka 내장 연동: 별도 Consumer 서비스 개발 불필요
      - Grafana PostgreSQL 와이어 프로토콜 지원: 플러그인 추가 없이 연동
      - HTTP API 내장: FastAPI 래퍼 개발 불필요
      - DuckDB는 Consumer 서비스 + HTTP 래퍼 = 신규 코드 2개 필요 → 홈랩 유지보수 부담
    - **스테이징 진행 상황** (Option B — 병렬 스택, `docker-compose.staging3.yml`):
      - [x] `docker-compose.staging3.yml` + `src/questdb_consumer/` 작성 완료
      - [x] QuestDB SLI 검증: P3 8~27ms ✅ / D1 4~8s ✅ / P5 1,573/min ✅ / 메모리 365 MiB ✅
      - [x] Grafana PostgreSQL 데이터소스 추가 + 대시보드 24개 패널 마이그레이션 완료
      - [x] Reporter SQL 호환성 검증 완료 (번역 패턴 확립)
      - [ ] 2단계 Go/No-Go 완료 후 운영 전환 진행
    - **개발 범위 (운영 전환 시)**:
      - `docker-compose.yml`: `clickhouse` → `questdb` 이미지 교체, `questdb-consumer` 서비스 추가
      - Grafana 데이터소스 교체: ClickHouse 플러그인 → PostgreSQL (포트 8812)
      - `src/reporter/fetcher.py`: `_query()` 엔드포인트 + SQL 번역 패치 (ClickHouse → QuestDB)
    - 완료 후 SLI-P3(쿼리 응답시간) 재측정, ClickHouse 대비 성능 비교 기록

  - [ ] **4단계: Loki + Alloy 제거** *(3단계 완료 후 검토)*
    - SLO 대시보드 SLI 대부분이 Loki 기반 → 제거 시 측정 방식 전면 교체 필요
    - 대안: 구조화 로그를 QuestDB 로그 테이블에 직접 INSERT → Grafana HTTP 쿼리
    - 또는 SLI 측정 기준을 QuestDB 적재 데이터만으로 재설계
    - 절감: ~288 MiB (loki + alloy)


## 우선순위 중간



- [ ] **ClickHouse 메모리 Drift 장기 관찰** *(2026-03-01 관찰 시작)*
  - **배경**: 20분간 메모리가 3,284 MB → 3,413 MB (+6 MB/분)으로 완만하게 증가. MergeTree 백그라운드 merge 중 캐시 미반환 가능성.
  - **관찰 기준**: 수일간 `mem_mb` 추이가 선형 증가를 유지하면 조치 필요.
  - **조치 후보**:
    - `OPTIMIZE TABLE wikimedia.events FINAL` — 파트 강제 병합으로 메모리 반환 유도
    - ClickHouse `max_memory_usage` / `max_bytes_before_external_group_by` 설정 검토
    - resource-monitor 베이스라인 학습 완료(시간대별 30+ 샘플) 후 메모리 drift anomaly 자동 감지 여부 확인

- [ ] **AsyncIO 리팩토링**
  - 현재 동기식(Blocking) I/O 구조: Wikidata API 호출이 배치 처리를 블로킹
  - `asyncio` + `httpx` (이미 사용 중) + `aiokafka`로 전환
  - 처리량(Throughput) 및 10초 타임아웃 의존도 개선 기대


- [ ] **SQLite 캐시를 공유 캐시로 교체**
  - 현재 SQLite는 단일 프로세스에서만 유효 (Producer scale-out 불가)
  - 2단계(Kafka → Redpanda)에서 Redis를 도입하지 않으므로, scale-out이 필요해지는 시점에 재검토
  - 대안: Redpanda 전환 완료 후 Redis를 캐시 전용으로 별도 추가하거나, QuestDB 전환 시 SQLite 캐시 유지 (Producer 전용이므로 영향 없음)



## 우선순위 낮음

- [ ] **무중단 배포 안전성 확보**
  - **배경**: 운영 중 컨테이너에 직접 배포 시 설정 오류(예: Grafana 환경변수 누락)로 전체 서비스가 중단되는 상황 체감. 단일 호스트 Docker Compose 환경에서 현실적으로 적용 가능한 안전장치 필요.

  - [ ] **1단계: Health Check 추가** *(우선순위 높음)*
    - `docker-compose.yml` 각 서비스에 `healthcheck` 추가 (producer, reporter, dlq-consumer, clickhouse)
    - `depends_on`에 `condition: service_healthy` 설정 — upstream 준비 전 downstream 기동 방지
    - 효과: 새 컨테이너가 정상 상태가 아니면 Docker가 healthy로 처리하지 않음

  - [ ] **2단계: Build → Test → Deploy 스크립트 작성**
    - `scripts/deploy.sh` 작성: `build` → `pytest tests/unit/` → 통과 시에만 `up -d` 실행
    - 코드 변경 배포 시 반드시 이 스크립트를 통하도록 운영 규칙 수립
    - 인프라 변경(`docker-compose.yml`) 시 `docker compose config`로 문법 검증 먼저

  - [ ] **3단계: 롤백용 stable 이미지 태깅**
    - 배포 전 `docker tag <image>:latest <image>:stable` 보존
    - 문제 발생 시 `stable` 태그로 즉시 롤백 가능
    - 배포 스크립트에 태깅 단계 포함

  - **변경 유형별 리스크 기준**:
    - `src/` 코드 변경 → build → test → `up -d <service>` (서비스 단위 교체)
    - `docker-compose.yml` 변경 → `docker compose config` 검증 → 영향받는 서비스만 재시작
    - `monitoring/` 설정 변경 → Grafana/Loki만 재시작, 파이프라인 서비스 유지
    - ClickHouse 스키마 변경 → 마이그레이션 스크립트 작성 후 적용 (가장 위험)

- [ ] **중복 이벤트 제거 (Deduplication)**
  - SSE 재연결 시 중복 이벤트 수신 가능 (Exactly-once 미보장)
  - `Last-Event-ID` 헤더로 재연결 시 서버 백필을 받으므로, 짧은 재연결에서는 누락보다 중복이 더 발생할 수 있음
  - Kafka 메시지 키를 이벤트 고유 ID로 설정하거나 ClickHouse ReplacingMergeTree 엔진으로 중복 제거 검토

- [x] **이상 감지 알림 (Anomaly Detection)** *(2026-03-01 완료, 리소스 이상 감지로 구현)*
  - 리소스(CPU/메모리/I/O) z-score 기반 이상 감지 → Discord Embed 알림으로 구현
  - 처리량(Events/min) 급감·DLQ 급증 알림은 향후 Grafana Alert Rule로 보완 가능

- [x] **CI 파이프라인 이원화** *(2026-03-01 완료)*
  - `unit-tests` job: PR + main push — Lint, Format, Unit Tests (Docker 불필요, 빠름)
  - `integration-tests` job: main push 전용 — `needs: unit-tests` + `if: github.event_name == 'push'` 조건으로 unit 통과 후에만 실행, Docker Compose 기동 후 통합/E2E 테스트

- [ ] **확장성 검증 리포트 작성**
  - `k6` 또는 `Locust`로 초당 수천 건의 가상 이벤트를 Producer에 주입
  - Kafka / ClickHouse 처리 한계(Throughput) 측정 및 병목 구간 파악
  - 결과를 `docs/` 하위에 리포트로 정리

- [ ] **클라우드 배포 (CD 파이프라인)**
  - AWS EC2 또는 ECS에 Docker Compose 스택 배포
  - GitHub Actions → AWS 간단한 CD 파이프라인 구성
