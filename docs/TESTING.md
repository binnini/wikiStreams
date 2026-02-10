# 테스트 구조 (`test.md`)

이 문서는 `wikiStreams` 프로젝트의 테스트 구조와 실행 방법에 대해 설명합니다.

## 1. 디렉토리 구조

이 프로젝트는 표준 `src` 레이아웃을 따르며, 소스 코드와 테스트 코드를 명확하게 분리합니다.

```
project_root/
├── src/                  # 애플리케이션 소스 코드
│   └── producer/
├── tests/                # 모든 테스트 코드
│   ├── conftest.py       # 전역 설정 및 공용 Fixture
│   ├── unit/             # 단위 테스트
│   │   └── producer/
│   │       ├── test_cache.py
│   │       ├── test_collector.py
│   │       ├── test_enricher.py
│   │       ├── test_main.py
│   │       └── test_sender.py
│   ├── integration/      # (미래의) 통합 테스트
│   └── e2e/              # (미래의) 종단 간 테스트
└── pytest.ini            # pytest 설정 파일
```

-   **`tests/unit/`**: 각 모듈(함수, 클래스)을 외부 의존성(네트워크, DB 등)으로부터 완전히 분리(고립)하여 테스트합니다. 매우 빠르고 실패 원인을 명확하게 알 수 있습니다.
-   **`tests/integration/`**: 두 개 이상의 모듈이나 서비스(e.g., Sender와 실제 Kafka)를 연동하여 상호작용을 검증하는 테스트를 위치시킵니다.
-   **`tests/e2e/`**: 전체 시스템의 흐름을 사용자 관점에서 처음부터 끝까지 검증하는 테스트를 위치시킵니다.
-   **`conftest.py`**: 모든 테스트 파일에서 공용으로 사용할 수 있는 Pytest Fixture나 헬퍼 함수를 정의하는 곳입니다.

## 2. 테스트 실행 방법

테스트 실행에는 `pytest` 프레임워크를 사용합니다.

### 전체 테스트 실행

프로젝트 루트 디렉토리에서 다음 명령어를 실행하면 `tests/` 디렉토리 하위의 모든 테스트를 실행할 수 있습니다.

```bash
PYTHONPATH=src pytest tests/
```

-   `PYTHONPATH=src`: `src` 디렉토리를 Python의 모듈 검색 경로에 추가하여, 테스트 코드에서 `from producer import ...`와 같은 import 구문을 올바르게 사용할 수 있도록 합니다.

### 특정 테스트만 실행

특정 파일이나 디렉토리의 테스트만 실행할 수도 있습니다.

```bash
# 단위 테스트만 실행
PYTHONPATH=src pytest tests/unit/

# collector 테스트만 실행
PYTHONPATH=src pytest tests/unit/producer/test_collector.py
```

## 3. 테스트 설정 (`pytest.ini`)

`pytest.ini` 파일은 `pytest`의 동작을 설정합니다. 현재는 테스트 실행 시 `INFO` 레벨 이상의 로그가 터미널에 실시간으로 출력되도록 설정되어 있습니다.
