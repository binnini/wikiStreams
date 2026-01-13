import pytest
import time
import threading
from unittest.mock import patch, MagicMock
from producer import main
from producer.config import settings


@pytest.fixture
def mock_dependencies():
    # 모든 의존성을 Mocking합니다.
    with patch("producer.main.setup_database") as mock_setup, patch(
        "producer.main.close_db_connection"
    ) as mock_close, patch(
        "producer.main.WikidataEnricher"
    ) as MockEnricher, patch(
        "producer.main.KafkaSender"
    ) as MockSender, patch(
        "producer.main.WikimediaCollector"
    ) as MockCollector:

        yield {
            "setup_db": mock_setup,
            "close_db": mock_close,
            "Enricher": MockEnricher,
            "Sender": MockSender,
            "Collector": MockCollector,
        }


def test_run_producer_initializes_and_runs_pipeline(mock_dependencies):
    # Act
    # run_producer 함수를 실행합니다.
    main.run_producer()

    # Assert
    # 1. 초기화 함수들이 호출되었는지 확인
    mock_dependencies["setup_db"].assert_called_once()

    # 2. 각 클래스가 올바른 인자로 인스턴스화되었는지 확인
    mock_dependencies["Enricher"].assert_called_once_with()
    mock_dependencies["Sender"].assert_called_once_with(
        settings.kafka_broker, settings.kafka_topic
    )
    mock_dependencies["Collector"].assert_called_once_with(
        settings.batch_size, settings.batch_timeout_seconds
    )

    # 3. Collector가 실행되었는지 확인
    collector_instance = mock_dependencies["Collector"].return_value
    collector_instance.set_callback.assert_called_once()
    collector_instance.run.assert_called_once()


def test_process_batch_callback_flow(mock_dependencies):
    # Arrange
    # run_producer를 실행하여 내부의 process_batch 함수가 callback으로 등록되게 합니다.
    main.run_producer()

    # 등록된 콜백 함수 가져오기
    collector_instance = mock_dependencies["Collector"].return_value
    args, _ = collector_instance.set_callback.call_args
    process_batch_callback = args[0]

    # 테스트용 이벤트 데이터
    raw_events = [{"title": "Event1"}, {"title": "Event2"}]
    enriched_events = [{"title": "Event1", "label": "L1"}, {"title": "Event2"}]

    # Mock 객체들의 동작 설정
    enricher_instance = mock_dependencies["Enricher"].return_value
    enricher_instance.enrich_events.return_value = enriched_events

    sender_instance = mock_dependencies["Sender"].return_value

    # Act
    # 콜백 함수 실행 (마치 Collector가 배치 처리를 완료하고 호출한 것처럼)
    process_batch_callback(raw_events)

    # Assert
    # Enricher가 호출되었는지 확인
    enricher_instance.enrich_events.assert_called_once_with(raw_events)

    # Sender가 보강된 데이터를 전송했는지 확인
    sender_instance.send_events.assert_called_once_with(enriched_events)
