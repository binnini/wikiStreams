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

---
*Next Step: 필터 박스 추가 및 대시보드 최종 레이아웃 최적화*
