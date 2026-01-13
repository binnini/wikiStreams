# Gemini를 위한 WikiStreams 프로젝트 분석 (`GEMINI.md`)

이 문서는 Gemini AI 에이전트가 `wikiStreams` 프로젝트의 구조와 목적을 신속하게 파악할 수 있도록 돕기 위해 작성되었습니다.

## 1. 프로젝트 목적

**WikiStreams**는 위키미디어(위키피디아, 위키데이터 등)에서 발생하는 변경사항을 실시간으로 수집하고 분석하여 최신 트렌드를 파악하는 데이터 파이프라인 프로젝트입니다. 최종 목표는 Apache Superset을 사용하여 분석 결과를 시각화하는 대시보드를 구축하는 것입니다.

## 2. 핵심 아키텍처 (카파 아키텍처)

이 프로젝트는 실시간 스트림 처리에 중점을 둔 경량화된 카파 아키텍처를 따릅니다. 모든 서비스는 Docker Compose를 통해 관리됩니다.

**데이터 흐름:**

1.  **Source**: 위키미디어의 실시간 이벤트 스트림 (SSE)
2.  **Ingestion & Enrichment**: Python으로 작성된 `producer`가 이벤트를 수집합니다.
    -   이벤트의 `title`이 위키데이터 Q-ID인 경우, Wikidata API를 호출하여 국문/영문 이름(Label)과 설명(Description)을 가져와 데이터에 추가합니다.
    -   API 호출을 최소화하기 위해 SQLite 기반의 로컬 캐시(`producer/cache.py`)를 사용합니다.
3.  **Message Bus**: 보강된 데이터는 `Apache Kafka`로 전송됩니다.
4.  **Real-time Analytics**: `Apache Druid`가 Kafka로부터 데이터를 실시간으로 수집하여 분석 및 집계를 수행합니다.
5.  **Visualization (목표)**: `Apache Superset`을 통해 Druid의 데이터를 시각화합니다.

## 3. 주요 파일 및 디렉토리 설명

-   `.github/workflows/ci.yml`: GitHub Actions 워크플로우 파일입니다. `Unit -> Integration -> E2E` 단계별 테스트와 `black`, `flake8` 검사를 수행합니다.

-   `detect_surge.py`: **독립 실행형 분석 스크립트**입니다. Druid에 SQL 쿼리를 보내 편집 급상승 문서를 찾아냅니다.

-   `druid/ingestion-spec.json`: Kafka 데이터를 Druid로 수집하기 위한 Ingestion Supervisor 설정 파일입니다.

-   `superset/`: Apache Superset 설정 및 초기화 관련 파일들입니다.
    -   `Dockerfile`: 드라이버 설치 등을 위한 커스텀 이미지 빌드 파일.
    -   `superset_config.py`: 보안, DB 연동, 언어 설정 등.
    -   `init_superset.sh`: 초기화(계정 생성, DB 마이그레이션) 스크립트.
    -   `datasources/druid.yaml`: Druid 연결 정보 (IaC).

-   `src/producer/`: 데이터 수집 및 보강을 담당하는 Python 애플리케이션입니다.
    -   `config.py`: **중앙 집중식 설정 관리 모듈**입니다. `pydantic-settings`를 사용하여 환경변수 및 `.env` 파일을 통해 시스템 설정을 관리합니다.
    -   `main.py`: 파이프라인 실행 엔트리 포인트입니다.
    -   `cache.py`: Wikidata API 캐시(SQLite) 관련 함수들입니다.
    -   `requirements.txt`: `pydantic-settings` 등 필요한 라이브러리 목록입니다.

## 4. 설정 및 환경 관리

프로젝트의 모든 설정은 `src/producer/config.py`의 `Settings` 클래스에서 관리됩니다.
-   **환경변수 우선순위**: 1) 시스템 환경변수, 2) `.env` 파일, 3) 코드 내 기본값.
-   주요 설정 항목: Kafka 브로커/토픽 주소, SQLite DB 경로, 배치 사이즈 등.

## 5. 테스트 전략 (`pytest`)

이 프로젝트는 강력한 자동화 테스트 체계를 갖추고 있습니다.

