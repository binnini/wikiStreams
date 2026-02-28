# 📔 Development Log (WikiStreams)

이 문서는 프로젝트 개발 과정에서 발생한 주요 이슈, 해결 방법, 그리고 기술적 의사결정을 기록합니다.

## 2026-02-03

### 1. 테스트 인프라 안정화 (Druid Resource Leak)
- **이슈**: E2E 테스트(`test_e2e_pipeline.py`)가 반복 실행 시 중단되거나 400 에러(invalidInput)를 반환하며 실패함.
- **원인**: 
    - 테스트가 비정상 종료될 때 Druid의 Supervisor와 Task가 정리되지 않고 슬롯을 차지함.
    - Druid MiddleManager의 작업 용량(Capacity: 2)이 가득 차서 새로운 수집 작업을 시작하지 못함.
- **해결**: 
    - `tests/cleanup_druid.py` 스크립트를 작성하여 좀비 리소스 강제 종료 로직 구현.
    - `tests/conftest.py`에 Pytest 세션 시작 전 자동 정리(Self-Healing) 픽스처 추가.
- **결과**: 테스트 실행 전후로 항상 깨끗한 상태를 유지하여 테스트 성공률 100% 달성.

### 2. Superset 시각화 자동화 (Dashboard as Code)
- **이슈**: `docker compose up` 후 Superset에서 일일이 DB를 연결하고 데이터셋을 등록해야 하는 번거로움.
- **작업**:
    - `init_superset.sh` 개선: Druid Router가 응답할 때까지 대기하는 루프 추가.
    - `druid.yaml`을 통한 DB 연결 자동 임포트 구성.
    - `wikimedia.recentchange` 데이터셋 및 기본 메트릭(`Edit Count`) 정의 파일 추가.

### 3. Superset 무한 로딩 이슈 (Plugin API 404)
- **이슈**: 대시보드 생성 및 차트 추가 시 화면이 무한 로딩되는 현상 발생.
- **원인**: `FEATURE_FLAGS` 중 `DYNAMIC_PLUGINS`가 활성화되어 존재하지 않는 `/dynamic-plugins/api/read` 경로를 호출하며 프론트엔드 에러 유발.
- **해결**: `superset/superset_config.py`에서 `DYNAMIC_PLUGINS: False`로 설정 변경.

### 4. 타임존 불일치 및 필터링 오류
- **이슈**: Superset에서 '최근 10분' 등 Time Range 필터 적용 시 데이터가 조회되지 않음.
- **원인**: Druid 연결 설정(`druid.yaml`)에 `sqlTimeZone: Asia/Seoul`이 적용되어, 쿼리 생성 기준(UTC)과 반환 데이터 기준(KST)이 충돌함 (9시간 오차).
- **해결**: 
    - 연결 설정에서 `sqlTimeZone` 옵션 제거하여 **UTC 기준 통일**.
    - 사용자에게 보여주는 시간은 Superset 차트의 가상 컬럼(`TIME_SHIFT`)이나 대시보드 설정을 통해 보정하도록 가이드라인 수립.

## 2026-02-09

### 1. 데이터 적재 중단 (OffsetOutOfRangeException)
- **이슈**: Druid에 최신 데이터가 적재되지 않음.
- **원인**:
    - Kafka 컨테이너 재시작 등으로 인해 실제 Kafka의 오프셋 정보가 초기화되었으나, Druid는 메타데이터 저장소에 기록된 이전 오프셋 정보를 계속 참조함.
    - 이로 인해 `OffsetOutOfRangeException`이 발생하며 수집 태스크(Supervisor)가 중단됨.
- **해결**:
    - **즉시 조치**: Supervisor 리셋 API(`POST /druid/indexer/v1/supervisor/{supervisorId}/reset`)를 호출하여 오프셋 정보를 초기화.
    - **영구 조치**: `druid/ingestion-spec.json`의 `tuningConfig`에 `resetOffsetAutomatically: true` 옵션을 추가하여, 향후 유사한 불일치 발생 시 Druid가 자동으로 복구하도록 설정.

