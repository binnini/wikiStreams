import pytest
from unittest.mock import patch
from producer import main
from producer.config import settings

VALID_EVENT = {
    "title": "South Korea",
    "server_name": "en.wikipedia.org",
    "type": "edit",
    "namespace": 0,
    "timestamp": 1700000000,
    "user": "TestUser",
    "bot": False,
}


@pytest.fixture
def mock_dependencies():
    # 모든 의존성을 Mocking합니다.
    with patch("producer.main.setup_database") as mock_setup, patch(
        "producer.main.close_db_connection"
    ) as mock_close, patch("producer.main.WikidataEnricher") as MockEnricher, patch(
        "producer.main.KafkaSender"
    ) as MockSender, patch(
        "producer.main.WikimediaCollector"
    ) as MockCollector, patch(
        "producer.main.SloWriter"
    ) as MockSloWriter:

        # SloWriter 기본 동작: ensure_table 성공
        MockSloWriter.return_value.ensure_table.return_value = None
        MockSloWriter.return_value.write.return_value = None

        yield {
            "setup_db": mock_setup,
            "close_db": mock_close,
            "Enricher": MockEnricher,
            "Sender": MockSender,
            "Collector": MockCollector,
            "SloWriter": MockSloWriter,
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
        settings.kafka_broker, settings.kafka_topic, settings.kafka_dlq_topic
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

    # 테스트용 이벤트 데이터 (필수 필드를 모두 갖춘 유효한 이벤트)
    raw_events = [
        {**VALID_EVENT, "title": "Event1"},
        {**VALID_EVENT, "title": "Event2"},
    ]
    enriched_events = [{"title": "Event1", "label": "L1"}, {"title": "Event2"}]
    enrich_stats = {"total_enriched": 2, "new_api_calls": 1}

    # Mock 객체들의 동작 설정
    enricher_instance = mock_dependencies["Enricher"].return_value
    enricher_instance.enrich_events.return_value = (enriched_events, enrich_stats)

    sender_instance = mock_dependencies["Sender"].return_value

    # Act
    # 콜백 함수 실행 (마치 Collector가 배치 처리를 완료하고 호출한 것처럼)
    process_batch_callback(raw_events)

    # Assert
    # Enricher가 호출되었는지 확인
    enricher_instance.enrich_events.assert_called_once_with(raw_events)

    # Sender가 보강된 데이터를 전송했는지 확인
    sender_instance.send_events.assert_called_once_with(enriched_events)


def test_process_batch_invalid_events_routed_to_dlq(mock_dependencies):
    """필수 필드가 누락된 이벤트는 DLQ로 격리되어야 한다."""
    main.run_producer()

    collector_instance = mock_dependencies["Collector"].return_value
    args, _ = collector_instance.set_callback.call_args
    process_batch_callback = args[0]

    invalid_events = [{"title": "no_required_fields"}]

    enricher_instance = mock_dependencies["Enricher"].return_value
    enricher_instance.enrich_events.return_value = ([], {"total_enriched": 0, "new_api_calls": 0})
    sender_instance = mock_dependencies["Sender"].return_value

    process_batch_callback(invalid_events)

    sender_instance.send_to_dlq.assert_called_once()
    call_kwargs = sender_instance.send_to_dlq.call_args
    assert call_kwargs[0][0] == invalid_events[0]
    assert "Schema validation error" in call_kwargs[0][1]

    enricher_instance.enrich_events.assert_called_once_with([])


def test_process_batch_mixed_valid_and_invalid(mock_dependencies):
    """유효한 이벤트만 enricher로 전달되고, 무효한 이벤트는 DLQ로 격리된다."""
    main.run_producer()

    collector_instance = mock_dependencies["Collector"].return_value
    args, _ = collector_instance.set_callback.call_args
    process_batch_callback = args[0]

    valid_event = {**VALID_EVENT, "title": "ValidEvent"}
    invalid_event = {"title": "no_required_fields"}
    mixed_events = [valid_event, invalid_event]

    enricher_instance = mock_dependencies["Enricher"].return_value
    enricher_instance.enrich_events.return_value = ([valid_event], {"total_enriched": 1, "new_api_calls": 0})
    sender_instance = mock_dependencies["Sender"].return_value

    process_batch_callback(mixed_events)

    enricher_instance.enrich_events.assert_called_once_with([valid_event])
    sender_instance.send_to_dlq.assert_called_once()
    sender_instance.send_events.assert_called_once_with([valid_event])


# --- _should_skip() 단위 테스트 ---


def test_should_skip_log_type_event():
    """type=log 이벤트는 조용히 버려진다."""
    assert (
        main._should_skip({"type": "log", "meta": {"domain": "en.wikipedia.org"}})
        is True
    )


def test_should_skip_canary_domain_event():
    """domain=canary 이벤트는 조용히 버려진다."""
    assert main._should_skip({"type": "edit", "meta": {"domain": "canary"}}) is True


def test_should_not_skip_normal_edit_event():
    """정상 edit 이벤트는 skip되지 않는다."""
    assert (
        main._should_skip({"type": "edit", "meta": {"domain": "en.wikipedia.org"}})
        is False
    )


def test_should_not_skip_new_event():
    """type=new 이벤트는 skip되지 않는다."""
    assert (
        main._should_skip({"type": "new", "meta": {"domain": "ko.wikipedia.org"}})
        is False
    )


def test_process_batch_log_events_silently_dropped(mock_dependencies):
    """type=log 이벤트는 DLQ로 보내지 않고 조용히 버려진다."""
    main.run_producer()

    collector_instance = mock_dependencies["Collector"].return_value
    args, _ = collector_instance.set_callback.call_args
    process_batch_callback = args[0]

    log_event = {"type": "log", "meta": {"domain": "en.wikipedia.org"}}

    enricher_instance = mock_dependencies["Enricher"].return_value
    enricher_instance.enrich_events.return_value = ([], {"total_enriched": 0, "new_api_calls": 0})
    sender_instance = mock_dependencies["Sender"].return_value

    process_batch_callback([log_event])

    sender_instance.send_to_dlq.assert_not_called()
    enricher_instance.enrich_events.assert_called_once_with([])


def test_process_batch_canary_events_silently_dropped(mock_dependencies):
    """domain=canary 이벤트는 DLQ로 보내지 않고 조용히 버려진다."""
    main.run_producer()

    collector_instance = mock_dependencies["Collector"].return_value
    args, _ = collector_instance.set_callback.call_args
    process_batch_callback = args[0]

    canary_event = {"type": "edit", "meta": {"domain": "canary"}}

    enricher_instance = mock_dependencies["Enricher"].return_value
    enricher_instance.enrich_events.return_value = ([], {"total_enriched": 0, "new_api_calls": 0})
    sender_instance = mock_dependencies["Sender"].return_value

    process_batch_callback([canary_event])

    sender_instance.send_to_dlq.assert_not_called()
    enricher_instance.enrich_events.assert_called_once_with([])