-   **단위 테스트 (`tests/unit/`)**: 외부 의존성 없이 각 모듈의 로직을 독립적으로 검증합니다.
-   **통합 테스트 (`tests/integration/`)**: 
    -   **Enrichment Cache**: Wikidata API 모킹과 실제 SQLite 캐시 간의 상호작용을 검증합니다.
    -   **Kafka Integration**: 실제 Kafka 브로커와의 메시지 송수신을 검증합니다. (이미 실행 중인 인프라 활용 가능)
    -   **E2E Pipeline**: `Producer -> Kafka -> Druid` 전체 흐름을 검증합니다. 테스트마다 고유한 토픽과 데이터소스를 생성하여 **리소스 격리**를 보장하며, 테스트 종료 후 **Teardown(Supervisor 종료)**을 수행합니다.

## 6. 주요 명령어

-   **모든 서비스 시작**: `docker compose up -d`
-   **전체 테스트 실행**: `PYTHONPATH=src pytest tests/`
-   **로컬 코드 품질 검사**: `black .` 및 `flake8 .`

## 7. Gemini 에이전트를 위한 가이드

-   **설정 변경 시**: `src/producer/config.py`를 먼저 확인하고 필요한 경우 환경변수를 추가하십시오.
-   **인프라 변경 시**: `docker-compose.yml`과 `druid/ingestion-spec.json`을 함께 확인해야 합니다.
-   **테스트 추가 시**: E2E 테스트의 경우 `tests/integration/test_e2e_pipeline.py`의 `e2e_context` Fixture를 활용하여 리소스를 격리하십시오.

## 8. 개선 로드맵 (Tech Lead Feedback)

다음은 프로젝트의 안정성과 확장성을 높이기 위해 제안된 기술 개선 사항들입니다.

### 완료된 항목
- [x] **테스트 격리 및 정리 (Test Isolation & Teardown)**: E2E 테스트 시 리소스 격리 및 자동 종료 구현.
- [x] **설정 관리 (Configuration Management)**: `pydantic-settings` 도입 및 설정 중앙화.
- [x] **Superset 통합 (Infrastructure Integration)**: Docker Compose에 Superset/Redis 추가 및 초기화 스크립트 구현.

### 진행 예정 항목
- [ ] **예외 처리 및 복구 (Resilience & DLQ)**:
    -   데이터 처리 실패 시 로그만 남기는 대신 **Dead Letter Queue (DLQ)** 패턴을 도입하여 실패한 메시지를 별도 저장/재처리.
- [ ] **아키텍처 확장성 (AsyncIO 리팩토링)**:
    -   현재의 동기식(Blocking) I/O 구조를 `asyncio`, `aiohttp`, `aiokafka` 등을 활용한 **비동기 파이프라인**으로 전환하여 처리량 증대.
- [ ] **CI 파이프라인 최적화**:
    -   **Smoke Test** (PR 단계)와 **Full E2E Test** (Merge 단계)로 CI 단계를 이원화하여 빌드 시간 및 비용 최적화.

## 9. 향후 과제 (Superset Visualization)

다음 에이전트는 아래 항목들을 우선적으로 수행해야 합니다.

1.  **Druid 데이터베이스 연결 완전 자동화**:
    -   현재 `init_superset.sh`에서 `import-datasources`를 실행하지만, Druid Router 부팅 지연 등으로 인해 실패하는 경우가 있음.
    -   `wait-for-it` 스크립트 등을 도입하여 Druid가 준비될 때까지 기다린 후 등록하도록 개선 필요.
2.  **기본 데이터셋(Dataset) 및 지표(Metric) 생성**:
    -   `wikimedia.recentchange` 테이블을 Superset Dataset으로 등록.
    -   주요 지표(Edit Count, Added Length Sum 등)를 코드로 미리 정의(YAML).
3.  **기초 대시보드 템플릿 작성 (Dashboard as Code)**:
    -   실시간 트렌드를 보여주는 기본 대시보드(Chart + Dashboard)를 YAML 파일로 작성하여 컨테이너 기동 시 자동 임포트.
4.  **영속성(Persistence) 검증**:
    -   컨테이너 재시작 시 대시보드 및 설정이 유지되는지 확인.
