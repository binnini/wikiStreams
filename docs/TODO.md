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
  - [x] Analytics 대시보드 반달리즘 모니터 섹션 추가
    - Overview에 Anonymous Edit %, Revert Rate % stat 추가
    - Vandalism Monitor 섹션: 총 Revert 수, Revert Rate, Bot/Human Revert 분류 stat
    - Editor Types Over Time 스택 시계열 (Bot/Anonymous/Registered)
    - Vandalism Pressure 오버레이 시계열 (익명 편집 + 전체/봇 Revert)
    - Top Reverted Articles 테이블
  - [x] Analytics 대시보드 실시간 트렌드 섹션 추가
    - Edit Velocity stats 4종 (고정 5분 창: Total/Human/Bot/Anonymous edits/min)
    - Edit Velocity Trend 시계열 (편집/분 정규화)
    - Trending Articles 테이블 (spike_ratio: 최근 15분 vs 이전 60분 기준)
    - Cross-wiki Trending 테이블 (2개 이상 언어판에 동시 등장한 문서)
  - [x] Producer Performance 대시보드 전면 개편
    - Row 구조화 (Overview / Throughput / Cache / Logs)
    - Cache Hit Rate Trend 시계열, DLQ Events stat 추가
    - 로그 필터링 (핵심 이벤트만), Multi-tooltip, 10초 자동 갱신
  - [x] 전체 대시보드 x축 과밀 방지
    - ClickHouse 쿼리: `greatest($__interval_s, 60)` 최소 1분 버킷 보장
    - Loki 바 차트: `maxDataPoints: 60` 적용
  - [x] Wikidata enricher 레이블 정규화
    - 레이블 미존재 시 `"-"` → `""` 빈 문자열로 변경 (enricher.py)
    - 기존 캐시 DB의 `"-"` 항목 일괄 정리

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

  - [x] **2단계: Apple Silicon 아키텍처 호환성 확인** *(2026-03-01 완료)*
    - [x] ClickHouse arm64 네이티브 지원 확인 (ClickHouse 도입으로 Druid 에뮬레이션 문제 해소)
    - [x] `confluentinc/cp-kafka:8.1.1` arm64 지원 확인 → Confluent Platform 7.x 이후 multi-arch 지원, `platform: linux/amd64` 불필요
    - [x] 나머지 이미지 (`grafana/loki`, `grafana/alloy`, `clickhouse/clickhouse-server`, `docker:cli`) 모두 arm64 네이티브 지원

  - [x] **3단계: Promtail → Grafana Alloy 교체 (macOS 로그 수집 수정)** *(2026-03-01 완료)*
    - macOS에서 `/var/lib/docker/containers`는 Docker Desktop 내부 VM 경로 → 호스트에서 직접 마운트 불가
    - [x] Promtail 제거 → Grafana Alloy(`grafana/alloy:latest`)로 교체 (`docker-compose.yml`)
    - [x] `monitoring/alloy-config.alloy` 작성 — `loki.source.docker` 컴포넌트로 Docker socket API 직접 스트리밍
    - [x] `/var/lib/docker/containers` 마운트 제거, `/var/run/docker.sock` 만 사용
    - [x] `container` 레이블 유지 (`discovery.relabel`로 `__meta_docker_container_name` → `container`)

  - [ ] **4단계: 데이터 볼륨 마이그레이션** *(2026-03-01 생략)*
    - [ ] ~~Grafana 대시보드/설정 볼륨 내보내기 (`docker cp` 또는 `docker run --volumes-from`)~~
    - [ ] ~~SQLite 캐시(`producer_cache`)는 복사 시 30일치 캐시 유지 가능, 생략 시 초기 API 호출 증가~~
    - [ ] ~~ClickHouse 데이터는 재수집 가능하므로 마이그레이션 생략 가능~~

  - [x] **5단계: 서비스 자동 시작 설정** *(2026-03-01 완료)*
    - [x] Docker Desktop → "Start Docker Desktop when you log in" 활성화 *(Mac Mini에서 직접 설정)*
    - [x] `scripts/com.wikistreams.startup.plist` 작성 (launchd, 로그인 시 `docker compose up -d` 자동 실행)
      - 설치: `cp scripts/com.wikistreams.startup.plist ~/Library/LaunchAgents/` 후 `REPO_PATH` 수정 → `launchctl load`
      - Docker Desktop 기동 완료 대기(120초) 후 compose 실행

  - [ ] **6단계: 네트워크 설정**
    - [ ] Mac Mini에 고정 IP 할당 (공유기 DHCP 예약 또는 macOS 수동 IP 설정)
    - [ ] (선택) 외부 접근을 위한 공유기 포트포워딩 설정 (3000 Grafana, 8123 ClickHouse HTTP)

  - [x] **7단계: 검증** *(2026-03-01 완료)*
    - [x] `docker compose up -d` 후 전체 서비스 정상 기동 확인
    - [x] `PYTHONPATH=src pytest tests/unit/` 통과 확인
    - [x] Grafana Analytics 대시보드에 실시간 데이터 수신 확인



