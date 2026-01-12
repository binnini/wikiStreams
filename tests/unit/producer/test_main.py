import pytest
from unittest.mock import MagicMock, ANY

from producer import main


@pytest.fixture
def mock_dependencies(mocker):
    """main 모듈이 의존하는 모든 외부 클래스와 함수를 모킹합니다."""
    mock_setup_db = mocker.patch("producer.main.setup_database")
    mock_close_db = mocker.patch("producer.main.close_db_connection")

    mock_collector_class = mocker.patch("producer.main.WikimediaCollector")
    mock_enricher_class = mocker.patch("producer.main.WikidataEnricher")
    mock_sender_class = mocker.patch("producer.main.KafkaSender")

    # 클래스들의 인스턴스 반환값을 MagicMock으로 설정
    mock_collector_instance = MagicMock()
    mock_enricher_instance = MagicMock()
    mock_sender_instance = MagicMock()

    mock_collector_class.return_value = mock_collector_instance
    mock_enricher_class.return_value = mock_enricher_instance
    mock_sender_class.return_value = mock_sender_instance

    return {
        "setup_db": mock_setup_db,
        "close_db": mock_close_db,
        "Collector": mock_collector_class,
        "Enricher": mock_enricher_class,
        "Sender": mock_sender_class,
        "collector_instance": mock_collector_instance,
        "enricher_instance": mock_enricher_instance,
        "sender_instance": mock_sender_instance,
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
        main.KAFKA_BROKER, main.KAFKA_TOPIC
    )
    mock_dependencies["Collector"].assert_called_once_with(
        main.BATCH_SIZE, main.BATCH_TIMEOUT_SECONDS
    )

    # 3. 콜백 함수가 올바르게 설정되었는지 확인
    mock_dependencies["collector_instance"].set_callback.assert_called_once_with(
        ANY
    )  # process_batch 함수

    # 4. 파이프라인의 핵심인 run() 메서드가 호출되었는지 확인
    mock_dependencies["collector_instance"].run.assert_called_once()


def test_process_batch_callback_flow(mock_dependencies):
    # Arrange
    # collector.set_callback으로 전달된 실제 콜백 함수(process_batch)를 가져옵니다.
    main.run_producer()  # run_producer를 실행하여 콜백이 설정되도록 함

    # set_callback이 호출될 때 사용된 인자(콜백 함수)를 캡처
    process_batch_callback = mock_dependencies[
        "collector_instance"
    ].set_callback.call_args[0][0]

    test_events = [{"id": 1}, {"id": 2}]
    enriched_events = [{"id": 1, "enriched": True}, {"id": 2, "enriched": True}]

    # enricher와 sender의 동작을 미리 정의
    mock_dependencies["enricher_instance"].enrich_events.return_value = enriched_events

    # Act
    # 캡처한 콜백 함수를 직접 실행합니다.
    process_batch_callback(test_events)

    # Assert
    # 콜백 함수 내부의 흐름(enricher -> sender)이 올바른지 확인
    mock_dependencies["enricher_instance"].enrich_events.assert_called_once_with(
        test_events
    )
    mock_dependencies["sender_instance"].send_events.assert_called_once_with(
        enriched_events
    )
