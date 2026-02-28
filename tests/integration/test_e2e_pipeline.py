import pytest
import time
import uuid
import requests
import logging

from producer.sender import KafkaSender

logger = logging.getLogger(__name__)

KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC = "wikimedia.recentchange"
CLICKHOUSE_URL = "http://localhost:8123"


def wait_for_clickhouse_ingestion(unique_id, timeout=60, interval=3):
    """
    ClickHouse HTTP API를 폴링하여 테스트 이벤트가 적재될 때까지 대기합니다.
    comment 필드에 unique_id를 심어 식별합니다.
    """
    query = f"SELECT count() FROM wikimedia.events WHERE comment = '{unique_id}'"
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(CLICKHOUSE_URL, params={"query": query}, timeout=5)
            if resp.status_code == 200 and int(resp.text.strip()) > 0:
                return True
            logger.info(f"Waiting for ClickHouse ingestion... ({resp.text.strip()})")
        except requests.exceptions.RequestException as e:
            logger.warning(f"ClickHouse connection error: {e}")
        time.sleep(interval)
    return False


@pytest.mark.integration
def test_e2e_data_pipeline():
    """
    Producer → Kafka → ClickHouse 전체 파이프라인이 정상 작동하는지 검증합니다.
    unique_id를 comment 필드에 심어 ClickHouse에서 해당 이벤트를 식별합니다.
    """
    unique_id = str(uuid.uuid4())
    sender = KafkaSender(KAFKA_BROKER, KAFKA_TOPIC, dlq_topic=f"{KAFKA_TOPIC}.dlq")

    test_event = {
        "id": int(time.time()),
        "title": f"Test Page {unique_id}",
        "user": "E2E_Tester",
        "type": "edit",
        "namespace": 0,
        "comment": unique_id,
        "timestamp": int(time.time()),
        "server_name": "ko.wikipedia.org",
        "bot": False,
        "minor": False,
        "length": {"old": 100, "new": 150},
    }

    logger.info(f"[E2E] Sending event to Kafka with ID: {unique_id}")
    sender.send_events([test_event])

    logger.info("[E2E] Waiting for event to appear in ClickHouse...")
    ingested = wait_for_clickhouse_ingestion(unique_id)

    assert ingested, (
        f"E2E pipeline failed: event '{unique_id}' not found in ClickHouse "
        f"within timeout. Check ClickHouse Kafka engine and Materialized View."
    )
    logger.info(f"[E2E] Pipeline verified. Event '{unique_id}' found in ClickHouse.")
