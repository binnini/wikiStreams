import pytest
from unittest.mock import MagicMock, ANY
from kafka.errors import KafkaError

# 테스트할 모듈 임포트
from producer.sender import KafkaSender

TEST_TOPIC = "test_topic"
TEST_DLQ_TOPIC = "test_topic.dlq"


@pytest.fixture
def mock_kafka_producer(mocker):
    """KafkaProducer 클래스를 모킹하는 Fixture"""
    return mocker.patch("producer.sender.KafkaProducer")


def test_create_kafka_producer_success(mock_kafka_producer):
    # Act
    sender = KafkaSender("localhost:9092", TEST_TOPIC, TEST_DLQ_TOPIC)

    # Assert
    assert sender.producer is not None
    mock_kafka_producer.assert_called_once_with(
        bootstrap_servers=["localhost:9092"],
        value_serializer=ANY,  # 람다 함수 비교 대신 ANY 사용
        retries=5,
    )


def test_create_kafka_producer_retry_on_failure(mocker, mock_kafka_producer):
    # Arrange
    mocker.patch("time.sleep", return_value=None)
    mock_kafka_producer.side_effect = [Exception("Kafka connection error"), MagicMock()]

    # Act
    sender_with_retry = KafkaSender("localhost:9092", TEST_TOPIC, TEST_DLQ_TOPIC)

    # Assert
    assert mock_kafka_producer.call_count == 2
    assert sender_with_retry.producer is not None


def test_send_events(mocker, mock_kafka_producer):
    # Arrange
    sender = KafkaSender("localhost:9092", TEST_TOPIC, TEST_DLQ_TOPIC)
    mock_future = MagicMock()
    mock_future.get.return_value = None
    sender.producer.send.return_value = mock_future

    events = [
        {"id": 1, "data": "event1"},
        {"id": 2, "data": "event2"},
    ]

    # Act
    sender.send_events(events)

    # Assert
    assert sender.producer.send.call_count == 2
    sender.producer.send.assert_any_call(TEST_TOPIC, value={"id": 1, "data": "event1"})
    sender.producer.send.assert_any_call(TEST_TOPIC, value={"id": 2, "data": "event2"})
    sender.producer.flush.assert_called()


def test_send_empty_events(mocker, mock_kafka_producer):
    # Arrange
    sender = KafkaSender("localhost:9092", TEST_TOPIC, TEST_DLQ_TOPIC)
    events = []

    # Act
    sender.send_events(events)

    # Assert
    sender.producer.send.assert_not_called()
    sender.producer.flush.assert_not_called()


def test_send_events_routes_to_dlq_on_failure(mock_kafka_producer):
    # Arrange
    sender = KafkaSender("localhost:9092", TEST_TOPIC, TEST_DLQ_TOPIC)
    event = {"id": 1, "data": "event1"}

    mock_future = MagicMock()
    mock_future.get.side_effect = KafkaError("send failed")
    sender.producer.send.return_value = mock_future

    # Act
    sender.send_events([event])

    # Assert: DLQ 토픽으로 전송됐는지 확인
    dlq_calls = [
        call for call in sender.producer.send.call_args_list
        if call.args[0] == TEST_DLQ_TOPIC
    ]
    assert len(dlq_calls) == 1

    dlq_message = dlq_calls[0].kwargs["value"]
    assert dlq_message["original_event"] == event
    assert "error" in dlq_message["dlq_metadata"]
    assert dlq_message["dlq_metadata"]["source_topic"] == TEST_TOPIC
    assert dlq_message["dlq_metadata"]["retry_count"] == 0


def test_send_events_partial_failure(mock_kafka_producer):
    # Arrange
    sender = KafkaSender("localhost:9092", TEST_TOPIC, TEST_DLQ_TOPIC)
    events = [
        {"id": 1, "data": "event1"},
        {"id": 2, "data": "event2"},
        {"id": 3, "data": "event3"},
    ]

    ok_future = MagicMock()
    ok_future.get.return_value = None
    fail_future = MagicMock()
    fail_future.get.side_effect = KafkaError("timeout")

    # 2번째(index 1) 이벤트만 실패
    sender.producer.send.side_effect = [ok_future, fail_future, ok_future, MagicMock()]

    # Act
    sender.send_events(events)

    # Assert: 메인 토픽 3회 + DLQ 1회
    main_calls = [
        call for call in sender.producer.send.call_args_list
        if call.args[0] == TEST_TOPIC
    ]
    dlq_calls = [
        call for call in sender.producer.send.call_args_list
        if call.args[0] == TEST_DLQ_TOPIC
    ]
    assert len(main_calls) == 3
    assert len(dlq_calls) == 1


def test_dlq_send_failure_logs_critical(mock_kafka_producer, caplog):
    # Arrange
    sender = KafkaSender("localhost:9092", TEST_TOPIC, TEST_DLQ_TOPIC)
    event = {"id": 1, "data": "event1"}

    fail_future = MagicMock()
    fail_future.get.side_effect = KafkaError("main send failed")

    # 첫 send(메인 토픽) → fail_future 반환, 두 번째 send(DLQ) → 예외 발생
    sender.producer.send.side_effect = [fail_future, Exception("DLQ also failed")]

    # Act
    import logging
    with caplog.at_level(logging.CRITICAL, logger="root"):
        sender.send_events([event])

    # Assert
    assert any("DLQ 전송도 실패" in record.message for record in caplog.records)
