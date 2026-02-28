# TODO

## 아키텍처 개편: Druid + Superset → ClickHouse + Grafana

> 기존 아키텍처(Druid + Superset)는 `archive/druid-superset` 브랜치에 보존됨

**배경**: Druid 5컨테이너 + ZooKeeper + Superset은 이 프로젝트 규모(수천 건/분)에 과도한 인프라.
Grafana가 이미 스택에 포함되어 있으므로, ClickHouse + Grafana로 단일화하여 서비스 수 및 리소스 대폭 절감.

```
변경 전: Kafka → Druid(5컨테이너) + ZooKeeper → Superset  +  Grafana(모니터링)
변경 후: Kafka → ClickHouse(1컨테이너)                     →  Grafana(시각화 + 모니터링 통합)
```

- [x] **1단계: 기존 서비스 제거** *(2026-02-28 완료)*
  - [x] `docker-compose.yml`에서 Druid 5개 서비스 제거 (coordinator, broker, historical, middlemanager, router)
  - [x] `docker-compose.yml`에서 ZooKeeper, Postgres, Redis 제거 (Druid/Superset 전용 의존성)
  - [x] `docker-compose.yml`에서 Superset 제거
  - [x] `druid/` 디렉토리 제거 (ingestion-spec.json, environment)
  - [x] `superset/` 디렉토리 제거 (Dockerfile, dashboards, init 스크립트 등)
  - [x] `monitoring/dashboards/wikistreams-druid.json` 제거
  - [x] `tests/cleanup_druid.py`, `tests/integration/test_e2e_pipeline.py` 제거
  - [x] `tests/conftest.py`에서 Druid 좀비 정리 픽스처 제거

- [x] **2단계: ClickHouse 도입** *(2026-02-28 완료)*
  - [x] `docker-compose.yml`에 ClickHouse 서비스 추가 (단일 컨테이너, arm64 네이티브)
  - [x] ClickHouse Kafka 테이블 엔진 설정 — `wikimedia.recentchange` 토픽 직접 구독
  - [x] ClickHouse Materialized View로 Kafka → MergeTree 저장 파이프라인 구성
  - [x] ClickHouse 스키마 정의 (`wikimedia.events`: event_time, title, server_name, wiki_type, namespace, user, bot, minor, comment, wikidata_label, wikidata_description)
  - [x] Grafana `grafana-clickhouse-datasource` 플러그인 설치 및 데이터소스 프로비저닝

- [x] **3단계: Grafana 시각화 확장** *(2026-02-28 완료)*
  - [x] Grafana ClickHouse 데이터소스 추가 (`grafana-datasources.yaml`)
  - [x] Superset 대체 대시보드 작성 (`wikistreams-analytics.json`)
    - KPI stats: Total Edits, Active Users, New Articles, Bot Traffic %
    - 시계열: Human/Bot Edits Over Time
    - 분포: Top 10 Wikis (bar), Edit Type (pie)
    - 테이블: Top Edited Pages (wikidata_label, description 포함)

- [x] **4단계: 테스트 및 문서 업데이트** *(2026-02-28 완료)*
  - [x] E2E 테스트를 ClickHouse 검증으로 교체 (`tests/integration/test_e2e_pipeline.py`)
  - [x] `CLAUDE.md` 아키텍처 설명 업데이트 (Data Flow, 서비스 목록, 포트, 로드맵)
  - [x] `README.md` 업데이트 (Mermaid 다이어그램, 기술 스택, Getting Started)
  - [x] `src/producer/models.py` docstring에서 Druid 참조 제거
  - [x] ClickHouse 버전 24.8 → 25.8 LTS 업그레이드 (비트랜잭션 Kafka 토픽 호환성 수정)

---

## 우선순위 높음

- [x] **Dead Letter Queue (DLQ) 도입** *(2026-02-26 완료)*
  - [x] 실패 메시지를 별도 Kafka 토픽(`wikimedia.recentchange.dlq`)으로 라우팅
  - [x] DLQ 메시지에 `error`, `failed_at`, `source_topic`, `retry_count` 메타데이터 포함
  - [x] Grafana Error Monitor에 DLQ Events/min, DLQ Total 패널 추가
  - [x] DLQ 컨슈머 서비스 구성 (재처리 또는 알림) *(2026-02-26 완료)*

- [x] **입력 데이터 스키마 검증** *(2026-02-27 완료)*
  - [x] Wikimedia SSE 이벤트를 Pydantic 모델로 정의 (`WikimediaEvent`)
  - [x] 필수 필드 누락 또는 타입 불일치 시 DLQ로 격리
  - [x] Wikidata API 응답도 동일하게 검증 (`WikidataApiResponse`)

