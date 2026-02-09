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


def check_kafka_connection(address):
    """Kafka 브로커에 연결 가능한지 확인하는 헬퍼 함수"""
    try:
        from kafka import KafkaAdminClient

        client = KafkaAdminClient(bootstrap_servers=address)
        client.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def kafka_service(docker_ip, request):
    """
    Kafka 서비스를 준비합니다.
    1. 먼저 localhost:9092에 이미 떠 있는지 확인합니다.
    2. 없다면 pytest-docker를 통해 기동을 시도하며, 이름 충돌(Conflict) 발생 시 기존 컨테이너를 사용합니다.
    """
    local_address = "localhost:9092"

    # 1. 이미 로컬에 떠 있는지 확인
    if check_kafka_connection(local_address):
        return local_address

    # 2. 없으면 pytest-docker 시도
    try:
        # docker_services 피처를 동적으로 가져옴 (이 시점에 컨테이너 기동 시도)
        docker_services = request.getfixturevalue("docker_services")
        port = docker_services.port_for("kafka-kraft", 9092)
        broker_address = f"{docker_ip}:{port}"

        # 서비스가 준비될 때까지 대기
        docker_services.wait_until_responsive(
            timeout=30.0,
            pause=1.0,
            check=lambda: check_kafka_connection(broker_address),
        )
        return broker_address
    except Exception as e:
        # 에러 메시지에 'Conflict'가 포함되어 있으면 이미 컨테이너가 떠 있는 것이므로 로컬 주소 반환
        if "Conflict" in str(e) or "already in use" in str(e):
            return local_address
        # 그 외의 에러는 그대로 발생시킴
        raise e


@pytest.fixture(scope="module")
def kafka_topic(kafka_service):
    topic_name = f"test-topic-{int(time.time())}"
    yield topic_name

    # Teardown: Remove the topic after test
    try:
        from kafka.admin import KafkaAdminClient

        # kafka_service is "host:port" string
        admin_client = KafkaAdminClient(bootstrap_servers=kafka_service)
        admin_client.delete_topics([topic_name])
        admin_client.close()
        print(f"🧹 Deleted temporary topic: {topic_name}")
    except Exception as e:
        print(f"⚠️ Failed to delete topic {topic_name}: {e}")


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
    # Arrange: 고유한 ID와 제목을 사용하여 테스트 메시지 생성
    test_id = int(time.time())
    test_title = f"Test_Page_{test_id}"
    test_message = {
        "id": test_id,
        "meta": {"uri": f"https://test.wikimedia.org/wiki/{test_title}"},
        "title": test_title,
        "comment": "Integration test message",
        "timestamp": int(time.time()),
    }

    # Act
    kafka_producer_client.send_events([test_message])

    # Assert
    messages = []
    start_time = time.time()
    # 최대 20초 동안 메시지 폴링하며 우리가 보낸 메시지를 찾음
    found = False
    while not found and (time.time() - start_time < 20):
        polled = kafka_consumer_client.poll(timeout_ms=1000, max_records=10)
        for records in polled.values():
            for record in records:
                msg_value = record.value
                if msg_value.get("title") == test_title:
                    messages.append(msg_value)
                    found = True
                    break

    assert (
        len(messages) > 0
    ), f"Kafka Consumer가 제목이 '{test_title}'인 메시지를 수신하지 못했습니다."
    assert messages[0]["id"] == test_id
    assert messages[0]["title"] == test_title
