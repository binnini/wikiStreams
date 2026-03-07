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

## 2026-03-01

### 1. Reporter 고도화 (Discord Embed 5카드 체계)

- **배경**: 초기 구현(4개 Embed, 단순 목록)에서 가독성·정보 밀도 개선 요청.
- **작업 — 콘텐츠 강화**:
  - `TopPage` 데이터클래스에 `url`, `thumbnail_url`, `rank_change`, `is_spike`, `spike_ratio_val`, `crosswiki_count` 필드 추가.
  - `wiki_url()`: 문서 제목을 URL 인코딩하여 Wikipedia 직접 링크 생성.
  - Wikipedia REST API(`/api/rest_v1/page/summary/{title}`)로 1위 문서 썸네일 자동 수집.
  - Wikipedia Featured Article API(`/api/rest_v1/feed/featured/{y}/{m}/{d}`)로 오늘의 특집 문서 수집 — Discord에 "📚 교양 코너"로 표시.
  - ClickHouse에서 전일 Top 10을 별도 조회하여 `rank_change` 계산 (신규 진입 시 `None` → 🆕 배지).
  - 편집 피크 시간대(`PeakHour`) 조회 및 숫자 브리핑 Embed에 표시.
  - `wiki_type='edit'` 필터: 신규 문서 생성 이벤트를 Top 5와 Grafana 2개 패널에서 제외.
  - 언어 국기 이모지 매핑 15개(`_WIKI_FLAGS`), 스파이크(⚡)·다국어(🌍) 시각 배지.

- **작업 — 뉴스 스크래핑 개선**:
  - Google News RSS 스크래핑 도입: `https://news.google.com/rss/search?q={query}&{edition}`.
  - 한국어판 우선 조회 → 결과 없을 시 영어판 fallback (2단계 edition 루프).
  - 48시간 freshness 필터: `pubDate`를 `email.utils.parsedate_to_datetime()`으로 파싱.
  - 한국어판은 관련성 필터 스킵 (한글 헤드라인은 영어 키워드 매칭 불가), 영어판에만 키워드 필터 적용.

- **작업 — Claude 배치 키워드 추출**:
  - `build_report()` 반환 타입 `dict[str, str]` → `tuple[dict[str, str], list[list[str]]]`.
  - 기존 Claude 호출 1회로 섹션 5개 + `news_keywords`(상위 3개 문서별 고유명사 1~3개) 동시 추출 — 추가 API 비용 없음.
  - 파이프라인 재구조: `fetch_report_data()` → `build_report()` → `fetch_news_with_keywords()` → `publish_report()`.

- **작업 — Embed 재구성**:
  - "글로벌 관심사 & 트렌딩" Embed를 Top 5 Embed로 통합 (6개 → 5개 카드).
  - 최종 순서: 헤드라인 → 숫자 브리핑 → Top 5 문서 → 논쟁/반달리즘 → 교양코너.
  - `top5_analysis` 단일 Claude 섹션으로 스파이크·다국어 문서 통합 해설.

### 2. Reporter 단위/통합 테스트 구축 (Claude API 비용 절감)

- **배경**: 리포터 개발 시 매번 Claude API를 직접 호출하여 비용이 발생. 모든 외부 의존성을 mock으로 대체하는 테스트 스위트 구축.
- **작업**:
  - `tests/unit/reporter/test_fetcher.py` (30개): `wiki_url` 순수 함수, `_fetch_news` 한국어/영어 fallback·48h 필터·관련성 필터, `fetch_news_with_keywords`, `_fetch_featured_article`, `_fetch_thumbnail`, `fetch_report_data` spike/crosswiki enrichment·rank_change 계산.
  - `tests/unit/reporter/test_builder.py` (16개): `_build_context` 컨텐츠 검증, `build_report` Claude 응답 파싱·JSON fallback·`news_keywords` 분리.
  - `tests/unit/reporter/test_publisher.py` (28개): `_rank_badge`·`_wiki_flag`·`_truncate` 순수 함수, `_build_top5_embed`·`_build_featured_embed` 구조, `publish_report` Embed 순서·개수.
  - `tests/unit/reporter/test_main.py` (5개): `run_report` 파이프라인 순서, 뉴스 데이터 전달, 예외 격리.
  - `tests/integration/test_reporter_integration.py` (7개): 실제 Wikipedia Featured Article API, Google News RSS (`@pytest.mark.integration`).
- **httpx mock 패턴** (컨텍스트 매니저):
  ```python
  mock_cm = MagicMock()
  mock_cm.__enter__.return_value = mock_cm
  mock_cm.__exit__.return_value = False
  mock_cm.get.return_value = mock_resp
  mocker.patch("httpx.Client", return_value=mock_cm)
  ```
- **총 88개 단위 테스트 통과**.

### 3. ElementTree bool 버그 수정 (`fetcher.py`)

- **이슈**: `_fetch_news()`가 항상 빈 리스트(`[]`)를 반환 — 뉴스 스크래핑이 동작하지 않았음.
- **원인**: Python의 `xml.etree.ElementTree.Element`는 자식 엘리먼트가 없을 때 `bool(element) == False`로 평가됨. `<title>텍스트</title>` 처럼 텍스트만 있는 엘리먼트도 자식 없으면 falsy. 결과적으로 `if not title_el` 조건이 항상 `True`가 되어 모든 RSS 아이템이 필터링됨.
- **해결**: `if not title_el or not link_url:` → `if title_el is None or not link_url:`
- **교훈**: ElementTree 엘리먼트 존재 여부 확인은 반드시 `is None` / `is not None`으로 해야 함 (`not element` 사용 금지).

### 4. 뉴스 스크래핑 관련성 필터 개선 및 Docker 이미지 재빌드

- **이슈**: 운영 환경(`docker compose run --rm reporter`)에서 "News fetched: 0 items" 지속 — 단위 테스트는 전부 통과하는 상황.

- **원인 1 — 다중 단어 키워드 미분리 (`fetch_news_with_keywords`)**:
  - Claude가 `['Ali Khamenei']` 같은 다중 단어 키워드를 반환할 때 관련성 집합을 `{"ali khamenei"}`(구문 전체)로 만들어, 헤드라인에 부분 문자열 매칭이 불가능.
  - **해결**: `{kw.lower() for kw in kws if len(kw) >= 3}` → `{word.lower() for kw in kws for word in kw.split() if len(word) >= 3}` — 단어 단위로 분리.

- **원인 2 — 한국어판에도 관련성 필터 적용 (`_fetch_news`)**:
  - 초기 구현에서 관련성 필터를 한국어판/영어판 구분 없이 적용. 한국어 구글 뉴스는 이미 쿼리로 관련성이 보장되므로 추가 키워드 필터가 오히려 결과를 차단.
  - **해결**: `apply_relevance = (i > 0) and bool(relevance_keywords)` 플래그 도입 — 영어판(fallback)에만 관련성 필터 적용.

- **원인 3 — Docker 이미지 stale**:
  - 위 두 수정 사항이 소스코드에 반영됐으나 `reporter` 컨테이너 이미지가 재빌드되지 않아 운영에 미반영 상태였음.
  - 단위 테스트는 로컬 소스 코드를 직접 참조하므로 이상 없이 통과 → 테스트 통과와 운영 동작 불일치 발생.
  - **해결**: `docker compose build reporter` 후 `docker compose up -d reporter`로 재시작.

- **결과**: News fetched: 4 items (Discord 5 Embed 정상 발송 확인).
- **단위 테스트**: 다중 단어 키워드 분리 케이스 `test_multiword_keyword_split_into_individual_words` 추가 → **총 89개 통과**.

### 5. Discord Embed 템플릿 개선

- **배경**: 숫자 브리핑이 Claude 생성 텍스트 단일 블록으로 가독성이 낮고, 논쟁 문서 섹션이 Claude 텍스트만 나열되어 구조화된 데이터를 활용하지 못하는 문제.

- **숫자 브리핑 개편** (`publisher.py`):
  - 제목: `숫자 브리핑` → `📊 숫자로 보는 위키백과 (최근 24시간)`
  - Claude 텍스트 단일 필드 → **Big Number 인라인 필드** 4종으로 교체:
    - ✏️ 총 편집 수 / 👥 활성 편집자 / 🤖 봇 편집 비율 / 📄 신규 문서 (3열 그리드)
    - ⏰ 편집 피크 시간대 (peak_hour >= 0 일 때만 추가)

- **논쟁/반달리즘 Embed 개편** (`publisher.py`):
  - 제목: `⚠️ 논쟁/반달리즘 문서` → `⚠️ 논쟁 및 반달리즘 (편집 분쟁) 주요 문서`
  - Description: Claude 생성 **1-2문장 도입부** (분야·맥락 요약)
  - Fields: `data.revert_pages`에서 문서별 구조화 필드 — `되돌리기율 N%  ·  총 N회 편집 중 N회 되돌림`

- **`controversy` 프롬프트 개선** (`builder.py`):
  - 기존: 문서별 현황 2-3문장 나열 → 신규: 분야/주제 공통 맥락 1-2문장 도입부만 작성 (개별 수치 언급 금지 — structured field로 별도 표시)

