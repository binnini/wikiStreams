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

  - [x] **4단계: 관측 기간** *(2026-03-08 조기 완료)*
    - [x] SLI 1차 실측 baseline 확보 (39시간, 2026-03-07 리뷰) — SLO 목표 재조정 완료
    - [x] baseline 최종 확정 (49시간 / 5,160,451건, 2026-03-08) — 전 SLO 수치 갱신
    - 관측 기간 조기 종료 근거: 49시간 / 5.16M건으로 SLO 목표 재조정 및 수치 안정 확인. 아키텍처 경량화 로드맵 진입 조건 해제.

  - [x] **5단계: SLO.md 작성** *(2026-03-06 초기 목표값으로 완료)*
    - [x] NFR 기반 초기 목표 수치 정의 (관측 완료 후 확정 예정)
    - [x] 에러 버짓 계산 (SLO 수치 → 허용 위반 시간/횟수)
    - [x] 외부 의존성 제외 조건 명시 (NFR.md 섹션 2 기준)

  - [x] **6단계: SLA.md 작성** *(2026-03-06 초기 협약으로 완료)*
    - [x] SLO 기반 책임 범위 및 위반 처리 정의
    - [x] 월간 리포팅 주기 및 SLO 재조정 주기 명시


- [ ] **아키텍처 경량화** *(진행 중)*
  - **배경**: 현재 컨테이너 합산 메모리 ~3,909 MiB + OS ~400 MiB = ~4,309 MiB로 t4g.medium(4 GiB) 초과.
  - **목표**: AWS t3.small(2 GiB) 마이그레이션. Kafka→Redpanda(-802 MiB) + ClickHouse→QuestDB(-1,750 MiB) 로 달성.
  - **원칙**: 단계별 완료 후 SLI 재측정 → Trade-Off 수치화 → 다음 단계 진행.

  - [x] **전제: SLO 수립 로드맵 4단계(관측 기간) 완료** *(2026-03-08 완료)*
    - baseline 확정: 49시간 / 5,160,451건. 경량화 후 동일 SLI 재측정 기준값으로 사용.

  - [x] **1단계: DLQ Consumer 제거** *(2026-03-07 스테이징 완료, 운영 전환 보류)*
    - 18 msg/sec 처리량에서 재처리 가치 없음 — log/canary 이벤트가 DLQ의 유일한 원인으로 확인
    - [x] `docker-compose.staging.yml`에서 `dlq-consumer` 서비스 제거 완료
    - [x] `src/producer/main.py`에 `_should_skip()` 사전 필터 추가 (log 타입·canary 도메인 드롭)
    - [x] 단위 테스트 5개 추가, DLQ 토픽 near-zero 확인
    - [ ] 운영 `docker-compose.yml` 반영 — 2단계 운영 전환 시 함께 적용 예정
    - 절감: ~27 MiB

  - [x] **2단계: Kafka → Redpanda 전환** *(2026-03-08 운영 전환 완료)*
    - 절감: ~802 MiB → 전환 후 예상 총 메모리 ~3,214 MiB (t4g.medium 78%)
    - **조기 Go 판정** (2026-03-08): 스테이징 21시간 관측, 전 수치 충분한 여유로 Go
      - P1 p95=0.804s ✅ / P5 p5=1,477/min ✅ / D1 12s ✅ / 메모리 387.6 MiB ✅
    - [x] `docker-compose.yml`: `kafka-kraft` → `redpanda` 교체, `dlq-consumer` 제거
    - [x] `clickhouse/init-db.sql`: `kafka_broker_list = 'redpanda:9092'` 업데이트
    - [x] 운영 ClickHouse `kafka_raw` 테이블 + `events_mv` 재생성 (Redpanda 브로커로)
    - [x] 파이프라인 정상 확인: 전환 직후 2분간 3,037건 적재 ✅
    - [ ] SLI-P1·P5·D1 재측정 — 운영 Redpanda 기준 baseline 갱신 (1주 후)

  - [x] **3단계: ClickHouse → QuestDB 전환** *(2026-03-08 운영 전환 완료 / 2026-03-09 운영 안정화)*
    - 실측 절감: ~1,756 MiB → 전환 후 24h 실측 총 메모리 **~1,446 MiB (t3.small 71% ✅)**
    - [x] `docker-compose.yml`: `clickhouse` → `questdb` + `questdb-consumer` 추가
    - [x] `monitoring/grafana-datasources.yaml`: ClickHouse 플러그인 → PostgreSQL (포트 8812), `deleteDatasources`로 ClickHouse 레거시 제거
    - [x] `monitoring/grafana-alert-rules.yaml`: SLI-D1 SQL 수정 (QuestDB datediff 제약: CHAR 단위, 집계함수 서브쿼리 분리)
    - [x] `monitoring/dashboards/wikistreams-slo.json`: 전 패널 ClickHouse SQL → QuestDB SQL 재작성 (A2/P3/P5/D1/D2/CAP1/CAP2)
    - [x] `monitoring/dashboards/wikistreams-analytics.json`: QuestDB-staging UID 제거, 대시보드 UID 복원
    - [x] `monitoring/dashboards/wikistreams-resources.json`: 전 패널 QuestDB 데이터소스로 전환
    - [x] `src/reporter/config.py`: `clickhouse_host/port` → `questdb_host/port`
    - [x] `src/reporter/fetcher.py`: `_query()` QuestDB REST API + SQL 10개 번역, 재시도 로직(3회/2s) 추가
    - [x] `src/questdb_consumer/main.py`: `_ensure_table()` 추가 — 시작 시 명시적 스키마로 테이블 생성 (ILP auto-create 방지)
    - [x] QuestDB 8.2.1 → **9.3.3 업그레이드** (TTL 지원 버전)
    - [x] `docker-compose.yml` questdb: `mem_limit: 1100m` 추가 (page cache 예산 제한)
    - [x] `wikimedia_events` 테이블: `PARTITION BY DAY TTL 5d` 적용 (디스크 무한 증가 방지)
    - 트러블슈팅: orphan container(clickhouse) 포트 9000 충돌로 questdb 네트워크 미연결 → force-recreate로 해결
    - **ClickHouse vs QuestDB 메모리 트레이드오프**:
      - ClickHouse: `uncompressed_cache_size` / `mark_cache_size` / `max_server_memory_usage_ratio` — 명시적 LRU 예산. OS page cache와 독립적으로 동작하여 메모리 사용량 예측 가능.
      - QuestDB: 컬럼 파일을 mmap으로 읽어 RSS에 반영. mmap 할당량 설정 없음 — OS page cache에 완전 위임. RAM이 넉넉한 환경에서는 page eviction 없이 RSS가 working set에 비례해 선형 증가(24h 관측: +34 MiB/h).
      - 대응 전략: `mem_limit: 1100m`으로 cgroup 압력 부여(강제 eviction) + TTL 5d로 working set 상한 제한(최대 ~575 MiB × 5일 = ~2.9 GiB 컬럼 파일, cgroup 1.1 GiB 내에서 OS가 LRU evict).

  - [x] **[벤치마크] ClickHouse(t4g.medium) vs QuestDB(t3.small) Cold Read 비교** *(설계 완료, 구현 대기)*
    - **목적**: 마이그레이션 트레이드오프 수치화 — 인스턴스 다운그레이드로 얻는 비용 절감이 어느 정도의 cold read 성능 저하를 감수하는 것인지 정량화.
    - **비교 환경** (각자 자연스러운 동작 조건):
      - ClickHouse: `mem_limit: 4000m` (t4g.medium 4 GiB 시뮬레이션), `uncompressed_cache: 1 GiB`, `mark_cache: 256 MiB`
      - QuestDB: `mem_limit: 1100m` (t3.small 시뮬레이션, 현재 설정)
    - **데이터**: 합성 5일치 ~780만 건 (18 events/sec 기준) — 양쪽 DB에 동일 주입
    - **측정 쿼리**: Reporter 실제 쿼리 기반 3개 (Q1: 집계, Q3: GROUP BY, Q5: DISTINCT+정렬)
    - **측정 조건**: recent(최근 1일) vs old(4~5일 전 하루) × cold vs warm × N=10
    - **캐시 초기화**: QuestDB → `sudo purge` (macOS) / ClickHouse → `SYSTEM DROP MARK CACHE` + `SYSTEM DROP UNCOMPRESSED CACHE`
    - **결과 형태**: p50/p95/p99 per (db × range × query × mode), SLO 2s 통과 여부
    - **로컬→AWS 보정**: 절대 수치는 EBS/NVMe 속도비(~23x) 곱해 worst-case 예측치로 활용
    - [x] `benchmark/docker-compose.bench.yml` 작성 (ClickHouse 임시 기동)
    - [x] `benchmark/clickhouse/bench-config.xml` 작성 (t4g.medium 캐시 설정)
    - [x] `benchmark/clickhouse/bench-init.sql` 작성 (bench.events 테이블)
    - [x] `benchmark/data_generator.py` 작성 (합성 5일치 데이터 → QuestDB ILP + ClickHouse HTTP)
    - [x] `benchmark/queries.py` 작성 (Q1/Q3/Q5 양쪽 SQL)
    - [x] `benchmark/runner.py` 작성 (캐시 초기화 → 측정 → p50/p95/p99 CSV 출력)
    - [x] 결과를 `docs/ARCH_LIGHTENING_REPORT.md` 트레이드오프 섹션에 추가 *(2026-03-10 완료, Section 6)*

  - [x] **[벤치마크] Kafka vs Redpanda 트레이드오프 Deep Dive** *(2026-03-10 완료)*
    - **목적**: 메모리 절감 외에 latency/안정성 관점의 트레이드오프 수치화.
    - **핵심 인사이트**: 18 msg/sec에서 전환의 실질적 이유는 latency가 아닌 메모리. GC pause 영향은 p99/p999에서 드러남. 환경(로컬 vs AWS) 차이가 결과에 거의 영향 없음 (CPU/RAM bound, disk 무관).
    - **비교 환경** (t3.small 시뮬레이션):
      - Kafka:    `mem_limit: 800m`, `KAFKA_HEAP_OPTS="-Xms256m -Xmx512m"` (힙 압박으로 GC 빈도 재현)
      - Redpanda: `mem_limit: 500m` (현재 실측 ~387 MiB 기준)
    - **측정 1 — Send Latency**: 18 / 50 / 200 msg/sec × 각 30분, p50/p95/p99/p999 수집
      - 18/sec: 운영 실부하. 50/sec: GC 빈도 증가 시작. 200/sec: GC pause p99 명확히 드러나는 구간.
    - **측정 2 — RSS 시계열**: 5초 간격 docker stats → Kafka saw-tooth vs Redpanda 안정선 비교
    - **측정 3 — 재시작 복구 시간**: `docker restart` 후 Consumer 첫 메시지 수신까지 gap, 5회 반복
      - SLI-D1 연결: Kafka 20~40s 복구 시 30s SLO 위반 가능 / Redpanda 2~5s → SLO 여유
    - **측정 4 — CPU 패턴**: RSS와 교차 수집 → GC 시 CPU 스파이크 + RSS 급감 동시 검증
    - **결과 형태**: p50/p95/p99/p999 per (db × rate), RSS 시계열 그래프, 복구 시간 평균/최대
    - **실측 결과 요약** (→ `docs/ARCH_LIGHTENING_REPORT.md` 섹션 7):
      - p999 (18 msg/sec): Kafka 6.3ms → Redpanda 3.9ms (-38%)
      - p999 (50 msg/sec): Kafka 13.0ms ⚠️ → Redpanda 3.8ms (-71%, GC pause 효과)
      - RSS mean: Kafka 510 MiB (선형 증가) → Redpanda 316 MiB (수평 고정) (-38%)
      - 복구 avg: Kafka 4.13s → Redpanda 1.86s (-55%), 양쪽 모두 SLO(30s) 통과
      - 예측(Kafka 20~40s 복구)과 달리 KRaft 덕분에 Kafka도 4초대로 빠름
    - [x] `benchmark/docker-compose.kafka-bench.yml` 작성 (Kafka KRaft 단일 노드)
    - [x] `benchmark/kafka/kraft.properties` 작성
    - [x] `benchmark/load_generator.py` 작성 (send latency 측정, 처리량 3구간)
    - [x] `benchmark/memory_monitor.py` 작성 (RSS + CPU 시계열 수집)
    - [x] `benchmark/recovery_test.py` 작성 (재시작 복구 gap 측정)
    - [x] 결과를 `docs/ARCH_LIGHTENING_REPORT.md` 트레이드오프 섹션에 추가

  - [ ] **4단계: Loki/Alloy 경량화** *(3단계 운영 전환 완료 후 옵션 선택)*
    - **배경**: Loki(253 MiB) + Alloy(104 MiB) = 357 MiB. 대시보드 41개 Loki 쿼리 중 25개가
      `unwrap`(로그→숫자 추출) 사용 → SLI-P1·P2·P7·R1·CAP1·CAP2·CAP3 핵심 지표.
    - **선택은 SLO 관측 기간 완료 후 결정.**

    - **Option A — 4단계 스킵** *(절감 0 MiB, 복잡도 없음)*
      - 2+3단계 완료 시 t3.small 93% → 스왑 1 GiB 추가로 안정 운영 가능
      - 로그 관측성 완전 유지
      - 권장: "메모리 여유보다 운영 안정성 우선"일 때

    - **Option B — Alloy → Promtail 교체만** *(절감 ~79 MiB, 복잡도 매우 낮음)*
      - `grafana/promtail` 이미지 교체 + 설정 파일 수정 (Loki 유지)
      - 대시보드·쿼리·코드 변경 없음
      - 권장: "쉽게 조금 절감"할 때

    - **Option C — QuestDB 직접 메트릭** *(절감 ~357 MiB, 복잡도 높음)*
      - Producer·resource-monitor·Reporter가 메트릭을 QuestDB ILP로 직접 씀
      - SLO 대시보드 Loki 패널 전체를 QuestDB SQL로 재작성 필요
      - Error Monitor 로그 뷰어 포기 (docker logs로만 확인)
      - 권장: "최대 절감 + QuestDB 단일 스택 통합"이 목표일 때

    - **Option D — VictoriaLogs 교체** *(절감 ~200 MiB 예상, 복잡도 매우 높음)*
      - `unwrap` 미지원 → SLI 수치 패널 25개 전부 깨짐 (No data)
      - 살아남는 것: 로그 라인 뷰어·단순 count_over_time만
      - **사실상 불가**: 이 프로젝트 구조에서 drop-in 교체 아님
      - 권장: 없음 (참고용 기록)


## 우선순위 중간



- [ ] **QuestDB 메모리 Drift 장기 관찰** *(2026-03-09 관찰 시작)*
  - **배경**: 24h 관측에서 RSS가 ~387 → ~498 MiB (+34 MiB/h)로 선형 증가. OS page cache 채움 현상(leak 아님).
  - **대응 완료**: `mem_limit: 1100m` + TTL 5d 적용. cgroup 압력으로 page eviction 강제, working set ~5일치로 제한.
  - **관찰 기준**: `mem_limit` 적용 후 RSS가 1,100 MiB 이하에서 안정되는지 수일간 확인.

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
