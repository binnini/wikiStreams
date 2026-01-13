import pytest
import os
import json
import time
from kafka import KafkaConsumer
from producer.sender import KafkaSender

# docker-compose.yml 파일이 있는 프로젝트 루트 경로 설정
# 현재 파일 위치: tests/integration/test_producer_kafka_integration.py
# 루트 위치: ../../
COMPOSE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig):
    """docker-compose.yml 파일의 경로를 pytest-docker에 알려줍니다."""
    return os.path.join(COMPOSE_PATH, "docker-compose.yml")


@pytest.fixture(scope="module")
def kafka_service(docker_ip, docker_services):
    """
    pytest-docker를 사용하여 Kafka 서비스를 시작하고 준비될 때까지 대기합니다.
    'docker_compose' 대신 'docker_services'를 사용합니다.
    """
    # docker_services.port_for를 호출하는 순간 해당 컨테이너가 실행됩니다.
    port = docker_services.port_for("kafka-kraft", 9092)
    broker_address = f"{docker_ip}:{port}"

    # 서비스가 준비될 때까지 대기 (Health Check)
    # wait_until_responsive는 내부적으로 루프를 돌며 성공할 때까지 확인합니다.
    def check_kafka():
        try:
            from kafka import KafkaAdminClient

            client = KafkaAdminClient(bootstrap_servers=broker_address)
            client.close()
            return True
        except Exception:
            return False

    docker_services.wait_until_responsive(timeout=30.0, pause=1.0, check=check_kafka)

    return broker_address


@pytest.fixture(scope="module")
def kafka_topic():
    return "wikimedia.recentchange"


@pytest.fixture(scope="module")
def kafka_producer_client(kafka_service, kafka_topic):
    # kafka_service는 이미 'host:port' 문자열을 반환함
    sender = KafkaSender(kafka_service, kafka_topic)
    return sender


@pytest.fixture(scope="module")
def kafka_consumer_client(kafka_service, kafka_topic):
    consumer = KafkaConsumer(
        kafka_topic,
        bootstrap_servers=[kafka_service],
        group_id=f"test-consumer-group-{time.time()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda x: json.loads(x.decode("utf-8")),
    )
    # Consumer가 연결될 수 있게 짧게 대기
    time.sleep(2)
    yield consumer
    consumer.close()


@pytest.mark.integration
def test_producer_sends_to_kafka(
    kafka_producer_client, kafka_consumer_client, kafka_topic
):
    # Arrange
    test_message = {
        "id": 1,
        "meta": {"uri": "https://test.wikimedia.org/wiki/Test_Page"},
        "title": "Test_Page",
        "comment": "Integration test message",
        "timestamp": int(time.time()),
    }

    # Act
    kafka_producer_client.send_events([test_message])

    # Assert
    messages = []
    start_time = time.time()
    # 최대 20초 동안 메시지 폴링
    while not messages and (time.time() - start_time < 20):
        polled = kafka_consumer_client.poll(timeout_ms=1000, max_records=1)
        for records in polled.values():
            for record in records:
                messages.append(record.value)

    assert len(messages) > 0, "Kafka Consumer가 메시지를 수신하지 못했습니다."
    assert messages[0]["id"] == test_message["id"]
    assert messages[0]["title"] == test_message["title"]