- **테스트**: `test_embed_order` 숫자 브리핑 제목 검사 업데이트 → **89개 전부 통과**.

### 6. 전체 단위 테스트 스위트 정상화 (`PYTHONPATH=src pytest tests/unit/`)

- **이슈 1 — pytest 모듈명 충돌**: `tests/unit/producer/test_main.py`와 `tests/unit/reporter/test_main.py`가 동일한 모듈명으로 충돌하여 컬렉션 오류 발생.
  - **원인**: 테스트 디렉터리에 `__init__.py`가 없으면 pytest가 파일명만으로 모듈을 식별 → 중복 시 `import file mismatch` 에러.
  - **해결**: `tests/`, `tests/unit/`, `tests/unit/producer/`, `tests/unit/dlq_consumer/`, `tests/unit/reporter/`, `tests/integration/` 모든 디렉터리에 `__init__.py` 추가.

- **이슈 2 — enricher 테스트 기대값 불일치**: `test_enricher.py`의 4개 케이스가 `wikidata_label: "-"` / `wikidata_description: "-"` 를 기대했으나 실제 enricher가 `""` 반환.
  - **원인**: 2026-02-28 ClickHouse 마이그레이션 시 enricher의 누락 값 폴백을 `"-"` → `""` 빈 문자열로 정규화했으나 테스트 기대값은 갱신되지 않음.
  - **해결**: 4개 케이스 기대값 `"-"` → `""` 수정.

- **결과**: **135개 전부 통과** (producer 44 + dlq_consumer 4 + reporter 87).

### 7. Top 5 다양성 개선: Q-ID 중복 제거 + LLM 주제 그룹핑 (feat/top5-diversity)

- **배경**: Top 5가 `ORDER BY edits DESC LIMIT 10`으로 단순 선정되어, 동일 사건(예: 이스라엘-이란 공습)의 영어판·러시아어판·스페인어판·아랍어판이 여러 슬롯을 차지하는 중복 문제 발생. 두 가지 개선으로 해결.

- **개선 1 — Q-ID 기반 중복 제거**:
  - ClickHouse 쿼리를 `LIMIT 10` → `LIMIT 20`으로 확장하여 더 많은 후보 확보.
  - `_fetch_qid(server_name, title)`: Wikipedia REST API(`/api/rest_v1/page/summary/{title}`)의 `wikibase_item` 필드로 Wikidata Q-ID 조회. Wikidata 문서면 타이틀 자체(`Q\d+`)를 반환, HTTP 오류 시 `None`.
  - `ThreadPoolExecutor(max_workers=10)`으로 모든 후보 페이지의 Q-ID를 병렬 조회.
  - `_deduplicate_by_qid()`: 동일 Q-ID의 첫 번째(편집 수 최다) 페이지만 유지. Q-ID 없는 페이지는 고유 fallback 키(`_{server_name}/{title}`)로 처리하여 항상 보존.
  - 실제 데이터 기준: `LIMIT 20` 후보 → 약 12개 고유 주제로 압축 (8개 중복 제거).

- **개선 2 — LLM 주제 그룹핑 (selected_indices)**:
  - `_build_context()` 수정: 상위 5개 대신 **전체 후보**를 `[0]`, `[1]`, … 0-based 인덱스 형식으로 표시. 스파이크(⚡)·다국어(🌍) 배지 포함.
  - `build_report()` 프롬프트에 `selected_indices` 지시 추가: Claude가 같은 사건/인물 중복 배제, 스파이크·다국어 우선, 분야 다양성을 기준으로 5개 인덱스 선택.
  - 응답 파싱 후 `data.top_pages`를 선택된 인덱스 순으로 재구성. 인덱스 범위 초과·비리스트·빈 배열 등 모든 비정상 응답에 대해 `[:5]` fallback 적용.
  - `max_tokens` 1400 → 1800 (후보 목록 증가 대응).
  - 썸네일 fetch를 `fetch_report_data()` 내부 Step 9에서 제거 → `main.py`의 `build_report()` 직후로 이동하여 LLM이 최종 선택한 1위 문서의 썸네일을 표시.

- **결과**: `After Q-ID dedup: 12 unique topic candidates` → `LLM selected indices: [0, 1, 3, 4, 6]` 로그 확인. 단위 테스트 89개 → **115개 전부 통과**.

### 8. 다언어판 편집 수 표시 및 뉴스 주제별 3건 개선

- **배경**: Q-ID 중복 제거 후 대표 페이지 하나만 표시되어, 묶인 언어판들의 편집 수 정보가 소실됨. 뉴스 스크래핑도 전체 5건 상한으로 주제별 불균형 발생.

- **언어판별 편집 수 + 합계 표시**:
  - `LangEdition(server_name, edits)` 데이터클래스 신규 추가.
  - `TopPage.lang_editions: list[LangEdition]` 필드 추가 (기본값 빈 리스트).
  - `_deduplicate_by_qid()` 개선: 첫 번째 중복 발견 시 대표 페이지 자체를 `lang_editions[0]`으로, 이후 중복들을 순서대로 추가. 단일 언어판 페이지는 `lang_editions = []` 유지.
  - `publisher._build_top5_embed()`: `lang_editions`가 비어 있으면 기존 단일 포맷(`🇺🇸 EN · 450회 편집`), 2개 이상이면 `🇺🇸 EN 450회 · 🇷🇺 RU 320회 · 🇪🇸 ES 280회 | 합계 1,050회` 포맷으로 분기.

- **뉴스 주제별 3건**:
  - `fetch_news_with_keywords()`: `_fetch_news(max_items=2)` → `max_items=3`, 전체 `[:5]` 상한 제거.
  - 3개 주제 × 최대 3건 = 최대 9건. 실제 운영에서 "News fetched: 7 items" 확인.

- **테스트**: `TestDeduplicateByQid`에 `lang_editions` 검증 케이스 4개, `TestBuildTop5Embed`에 다언어판·단일 포맷 분기 테스트 2개, `TestFetchNewsWithKeywords`에 `max_items=3` 검증 2개 추가 → **115개 전부 통과**.

### 9. `collector.py` 개선 (지수 백오프 + 로깅 정리)

- **배경**: 재연결 대기가 고정 10초로 하드코딩되어 있고, 모듈 레벨 `logging.basicConfig()` 호출이 앱 진입점(`main.py`)과 중복되는 문제.

- **변경 1 — 지수 백오프 도입**:
  - 기존: `time.sleep(10)` 고정
  - 변경: 초기 2초에서 시작해 실패할 때마다 2배씩 증가, 최대 60초 상한 (`_RETRY_BASE_DELAY = 2.0`, `_RETRY_MAX_DELAY = 60.0`)
  - 연결 성공 시 `retry_delay`를 `_RETRY_BASE_DELAY`로 초기화
  - `httpx.HTTPError`와 그 외 예외 양쪽 모두 동일한 백오프 적용

- **변경 2 — 모듈 레벨 로깅 제거**:
  - `logging.basicConfig(...)` 제거 → `logger = logging.getLogger(__name__)`
  - 로깅 설정 책임을 앱 진입점(`main.py`)으로 일원화
  - f-string 로그 메시지 → `%s` lazy 포맷으로 변경 (불필요한 문자열 생성 방지)

- **테스트**: `test_exponential_backoff` 추가 — HTTP 오류 2회 연속 발생 시 `sleep(2.0)` → `sleep(4.0)` 순서로 호출되는지 검증 → **136개 전부 통과**.

### 10. Reporter 프롬프트 패키지화 및 스타일 선택 기능 추가

- **배경**: Claude 호출에 사용하는 프롬프트 파일이 `prompts.py`(기본 뉴스 에디터)와 `prompts_doro.py`(도로롱 캐릭터) 두 개의 플랫 파일로 분리되어 있어, 스타일 추가 시 관리가 어렵고 실행 중 스타일 전환이 불가능했음.

- **작업**:
  - `src/reporter/prompts.py`, `src/reporter/prompts_doro.py` → `src/reporter/prompts/` 패키지로 이전.
    - `prompts/default.py`: 기존 기본 에디터 프롬프트 (한국어 뉴스 에디터 역할).
    - `prompts/doro.py`: 도로롱(Doro) 캐릭터 프롬프트 (아가씨 말투 + 광기).
    - `prompts/__init__.py`: `settings.prompt_style`을 읽어 `importlib.import_module()`으로 해당 스타일 모듈을 동적 로드. `SYSTEM_PROMPT`와 `build_user_message`를 패키지 레벨로 re-export.
  - `src/reporter/config.py`에 `prompt_style: str = "default"` 설정 추가. `PROMPT_STYLE` 환경변수로 런타임 제어 가능.
  - `builder.py` 임포트는 `from reporter.prompts import ...` 그대로 유지 — 변경 불필요.