## 우선순위 중간

- [ ] **SLO 수립 로드맵** *(진행 중)*
  - 목표: 실측 데이터 기반 SLO.md 작성 → SLA.md 작성
  - 선행 산출물: NFR.md ✅, SLI.md ✅

  - [ ] **1단계: 계측 보강 (Instrumentation Gap 해소)**
    - [ ] `process_batch()` 시작·종료 시 `time.perf_counter()` 로그 추가 → SLI-P1 (배치 처리 소요 시간) 측정 가능화
    - [ ] `_process_buffer()` 호출 시 배치 크기 로그 추가 → SLI-P2 (배치 크기) 측정 가능화
    - [ ] Kafka JMX Exporter 또는 `kafka-consumer-groups.sh` polling → Grafana 연동 → SLI-P6 (Kafka 컨슈머 레그) 측정 가능화
    - [ ] `collector.py`에 SSE 수신 이벤트 누적 카운터 로그 추가 → SLI-R5 (파이프라인 완전성) 측정 가능화
    - [ ] S3 백업 구현 후 백업 완료 타임스탬프 로그 기록 → SLI-RC4 (RPO) 측정 가능화
    - [ ] `node-exporter` 또는 `df -h` polling 스크립트 추가 → SLI-CAP3 (디스크 사용률) 측정 가능화
    - [ ] SLI.md 계측 불가 항목 → 자동/수동 측정으로 상태 업데이트

  - [ ] **2단계: SLO 대시보드 구현 (Grafana)**
    - [ ] `monitoring/dashboards/wikistreams-slo.json` 신규 작성
    - [ ] 각 SLI 현재값 패널
      - 가용성: SLI-A2 (ClickHouse 가용성), SLI-A3 (Reporter 발송 성공)
      - 성능: SLI-P3 (쿼리 응답), SLI-P5 (처리량), SLI-P7 (캐시 히트율)
      - 신뢰성: SLI-R1 (DLQ 비율)
      - 데이터 품질: SLI-D1 (신선도), SLI-D2 (레이블 보강률)
      - 용량: SLI-CAP1 (ClickHouse 메모리), SLI-CAP2 (Producer CPU)
    - [ ] 30일 롤링 윈도우 SLO 달성률 패널
    - [ ] 에러 버짓 잔량 패널 (소진률 % 시계열)

  - [ ] **3단계: 알림 구현 (Grafana Alert Rule)**
    - [ ] SLI-D1: 데이터 신선도 lag > 30초 지속 시 Discord 알림
    - [ ] SLI-A3: 당일 09:00~10:00 KST 내 Reporter 발송 없음 → Discord 알림
    - [ ] SLI-R1: DLQ 비율 > 1% 감지 시 Discord 알림
    - [ ] SLI-P7: 캐시 히트율 < 80% 지속 시 Discord 알림
    - [ ] SLI-CAP1: ClickHouse 메모리 사용률 > 80% 시 Discord 알림
    - [ ] SLI-CAP2: Producer CPU 사용률 > 70% 지속 시 Discord 알림
    - [ ] 에러 버짓 소진률 75% 초과 시 Discord 경고

  - [ ] **4단계: 관측 기간 (1~4주)**
    - [ ] SLI별 baseline 수집 (SLI-D1, SLI-P3는 1~2주 / SLI-A3, SLI-R1은 2~4주)
    - [ ] 시간대별·요일별 패턴 파악
    - [ ] 이상 구간 원인 분석 및 기록

  - [ ] **5단계: SLO.md 작성**
    - [ ] 관측 데이터 기반으로 각 SLI에 목표 수치 + 측정 기간 정의
    - [ ] 에러 버짓 계산 (SLO 수치 → 허용 위반 시간/횟수)
    - [ ] 외부 의존성 제외 조건 명시 (NFR.md 섹션 2 기준)

  - [ ] **6단계: SLA.md 작성**
    - [ ] SLO 기반 책임 범위 및 위반 처리 정의
    - [ ] 월간 리포팅 주기 및 SLO 재조정 주기 명시

