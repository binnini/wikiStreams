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
def kafka_config():
    return {
        "bootstrap_servers": "localhost:9092",
        "topic": "wikimedia.recentchange"
    }

@pytest.fixture(scope="module")
def sender(kafka_config):
    return KafkaSender(kafka_config["bootstrap_servers"], kafka_config["topic"])

def setup_druid_supervisor():
    """
    Druid에 Kafka 수집 설정을 등록합니다.
    """
    spec_path = os.path.join(os.path.dirname(__file__), "../../druid/ingestion-spec.json")
    with open(spec_path, "r") as f:
        spec = json.load(f)
    
    logger.info("Registering Druid Kafka Supervisor...")
    try:
        response = requests.post(
            DRUID_COORDINATOR_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(spec)
        )
        if response.status_code in [200, 400]: # 400은 이미 존재할 경우일 수 있음
            logger.info(f"Druid Supervisor registration response: {response.status_code}")
        else:
            logger.error(f"Failed to register Druid Supervisor: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error connecting to Druid Coordinator: {e}")

def wait_for_druid_ingestion(unique_id, timeout=120, interval=5):
    """
    Druid에서 특정 ID를 가진 데이터가 조회될 때까지 대기합니다.
    """
    query = f"""
    SELECT count(*) as "cnt"
    FROM "wikimedia.recentchange"
    WHERE "comment" = '{unique_id}'
    """
    
    payload = {
        "query": query,
        "context": {"sqlTimeZone": "Asia/Seoul"}
    }
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.post(
                DRUID_ROUTER_URL, 
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload)
            )
            
            if response.status_code == 200:
                data = response.json()
                if data and data[0]['cnt'] > 0:
                    return True
            else:
                logger.info(f"Druid Status: {response.status_code} - Waiting for data... Response: {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Connection Error: {e}")
            
        time.sleep(interval)
        
    return False

@pytest.mark.integration
def test_e2e_data_pipeline(sender):
    """
    Producer -> Kafka -> Druid 전체 파이프라인이 정상 작동하는지 검증합니다.
    """
    # 0. Druid 설정 등록
    setup_druid_supervisor()
    
    # 1. 고유한 식별자를 가진 테스트 이벤트 생성
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
        "length": {"old": 100, "new": 150}
    }

    # 2. Kafka로 이벤트 전송
    logger.info(f"[Test] Sending event with ID: {test_id}")
    sender.send_events([test_event])

    # 3. Druid에서 데이터 조회 확인 (최대 120초 대기)
    logger.info("[Test] Waiting for data to appear in Druid...")
    is_ingested = wait_for_druid_ingestion(test_id)

    # 4. 결과 검증
    assert is_ingested, f"데이터 파이프라인 실패: ID {test_id}인 이벤트를 Druid에서 찾을 수 없습니다."
    logger.info(f"[Success] 데이터가 Kafka를 거쳐 Druid에 성공적으로 적재되었습니다. (ID: {test_id})")