### 2. Superset 대시보드 고도화 (Top Trending Topics)
- **작업**: 실시간 트렌드 파악을 위한 전용 대시보드 구축 및 데이터 전처리.
- **해결**:
    - **Calculated Columns 도입**:
        - `edit_severity`: `minor` (true/false)를 'Minor Edit', 'Major Edit'으로 변환 및 Null/Unclassified 처리.
        - `clean_type`: `type` 컬럼의 Null 값을 'Other'로 보정.
        - `display_title`: `wikidata_label`이 'NewItem', '-' 이거나 Null일 경우 원본 `title`을 사용하도록 Fallback 로직 구현.
        - `wiki_link`: `server_name`과 `title`을 조합하여 실제 위키백과 문서로 이동하는 HTML 하이퍼링크 컬럼 생성.
    - **실시간 트렌드 시각화 구성**:
        - **Word Cloud**: 실시간 핫 토픽 시각화 (`display_title` 기준, `namespace=0`, `bot=false` 필터 적용).
        - **Detailed Table**: 토픽별 상세 설명(`wikidata_desc`) 및 수치 제공, `wiki_link`를 통한 외부 연결.
        - **Big Numbers (KPIs)**: 총 편집 수, 활성 사용자 수, 신규 문서 생성 수 배치 (Trendline 및 전일/전시간 대비 증감률 포함).
        - **Editing Type Breakdown**: Sunburst 차트를 사용하여 편집 유형과 강도의 계층적 분포 가시화.

## 2026-02-10

### 1. Superset 초기화 프로세스 최적화 및 자동화
- **이슈**: Druid Router의 부팅 지연으로 인해 Superset 초기화 시 DB 연결 임포트가 실패하는 현상이 간헐적으로 발생함.
- **작업**:
    - **상태 확인 로직 강화**: `init_superset.sh`의 `curl` 기반 체크를 파이썬(`urllib`) 스크립트로 교체. 최대 5분간 대기하며 연결 안정성 확보.
    - **Dashboard as Code (Export/Import)**: 
        - 최신 Superset 대시보드 내보내기 형식인 `.zip` 아카이브 구조 도입.
        - 컨테이너 기동 시 `wikimedia_dashboard.zip`을 자동으로 임포트하도록 설정하여 수동 설정 과정 제거.
- **결과**: 인프라 기동 후 별도의 조작 없이 즉시 완성된 실시간 대시보드 확인 가능.

### 2. Kafka 통합 테스트 안정화 (Test Isolation & Cleanup)
- **이슈**: `test_producer_kafka_integration.py` 실행 시 타임아웃 에러 발생.
- **원인**: 
    - 공유 토픽(`wikimedia.recentchange`)에 수십만 개의 데이터가 쌓여 있어, 테스트 메시지를 찾기 위해 Consumer가 이전 데이터를 읽는 과정에서 20초 타임아웃 초과.
- **해결**:
    - **테스트 격리(Isolation)**: 각 테스트 모듈 실행 시마다 고유한 임시 토픽(`test-topic-{timestamp}`)을 생성하여 사용하도록 수정.
    - **자동 정리(Cleanup)**: `kafka_topic` 피처에 `KafkaAdminClient`를 연동하여 테스트 종료 후 생성된 임시 토픽을 즉시 삭제하도록 보강.
- **결과**: 기존 데이터 규모와 상관없이 테스트 실행 속도 및 성공률 대폭 향상 (약 5초 내외 완료).

### 3. 프로젝트 가이드라인 업데이트 (GEMINI.md)
- **작업**: Superset 대시보드 관리 방식(Dashboard as Code)에 대한 가이드라인 추가 및 진행 현황 최신화.
- **내용**: 
    - `.zip` 파일을 이용한 대시보드 내보내기/가져오기 워크플로우 명시.
    - UUID 기반 동기화 원리 및 사용자 수정 시 덮어쓰기 주의사항 기록.
    - 개선 로드맵의 완료된 항목 최신화.

### 4. 중앙 집중식 로깅 시스템 구축 (Loki & Grafana)
- **이슈**: 장시간 운영 시 컨테이너별 로그 추적이 어렵고, 에러 발생 시 원인 파악이 지연됨.
- **작업**:
    - **Loki + Promtail 도입**: Docker 소켓을 연동하여 모든 컨테이너(`producer`, `kafka`, `druid` 등)의 로그를 실시간 수집하도록 구성.
    - **Grafana 연동 (Dashboard as Code)**: 
        - 로그 통합 조회를 위한 전용 대시보드(`WikiStreams Logs`) JSON 정의.
        - `provisioning` 설정을 통해 컨테이너 재시작 시에도 대시보드가 자동 유지되도록 구현.