- **새 스타일 추가 방법**: `src/reporter/prompts/` 디렉터리에 `SYSTEM_PROMPT`와 `build_user_message()`를 정의한 `{name}.py` 파일 추가 → `PROMPT_STYLE={name}` 환경변수만 설정하면 즉시 적용.

- **테스트**: `test_prompts.py` 대폭 보강.
  - `TestDefaultPrompts` (6개): default 모듈 독립 검증.
  - `TestDoroPrompts` (6개): doro 모듈 캐릭터·말투·스키마 검증.
  - `TestPromptStyleDispatch` (3개): 두 스타일 인터페이스 동일성, 콘텐츠 상이성 검증.
  - 기존 6개 유지 → **총 21개 통과** (reporter 단위 전체 52개 통과).

### 11. Reporter 결과물 JSON 저장 기능 추가

- **배경**: 매일 Discord로 발송되는 리포트가 별도로 보존되지 않아 과거 데이터 조회·비교·재활용이 불가능했음.

- **작업**:
  - `src/reporter/storage.py` 신규 생성 — `save_report(sections, data)` 함수 하나로 구성.
    - `dataclasses.asdict()`로 모든 dataclass 필드를 직렬화.
    - `reports/YYYY-MM-DD.json`으로 저장 (같은 날 재실행 시 덮어씀 — 최신 결과 유지).
    - 저장 경로는 `settings.report_storage_dir`(기본값 `/app/reports`)로 추상화.
  - `src/reporter/config.py`에 `report_storage_dir: str = "/app/reports"` 설정 추가.
  - `src/reporter/main.py`의 `run_report()`에서 Discord 발송 직후 `save_report()` 호출 (Step 6).
  - `docker-compose.yml` reporter 서비스에 `./reports:/app/reports` 볼륨 마운트 + `REPORT_STORAGE_DIR` 환경변수 추가 → 컨테이너 재시작·재빌드 후에도 파일 유지.
  - `reports/.gitkeep`으로 디렉토리 구조만 git 추적, `.gitignore`에 `reports/*.json` 추가 (실제 리포트 파일은 미추적).

- **저장 JSON 스키마**:
  ```json
  {
    "generated_at": "2026-03-01T17:22:54+09:00",
    "prompt_style": "doro",
    "sections": { "headline": "...", "top5_analysis": "...", ... },
    "stats": { "total_edits": 2508953, "active_users": 13420, ... },
    "peak_hour": { "hour": 20, "edits": 158432 },
    "top_pages": [ { "label": "...", "edits": 1359, "lang_editions": [...], ... } ],
    "revert_pages": [ ... ],
    "featured_article": { "title": "...", "url": "...", ... },
    "news_items": [ { "title": "...", "link": "...", "source": "..." } ]
  }
  ```

- **결과**: 첫 실행에서 `reports/2026-03-01.json` (10KB) 정상 생성 확인. `Report saved → /app/reports/2026-03-01.json` 로그 출력.

### 12. CI 의존성 누락 수정 (`requests`, `docker`)

- **이슈 1 — `requests` 미설치**:
  - `tests/integration/test_e2e_pipeline.py`가 `import requests`를 사용하나 `requirements-dev.txt`에 미포함.
  - CI에서 `ModuleNotFoundError: No module named 'requests'` 발생 → 전체 integration 테스트 컬렉션 실패.
  - **해결**: `requirements-dev.txt`에 `requests` 추가.

- **이슈 2 — `docker` SDK 미설치**:
  - `resource-monitor` 단위 테스트(`test_collector.py`)가 `docker` 패키지를 임포트하나 `requirements-dev.txt`에 미포함.
  - **해결**: `requirements-dev.txt`에 `docker` 추가.

- **이슈 3 — CI `Install dependencies` 단계 누락**:
  - `src/resource_monitor/requirements.txt`가 CI workflow에서 설치되지 않아 단위 테스트 임포트 오류 예상.
  - **해결**: `.github/workflows/ci.yml`에 `pip install -r src/resource_monitor/requirements.txt` 단계 추가.

### 13. 리소스 이상 감지 서비스 구현 (`resource-monitor`)

- **배경**: `docker-stats-logger`는 단순 shell script로 CPU/Memory 2개 메트릭만 stdout으로 출력. 이상 감지·알림 로직이 전혀 없고 메모리 누수(`mem_mb`)나 I/O 폭증(`block_io_mb`) 감지도 불가능했음.

- **작업**:
  - `src/resource_monitor/` 신규 패키지 생성 (config, baseline, detector, alerter, collector, main).
  - **`collector.py`**: Docker SDK(`docker.from_env()`)로 10초 간격 stats 수집. 4개 메트릭:
    - `cpu_pct`: `cpu_delta / sys_delta × num_cpus × 100`
    - `mem_pct`: `(usage - cache) / limit × 100`
    - `mem_mb`: 절댓값 MB (점진적 메모리 누수 감지)
    - `block_io_mb`: `blkio_stats` 누적값 델타 / 10초 — ClickHouse merge/write 폭증 감지
  - **`baseline.py`**: SQLite 기반 컨테이너 × 시간대(hour bucket 0–23) 학습 저장소.
    - EMA (Exponential Moving Average, `alpha=0.1`): 느린 평활화로 장기 baseline 추적.
    - Welford online variance: 표본 분산을 실시간 1-pass 갱신. 재시작 후에도 `resource_monitor_baseline.db`에서 학습 상태 복원.
    - `INSERT OR REPLACE`로 upsert 구현.
  - **`detector.py`**: z-score = `(current - ema) / std`. `|z| > 2.5` 이고 `count >= 30` 샘플 이상일 때만 `AnomalyResult` 반환 (학습 초기 억제).
  - **`alerter.py`**: Discord Embed 카드 발송. `(container, metric)` 쌍별 1시간 cooldown — `monotonic()` 기반 인메모리 추적. Embed 필드: 컨테이너명, 메트릭, 현재값, 시간대 EMA, z-score, 방향(급증/급감).
  - **`main.py`**: 메인 루프. 이상 감지 시 `level=warn msg="AnomalyDetected"` 구조화 로그 → Loki + Discord 동시 발송.
  - `docker-compose.yml`: `docker-stats-logger` 제거 → `resource-monitor` 교체. `resource_monitor_data` 볼륨으로 SQLite DB 영속화.

- **테스트**: 단위 테스트 39개 (baseline 9 / detector 8 / alerter 10 / collector 12) — 전체 **235개 통과**.

- **설계 결정 — EMA vs 단순 이동평균**:
  - 단순 이동평균은 윈도우 크기만큼의 히스토리를 보관해야 함. EMA는 단일 `ema` 값만 유지 — SQLite row 1개로 충분.
  - Welford 알고리즘은 분산 계산 시 중간값을 저장하지 않아도 되며, 수치적으로 안정적 (Big sum 빼기 Big sum 문제 없음).

- **`docker compose up -d` 후 min_samples 30개 도달까지(약 5분) 이상 감지 억제** — false alarm 방지.

### 14. Grafana Resources 대시보드 — Anomaly Detection 패널 추가

- **배경**: `resource-monitor`가 Loki에 `level=warn msg="AnomalyDetected"` 로그를 기록하나, 대시보드에서 조회할 방법이 없었음. 기존 패널 쿼리의 컨테이너 레이블도 구버전(`docker-stats-logger`)을 참조 중.

- **작업**:
  - **기존 패널 쿼리 수정**:
    - 모든 Loki 쿼리의 `container="docker-stats-logger"` → `container="resource-monitor"` 교체.
    - CPU/Memory 쿼리에 `|= "DockerStats"` 필터 추가 — AnomalyDetected 로그가 `unwrap cpu_pct` 집계에 섞이지 않도록 격리.
  - **Anomaly Detection 섹션 신규 추가** (y=45 이후):
    - **Anomaly Rate** (timeseries, stacked bar): `count_over_time({container="resource-monitor"} |= "AnomalyDetected" | logfmt | msg="AnomalyDetected" [$__interval])`. `sum by (container, metric)`으로 모니터링 대상 컨테이너 × 메트릭 조합 구분.
    - **Anomaly Events** (logs): `{container="resource-monitor"} |= "AnomalyDetected" | logfmt | msg="AnomalyDetected"`. 최신 순 로그 라인 표시, 상세 보기(Enable Log Details) 활성화.
  - 대시보드 version: 10 → 11.

- **orphan 컨테이너 정리**:
  - `docker compose up -d`만으로는 compose 파일에서 제거된 컨테이너(`docker-stats-logger`, `promtail`)가 자동으로 제거되지 않음.
  - `docker compose up -d --remove-orphans` 실행으로 두 컨테이너 정상 제거 확인.

### 15. ClickHouse CPU Spike 원인 분석 — MergeTree 백그라운드 Merge

- **관찰**: Grafana Resources Monitor CPU Trends에서 50~68% CPU spike가 약 60~90초 주기로 반복 발생. 각 spike는 30초 내외로 종료되며 이후 4~12%로 즉시 복귀.

