# WikiStreams: 실시간 위키미디어 트렌드 분석기

[![Python Code Quality CI](https://github.com/puding-development/wikiStreams/actions/workflows/ci.yml/badge.svg)](https://github.com/puding-development/wikiStreams/actions/workflows/ci.yml)

**WikiStreams**는 전 세계 위키미디어(위키피디아, 위키데이터 등)의 실시간 변경 로그 스트림을 분석하여 트렌드를 파악하는 데이터 파이프라인 프로젝트입니다. 홈 랩(Home Lab) 환경에서 운영되며, 비용을 들이지 않고 현업 수준의 실시간 데이터 처리 아키텍처를 구축하는 것을 목표로 합니다.

## 🏛️ 아키텍처 (Architecture)

복잡한 배치(Batch) 레이어를 제거하고 스트림 처리에 집중한 경량화된 **카파 아키텍처(Kappa Architecture)**를 따릅니다. 모든 인프라는 Docker Compose를 통해 코드로 관리됩니다(IaC).

```mermaid
graph TD
    subgraph " "
        direction LR
        A[<fa:fa-globe> Wikimedia SSE]
    end

    subgraph "Docker Host"
        direction TB

        subgraph "Ingestion & Enrichment"
            B[<fa:fa-brands fa-python> Python Producer] -- "SQLite" --> C[<fa:fa-database> On-demand Cache]
            B -- "API Call (Cache Miss)" --> D[<fa:fa-server> Wikidata API]
        end

        subgraph "Message Bus"
            E{<fa:fa-layer-group> Apache Kafka}
        end

        subgraph "Storage & Analytics"
            F[<fa:fa-bolt> ClickHouse]
        end

        subgraph "Visualization & Monitoring"
            G[<fa:fa-chart-simple> Grafana]
        end
    end

    %% Data Flow
    A -- "1. Real-time Events" --> B
    B -- "2. Enrich & Publish" --> E
    E -- "3. Kafka Engine (MV)" --> F
    F -- "4. SQL Queries" --> G
    B -.-> G

    %% Styling
    style A fill:#fff,stroke:#111,stroke-width:2px
```

*   **Source:** Wikimedia의 실시간 변경 이벤트 스트림 (SSE)
*   **Ingestion & Enrichment:** Python Producer가 이벤트를 실시간으로 수집 및 보강합니다.
    *   **On-demand Caching:** 위키데이터 Q-ID에 대한 정보를 **SQLite 로컬 캐시**에서 먼저 조회하여 API 호출을 최소화합니다.
*   **Message Bus:** Apache Kafka (KRaft 모드)가 데이터 허브 역할을 수행합니다.
*   **Storage & Analytics:** ClickHouse가 Kafka 토픽을 직접 구독(Kafka 테이블 엔진)하고 Materialized View로 실시간 적재합니다.
*   **Visualization & Monitoring:** Grafana가 ClickHouse 데이터를 시각화하고 Loki 로그로 시스템을 모니터링합니다.

## 📂 프로젝트 구조

```
wikiStreams/
├── .github/workflows/   # CI/CD 파이프라인 (단위/통합/E2E 테스트)
├── clickhouse/          # ClickHouse 스키마 및 초기화 SQL
├── docs/                # 개발 로그 및 문서
├── monitoring/          # Grafana, Loki, Promtail 설정 및 대시보드
├── src/
│   ├── producer/        # Python 데이터 수집기 소스
│   │   ├── config.py    # 중앙 집중식 설정 관리 (Pydantic)
│   │   └── ...
│   └── dlq_consumer/    # Dead Letter Queue 컨슈머
├── tests/               # 테스트 슈트 (Unit, Integration, E2E)
└── docker-compose.yml   # 전체 인프라 정의
```

## 🛠️ 기술 스택

*   **Data Pipeline:** Python 3.12+, Apache Kafka (KRaft)
*   **Storage & Analytics:** ClickHouse (Kafka 테이블 엔진 + MergeTree)
*   **Visualization & Monitoring:** Grafana, Loki, Promtail
*   **Local Cache:** SQLite
*   **Infrastructure:** Docker, Docker Compose
*   **Testing:** Pytest
*   **Code Quality:** Black, Flake8

## 🚀 시작하기 (Getting Started)

### 사전 요구사항

*   Docker 및 Docker Compose
*   Git

### 설치 및 실행

1.  **Git 저장소 복제:**
    ```bash
    git clone https://github.com/puding-development/wikiStreams.git
    cd wikiStreams
    ```

2.  **서비스 실행:**
    ```bash
    docker compose up -d
    ```
    *초기 실행 시 이미지 다운로드 및 ClickHouse 초기화에 수십 초가 소요됩니다.*

3.  **서비스 접속:**
    *   **Grafana:** [http://localhost:3000](http://localhost:3000) — Analytics + 모니터링 대시보드
    *   **ClickHouse HTTP:** [http://localhost:8123](http://localhost:8123) — 직접 SQL 쿼리

## ⚙️ 설정 관리 (Configuration)

`src/producer/config.py`의 `Settings` 클래스를 통해 주요 설정을 관리합니다. `pydantic-settings`를 사용하여 환경변수 우선순위를 적용합니다.

*   `KAFKA_BROKER`: Kafka 브로커 주소 (기본값: `localhost:9092`)
*   `BATCH_SIZE`: 한 번에 처리할 이벤트 수 (기본값: `500`)
*   `LOG_LEVEL`: 로그 레벨 (기본값: `INFO`)

## 🧪 테스트 전략

```bash
# 테스트 의존성 설치
pip install -r src/producer/requirements-dev.txt

# 전체 테스트 실행
PYTHONPATH=src pytest tests/

# 카테고리별 실행
PYTHONPATH=src pytest tests/unit/        # 단위 테스트 (외부 의존성 없음)
PYTHONPATH=src pytest tests/integration/ # 통합/E2E 테스트 (Kafka, ClickHouse 필요)
```

*   **Unit Tests:** 외부 의존성 없이 로직 검증.
*   **Integration Tests:** Kafka, SQLite 캐시 등 실제 구성 요소와의 연동 검증.
*   **E2E Pipeline Tests:** `Producer → Kafka → ClickHouse` 전체 흐름 검증.

## ✅ 코드 품질 관리

```bash
black .   # 코드 포매팅
flake8 .  # 정적 분석
```
