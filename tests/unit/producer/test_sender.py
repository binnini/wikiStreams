import pytest
from unittest.mock import MagicMock, ANY

# 테스트할 모듈 임포트
from producer.sender import KafkaSender

@pytest.fixture
def mock_kafka_producer(mocker):
    """KafkaProducer 클래스를 모킹하는 Fixture"""
    return mocker.patch('producer.sender.KafkaProducer')

def test_create_kafka_producer_success(mock_kafka_producer):
    # Act
    sender = KafkaSender("localhost:9092", "test_topic")

    # Assert
    assert sender.producer is not None
    mock_kafka_producer.assert_called_once_with(
        bootstrap_servers=['localhost:9092'],
        value_serializer=ANY, # 람다 함수 비교 대신 ANY 사용
        retries=5,
    )

def test_create_kafka_producer_retry_on_failure(mocker, mock_kafka_producer):
    # Arrange
    mocker.patch('time.sleep', return_value=None)
    mock_kafka_producer.side_effect = [Exception("Kafka connection error"), MagicMock()]
    
    # Act
    sender_with_retry = KafkaSender("localhost:9092", "test_topic")
    
    # Assert
    assert mock_kafka_producer.call_count == 2
    assert sender_with_retry.producer is not None

def test_send_events(mocker, mock_kafka_producer):
    # Arrange
    sender = KafkaSender("localhost:9092", "test_topic")
    events = [
        {'id': 1, 'data': 'event1'},
        {'id': 2, 'data': 'event2'},
    ]
    
    # Act
    sender.send_events(events)

    # Assert
    assert sender.producer.send.call_count == 2
    sender.producer.send.assert_any_call(
        sender.kafka_topic, value={'id': 1, 'data': 'event1'}
    )
    sender.producer.send.assert_any_call(
        sender.kafka_topic, value={'id': 2, 'data': 'event2'}
    )
    sender.producer.flush.assert_called_once()

def test_send_empty_events(mocker, mock_kafka_producer):
    # Arrange
    sender = KafkaSender("localhost:9092", "test_topic")
    events = []

    # Act
    sender.send_events(events)

    # Assert
    sender.producer.send.assert_not_called()
    sender.producer.flush.assert_not_called()