- **원인 파악**:
  - `system.part_log`를 조회하여 `MergeParts` 이벤트가 spike와 정확히 일치함을 확인.
  - Kafka Materialized View가 수신 데이터를 소형 파트로 지속 생성 → MergeTree 백그라운드 워커가 주기적으로 파트를 병합.
  - spike 정점에서 항상 `block_io_mb` 13~21 MB/s 동반 — I/O와 CPU가 동시 상승하는 패턴이 merge의 특징.
  - 현재 `wikimedia.events` 파트 수: **22개** (정상 범위), 총 데이터 크기: 123 MB.

  ```
  12:32:56  merge 61ms  202603_5922_6172_23   ← 대형 누적 merge
  12:33:11  merge  7ms  202603_6173_6178_1
  12:34:23  merge  9ms  202603_6173_6185_2
  12:35:35  merge  5ms  202603_6173_6194_3
  (이후 약 60~90초 간격으로 반복)
  ```

- **결론 — 정상 동작, 단 두 지표 주시 필요**:

  | 지표 | 현재 | 판단 |
  |---|---|---|
  | CPU spike 높이 | 50~68% | 일시적(~30초), merge 후 즉시 복구 → 정상 |
  | CPU spike 주기 | 60~90초 | Kafka 수신량에 비례한 예측 가능한 노이즈 |
  | Merge 소요 시간 | 5~61ms | 매우 빠름, 쿼리 차단 없음 → 정상 |
  | Block I/O | 15~22 MB/s 상시 | 지속적인 Kafka 쓰기 + merge — 관찰 지속 필요 |
  | 메모리 drift | +6 MB/분 (20분간) | 장기 선형 증가 시 OOM 위험 → **장기 관찰 필요** |

- **Resource Monitoring 시 고려 사항**:
  1. **예측 가능한 노이즈 구별**: MergeTree merge처럼 주기적으로 반드시 발생하는 CPU spike는 이상이 아님. z-score 베이스라인이 충분히 쌓이면 이 패턴도 "평균"에 흡수되어 오알람이 억제됨.
  2. **CPU보다 메모리 drift와 IO 지속 상승이 더 위험한 신호**: CPU spike는 짧고 복구되지만, 메모리 완만한 증가는 누수(leak) 또는 캐시 미반환의 전조일 수 있음.
  3. **메트릭 간 상관관계**: "CPU 60% + IO 17MB/s 동시" → merge. "CPU 60% + IO 0" → 순수 연산(쿼리 집중). 단일 메트릭만으로는 오판 가능.
  4. **지속 시간(Duration)이 severity를 결정**: 60% CPU 30초 → 정상 merge. 60% CPU 5분 지속 → 비정상 쿼리 또는 루프.
  5. **홈랩 CPU 공유 환경**: ClickHouse merge가 활발할 때 producer CPU도 순간 상승 (`producer cpu_pct=11.82` 관찰). OS 스케줄러 경쟁 효과.

- **향후 조치**:
  - 메모리 drift를 며칠 더 관찰. 선형 증가가 지속되면 `OPTIMIZE TABLE wikimedia.events FINAL`로 파트 강제 병합하거나 ClickHouse `max_memory_usage` 설정 검토.
  - resource-monitor 베이스라인이 충분히 학습되면 (시간대별 30+ 샘플) merge spike가 자동으로 "정상 범위"로 인식될 예정.

### 16. resource-monitor hour 버킷 UTC → KST 교체

- **이슈**: `main.py`에서 `datetime.now(tz=timezone.utc)`로 시간대를 UTC 기준으로 나눠 베이스라인을 저장. Discord 알림의 "시간대 평균 (12시)"가 실제 KST 21시 패턴을 가리켜 혼란 발생.
- **해결**: `zoneinfo.ZoneInfo("Asia/Seoul")`로 교체. `zoneinfo`는 Python 3.9+ 표준 라이브러리로 별도 의존성 없음.
- **부작용**: 기존 SQLite에 UTC 기준으로 학습된 hour 버킷 데이터가 잔존. KST 버킷이 min_samples=360에 도달하기 전까지(새 시간대당 약 1시간) 이상 감지 억제됨. 깔끔하게 재시작하려면 `resource_monitor_data` 볼륨 초기화 필요.

### 17. resource-monitor min_samples 조정 (30 → 360) 및 이원화 배경 이해

- **배경**: `min_samples=30`은 수집 간격 10초 기준 5분만 지나면 알람이 활성화됨 — EMA·분산이 충분히 안정되지 않은 상태에서 false alarm 가능성 높음.

- **hour 버킷 구조 이해**:
  - SQLite에 `(container, metric, hour)` 조합별로 독립적인 EMA·variance 레코드 유지.
  - 각 hour 버킷은 하루에 딱 1시간(3600초 ÷ 10초 = 360 샘플/일)만 데이터를 받음.
  - 시간대를 나누는 이유: 새벽 3시의 "정상 CPU 5%"와 저녁 9시의 "정상 CPU 25%"를 같은 평균으로 취급하면 오알람 발생.

- **min_samples 계산**:
  ```
  min_samples = 360  →  360 × 10초 = 1시간분 데이터 필요
  24개 버킷 전체 활성화 = 약 1일 (각 시간대를 최소 1회 통째로 관찰)
  ```

- **결정**: `min_samples = 360` 설정. 첫날은 학습 전용, 이튿날부터 점진적으로 버킷이 활성화됨.

### 18. CI 파이프라인 이원화 (unit-tests / integration-tests 분리)

- **배경**: 단일 job에서 PR마다 `docker compose up` + 60초 대기 + 통합 테스트를 실행하여 불필요한 시간과 비용 발생. PR에서는 빠른 피드백만 필요.

- **변경**:
  - `unit-tests` job (PR + main push): Lint → Format → Unit Tests. Docker 불필요. 약 1~2분.
  - `integration-tests` job (main push 전용):
    - `needs: unit-tests` — unit 통과 후에만 시작.
    - `if: github.event_name == 'push' && github.ref == 'refs/heads/main'` — `pull_request` 이벤트는 조건 불충족으로 job 자체가 스킵.
    - Docker Compose 기동 → sleep 60 → `tests/integration/` 전체 실행.

- **결과**: PR 피드백 속도 향상, main 머지 시에만 인프라 의존 테스트 실행.

## 2026-03-03

### 1. Loki 데이터 영속화 및 30일 Retention 설정

- **이슈**: `docker compose down` 후 재시작 시 Error Monitor, Producer Performance, Resources Monitor 대시보드의 모든 로그 데이터가 소실됨.
- **원인**:
  - `loki-config.yaml`의 `path_prefix`가 `/tmp/loki`로 설정되어, 컨테이너 종료 시 임시 경로의 데이터가 함께 삭제됨.
  - `docker-compose.yml`의 loki 서비스에 데이터 저장용 named volume이 없어 영속화가 불가능한 구조였음.
  - ClickHouse(`clickhouse_data`), Grafana(`grafana_data`) 등 다른 서비스는 named volume을 사용하고 있어 재시작 후에도 데이터가 유지됨.
- **해결**:
  - `docker-compose.yml`: `loki_data` named volume 추가 + loki 서비스에 `loki_data:/loki` 마운트.
  - `loki-config.yaml`: `path_prefix` 및 `chunks_directory`, `rules_directory`를 `/tmp/loki` → `/loki`로 변경.
  - `compactor` + `limits_config` 추가로 30일(720h) retention 설정 — 오래된 로그 자동 삭제로 용량 무한 증가 방지.

### 2. Loki 설정 오류 수정 (`delete_request_store` 누락)

- **이슈**: retention 설정 적용 후 loki 컨테이너가 반복 재시작하며 로그 수집 중단.
- **원인**: Loki 3.0에서 `retention_enabled: true` 사용 시 `compactor.delete_request_store`를 반드시 명시해야 함. 누락 시 `CONFIG ERROR: invalid compactor config: compactor.delete-request-store should be configured when retention is enabled` 에러로 기동 실패.
- **해결**: `loki-config.yaml`의 `compactor`에 `delete_request_store: filesystem` 추가.
- **결과**: `Loki started` 정상 기동 확인. 이후 `docker compose down/up` 사이클에서도 로그 데이터 유지됨.

## 2026-03-06

### 1. SLO 수립 로드맵 완료 (Stage 1–3, 5–6)

- **배경**: 운영 품질을 정량적으로 측정하고 관리하기 위한 SLI/SLO/SLA 프레임워크 수립.
- **작업**:
  - `docs/NFR.md` + `docs/SRE.md`: 비기능 요구사항 및 SRE 운영 원칙 정의 (Stage 1).
  - `docs/SLI.md`: 14개 SLI 계측 정의 — 가용성(A), 성능(P), 신뢰성(R), 데이터 품질(D), 용량(CAP), 복구(RC) 6개 카테고리 (Stage 2).
  - `docs/SLO.md`: 11개 SLO + 에러 버짓 + 측정 방법 + 제외 조건 정의 (Stage 3).
  - `docs/SLA.md`: 가용성 약속, 위반 처리 절차, 월간 리뷰 주기, 데이터 보존 목표 (Stage 5).
  - `monitoring/grafana-alert-rules.yaml`: SLI-D1, A3, R1, P7, CAP1, CAP2 6개 알림 규칙 (Stage 6).
  - `monitoring/grafana-contact-points.yaml`: Discord Webhook 연락처 설정.
  - `monitoring/grafana-notification-policy.yaml`: 심각도별 라우팅 (critical 1시간 반복, warning 4시간 반복).
  - `monitoring/dashboards/wikistreams-slo.json`: Grafana SLO 대시보드 — 5개 Row(가용성·성능·신뢰성·데이터 품질·용량), 15개 패널 (Stage 6).