- [ ] **S3 Datalake 도입 — ClickHouse 백업 및 RTO/RPO 확보** *(NFR-RC4, NFR-RC5)*
  - **배경**: ClickHouse 데이터가 로컬 Docker 볼륨에만 존재. 호스트 장애 시 90일치 이벤트 이력 전체 손실. Wikimedia SSE는 실시간 스트림이므로 과거 데이터 재수집 불가.
  - **목표**: RPO ≤ 1시간 / RTO ≤ 30분 (NFR-RC4, NFR-RC5)
  - **백업 전략**: 일 1회 전체(Full) 백업 + 시간당 1회 증분(Incremental) 백업. ClickHouse 네이티브 `BACKUP TABLE ... TO S3(...)` 및 `SETTINGS base_backup=...` 사용.

  - [ ] **1단계: S3 스토리지 준비**
    - [ ] S3 Compatible 스토리지 선택 (AWS S3 / Cloudflare R2 / 자체 MinIO 중 선택)
    - [ ] 백업 전용 버킷 생성 및 액세스 키 발급
    - [ ] `.env`에 `S3_BACKUP_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT` 추가

  - [ ] **2단계: ClickHouse 백업 스케줄 구성**
    - [ ] `docker-compose.yml`에 `clickhouse-backup` 서비스 추가 (크론 기반)
    - [ ] 일 1회 전체 백업 스크립트 작성 (`BACKUP TABLE wikimedia.events TO S3(...)`)
    - [ ] 시간당 증분 백업 스크립트 작성 (`SETTINGS base_backup = '...'`)
    - [ ] 백업 완료 여부 로깅 (Loki 연동)

  - [ ] **3단계: 복구 절차 검증**
    - [ ] S3 → ClickHouse 복원 runbook 작성 (`docs/runbook-restore.md`)
    - [ ] 실제 복원 테스트 수행 (스테이징 또는 로컬 ClickHouse 인스턴스)
    - [ ] RTO 30분 이내 복원 완료 확인

- [x] **일일 트렌드 뉴스 리포트 (Discord Embed, 한국어)** *(2026-03-01 완료)*
  - ClickHouse 24시간 데이터를 분석해 뉴스 기사 형식으로 요약, 매일 오전 9시 KST에 Discord Embed 카드로 자동 발송
  - **데이터 수집** (`src/reporter/fetcher.py`): 전체 통계, 상위 편집 문서(봇 제외, `wiki_type='edit'`), 스파이크 문서, Cross-wiki 트렌드, 논쟁 문서, 전일 대비 랭크 변화, 편집 피크 시간대, Wikipedia 오늘의 특집 문서, 문서 썸네일
  - **기사 생성** (`src/reporter/builder.py`): Claude Haiku (`claude-haiku-4-5-20251001`) 단일 호출로 5섹션 브리핑 + 뉴스 검색 키워드 배치 추출 (API 추가 호출 없음)
  - **뉴스 스크래핑** (`src/reporter/fetcher.py`): Google News RSS, 한국어 우선 → 영어 fallback, 48시간 필터, 영어판 관련성 필터
  - **Discord 발송** (`src/reporter/publisher.py`): 5개 Embed 카드 순서 — 헤드라인 → 숫자 브리핑(Big Number) → Top 5 문서(URL·랭크배지·스파이크·다국어·썸네일·관련뉴스) → 논쟁/반달리즘(구조화 필드) → 교양코너(오늘의 특집 문서)
  - **스케줄링** (`src/reporter/main.py`): APScheduler `CronTrigger(hour=9, timezone='Asia/Seoul')`
  - **컨테이너** (`docker-compose.yml`): `reporter` 서비스, `ANTHROPIC_API_KEY` + `DISCORD_WEBHOOK_URL` env 주입
  - **대시보드 연동**: Analytics 대시보드 Top Edited Pages, Trending Articles 패널에 `wiki_type = 'edit'` 필터 추가

- [x] **Reporter 단위/통합 테스트** *(2026-03-01 완료)*
  - `tests/unit/reporter/` — 115개 단위 테스트 (Claude API 호출 없이 개발 가능)
    - `test_fetcher.py`: `wiki_url`, `_fetch_news` (fallback·48h·관련성), `fetch_news_with_keywords`, `_fetch_featured_article`, `fetch_thumbnail`, `_fetch_qid`, `_deduplicate_by_qid`, `fetch_report_data` enrichment
    - `test_builder.py`: `_build_context` 컨텐츠 검증, `build_report` Claude 응답 파싱·`selected_indices` 필터링·fallback
    - `test_publisher.py`: `_rank_badge`, `_wiki_flag`, `_truncate`, `_build_top5_embed`(단일·다언어판 표시), `_build_featured_embed`, `publish_report` Embed 순서·개수
    - `test_main.py`: `run_report` 파이프라인 오케스트레이션, 썸네일 타이밍, 예외 처리
  - `tests/integration/test_reporter_integration.py` — 실제 Wikipedia/Google News API 호출 (`@pytest.mark.integration`)