- **트러블슈팅**:
    - **Datasource UID 불일치**: 대시보드 JSON과 `datasources.yaml` 간의 UID가 일치하지 않아 데이터 로딩이 실패하는 문제 해결 (`uid: Loki` 명시).
    - **JSON Syntax Error**: 대시보드 JSON 내 `expr` 필드의 따옴표 이스케이프 오류 수정.
- **결과**: 전체 시스템 로그를 한곳에서 검색 및 필터링 가능하며, 이슈 발생 시 타임라인 기반의 신속한 디버깅 환경 확보.

### 5. 모니터링 고도화 및 리소스 감시 체계 구축

- **작업**: 단순 로그 조회를 넘어 성능 지표 시각화 및 시스템 자원 모니터링 대시보드 구축.
- **해결**:
    - **전용 대시보드 세분화**: 
        - `Error Monitor`: 전체 컨테이너의 에러 발생 빈도 및 핵심 예외 로그 필터링.
        - `Producer Performance`: 처리량(Events/Min) 및 캐시 적중률(Cache Hit Rate) 연산 지표 추가.
        - `Druid Monitor`: 쿼리 지연 시간(Latency) 및 세그먼트 핸드오프 성공 여부 추적.
    - **경량 리소스 컬렉터 도입**: 
        - `docker-stats-logger` 사이드카 컨테이너를 추가하여 호스트의 `docker stats` 정보를 10초 간격으로 로그화.
        - `WikiStreams Resources Monitor` 대시보드를 통해 실시간 CPU/Memory 사용량 시각화.
- **트러블슈팅 (LogQL Aggregation)**:
    - **이슈**: 메모리 사용량 합계가 100%를 초과(171%)하거나 데이터가 중복 집계되는 현상 발생.
    - **원인**: Loki의 `unwrap` 연산 시 라벨이 유실되어 모든 컨테이너의 데이터가 하나의 시리즈로 뭉치거나, Grafana의 집계 방식(Calcs) 불일치.
    - **해결**: LogQL에서 `logfmt` 파싱 후 명시적으로 `by (target_container)`를 사용하여 시리즈를 분리하고, `avg_over_time`과 `sum`을 조합하여 올바른 전체 사용량 도출.
- **결과**: 인프라와 애플리케이션 양쪽의 건강 상태를 수치화된 지표로 실시간 감시할 수 있는 완성도 높은 운영 환경 구축.

## 2026-02-28

### 1. 아키텍처 간소화 결정: Druid + Superset 제거 → ClickHouse + Grafana 전환

- **배경**:
  - Mac Mini로의 인프라 이전을 준비하는 과정에서 현 스택의 플랫폼 호환성 및 리소스 효율성을 재검토.
  - 두 가지 근본적인 문제가 드러나 아키텍처 변경을 결정.

- **문제 1 — 과도한 엔지니어링 (Over-engineering)**:
  - Apache Druid는 수십억 건/일 규모의 OLAP 워크로드를 위해 설계된 시스템. WikiStreams의 실제 처리량은 수천 건/분 수준으로, Druid가 제공하는 분산 아키텍처의 이점을 전혀 활용하지 못하고 있었음.
  - Druid 단독으로 5개 컨테이너(coordinator, broker, historical, middlemanager, router)와 ZooKeeper가 필요하여 전체 15개 서비스 중 절반에 가까운 리소스를 차지.
  - 메모리 요구사항이 12GB 이상으로, 개인 운영 환경에서 부담이 컸음.
  - Superset은 Druid와의 호환성을 이유로 도입됐으나, 동일한 시각화 기능을 Grafana(이미 스택에 포함)가 제공 가능. 두 도구가 중복됨.
  - Druid에서 발생한 운영 이슈들(OffsetOutOfRangeException, Supervisor 좀비 리소스, 타임존 불일치 등)이 모두 Druid 자체의 복잡성에서 기인했음.

- **문제 2 — macOS 호환성**:
  - `apache/druid:35.0.0`은 공식 arm64 이미지를 제공하지 않아 Apple Silicon Mac에서 `platform: linux/amd64` 에뮬레이션이 필수. Rosetta 에뮬레이션 시 성능 손실 발생.
  - Promtail이 `/var/lib/docker/containers`를 호스트 경로로 직접 마운트하나, macOS Docker Desktop은 Docker를 내부 Linux VM에서 실행하므로 해당 경로가 호스트에 존재하지 않음.
  - 위 두 이슈 모두 Druid 의존 구조에서 비롯된 문제임.

