import pytest
import time
import uuid
import requests
import logging

from producer.sender import KafkaSender

logger = logging.getLogger(__name__)

KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC = "wikimedia.recentchange"
QUESTDB_URL = "http://localhost:9000"


def wait_for_questdb_ingestion(unique_id, timeout=60, interval=3):
    """
    QuestDB REST API를 폴링하여 테스트 이벤트가 적재될 때까지 대기합니다.
    comment 필드에 unique_id를 심어 식별합니다.
    """
    query = f"SELECT count(1) FROM wikimedia_events WHERE comment = '{unique_id}'"
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(
                f"{QUESTDB_URL}/exec",
                params={"query": query, "fmt": "json"},
                timeout=5,
            )
            if resp.status_code == 200:
                body = resp.json()
                count = body.get("dataset", [[0]])[0][0]
                if count > 0:
                    return True
                logger.info(f"Waiting for QuestDB ingestion... (count={count})")
        except requests.exceptions.RequestException as e:
            logger.warning(f"QuestDB connection error: {e}")
        time.sleep(interval)
    return False


@pytest.mark.integration
def test_e2e_data_pipeline():
    """
    Producer → Kafka → QuestDB 전체 파이프라인이 정상 작동하는지 검증합니다.
    unique_id를 comment 필드에 심어 QuestDB에서 해당 이벤트를 식별합니다.
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

    logger.info("[E2E] Waiting for event to appear in QuestDB...")
    ingested = wait_for_questdb_ingestion(unique_id)

    assert ingested, (
        f"E2E pipeline failed: event '{unique_id}' not found in QuestDB "
        f"within timeout. Check questdb-consumer and Kafka topic."
    )
    logger.info(f"[E2E] Pipeline verified. Event '{unique_id}' found in QuestDB.")