- **현재 상태**: Stage 4(관측 기간, 1–4주)는 진행 중. SLO 초기값은 관측 데이터 수집 후 확정 예정.

### 2. Producer 침묵 버그 수정 (배치 타임아웃 미발동)

- **이슈**: Producer 컨테이너 재빌드 후에도 배치가 처리되지 않아 ClickHouse에 데이터가 적재되지 않음.
- **원인**:
  - 배치 타임아웃 체크가 `if not sse.data:` 분기 내부에 위치 — Wikimedia heartbeat는 SSE comment(`:ok`) 형식이라 `httpx-sse`가 `iter_sse()` 이벤트로 노출하지 않음. 따라서 저트래픽 상황에서 데이터 이벤트가 배치 크기(500)에 도달하기 전까지 타임아웃이 영원히 발동되지 않음.
- **해결**: 타임아웃 체크를 `for sse in event_source.iter_sse():` 루프 최상단으로 이동. 모든 SSE 이벤트(데이터·비데이터 무관)마다 타임아웃 조건을 평가.
- **추가 개선**:
  - `_sse_received_total` 카운터 추가 — 배치 처리 로그에 누적 수신 이벤트 수 표시 (`SLI-R5`).
  - `_last_event_id` 추적 + 재연결 시 `Last-Event-ID` 헤더 전송 — 재연결 후 서버 백필로 이벤트 손실 최소화.
  - `main.py`에 `time.perf_counter()` 기반 배치 처리 시간 계측 추가 (`SLI-P1`).
- **테스트 수정**:
  - `by_timeout` 시나리오: `time.time()` mock `side_effect`에 3번째 값 추가 (`[0.0, 0.2, 0.2]`) — Python `LogRecord.__init__`가 `time.time()`을 내부적으로 호출하여 side_effect를 소비하는 문제.
  - `last_processed_time = 0.0` 설정을 `if time_side_effect:` 블록 안으로 이동 — 다른 시나리오에서 초기 타임아웃이 오발동되는 문제 수정.

### 3. Grafana 재시작 불가 수정 (alerting provisioning 환경변수 누락)

- **이슈**: `docker compose up -d` 후 Grafana 컨테이너가 `Restarting (1)` 루프에 빠져 접속 불가.
- **원인**: `grafana-contact-points.yaml`에서 `${DISCORD_WEBHOOK_URL}`을 참조하나, Grafana 컨테이너 환경변수에 해당 값이 주입되지 않아 provisioning 단계에서 hard fail.
- **해결**: `docker-compose.yml` Grafana 서비스 `environment`에 `DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}` 추가.
- **교훈**: Grafana provisioning YAML의 `${VAR}` 치환은 Grafana 프로세스의 환경변수를 참조. `.env`에 정의된 변수라도 해당 컨테이너의 `environment` 섹션에 명시적으로 전달해야 함.

### 4. [트러블슈팅] Wikimedia SSE Rate Limit으로 인한 28분 데이터 유실

- **현상**: Producer가 Wikimedia EventStreams에 연결했으나 이벤트를 전혀 수신하지 못하는 상태가 반복됨. 약 60초 간격으로 아래 에러와 함께 재연결:
  ```
  peer closed connection without sending complete message body (incomplete chunked read)
  ```
  1주일 넘게 운영하면서 한 번도 발생하지 않은 현상이었음.

- **원인 분석**: 처음에는 **클라이언트 IP의 동시 연결 과다로 인한 rate limit**으로 추정했으나 실제 원인은 **Wikimedia 백엔드 서버에서의 모든 유저 Write 권한 박탈**로 밝혀졌다.

  진단 세션 중 동일 호스트 IP에서 열린 연결:
  1. 운영 중인 producer 컨테이너 (상시 연결)
  2. 진단 목적 curl 명령어 (호스트에서 직접 SSE 접속 시도)
  3. Python 스크립트 테스트 (추가 연결)
  4. 이전 코드의 고정 10초 재시도 루프 (분당 6회 재연결 시도)

  실제로 curl 테스트 중 HTTP 응답에서 **"Too Many Concurrent Connections From Your Client IP"** 메시지가 확인됨. Wikimedia가 IP당 동시 연결 수를 제한하고 있었음.

- **rate limit 동작 메커니즘**:
  ```
  동시 연결 수 초과
    → Wikimedia: HTTP 200으로 연결은 수락 (차단이 아닌 soft-ban)
    → 이벤트 전송 없이 연결만 유지
    → 60초 후 서버 측에서 연결 강제 종료
    → Producer 재연결 시도 → 또 rate limit → 루프 반복
  ```

- **`Last-Event-ID`와의 관계**: 이번에 추가한 `Last-Event-ID` 기능은 rate limit 문제를 해결하지 않음. 일반적인 짧은 재연결(네트워크 순단 등) 시 서버가 백필을 제공하여 이벤트 손실을 최소화하는 기능. rate limit 상태에서는 서버가 데이터를 보내지 않으므로 무효.

- **[후속] 두 번째 발생 — 원인은 rate limit이 아닌 Wikimedia idle timeout (정상 동작)**:

  같은 날 UTC 16:46 이후 동일한 60초 끊김 패턴이 재발. 이번에는 추가 연결이 전혀 없었음. 핸드폰 LTE(완전히 다른 IP)로 Wikimedia EventStreams에 직접 접속해보니 `:ok` heartbeat만 수신되고 이벤트 데이터가 전혀 오지 않음.

  **결론**: Wikimedia 서버는 보낼 이벤트가 없을 때 `:ok` SSE comment만 전송하며, 약 60초 idle 후 연결을 강제 종료. 이는 모든 클라이언트에 동일하게 적용되는 서버 측 정상 동작.
            이후 phabricator.wikimedia.org 에서 확인 결과, 해당 시간대에 세션 하이재킹 공격이 있었고 이로 인해 피해를 입어 보안상의 목적으로 쓰기 권한을 박탈했던 것이었다.

  **전체 타임라인 (UTC 기준, KST = UTC+9)**:

  ```
  15:30:00  연결 끊김

  16:37:24  ✅ Producer 시작, Wikimedia SSE 연결 (00:30 KST)
  16:37:58
  ~ 16:45:31  정상 운영 (2~3 events/batch, sse_received_total=85)
  16:40:48  첫 끊김 → 16:40:52 재연결, 즉시 이벤트 수신 재개 (정상)
  16:44:16  두번째 끊김 → 16:44:20 재연결, 즉시 이벤트 수신 재개 (정상)

  ── idle timeout 구간 시작 (01:46 KST) ──────────────────────────
  16:46:31  ❌ → 16:46:34 재연결, 이벤트 0개
  16:47:34  ❌ → 16:47:37 재연결, 이벤트 0개
  16:48:37  ❌ → 16:48:40 재연결, 이벤트 0개
  16:49:24  ❌ → 16:49:27 재연결, 이벤트 0개
  16:50:27  ❌ → 16:50:30 재연결, 이벤트 0개
  16:51:30  ❌ → 16:51:33 재연결, 이벤트 0개
  16:52:36  재연결 → 이벤트 3개 수신 (total=86,87,88) — 일시적 트래픽
  16:54:36
  ~ 17:05:42  ❌ 60초 idle timeout 루프 11회 반복, 이벤트 0개

  ── 복구 (02:06 KST) ────────────────────────────────────────────
  17:05:45  재연결
  17:06:00  sse_received_total=89 (이벤트 수신 재개 신호)
  17:06:10  Last-Event-ID 백필 시작: batch_size=48  (total=137)
  17:06:21  batch_size=107 (total=244)
  17:06:31  batch_size=133 (total=377)
  17:06:42  batch_size=96  (total=473)
  ...이후 100~170 events/batch 속도로 79분치 누락 이벤트 순차 수신
  ```

  - idle timeout 구간 총 소요: **약 79분** (UTC 15:30 ~ 17:06)
  - 재연결 횟수: 19회 (모두 HTTP 200 성공 후 이벤트 없이 60초 대기)
  - 복구 방식: Wikimedia 트래픽 자연 재개 + `Last-Event-ID` 백필로 누락 이벤트 일괄 수신

### 5. SLO 대시보드 그래프 가독성 개선

- **이슈**: SLO Dashboard의 3개 추이 패널(SLI-P1 배치 처리 소요 시간, SLI-P2 배치 크기, SLI-CAP 리소스 사용률)에서 y축 값이 과도하게 파편화되어 그래프 판독 불가.

