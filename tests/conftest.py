# tests/conftest.py
# Pytest fixtures and plugins can be shared across multiple test files here.

import pytest
import requests
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

DRUID_COORDINATOR_URL = "http://localhost:8081/druid/indexer/v1/supervisor"
DRUID_TASK_URL = "http://localhost:8081/druid/indexer/v1/task"
DRUID_METADATA_DS_URL = (
    "http://localhost:8081/druid/coordinator/v1/metadata/datasources"
)
DRUID_DS_URL = "http://localhost:8081/druid/coordinator/v1/datasources"


@pytest.fixture(scope="session", autouse=True)
def cleanup_orphaned_druid_tasks():
    """
    테스트 세션 시작 전, 이전에 정리되지 않은 좀비 Supervisor, Task, Datasource를 정리합니다.
    (Self-Healing)
    """
    logger.info("🧹 [Global Setup] Checking for orphaned Druid resources...")

    # 1. 좀비 Supervisor 정리
    try:
        response = requests.get(DRUID_COORDINATOR_URL)
        if response.status_code == 200:
            supervisors = response.json()
            for sup in supervisors:
                sup_id = sup if isinstance(sup, str) else sup.get("id")
                if sup_id and sup_id.startswith("test_datasource_"):
                    logger.warning(f"⚠️ Terminating zombie supervisor: {sup_id}")
                    requests.post(f"{DRUID_COORDINATOR_URL}/{sup_id}/terminate")
    except Exception as e:
        logger.warning(f"Failed to cleanup supervisors: {e}")

    # 2. 좀비 Task 정리
    try:
        response = requests.get(
            "http://localhost:8081/druid/indexer/v1/tasks?state=running"
        )
        if response.status_code == 200:
            tasks = response.json()
            for task in tasks:
                datasource = task.get("dataSource", "")
                task_id = task.get("id")
                if datasource.startswith("test_datasource_"):
                    logger.warning(f"⚠️ Shutting down zombie task: {task_id}")
                    requests.post(f"{DRUID_TASK_URL}/{task_id}/shutdown")
    except Exception as e:
        logger.warning(f"Failed to cleanup tasks: {e}")

    # 3. 좀비 Datasource 정리 (Disable)
    try:
        response = requests.get(DRUID_METADATA_DS_URL)
        if response.status_code == 200:
            datasources = response.json()
            for ds in datasources:
                if ds.startswith("test_datasource_"):
                    logger.warning(f"⚠️ Disabling zombie datasource: {ds}")
                    requests.delete(f"{DRUID_DS_URL}/{ds}")
    except Exception as e:
        logger.warning(f"Failed to cleanup datasources: {e}")

    logger.info("✨ [Global Setup] Cleanup complete.")