- **결정**:
  - Druid 5개 서비스, ZooKeeper, Superset을 스택에서 제거.
  - 대체재로 **ClickHouse** 도입: 단일 컨테이너, arm64 네이티브 지원, Kafka 테이블 엔진 내장, Grafana 공식 지원.
  - 시각화는 **Grafana**로 통합 — 모니터링과 데이터 분석 대시보드를 단일 도구로 운영.
  - 기존 아키텍처는 `archive/druid-superset` 브랜치에 보존.

- **예상 효과**:
  - 서비스 수: 15개 → 약 8~9개
  - 메모리 요구사항: 12GB+ → 4~6GB 수준
  - arm64 호환성 문제 해소
  - 운영 복잡도 대폭 감소

---

## 2026-02-26

### 1. Dead Letter Queue (DLQ) 구현
- **배경**: Kafka `send()` 실패 시 이벤트가 로그에만 기록되고 영구 소실되는 문제.
- **작업**:
  - `config.py`에 `KAFKA_DLQ_TOPIC` 설정 추가 (기본값: `wikimedia.recentchange.dlq`).
  - `sender.py`를 Future 기반으로 재작성: 모든 이벤트를 `send()` 후 `flush()`, 이후 각 Future의 결과를 확인하여 실패 이벤트만 DLQ로 라우팅.
  - DLQ 메시지에 `original_event` + `dlq_metadata(error, failed_at, source_topic, retry_count)` 포함.
  - `docker-compose.yml` producer 서비스에 `KAFKA_DLQ_TOPIC` env 추가.
- **테스트**: DLQ 라우팅, 부분 실패(3개 중 1개), DLQ 전송 자체 실패 시 CRITICAL 로그 케이스 포함 (7/7 통과).
- **결과**: 실패 이벤트가 DLQ 토픽에 보존되어 추후 재처리 가능. 정상 이벤트 처리에는 영향 없음.

### 2. DLQ 모니터링 패널 추가 (Grafana Error Monitor)
- **배경**: DLQ에 얼마나 쌓이는지 대시보드에서 확인 필요.
- **작업**:
  - `monitoring/dashboards/wikistreams-errors.json`에 패널 2개 추가:
    - **DLQ Events/min**: LogQL `count_over_time`으로 분당 DLQ 라우팅 건수 시계열 표시.
    - **DLQ Total**: 선택 기간 내 누적 DLQ 이벤트 수 (0=녹색 / 1~99=주황 / 100+=빨강).
  - 기존 `producer` 대시보드의 stat 패널 UI 패턴(`colorMode: value`, `graphMode: area`)에 맞춰 일관성 유지.

### 3. Wikidata 캐시 TTL 도입
- **배경**: `timestamp` 컬럼이 있었으나 만료 검증 없이 캐시가 무기한 유효하게 유지됨.
- **작업**:
  - `config.py`에 `CACHE_TTL_SECONDS` 설정 추가 (기본값: 86400초 / 24시간).
  - `cache.py`의 `get_qids_from_cache()`에 TTL WHERE 절 추가:
    ```sql
    AND timestamp > datetime('now', '-{ttl} seconds')
    ```
  - Lazy expiry 방식: 만료된 항목은 DB에 남고 조회 시 무시됨. 다음 API 호출 후 `INSERT OR REPLACE`로 timestamp 갱신.
- **테스트**: 만료 항목 미반환, TTL 이내 항목 반환, 혼합 케이스 (7/7 통과, 전체 26/26).

### 4. DLQ 컨슈머 서비스 구현
- **배경**: DLQ 라우팅은 구현됐으나 DLQ 토픽을 소비하는 서비스가 없어 실패 이벤트가 영구 적체됨.
- **작업**:
  - `src/dlq_consumer/` 신규 모듈 생성 (`config.py`, `consumer.py`, `main.py`, `Dockerfile`, `requirements.txt`).
  - 재시도 전략: `retry_count < MAX_RETRIES(3)` → 메인 토픽 재전송, 실패 시 `retry_count + 1`로 DLQ 재큐잉. `retry_count >= MAX_RETRIES` → CRITICAL 로그 후 폐기.
  - `docker-compose.yml`에 `dlq-consumer` 서비스 추가 (`kafka-kraft` 의존, `on-failure` 재시작).
- **테스트**: 재시도 성공, 재시도 실패→재큐잉, 최대 재시도 초과→폐기, 마지막 재시도 실패→`retry_count=3` 재큐잉 (4/4 통과).