- **원인 1 — `[$__interval]` 가변 윈도우**: Loki `unwrap` + `max_over_time([$__interval])` 조합에서 패널 크기 대비 시간 범위가 넓을 경우 윈도우가 너무 작아져 단발성 최댓값만 스파이크 형태로 출력됨.
  - 해결: 모든 추이 패널의 윈도우를 `[5m]` 고정으로 변경.

- **원인 2 — Loki 다중 스트림 레전드 분산**: `avg_over_time({container="producer"} | unwrap value [5m])` 쿼리가 컨테이너 재시작으로 생성된 Loki 스트림 수만큼 시리즈를 반환 → 동일 레이블의 레전드 항목이 수십 개 생성되며 각각 다른 Max/Mean 표시.
  - 해결: 외부에 `avg()` 집계 래퍼 추가 → `avg(avg_over_time(...[5m]))` — 모든 스트림을 단일 시리즈로 병합.

- **원인 3 — `max` 시리즈 노이즈**: 평균 + 최대 두 시리즈를 동시에 그릴 때 `max`가 순간 스파이크를 증폭시켜 평균선이 바닥에 붙어 판독 불가.
  - 해결: max 시리즈 제거. 평균 단일 시리즈만 유지.

- **원인 4 — Resources Monitor vs SLO CPU 불일치**: SLI-CAP 패널의 Producer CPU가 Resources Monitor 대시보드 대비 현저히 낮게 표시.
  - 원인: `avg(avg_over_time(...))` 방식에서 컨테이너 재시작으로 동시에 복수 스트림이 존재하는 경우, `avg()`가 스트림 수로 나누어 값 희석 가능.
  - Loki API 직접 쿼리로 검증: 두 쿼리의 실제 반환값이 동일(producer 최근 CPU ~1.21%)함을 확인.
  - 해결: `avg()` 래퍼 제거 후 `avg_over_time(...) by (target_container)` 방식으로 교체 (Resources Monitor 쿼리 패턴과 일치). CPU는 [1m] 윈도우 유지 (메모리는 [5m]).
  - **결론**: producer CPU는 SSE 수집·Kafka 발행이 I/O 대기 중심이므로 실제로 1–2% 수준이 정상. Resources Monitor에서 높아 보였던 수치는 ClickHouse CPU(6–18%)였음.

### 6. [버그수정] SLI-A2 ClickHouse 쿼리 성공률 항상 ~50% 반환

- **현상**: SLO 대시보드의 SLI-A2 패널(ClickHouse 쿼리 성공률 24h)이 시간이 지나도 값이 변하지 않음.

- **원인**: `system.query_log`는 쿼리당 두 개의 행을 기록:
  - `QueryStart` — 쿼리 시작 시점
  - `QueryFinish` / `ExceptionWhileProcessing` / `ExceptionBeforeStart` — 쿼리 완료 시점

  기존 쿼리:
  ```sql
  SELECT countIf(type = 'QueryFinish') * 100.0 / count() AS value
  FROM system.query_log
  WHERE ... AND query NOT LIKE '%system.query_log%'
  ```
  분모에 `QueryStart`(1263건)와 `QueryFinish`(1263건)가 모두 포함 → 성공률 = 1263 / 2527 ≈ **50%** (고정값).

- **해결**: `AND type NOT IN ('QueryStart')` 추가로 분모에서 `QueryStart` 제외.
  ```sql
  SELECT countIf(type = 'QueryFinish') * 100.0 / count() AS value
  FROM system.query_log
  WHERE ... AND query NOT LIKE '%system.query_log%' AND type NOT IN ('QueryStart')
  ```
  수정 후 실제 값: **99.92%** (1289건 성공 / 1290건 완료) — 의미 있는 수치.
### 7. SLI 측정 검증 및 대시보드 쿼리 버그 수정

- **배경**: SLO 관측 기간 진입 전 전체 SLI 자동 측정 항목의 실제 동작 여부를 일괄 검증.

- **SLI-R1 DLQ 유입 비율 — 필터 불일치 버그**
  - **원인**: 대시보드 쿼리 필터가 `"DLQ로 라우팅"`이었으나, 실제 발생하는 로그는 `"DLQ로 이벤트 라우팅:"` (sender.py:69) 및 `"DLQ로 격리:"` (main.py:43). 두 문자열 모두 `"DLQ로 라우팅"`을 포함하지 않아 항상 No data.
  - **해결**: 필터를 `"DLQ로 이벤트 라우팅"`으로 변경. 게이지 쿼리도 `rate + unwrap` 방식에서 `count_over_time / sum_over_time` 방식으로 교체 (스키마 검증 실패는 이벤트당 1줄 로그로, 숫자 추출이 불가능한 구조).
  - **추가**: DLQ 이벤트 없는 구간에서 게이지가 "No data" 대신 `0%`를 표시하도록 `noValue: "0"` 설정.

- **SLI-P5 처리량 — 대시보드 쿼리 누락**
  - **원인**: 대시보드 SLI-P5 패널의 `expr` 필드가 빈 문자열.
  - **해결**: `sum(rate({container="producer"} |= "으로 전송했습니다" | regexp "(?P<count>[0-9]+)개의 이벤트" | unwrap count [5m])) * 60` 추가. 현재값: **1,063 events/min** (목표 ≥ 300 달성).

- **SLI-CAP3 전체 메모리 합산 — 쿼리 중복 합산 버그**
  - **원인**: `sum(last_over_time(...| unwrap mem_mb [1m]))` 쿼리가 logfmt 파싱 필드(cpu_pct, mem_pct, block_io_mb 등)를 모두 레이블로 취급, 동일 컨테이너의 10초 간격 샘플 4개를 각각 다른 시리즈로 분류 → 14,841 MB (실제 ~3,900 MB의 약 4배).
  - **해결**: `sum(avg by (target_container) (last_over_time(...)))` 로 교체. `avg by (target_container)`가 컨테이너당 하나의 값으로 축약 후 합산.
  - 수정 후 값: **~3,014 MB** (docker stats 합산 ~3,909 MiB와 근사 일치).

- **검증 결과 요약** (자동 측정 11개):

  | SLI | 현재값 | 목표 | 상태 |
  |-----|--------|------|------|
  | SLI-A2 ClickHouse 가용성 | 99.83% | ≥ 99% | ✅ |
  | SLI-A3 Reporter 발송 | 1회/일 | 1회/일 | ✅ |
  | SLI-P1 배치 처리 시간 | 0.67s | ≤ 5s | ✅ |
  | SLI-P2 배치 크기 | 211개 | ≤ 500개 | ✅ |
  | SLI-P3 쿼리 응답 p99 | 0.043s | ≤ 1s | ✅ |
  | SLI-P5 처리량 | 1,063 events/min | ≥ 300 | ✅ |
  | SLI-P7 캐시 히트율 | 93% | ≥ 80% | ✅ |
  | SLI-R1 DLQ 비율 | 0% (정상 구간) | ≤ 1% | ✅ |
  | SLI-CAP1 CH 메모리 | 20.93% | ≤ 80% | ✅ |
  | SLI-CAP2 Producer CPU | 0.69% | ≤ 70% | ✅ |
  | SLI-CAP3 전체 메모리 | 3,014 MB | 관측 중 | ✅ |

### 8. SLI/NFR 정리 및 아키텍처 경량화 로드맵 수립

- **SLI-P6 (Kafka 컨슈머 레그) 제거**
  - 18 msg/sec 처리량에서 ClickHouse Kafka 엔진이 offset을 즉시 커밋하여 lag가 항상 0.
  - `kafka-lag-monitor` 서비스(30초 폴링, confluentinc/cp-kafka 이미지 재사용)를 구현하고 실측했으나 항상 0 확인 → 서비스 제거, 대시보드 패널 제거, NFR-P6/SLI-P6 문서 삭제.
  - SLI-D1(데이터 신선도)이 실질적으로 동일한 정보를 제공.

- **SLI-CAP3 교체** (디스크 사용률 → 전체 컨테이너 합산 메모리)
  - 기존 SLI-CAP3(호스트 디스크 사용률)은 node-exporter 없이 측정 불가로 제거.
  - 신규 SLI-CAP3: `resource-monitor`의 컨테이너별 `mem_mb` 합산 → 별도 인프라 추가 없이 즉시 측정 가능.
  - NFR-CAP3 목표: "전체 컨테이너 합산 메모리를 Grafana에서 실시간 관측 가능".

- **아키텍처 경량화 로드맵 수립** (TODO.md 구체화)
  - 배경: 컨테이너 합산 ~3,909 MiB + OS ~400 MiB = ~4,309 MiB → t4g.medium(4 GiB) 초과.
  - 4단계 로드맵 수립:
    1. DLQ Consumer 제거 (~27 MiB, 리스크 없음)
    2. Kafka → Redpanda 전환 (~1,184 MiB 절감 → t4g.medium 76%)
    3. ClickHouse → DuckDB 전환 (~1,882 MiB 절감 → t4g.small 60%)
    4. Loki + Alloy 제거 (~288 MiB 절감, SLO 대시보드 전면 재작성 필요)
  - 각 단계 완료 후 SLI 재측정 → Trade-Off 수치화 원칙 명시.
  - 전제 조건: SLO 관측 기간(4단계) 완료 후 baseline 확보.