- [ ] **Mac Mini로 마이그레이션**
  - [x] **1단계: Mac Mini 환경 준비**
    - [x] Docker Desktop for Mac 설치 (Apple Silicon이면 arm64 빌드)
    - [x] Docker Desktop 리소스 설정 — 메모리 최소 12GB, CPU 4코어 이상 할당 (Druid가 메모리를 많이 소비)
    - [x] Git 설치 및 리포지토리 클론

  - [ ] **2단계: Apple Silicon 아키텍처 호환성 확인**
    - [ ] `apache/druid:35.0.0` arm64 이미지 지원 여부 확인 (미지원 시 `platform: linux/amd64` 명시)
    - [ ] `confluentinc/cp-kafka:8.1.1` arm64 지원 여부 확인
    - [ ] `zookeeper:3.5.10` arm64 지원 여부 확인
    - [ ] arm64 미지원 이미지에 `platform: linux/amd64`를 `docker-compose.yml`에 추가

  - [ ] **3단계: Promtail 컨테이너 로그 경로 수정 (필수)**
    - macOS에서 `/var/lib/docker/containers`는 Docker Desktop 내부 VM 경로 → 호스트에서 직접 마운트 불가
    - [ ] `monitoring/promtail-config.yaml`을 Docker socket API 기반 수집(`docker_sd_configs`)으로 변경하거나
    - [ ] Promtail 대신 Grafana Alloy(구 Agent) 등 macOS 친화적 로그 수집기로 교체 검토

  - [ ] **4단계: 데이터 볼륨 마이그레이션**
    - [ ] PostgreSQL 데이터 덤프 및 복원 (`pg_dump` → `pg_restore`)
    - [ ] Grafana 대시보드/설정 볼륨 내보내기 (`docker cp` 또는 `docker run --volumes-from`)
    - [ ] Druid 세그먼트는 재수집이 가능하므로 마이그레이션 생략 가능 (재기동 후 자동 재인제스천)
    - [ ] SQLite 캐시(`producer_cache`)는 복사 시 30일치 캐시 유지 가능, 생략 시 초기 API 호출 증가

  - [ ] **5단계: 서비스 자동 시작 설정**
    - [ ] Docker Desktop → "Start Docker Desktop when you log in" 활성화
    - [ ] macOS 재부팅 시 `docker compose up -d` 자동 실행 설정
      - `launchd` plist 작성 (`~/Library/LaunchAgents/`) 또는
      - macOS 로그인 항목(Login Items)에 셸 스크립트 등록

  - [ ] **6단계: 네트워크 설정**
    - [ ] Mac Mini에 고정 IP 할당 (공유기 DHCP 예약 또는 macOS 수동 IP 설정)
    - [ ] (선택) 외부 접근을 위한 공유기 포트포워딩 설정 (8088 Superset, 3000 Grafana 등)

  - [ ] **7단계: 검증**
    - [ ] `docker compose up -d` 후 전체 서비스 정상 기동 확인
    - [ ] `PYTHONPATH=src pytest tests/unit/` 통과 확인
    - [ ] Grafana 대시보드에 실시간 데이터 수신 확인 (Events/min 패널)
    - [ ] Superset 대시보드 접속 및 쿼리 정상 확인



## 우선순위 중간

- [ ] **`collector.py` 리팩토링**
  - 현재 1,137줄로 SSE 연결 관리 / 배치 로직 / 에러 처리가 혼재
  - 역할별로 클래스 또는 모듈 분리 (`SSEClient`, `BatchBuffer`, `RetryPolicy` 등)

- [ ] **AsyncIO 리팩토링**
  - 현재 동기식(Blocking) I/O 구조: Wikidata API 호출이 배치 처리를 블로킹
  - `asyncio` + `httpx` (이미 사용 중) + `aiokafka`로 전환
  - 처리량(Throughput) 및 10초 타임아웃 의존도 개선 기대

- [x] **캐시 TTL 도입** *(2026-02-26 완료)*
  - [x] `CACHE_TTL_SECONDS` 설정 추가 (기본값 2592000초 / 30일)
  - [x] `get_qids_from_cache()`에 TTL 만료 필터링 추가 (lazy expiry)
  - [x] Wikidata `"missing"` 응답 구분 및 차등 TTL 적용 *(2026-02-26 완료)*
    - 정상 enrichment 성공: 긴 TTL (30일, `CACHE_TTL_SECONDS`)
    - `"missing"` 응답 (엔티티 미존재): 짧은 TTL (24시간, `CACHE_MISSING_TTL_SECONDS`)

- [ ] **SQLite 캐시를 Redis로 교체**
  - 현재 SQLite는 단일 프로세스에서만 유효 (Producer scale-out 불가)
  - `docker-compose.yml`의 기존 Redis 서비스 활용 (Superset용으로 이미 실행 중)
  - 여러 Producer 인스턴스가 캐시를 공유하게 되어 API 중복 호출 제거

## 우선순위 낮음

- [ ] **중복 이벤트 제거 (Deduplication)**
  - SSE 재연결 시 중복 이벤트 수신 가능 (Exactly-once 미보장)
  - Kafka 메시지 키를 이벤트 고유 ID로 설정하거나 Druid 레벨 중복 필터링 검토
  - 현재 `rollup=false` 설정으로 Druid가 중복 이벤트를 그대로 저장

- [ ] **이상 감지 알림 (Anomaly Detection)**
  - 처리량(Events/min)이 평소 대비 급감하거나 DLQ 급증 시 자동 알림 미구현
  - Grafana Alert 또는 Loki Alert Rule 설정으로 임계치 기반 알림 추가
  - 파이프라인 자체가 성공하더라도 데이터 이상을 조기 감지하는 방어선 필요

- [ ] **CI 파이프라인 이원화**
  - 현재: 모든 테스트(Unit + Integration + E2E)를 PR마다 실행
  - PR 단계: Unit + Integration (Smoke Test)
  - Merge 단계: 전체 E2E
  - 빌드 시간 및 비용 절감

- [ ] **확장성 검증 리포트 작성**
  - `k6` 또는 `Locust`로 초당 수천 건의 가상 이벤트를 Producer에 주입
  - Kafka / Druid 처리 한계(Throughput) 측정 및 병목 구간 파악
  - 결과를 `docs/` 하위에 리포트로 정리

- [ ] **클라우드 배포 (CD 파이프라인)**
  - AWS EC2 또는 ECS에 Docker Compose 스택 배포
  - GitHub Actions → AWS 간단한 CD 파이프라인 구성