### 5. Wikidata `"missing"` 응답 차등 TTL 및 TTL 만료 모니터링
- **배경**: 정상 엔티티와 존재하지 않는(`"missing"`) 엔티티를 동일한 TTL로 캐싱하여 비효율 발생.
- **작업**:
  - `cache.py` 스키마에 `is_missing INTEGER DEFAULT 0` 컬럼 추가. 기존 DB 마이그레이션 처리(`ALTER TABLE ... ADD COLUMN`, 중복 시 무시).
  - `get_qids_from_cache()` 조회 쿼리를 차등 TTL로 변경:
    - 정상 엔티티: `CACHE_TTL_SECONDS` (기본값 30일)
    - `"missing"` 엔티티: `CACHE_MISSING_TTL_SECONDS` (기본값 24시간)
  - `enricher.py`에서 `"missing" in entity`로 누락 엔티티 감지 후 `is_missing=True` 플래그를 캐시에 전달.
  - TTL 만료 건수를 `(TTL 만료: N개)` 형식으로 로그에 추가 (Loki 파싱 가능).
  - `wikistreams-producer.json`에 패널 2개 추가:
    - **TTL Expired (Per Minute)**: 분당 만료 건수 시계열.
    - **Total TTL Expired**: 선택 기간 내 누적 만료 건수 stat.
- **테스트**: 차등 TTL 시나리오 3개, TTL 만료 로그 검증, missing 엔티티 저장 플래그 검증 (신규 5개 포함 전체 통과).

## 2026-02-27

### 1. 입력 데이터 스키마 검증 도입 (Pydantic + DLQ 격리)
- **배경**: Wikimedia SSE 스트림에서 수신한 raw dict이 검증 없이 파이프라인을 통과하여 Kafka에 적재됨. 필수 필드 누락이나 타입 불일치 이벤트가 하류 시스템(Druid)에서 오류를 유발할 가능성이 있었음.
- **작업**:
  - `src/producer/models.py`에 `WikimediaEvent` Pydantic 모델 정의 (필수 필드: `title`, `server_name`, `type`, `namespace`, `timestamp`, `user`, `bot`; `extra="allow"`로 미정의 필드 보존).
  - `WikidataApiResponse` 모델 추가 (`entities` 키 필수 보장, 나머지 필드는 허용).
  - `main.py`의 `process_batch()`에 이벤트별 검증 루프 추가: `WikimediaEvent.model_validate()` 실패 시 즉시 DLQ로 격리, 성공한 이벤트만 enricher로 전달.
  - `enricher.py`의 `_fetch_chunk()`에서 API 응답을 `WikidataApiResponse`로 검증: 스키마 불일치 시 빈 dict 반환 후 graceful 처리.
  - `sender.py`의 `_send_to_dlq()` → `send_to_dlq()`로 공개 메서드화 (main.py에서 직접 호출 가능하도록).
- **테스트**: `tests/unit/producer/test_models.py` 신규 작성 (9개), `test_main.py`에 DLQ 격리 케이스 2개 추가 — 전체 13/13 통과.
- **결과**: 스키마 불일치 이벤트가 파이프라인 초입에서 차단·보존되며, 정상 이벤트 처리에는 영향 없음.

### 2. Wikidata API ID 수 제한 버그 수정 (50개 청크 처리)
- **배경**: 한 배치의 Q-ID를 전부 한 번의 API 요청에 담아 보내고 있었으나, Wikidata API의 익명 사용자 제한(`lowlimit: 50`)을 초과하면 `toomanyvalues` 에러 응답(HTTP 200)이 반환됨. 응답에 `entities` 키가 없어 enrichment 결과가 항상 0개였음.
- **원인**: `fetch_wikidata_info_in_bulk()`가 q_ids 전체를 `"|".join(q_ids)`로 단일 요청에 전송. 실제 운영에서 배치당 Q-ID가 90~110개로 제한(50개)을 초과.
- **해결**:
  - `fetch_wikidata_info_in_bulk()`를 청크 오케스트레이터로, 실제 HTTP 호출은 `_fetch_chunk()`로 분리.
  - `WIKIDATA_API_BATCH_SIZE = 50` 상수로 청크 크기 명시.
  - Q-ID를 50개씩 나눠 순차 요청 후 결과를 병합.
- **결과**: `Wikidata API로부터 총 102개의 정보를 가져왔습니다.` — enrichment 정상 동작 확인.

## 2026-02-28

