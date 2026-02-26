import logging
import pytest
from unittest.mock import MagicMock

from dlq_consumer.consumer import DLQConsumer

TEST_BROKER = "localhost:9092"
TEST_TOPIC = "wikimedia.recentchange"
TEST_DLQ_TOPIC = "wikimedia.recentchange.dlq"
MAX_RETRIES = 3


@pytest.fixture
def mock_kafka(mocker):
    """KafkaConsumer와 KafkaProducer를 모킹하는 Fixture"""
    mock_consumer_cls = mocker.patch("dlq_consumer.consumer.KafkaConsumer")
    mock_producer_cls = mocker.patch("dlq_consumer.consumer.KafkaProducer")
    return mock_consumer_cls, mock_producer_cls


@pytest.fixture
def dlq_consumer(mock_kafka):
    return DLQConsumer(
        kafka_broker=TEST_BROKER,
        kafka_topic=TEST_TOPIC,
        dlq_topic=TEST_DLQ_TOPIC,
        max_retries=MAX_RETRIES,
        consumer_group="test-group",
    )


def make_dlq_message(retry_count: int) -> dict:
    return {
        "original_event": {"id": 1, "title": "TestEvent"},
        "dlq_metadata": {
            "error": "send failed",
            "failed_at": "2026-01-01T00:00:00",
            "source_topic": TEST_TOPIC,
            "retry_count": retry_count,
        },
    }


# 1. retry_count=0 → 메인 토픽 전송 성공
def test_retry_success_sends_to_main_topic(dlq_consumer):
    dlq_message = make_dlq_message(retry_count=0)
    mock_future = MagicMock()
    mock_future.get.return_value = None
    dlq_consumer.producer.send.return_value = mock_future

    dlq_consumer._process_message(dlq_message)

    dlq_consumer.producer.send.assert_called_once_with(
        TEST_TOPIC, value=dlq_message["original_event"]
    )


# 2. retry_count=0, 전송 실패 → DLQ 재큐잉 + retry_count=1
def test_retry_failure_requeues_with_incremented_count(dlq_consumer):
    dlq_message = make_dlq_message(retry_count=0)
    mock_future = MagicMock()
    mock_future.get.side_effect = Exception("send failed")
    dlq_consumer.producer.send.return_value = mock_future

    dlq_consumer._process_message(dlq_message)

    # 첫 번째 call: 메인 토픽 재시도, 두 번째 call: DLQ 재큐잉
    assert dlq_consumer.producer.send.call_count == 2
    requeue_call = dlq_consumer.producer.send.call_args_list[1]
    assert requeue_call.args[0] == TEST_DLQ_TOPIC
    requeued_msg = requeue_call.kwargs["value"]
    assert requeued_msg["dlq_metadata"]["retry_count"] == 1
    assert requeued_msg["original_event"] == dlq_message["original_event"]


# 3. retry_count=3 (>= MAX_RETRIES) → CRITICAL 로그, 전송 없음
def test_exceeds_max_retries_discards_message(dlq_consumer, caplog):
    dlq_message = make_dlq_message(retry_count=3)

    with caplog.at_level(logging.CRITICAL):
        dlq_consumer._process_message(dlq_message)

    dlq_consumer.producer.send.assert_not_called()
    assert any("최대 재시도 초과" in r.message for r in caplog.records)


# 4. retry_count=2, 전송 실패 → DLQ 재큐잉 + retry_count=3
def test_last_retry_requeues_with_max_count(dlq_consumer):
    dlq_message = make_dlq_message(retry_count=2)
    mock_future = MagicMock()
    mock_future.get.side_effect = Exception("send failed")
    dlq_consumer.producer.send.return_value = mock_future

    dlq_consumer._process_message(dlq_message)

    assert dlq_consumer.producer.send.call_count == 2
    requeue_call = dlq_consumer.producer.send.call_args_list[1]
    requeued_msg = requeue_call.kwargs["value"]
    assert requeued_msg["dlq_metadata"]["retry_count"] == 3