## 2026-03-07

### 1. 아키텍처 경량화 스테이징 환경 구축 (Kafka → Redpanda 섀도우 테스트)

- **배경**
  - 아키텍처 경량화 작업(Kafka → Redpanda)을 진행하는 동안 SLO 4단계 관측 기간이 진행 중.
  - 운영 파이프라인(SLI 수집)을 중단하지 않고 개발·검증을 병행하는 방법이 필요.

- **결정: 섀도우 테스트(Shadow Testing) 방식**
  - 동일한 Wikimedia SSE 스트림을 운영·스테이징 두 스택이 각각 독립 구독.
  - 동일 시간대 데이터에 대해 SLI를 나란히 수집 → 순차 before/after 비교가 아닌 **동시 A/B 비교** 가능.
  - 로컬 맥미니 16GB 환경이므로 병렬 스택 실행에 메모리 제약 없음.

- **구현**
  - 브랜치: `feat/arch-lightening`
  - `docker-compose.staging.yml` 신규 작성 (기존 compose와 독립 standalone 파일)
    - `kafka-kraft` → `redpanda` (Redpanda Kafka API 호환 이미지)
    - 포트 오프셋: Kafka 19092 / ClickHouse HTTP 18123 / ClickHouse TCP 19000
    - `-p wikistreams-staging` 프로젝트 격리 → 볼륨·네트워크 자동 분리
  - `clickhouse/init-db-staging.sql` 신규 작성
    - `kafka_broker_list = 'redpanda:9092'` (init-db.sql의 `kafka-kraft:29092` 대체)
    - 나머지 스키마는 운영과 동일 유지

- **기동 결과**
  - `docker compose -f docker-compose.staging.yml -p wikistreams-staging up -d` 로 4개 컨테이너 정상 기동
    - `redpanda`, `clickhouse-staging`, `producer-staging`, `dlq-consumer-staging`
  - 기동 15초 후 스테이징 ClickHouse에 424개 이벤트 적재 확인
  - `producer-staging` 배치 처리 시간: 0.697s ~ 0.748s (batch_size 238~260)

- **SLI 비교 방법**
  - ClickHouse 기반 SLI (P5 처리량, D1 신선도, D2 보강률): 운영 `:8123` vs 스테이징 `:18123` 직접 쿼리
  - 로그 기반 SLI (P1 배치 처리, P2 배치 크기): 운영 alloy가 `producer-staging` 컨테이너 로그도 자동 수집 → 운영 Grafana에서 `{container_name="producer-staging"}` 필터로 분리

### 2. SLO 1차 검증 리뷰 — Kafka baseline 실측 및 아키텍처 경량화 트레이드오프 SLO 작성

- **배경**
  - SLO 4단계 관측 기간 시작(2026-03-06 KST)으로부터 약 39시간 경과.
  - 운영 아키텍처(Kafka)의 SLI 실측값을 확보하여 1차 검증 리뷰 진행.
  - 최종 목표: AWS t3.small (2 GiB RAM) 마이그레이션 — Kafka → Redpanda → DuckDB 등 단계적 경량화.

- **Kafka baseline SLI 실측값 (2026-03-06 KST 이후, 39시간)**

  | SLI | 실측값 | 기존 목표 | 판정 |
  |-----|--------|----------|------|
  | A2 쿼리 성공률 | 99.71% | ≥ 99% | ✅ |
  | P1 배치 처리 p95 | 1.208s | ≤ 5s | ✅ (목표 너무 느슨) |
  | P3 쿼리 응답 p99 | 36ms | ≤ 1,000ms | ✅ (목표 너무 느슨) |
  | P5 처리량 p5 | 1,042 events/min | ≥ 300 | ✅ (목표 너무 느슨) |
  | P7 캐시 히트율 | 93.14% | ≥ 80% | ✅ |
  | D1 신선도 lag | 6s | ≤ 30s | ✅ |
  | D2 레이블 보강률 | 80.86% | ≥ 90% | ❌ (목표 재조정) |
  | CAP1 CH 메모리 p95 | 26.22% | ≤ 80% | ✅ |
  | CAP2 Producer CPU p95 | 6.00% | ≤ 70% | ✅ |

- **SLO 목표 재조정** (실측 기반, 1차 검증 리뷰)
  - P1: ≤5s → **≤2s** (실측 p95=1.208s, +65% 여유 허용)
  - P3: ≤1,000ms → **≤200ms** (실측 p99=36ms, ClickHouse→DuckDB 전환 시 비교 기준으로도 활용)
  - P5: ≥300 → **≥800 events/min** (실측 p5=1,042, -23% 허용 회귀)
  - D2: ≥90% → **≥80%** (Wikidata Q-ID의 구조적 21% 레이블 부재 — 코드 문제 아님)

- **D2 원인 분석 (2026-03-07)**
  - `title LIKE 'Q%'` 필터는 정확 — wikidata.org Q-ID만 포함.
  - 빈 label 87,919건 중: Q1.3억+ 신규 Q-ID 33,354건(37.9%), 기존 Q-ID인데 en/ko label 없음 54,565건(62.1%).
  - Wikidata 자체에 레이블 없는 엔티티 편집이 구조적으로 ~20%를 차지 → SLO 90% 목표가 비현실적.

- **P7 계산 방식 확정 (2026-03-07)**
  - 초기 분석에서 "순수 Q-ID 단위 캐시 히트율"(32.7%)을 잘못 사용.
  - Grafana 쿼리와 동일한 방식으로 확정: `(total_enriched - new_api_calls) / total_enriched × 100`
  - 실측 93.14% — SLO 목표(≥80%) 달성 중.

- **브로커 리소스 비교 (docker stats 순간값)**
  - Kafka: **1,174 MiB**, CPU ~1%
  - Redpanda (스테이징): **372 MiB**, CPU ~0.4%
  - 절감: **-802 MiB (-68%)**
  - 전체 스택 예상: Kafka ~4,043 MiB → Redpanda 전환 후 ~3,214 MiB

- **아키텍처 경량화 트레이드오프 SLO 신규 작성** (SLO.md §8)
  - t3.small (2 GiB) 달성을 위한 4단계 로드맵 및 단계별 누적 메모리 투영 기록.
  - 2단계(Kafka→Redpanda) Go/No-Go 조건 명시: P1 p95 ≤ 2.0s, P5 p5 ≥ 800/min, D1 ≤ 15s, 브로커 메모리 ≤ 500 MiB.
  - 스테이징 현재 실측: P1 0.69~0.75s ✅, D1 13s ✅, 브로커 메모리 372 MiB ✅.

### 3. DLQ Consumer 제거 (1단계 경량화) + Producer 이벤트 필터 개선

- **DLQ 토픽 원인 분석**
  - DLQ Consumer 로그에서 `retry_count=0` 재시도가 ~40~60분 간격으로 발생 중.
  - DLQ 토픽 직접 조회 결과: 모든 이벤트가 구조적으로 복구 불가능한 두 유형.
    1. `type=log`: Wikimedia 관리 이벤트 (삭제, visibility 변경 등) — `user` 필드 없음 → Pydantic 검증 실패.
    2. `domain=canary`: Wikimedia 스트림 헬스체크 이벤트 — 실제 편집 아님.
  - DLQ Consumer가 재시도해도 동일 실패 반복 → **제로 가치**.

- **결정 1: DLQ Consumer 제거** (staging 1단계 경량화)
  - `docker-compose.staging.yml`에서 `dlq-consumer` 서비스 제거.
  - 절감: ~27 MiB.
  - 리스크 대응: DLQ 토픽은 유지 (audit trail). `rpk topic consume` 명령으로 backlog 모니터링.

- **결정 2: Producer 이벤트 필터 추가** (`src/producer/main.py`)
  - `log`-타입 및 `canary`-도메인 이벤트를 Pydantic 검증 **이전에** 조용히 드롭.
  - 기존: 검증 실패 → DLQ 전송 (불필요한 DLQ 오염).
  - 변경: `_should_skip()` 함수로 사전 필터링 → `continue` (DLQ 전송 없음).
  - 기대 효과: DLQ 토픽 backlog가 near-zero로 감소.

- **테스트 추가** (`tests/unit/producer/test_main.py`)
  - `test_should_skip_log_type_event` — log 타입 이벤트 skip 확인.
  - `test_should_skip_canary_domain_event` — canary 도메인 이벤트 skip 확인.
  - `test_should_not_skip_normal_edit_event` — 정상 edit 이벤트 통과 확인.
  - `test_process_batch_log_events_silently_dropped` — DLQ 미전송 확인.
  - `test_process_batch_canary_events_silently_dropped` — DLQ 미전송 확인.
  - 전체 10/10 통과.

