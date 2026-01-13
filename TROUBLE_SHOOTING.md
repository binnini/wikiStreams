# 트러블슈팅 가이드 (Troubleshooting Guide)

이 문서는 프로젝트 개발 및 운영 과정에서 발생했던 주요 오류들과 해결 방법을 기록합니다.

## 1. Apache Superset 통합 관련

### 1.1. Python 모듈 누락 (`ModuleNotFoundError: No module named 'psycopg2'`)

*   **증상**: Superset 컨테이너 실행 중 로그에 `psycopg2` 모듈을 찾을 수 없다는 에러가 발생하며 서버가 시작되지 않음.
*   **원인**: 
    *   Apache Superset 공식 이미지는 `app` 사용자와 가상환경(`/.venv`)을 사용함.
    *   `Dockerfile`에서 `root` 권한으로 `pip install`을 실행하면 시스템 전역 경로(`/usr/local/lib/...`)에 설치됨.
    *   Superset 실행 시 가상환경만 참조하고 시스템 경로는 참조하지 않아 모듈을 찾지 못함.
*   **해결**: `Dockerfile`에서 `PYTHONPATH` 환경변수를 설정하여 시스템 라이브러리 경로를 명시적으로 추가함.
    ```dockerfile
    ENV PYTHONPATH="${PYTHONPATH}:/usr/local/lib/python3.10/site-packages"
    ```

### 1.2. 메타데이터 DB 연결 실패 (`FATAL: database "superset" does not exist`)

*   **증상**: Superset 실행 시 Postgres에 연결할 수 없다는 `OperationalError` 발생.
*   **원인**:
    *   `docker-compose.yml`에서 `postgres` 컨테이너에 초기화 스크립트(`init_postgres.sql`)를 마운트했으나, Postgres 이미지는 **데이터 디렉토리가 비어있을 때만** 초기화 스크립트를 실행함.
    *   이미 Druid용 데이터가 생성된 상태여서 스크립트가 무시됨.
*   **해결**: 실행 중인 Postgres 컨테이너에 접속하여 수동으로 DB 생성.
    ```bash
    docker exec -u postgres postgres psql -U druid -d druid -c "CREATE DATABASE superset;"
    ```

### 1.3. 프론트엔드 로딩 실패 (검은 화면, `Uncaught TypeError: ... reading 'flag'`)

*   **증상**: Superset 웹 UI 접속 시 로그인 화면이 뜨지 않고 검은 화면만 보임. 개발자 도구 콘솔에 `flag` 속성을 읽을 수 없다는 에러 발생.
*   **원인**:
    *   `superset_config.py`에서 언어를 한국어(`ko`)로 설정했으나, 프론트엔드 에셋(국기 아이콘 등) 로딩에 실패함.
    *   설정을 영어(`en`)로 변경했음에도 브라우저 캐시/쿠키에 한국어 설정이 남아있어 계속 오류 발생.
*   **해결**:
    *   `superset_config.py`에서 `BABEL_DEFAULT_LOCALE = "en"`으로 변경.
    *   브라우저 **시크릿 모드(Incognito)**로 접속하거나 캐시/쿠키 삭제 후 재접속.