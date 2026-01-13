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

-   `.github/workflows/ci.yml`: GitHub Actions 워크플로우 파일입니다. `main` 브랜치에 코드가 푸시될 때마다 `black` 포매터와 `flake8` 린터를 실행하여 코드 품질을 검사합니다.

-   `detect_surge.py`: **독립 실행형 분석 스크립트**입니다. 실시간 파이프라인의 일부가 아니며, Druid에 직접 SQL 쿼리를 보내 특정 기간 동안 편집 횟수가 급증한 문서를 찾아내는 데 사용됩니다. `pandas`를 사용하여 결과를 터미널에 출력합니다.

-   `docker-compose.yml`: 프로젝트의 모든 인프라(Kafka, Druid 클러스터, Producer)를 정의하고 실행하는 파일입니다. `docker compose up -d` 명령어로 모든 서비스를 시작할 수 있습니다.

-   `producer/`: 데이터 수집 및 보강을 담당하는 Python 애플리케이션입니다.
    -   `main.py`: Wikimedia SSE 스트림에 연결하고, 이벤트를 마이크로 배치로 처리하며, 데이터를 보강한 후 Kafka로 전송하는 핵심 로직이 포함되어 있습니다.
    -   `cache.py`: Wikidata API로부터 가져온 Q-ID 정보를 저장하고 조회하는 SQLite 캐시 관련 함수들이 정의되어 있습니다.
    -   `Dockerfile`: 이 producer 애플리케이션을 위한 Docker 이미지를 빌드하는 방법을 정의합니다.
    -   `requirements.txt`: producer 실행에 필요한 Python 라이브러리 목록입니다.

## 4. 주요 명령어

-   **모든 서비스 시작**:
    ```bash
    docker compose up -d
    ```

-   **Kafka 토픽 데이터 확인**:
    ```bash
    docker exec -it kafka-kraft kafka-console-consumer \
    --bootstrap-server kafka-kraft:29092 \
    --topic wikimedia.recentchange
    ```

-   **로컬 코드 품질 검사**:
    ```bash
    # Black으로 자동 포맷팅
    black .
    # Flake8으로 린트 검사
    flake8 .
    ```

-   **급상승 트렌드 분석 (예시)**:
    ```bash
    python detect_surge.py --recent-hours 1 --previous-hours 2 --min-edits 5
    ```

## 5. Gemini 에이전트를 위한 가이드

-   **코드 수정 시**: 프로젝트는 `black`과 `flake8`을 사용하므로, 코드 변경 후에는 반드시 이 두 도구를 사용하여 코드 스타일을 일관성 있게 유지해야 합니다.
-   **의존성 추가 시**: `producer`에 새로운 라이브러리를 추가할 경우, `producer/requirements.txt` 파일에 명시해야 합니다.
-   **인프라 변경 시**: Kafka, Druid 등 서비스의 설정을 변경해야 할 경우, `docker-compose.yml` 파일을 수정해야 합니다.