### 4. 3단계 DB 교체 대상: ClickHouse → QuestDB 선택

- **배경**: 아키텍처 경량화 3단계(ClickHouse 교체) 진입 전 DB 옵션 검토.
- **검토 후보**: DuckDB, QuestDB, TimescaleDB, chDB(ClickHouse 임베디드).

- **핵심 비교 기준**:
  - 메모리 절감 목표 달성 여부 (< 500 MiB)
  - Kafka 연동 방식 (내장 vs 별도 Consumer 개발)
  - Grafana 연동 (기존 플러그인 재사용 vs 신규 개발)
  - 홈랩 유지보수 부담

- **DuckDB 탈락 이유**:
  - Kafka 연동 없음 → 별도 Consumer 서비스 직접 개발 필요
  - HTTP API 없음 → FastAPI 래퍼 직접 개발 필요
  - 신규 코드 2개 추가 = 유지보수 포인트 증가

- **QuestDB 선택 이유**:
  - Kafka 내장 연동 (설정 파일만 작성, 별도 Consumer 불필요)
  - Grafana PostgreSQL 와이어 프로토콜 지원 (플러그인 추가 불필요)
  - HTTP API 내장 → FastAPI 래퍼 불필요
  - 예상 메모리: ~300~400 MiB (ClickHouse 2,048 MiB 대비 ~-1,750 MiB)
  - 2단계(Redpanda) + 3단계(QuestDB) 완료 시 ~1,464 MiB → t3.small(2 GiB) 72% ✅

- **문서 업데이트**: TODO.md 3단계, SLO.md §8.2·§8.4 전면 교체.
  - 3단계(ClickHouse→DuckDB) 예고 SLO 기준도 사전 정의.

### 5. 3단계 스테이징 환경 구축 (Redpanda + QuestDB 병렬 스택)

- **방식: Option B — 병렬 스테이징 스택**
  - 2단계 스테이징(Redpanda + ClickHouse)을 종료하지 않고 3단계 스테이징(Redpanda + QuestDB)을 동시 구동.
  - 2단계 SLI 관측 기간 지속 + 3단계 QuestDB 검증 병렬 진행.
  - Redpanda 공유: `wikistreams-staging_default` 외부 네트워크로 2단계 Redpanda(redpanda:9092) 접근.

- **구현** (`docker-compose.staging3.yml` 신규 작성)
  - `questdb/questdb:8.2.1` 컨테이너 + `questdb-consumer` (Kafka→ILP 변환 Consumer).
  - 포트 오프셋 (2단계와 충돌 없음): REST/Web Console 29000, PostgreSQL wire 28812.
  - `src/questdb_consumer/` 신규 패키지:
    - `main.py`: `kafka-python`으로 Redpanda 구독 → `event_to_ilp()` 변환 → TCP socket으로 QuestDB ILP(9009) 직접 송신.
    - ILP 필드: `server_name`, `wiki_type` (tag), `title`, `user`, `bot`, `namespace`, `minor`, `comment`, `wikidata_label`, `wikidata_description` (field), timestamp(ns).
    - `_should_skip()` 필터: log 타입·canary 도메인 사전 드롭.

- **트러블슈팅**
  - **Kafka advertised listener 문제**: Redpanda가 `localhost:19092`를 advertise하여 다른 네트워크의 컨테이너가 메타데이터 교환 후 `ECONNREFUSED`. `wikistreams-staging_default` 네트워크 참여 + `KAFKA_BROKER: "redpanda:9092"` (내부 주소)로 해결.

- **QuestDB SLI 검증 결과** (staging3 기동 직후 실측):

  | SLI | 실측값 | 목표 | 판정 |
  |-----|--------|------|------|
  | P3 쿼리 응답 p99 | 8~27ms | ≤ 500ms | ✅ |
  | D1 데이터 신선도 lag | 4~8s | ≤ 15s | ✅ |
  | P5 처리량 | 1,573/min | ≥ 800/min | ✅ |
  | D2 레이블 보강률 | 80.67% | ≥ 80% | ⚠️ 경계 |
  | QuestDB 메모리 | 365 MiB | ≤ 400 MiB | ✅ |

### 6. Grafana QuestDB 대시보드 마이그레이션

- **배경**: QuestDB는 Grafana ClickHouse 플러그인 불가 → PostgreSQL wire 프로토콜(포트 28812)로 Grafana 연동.

- **데이터소스 추가**: Grafana UI에서 PostgreSQL 데이터소스 `questdb-staging` 추가 (host: `localhost:28812`, db: `qdb`, user: `admin`).

- **대시보드 작성** (`monitoring/dashboards/wikistreams-analytics-questdb.json`)
  - `wikistreams-analytics.json` 기반으로 24개 패널을 QuestDB SQL로 전환.
  - 핵심 SQL 변환 규칙:

    | ClickHouse | QuestDB |
    |-----------|---------|
    | `count()` | `count(1)` |
    | `countIf(cond)` | `sum(CASE WHEN cond THEN 1 ELSE 0 END)` |
    | `uniq(col)` | `count(DISTINCT col)` |
    | `if(cond, a, b)` | `CASE WHEN cond THEN a ELSE b END` |
    | `toStartOfInterval() GROUP BY` | `SAMPLE BY $__interval` |
    | `toHour(col)` | `extract(hour from col)` |
    | `HAVING agg >= N` | 서브쿼리 `WHERE agg >= N` |
    | `arrayStringConcat(groupUniqArray(...))` | 제거 (QuestDB 미지원) |
    | `startsWith(col, 'str')` | `col LIKE 'str%'` |
    | `a * b / count()` | `cast(a as double) / count(1) * b` |
    | `col != ''` | `col <> ''` |

  - **주요 트러블슈팅**:
    - `count(*) * N` 파서 오류: `*`를 wildcard로 인식 → `count(1) * N`으로 해결.
    - `HAVING` 절 미지원: 서브쿼리 패턴으로 우회.
    - `$__interval_s` 미지원 (Grafana PostgreSQL 플러그인): `$__interval_ms`로 대체.
    - 파일 기반 프로비저닝: Grafana API로 저장 불가("Cannot save provisioned dashboard") → 파일 직접 수정 후 자동 리로드.

- **검증**: 24개 패널 전부 정상 렌더링 확인.

### 7. Reporter fetcher SQL QuestDB 호환성 검증

- **목적**: Reporter(`src/reporter/fetcher.py`)의 ClickHouse SQL 8개 쿼리를 수정 없이 QuestDB REST API(`http://localhost:29000/exec`)에 직접 실행하여 호환성 확인 (코드 수정 없음).
- **테이블**: `wikimedia.events` → `wikimedia_events`, `event_time` → `timestamp`, `now() - INTERVAL 24 HOUR` → `dateadd('d',-1,now())`.

- **호환성 결과**:

  | 쿼리 | ClickHouse 원본 | QuestDB 번역 | 상태 |
  |------|-----------------|-------------|------|
  | Q1 총 편집 수 | `count()` | `count(1)` | ✅ |
  | Q2 활성 편집자 | `uniq(user)` | `count(DISTINCT user)` | ✅ |
  | Q3 봇 비율 | `countIf(bot=1) / count()` | `sum(CASE WHEN bot=true ...) / count(1) * N` | ✅ (bot: BOOLEAN 타입) |
  | Q4 신규 문서 수 | `count() WHERE wiki_type='new'` | 동일 패턴 | ✅ |
  | Q5 Top 편집 페이지 | `if(wikidata_label != '', ...)` | `CASE WHEN ... <> ''` | ✅ (`!=` → `<>`) |
  | Q6 스파이크 페이지 | `countIf() HAVING` | `sum(CASE) WHERE` (서브쿼리) | ✅ |
  | Q7 다국어 편집 | `uniq() HAVING, arrayStringConcat()` | `count(DISTINCT) WHERE` (wikis 컬럼 제거) | ✅ (wikis 미지원) |
  | Q8 되돌리기 페이지 | `ILIKE, startsWith()` | `ilike, LIKE 'Reverted%'` | ✅ |
  | Q9 피크 시간대 | `toHour(event_time)` | `extract(hour from timestamp)` | ✅ |
  | Q10 어제 순위 | `ORDER BY count() DESC` | `ORDER BY count(1) DESC` | ✅ |

- **주요 발견사항**:
  - `bot` 필드: QuestDB가 ILP `t`/`f`를 BOOLEAN으로 저장 → `bot = 1` 아닌 `bot = true` 사용 필요.
  - `count(*) * N` 파서 오류: `count(1) * N`으로 해결.
  - `HAVING` 절: 서브쿼리 `WHERE` 패턴으로 우회.
  - `arrayStringConcat(groupUniqArray(...))`: 미지원 → `wikis` 컬럼 반환 포기, `wiki_count`만 반환.
  - `!=` 연산자: 파싱 오류 발생 → `<>` 사용.

- **결론**: Reporter의 8개 핵심 쿼리 모두 QuestDB에서 동작 가능. 운영 전환 시 `_query()` 함수의 엔드포인트 + SQL 번역 패치 필요.
