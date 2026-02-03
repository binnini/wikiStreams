import pytest
import time
import uuid
import requests
import json
import logging
import os
from producer.sender import KafkaSender

# 로깅 설정
logger = logging.getLogger(__name__)

# Druid 주소 설정
DRUID_COORDINATOR_URL = "http://localhost:8081/druid/indexer/v1/supervisor"
DRUID_ROUTER_URL = "http://localhost:8888/druid/v2/sql"


@pytest.fixture(scope="module")
def kafka_broker():
    return "localhost:9092"


@pytest.fixture(scope="function")
def e2e_context(kafka_broker):
    """
    E2E 테스트를 위한 격리된 환경(Topic, Datasource)을 설정하고 정리합니다.
    """
    # 1. 고유한 테스트 ID 생성
    test_run_id = str(uuid.uuid4())[:8]
    topic_name = f"test_topic_{test_run_id}"
    datasource_name = f"test_datasource_{test_run_id}"

    logger.info(
        f"Setting up E2E context: Topic={topic_name}, DataSource={datasource_name}"
    )

    # 2. Ingestion Spec 로드 및 수정
    spec_path = os.path.join(
        os.path.dirname(__file__), "../../druid/ingestion-spec.json"
    )
    with open(spec_path, "r") as f:
        spec = json.load(f)

    # Spec 내용 동적 변경 (격리)
    spec["spec"]["dataSchema"]["dataSource"] = datasource_name
    spec["spec"]["ioConfig"]["topic"] = topic_name

    # 3. Druid Supervisor 등록
    try:
        response = requests.post(
            DRUID_COORDINATOR_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(spec),
        )
        if response.status_code != 200:
            pytest.fail(f"Failed to register supervisor: {response.text}")
        logger.info(f"Registered Druid Supervisor for {datasource_name}")
    except Exception as e:
        pytest.fail(f"Error connecting to Druid: {e}")

    # 4. 테스트 실행 (Context 전달)
    yield {"topic": topic_name, "datasource": datasource_name, "run_id": test_run_id}

    # 5. Teardown: Supervisor 종료 및 잔여 Task 강제 종료
    logger.info(f"Tearing down E2E context for {datasource_name}...")
    try:
        # Supervisor 종료 API 호출
        terminate_url = f"{DRUID_COORDINATOR_URL}/{datasource_name}/terminate"
        requests.post(terminate_url)
        logger.info(f"Terminated supervisor: {datasource_name}")
        
        # 잠깐 대기 후 잔여 Task 확인 및 종료
        time.sleep(1) 
        tasks_url = "http://localhost:8888/druid/indexer/v1/tasks?state=running"
        tasks_resp = requests.get(tasks_url)
        if tasks_resp.status_code == 200:
            for task in tasks_resp.json():
                if task.get("dataSource") == datasource_name:
                    task_id = task.get("id")
                    logger.warning(f"Force killing remaining task: {task_id}")
                    requests.post(f"http://localhost:8888/druid/indexer/v1/task/{task_id}/shutdown")

    except Exception as e:
        logger.warning(f"Failed to clean up Druid resources: {e}")


def wait_for_druid_ingestion(datasource_name, unique_id, timeout=120, interval=5):
    """
    지정된 Datasource에서 특정 ID를 가진 데이터가 조회될 때까지 대기합니다.
    """
    query = f"""
    SELECT count(*) as "cnt"
    FROM "{datasource_name}"
    WHERE "comment" = '{unique_id}'
    """

    payload = {"query": query, "context": {"sqlTimeZone": "Asia/Seoul"}}

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.post(
                DRUID_ROUTER_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
            )

            if response.status_code == 200:
                data = response.json()
                if data and data[0]["cnt"] > 0:
                    return True
            else:
                logger.info(
                    f"Druid Status: {response.status_code} - Waiting for data... ({response.text[:100]})"
                )

        except requests.exceptions.RequestException as e:
            logger.warning(f"Connection Error: {e}")

        time.sleep(interval)

    return False


@pytest.mark.integration
def test_e2e_data_pipeline(kafka_broker, e2e_context):
    """
    Producer -> Kafka -> Druid 전체 파이프라인이 정상 작동하는지 검증합니다.
    격리된 환경(Topic, Datasource)을 사용합니다.
    """
    topic = e2e_context["topic"]
    datasource = e2e_context["datasource"]

    # 1. 테스트용 Kafka Sender 생성
    sender = KafkaSender(kafka_broker, topic)

    # 2. 테스트 이벤트 생성
    test_id = str(uuid.uuid4())
    test_event = {
        "id": int(time.time()),
        "title": f"Test Page {test_id}",
        "user": "E2E_Tester",
        "type": "edit",
        "namespace": 0,
        "comment": test_id,
        "timestamp": int(time.time()),
        "server_name": "ko.wikipedia.org",
        "bot": False,
        "minor": False,
        "length": {"old": 100, "new": 150},
    }

    # 3. Kafka로 이벤트 전송
    logger.info(f"[Test] Sending event to topic '{topic}' with ID: {test_id}")
    sender.send_events([test_event])

    # 4. Druid에서 데이터 조회 확인
    logger.info(f"[Test] Waiting for data to appear in datasource '{datasource}'...")
    is_ingested = wait_for_druid_ingestion(datasource, test_id)

    # 5. 결과 검증
    assert (
        is_ingested
    ), f"데이터 파이프라인 실패: Datasource '{datasource}'에서 이벤트를 찾을 수 없습니다."
    logger.info(f"[Success] E2E Pipeline Verified! (Datasource: {datasource})")