### 1. ClickHouse 도입 및 파이프라인 구성

- **작업**: Druid 대체재로 ClickHouse 단일 컨테이너 도입.
  - `docker-compose.yml`에 ClickHouse 서비스 추가 (arm64 네이티브, `clickhouse/clickhouse-server:25.8`).
  - Kafka 테이블 엔진(`wikimedia.recentchange`)으로 Kafka 토픽을 직접 구독.
  - Materialized View로 Kafka 테이블 → MergeTree(`wikimedia.events`) 자동 저장 파이프라인 구성.
  - `wikimedia.events` 스키마: `event_time`, `title`, `server_name`, `wiki_type`, `namespace`, `user`, `bot`, `minor`, `comment`, `wikidata_label`, `wikidata_description`.
- **트러블슈팅 — Kafka 비트랜잭션 토픽**:
  - ClickHouse 24.8에서 `"Kafka topic wikimedia.recentchange is not transactional"` 에러 발생.
  - ClickHouse 25.8 LTS로 업그레이드 후 해소.
- **결과**: 서비스 수 15개 → 8개, 메모리 요구사항 12GB+ → ~4GB 수준으로 감소.

### 2. Grafana Analytics 대시보드 신규 구축

- **작업**: Superset 대체 대시보드 `wikistreams-analytics.json` 작성.
  - Overview 섹션: Total Edits, Active Users, New Articles, Bot Traffic %, Anonymous Edit %, Revert Rate % (6개 stat).
  - 시계열: Human/Bot Edits Over Time.
  - 분포: Top 10 Wikis (bar), Edit Type (pie).
  - 테이블: Top Edited Pages.
  - **Vandalism Monitor 섹션**: 총 Revert 수, Revert Rate %, Bot/Human Revert 분류 stat 4종; Editor Types Over Time 스택 시계열; Vandalism Pressure 오버레이; Top Reverted Articles 테이블.
  - **Real-time Trends 섹션**: Edit Velocity stats 4종 (고정 5분 창); Edit Velocity Trend 시계열 (edits/min 정규화); Trending Articles (spike_ratio: 최근 15분 vs 이전 60분); Cross-wiki Trending.

### 3. Grafana 대시보드 전반 개선 및 버그 수정

- **Producer Performance 대시보드 개편**:
  - 기존 단일 페이지 → Row 구조 (Overview / Throughput / Cache / Logs)로 재편.
  - Cache Hit Rate Trend 시계열, DLQ Events stat 추가.
  - 로그 패널을 핵심 이벤트 키워드 필터링으로 변경 (배치 완료, DLQ, 오류, TTL 만료 등).

- **x축 과밀(Dense X-axis) 수정**:
  - 이슈: 1시간 범위에서 `$__interval_s`가 3~5초로 계산되어 수백 개의 얇은 막대 생성.
  - ClickHouse 쿼리: `INTERVAL $__interval_s second` → `INTERVAL greatest($__interval_s, 60) second` (최소 60초 버킷 보장).
  - Loki 바 차트 패널: `maxDataPoints: 60` 추가 (Grafana 패널 레벨 제한).

- **Top Reverted Articles SQL 버그 수정**:
  - 원인: `HAVING reverts > 0 GROUP BY ...` — ClickHouse가 표준 SQL 순서(`WHERE → GROUP BY → HAVING → ORDER BY`)를 엄격히 요구.
  - 수정: `GROUP BY ... HAVING reverts > 0 ORDER BY ...` 순서로 변경.

- **Cross-wiki Trending 데이터 없음 버그 수정**:
  - 원인: `wikidata_label` 기준 그룹핑 + `wikidata_label != ''` 필터 사용. Producer enrichment는 Wikidata Q-ID 타이틀에만 적용되므로 Wikipedia 언어판 이벤트는 `wikidata_label`이 항상 비어 있어 `wiki_count`가 항상 1.
  - 수정: 그룹핑 키를 `wikidata_label` → `title`로 변경, 공백 필터 제거.

- **Wikidata 레이블 `"-"` 정규화**:
  - 원인: `enricher.py`에서 레이블 미존재 시 `"-"` 폴백 사용. SQLite 캐시에 9,821개 항목이 `"-"`로 저장.
  - 수정: 폴백 값 `"-"` → `""` 빈 문자열로 변경; 기존 캐시 항목 일괄 업데이트.
  - Grafana 쿼리에도 `NOT IN ('', '-')` 방어 로직 추가.