- [x] **`collector.py` 개선** *(2026-03-01 완료)*
  - 모듈 레벨 `logging.basicConfig()` 제거 → `logging.getLogger(__name__)` (앱 진입점에서 설정)
  - 고정 10초 재연결 대기 → 지수 백오프 (2s → 4s → … → 최대 60s, 연결 성공 시 초기화)
  - f-string 로그 → `%s` lazy 포맷으로 변경
  - `test_exponential_backoff` 테스트 추가 → **136개 통과**

- [x] **리소스 이상 감지 알람 (Resource Anomaly Detection)** *(2026-03-01 완료)*
  - [x] `docker-stats-logger` (shell script) → Python `resource-monitor` 서비스로 교체
  - [x] **메트릭 수집** (10초 간격, 전체 컨테이너): `cpu_pct`, `mem_pct`, `mem_mb`, `block_io_mb`
  - [x] **Baseline** (`src/resource_monitor/baseline.py`): SQLite EMA + Welford online variance (컨테이너 × hour bucket 0–23), 재시작 후 학습 상태 유지
  - [x] **이상 감지** (`src/resource_monitor/detector.py`): z-score > 2.5, 최소 샘플 미확보 기간 감지 억제
  - [x] **감지 대상**: 기본값 `producer`, `clickhouse` — `MONITOR_TARGETS` 환경변수로 추가 가능
  - [x] **Alert** (`src/resource_monitor/alerter.py`): Discord Embed 발송, 동일 컨테이너·메트릭 1시간 cooldown
  - [x] **Loki 로깅**: `level=warn msg="AnomalyDetected"` 구조화 로그 출력
  - [x] 단위 테스트 39개 (baseline / detector / alerter / collector)

- [x] **Grafana Resources 대시보드 — 이상 감지 이력 패널 추가** *(2026-03-01 완료)*
  - `monitoring/dashboards/wikistreams-resources.json` 에 "Anomaly Detection" 섹션 추가
  - 기존 패널 쿼리: `docker-stats-logger` → `resource-monitor` 컨테이너 레이블 교체 + `|= "DockerStats"` 필터 추가
  - **Anomaly Rate** 시계열 — `container/metric` 별 누적 막대 (컨테이너 × 메트릭 조합)
  - **Anomaly Events** 로그 패널 — 이상 감지 이벤트 원문 타임라인 (최신 순)

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

- [x] **캐시 TTL 도입** *(2026-02-26 완료)*
  - [x] `CACHE_TTL_SECONDS` 설정 추가 (기본값 2592000초 / 30일)
  - [x] `get_qids_from_cache()`에 TTL 만료 필터링 추가 (lazy expiry)
  - [x] Wikidata `"missing"` 응답 구분 및 차등 TTL 적용 *(2026-02-26 완료)*
    - 정상 enrichment 성공: 긴 TTL (30일, `CACHE_TTL_SECONDS`)
    - `"missing"` 응답 (엔티티 미존재): 짧은 TTL (24시간, `CACHE_MISSING_TTL_SECONDS`)

- [ ] **SQLite 캐시를 Redis로 교체**
  - 현재 SQLite는 단일 프로세스에서만 유효 (Producer scale-out 불가)
  - `docker-compose.yml`에 Redis 서비스 추가 필요 (Superset 제거로 기존 Redis도 제거됨)
  - 여러 Producer 인스턴스가 캐시를 공유하게 되어 API 중복 호출 제거

- [x] **디스코드 Top 5 피드 다양성 개선** *(2026-03-01 완료, feat/top5-diversity)*
  - Wikidata Q-ID로 동일 사건의 다국어판(en/ko/de/ru/…)을 단일 후보로 통합 — `LIMIT 20` 쿼리 후 Q-ID 중복 제거 → 평균 ~12개 고유 주제 후보 확보
  - Wikipedia REST API(`/api/rest_v1/page/summary`)로 Q-ID를 `ThreadPoolExecutor`로 병렬 조회 후 `_deduplicate_by_qid()` 적용
  - Claude Haiku가 후보 전체를 보고 `selected_indices`(0-based)로 주제가 다른 5개 선택 — 정치·스포츠·과학·문화 분야 다양성 및 스파이크(⚡)·다국어(🌍) 우선 고려
  - `LangEdition` 데이터클래스로 그룹핑된 언어판 편집 수 보존 → Discord Embed에 `🇺🇸 EN 450회 · 🇷🇺 RU 320회 | 합계 770회` 형식으로 표시
  - 뉴스 스크래핑 개선: 주제별 최대 3건(기존 전체 5건 상한 제거) → 3개 주제 × 최대 3건 = 최대 9건
  - 썸네일 fetch를 `fetch_report_data()` → `main.py`(LLM 선택 이후)로 이동, 실제 선택된 1위 문서의 썸네일 표시

## 우선순위 낮음

- [ ] **중복 이벤트 제거 (Deduplication)**
  - SSE 재연결 시 중복 이벤트 수신 가능 (Exactly-once 미보장)
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
