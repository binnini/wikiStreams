# WikiStreams 테스트 가이드

> 현재 단위 테스트: **276개** | 통합 테스트: **4개 파일**

---

## 테스트 구조

```
tests/
├── conftest.py                          # 전역 Fixture
├── unit/
│   ├── producer/                        # 수집·보강·발행 로직
│   │   ├── test_cache.py                # SQLite TTL 캐시 (3-way TTL)
│   │   ├── test_collector.py            # SSE 수집, 지수 백오프, 배치 타임아웃
│   │   ├── test_enricher.py             # Wikidata Q-ID 보강, 캐시 히트/미스
│   │   ├── test_models.py               # Pydantic 스키마 검증, DLQ 격리
│   │   ├── test_sender.py               # Kafka 발행, DLQ 라우팅
│   │   └── test_main.py                 # 파이프라인 오케스트레이션
│   ├── reporter/                        # 트렌드 리포트
│   │   ├── test_fetcher.py              # ClickHouse 쿼리, 뉴스 스크래핑, 썸네일
│   │   ├── test_builder.py              # Claude API 호출, selected_indices 파싱
│   │   ├── test_publisher.py            # Discord Embed 구성
│   │   ├── test_prompts.py              # 프롬프트 스타일 동적 로드
│   │   └── test_main.py                 # 리포트 파이프라인 전체 흐름
│   ├── resource_monitor/                # 이상 감지
│   │   ├── test_baseline.py             # EMA + Welford online variance
│   │   ├── test_collector.py            # Docker stats 수집
│   │   ├── test_detector.py             # z-score, abs_threshold, severity
│   │   └── test_alerter.py              # Slack 알림, cooldown, runbook
│   └── s3_exporter/                     # S3 Datalake 내보내기
│       └── test_main.py                 # s3_key, s3_exists, export, next_run_utc
└── integration/
    ├── test_enrichment_cache.py          # 실제 SQLite 연동
    ├── test_producer_kafka_integration.py # 실제 Redpanda 연동
    ├── test_e2e_pipeline.py              # Producer → Redpanda → QuestDB 전체 흐름
    └── test_reporter_integration.py      # 실제 Wikipedia API, Google News RSS
```

---

## 실행 방법

```bash
# 단위 테스트 (외부 의존성 없음, ~1초)
PYTHONPATH=src pytest tests/unit/ -v

# 특정 모듈만
PYTHONPATH=src pytest tests/unit/producer/test_cache.py -v
PYTHONPATH=src pytest tests/unit/resource_monitor/ -v

# 통합 테스트 (Redpanda, QuestDB 실행 중 필요)
PYTHONPATH=src pytest tests/integration/ -m integration

# 전체
PYTHONPATH=src pytest tests/
```

---

## 단위 테스트 핵심 패턴

### SQLite 임시 DB (cache, baseline)

```python
@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "database_path", str(db_path))
    cache.setup_database()
    yield
    cache.close_db_connection()
```

`tmp_path`로 테스트마다 격리된 DB를 생성하고, `monkeypatch`로 설정 경로를 교체합니다.

### httpx 모킹 (alerter, publisher, fetcher)

```python
@pytest.fixture
def mock_httpx(mocker):
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cm
    mock_cm.__exit__.return_value = False
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_cm.post.return_value = mock_resp
    mocker.patch("resource_monitor.alerter.httpx.Client", return_value=mock_cm)
    return mock_cm
```

`httpx.Client`를 context manager mock으로 교체합니다. 복수 호출이 필요한 경우 `side_effect=[cm1, cm2]` 사용.

### Kafka/Redpanda 발행 모킹 (sender)

```python
mocker.patch("producer.sender.KafkaProducer")
```

`KafkaProducer` 클래스 자체를 mock으로 교체하여 실제 브로커 연결 없이 발행 로직만 검증합니다.

### Claude API 모킹 (builder)

```python
mocker.patch("reporter.builder.anthropic.Anthropic")
```

---

## 통합 테스트 마커

`pytest.ini`에 `integration` 마커가 등록되어 있습니다. 통합 테스트는 `@pytest.mark.integration` 데코레이터를 사용하며, 단위 테스트 실행(`tests/unit/`)에는 포함되지 않습니다.

CI에서는 `unit-tests` job(PR + main push)과 `integration-tests` job(main push 전용)으로 분리됩니다.

---

## pytest.ini 주요 설정

```ini
[pytest]
log_cli = true
log_cli_level = INFO
markers =
    integration: marks tests as integration tests
```
