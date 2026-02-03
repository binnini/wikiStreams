import requests
import json
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DRUID_COORDINATOR_URL = "http://localhost:8081/druid/indexer/v1/supervisor"
DRUID_DATASOURCE_URL = "http://localhost:8081/druid/coordinator/v1/datasources"

def cleanup_zombies():
    """
    좀비 Supervisor와 Datasource를 모두 정리합니다.
    """
    cleanup_supervisors()
    cleanup_datasources()

def cleanup_supervisors():
    try:
        # 1. 모든 Supervisor 목록 조회
        response = requests.get(DRUID_COORDINATOR_URL)
        if response.status_code != 200:
            logger.error(f"Failed to list supervisors: {response.text}")
            return

        supervisors = response.json()
        logger.info(f"Found {len(supervisors)} supervisors.")

        # 2. 'test_datasource_'로 시작하는 Supervisor 종료
        for sup in supervisors:
            sup_id = sup
            if isinstance(sup, dict): # 상세 정보가 포함된 경우
                sup_id = sup.get("id")
            
            if sup_id and sup_id.startswith("test_datasource_"):
                logger.info(f"Terminating zombie supervisor: {sup_id}")
                terminate_url = f"{DRUID_COORDINATOR_URL}/{sup_id}/terminate"
                requests.post(terminate_url)
    except Exception as e:
        logger.error(f"Error during supervisor cleanup: {e}")

def cleanup_datasources():
    try:
        # 1. 모든 Datasource 목록 조회 (metadata API 사용)
        meta_url = "http://localhost:8081/druid/coordinator/v1/metadata/datasources"
        response = requests.get(meta_url)
        if response.status_code != 200:
            logger.error(f"Failed to list datasources: {response.text}")
            return

        datasources = response.json()
        logger.info(f"Found {len(datasources)} datasources.")

        # 2. 'test_datasource_'로 시작하는 Datasource 삭제 (Disable)
        for ds in datasources:
            if ds.startswith("test_datasource_"):
                logger.info(f"Disabling and deleting zombie datasource: {ds}")
                # Datasource를 'unused' 상태로 변경 (영구 삭제 전 단계)
                delete_url = f"{DRUID_DATASOURCE_URL}/{ds}"
                resp = requests.delete(delete_url)
                if resp.status_code == 200:
                    logger.info(f"Successfully disabled datasource: {ds}")
                else:
                    logger.warning(f"Failed to disable datasource {ds}: {resp.status_code} - {resp.text}")

    except Exception as e:
        logger.error(f"Error during datasource cleanup: {e}")

if __name__ == "__main__":
    cleanup_zombies()
