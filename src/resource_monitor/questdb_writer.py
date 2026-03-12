"""컨테이너 리소스 메트릭을 QuestDB에 기록한다."""

import logging
import time
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resource_monitor.collector import ContainerMetrics

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS resource_metrics (
    container     VARCHAR,
    cpu_pct       DOUBLE,
    mem_pct       DOUBLE,
    mem_mb        DOUBLE,
    block_io_mb   DOUBLE,
    ts            TIMESTAMP
) timestamp(ts) PARTITION BY DAY TTL 7d;
""".strip()


class QuestDBWriter:
    """수집 주기마다 ContainerMetrics 목록을 QuestDB REST API로 기록한다."""

    def __init__(self, host: str, port: int):
        self._base_url = f"http://{host}:{port}"

    def _exec(self, sql: str) -> bool:
        try:
            params = urllib.parse.urlencode({"query": sql})
            url = f"{self._base_url}/exec?{params}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("QuestDBWriter 요청 실패: %s", e)
            return False

    def ensure_table(self, retries: int = 5, delay: float = 3.0) -> None:
        for attempt in range(1, retries + 1):
            if self._exec(_CREATE_TABLE_SQL):
                logger.info("QuestDBWriter: resource_metrics 테이블 준비 완료")
                return
            logger.warning(
                "QuestDBWriter: 테이블 생성 실패 (%d/%d), %.0fs 후 재시도...",
                attempt,
                retries,
                delay,
            )
            time.sleep(delay)
        logger.warning("QuestDBWriter: 테이블 생성 최종 실패 — 리소스 지표 기록 불가")

    def write(self, metrics_list: "list[ContainerMetrics]") -> None:
        """수집 주기 1회 분량의 메트릭을 일괄 INSERT한다. 실패해도 모니터링은 계속된다."""
        if not metrics_list:
            return

        rows = ", ".join(
            f"('{m.container}', {m.cpu_pct}, {m.mem_pct}, {m.mem_mb}, {m.block_io_mb}, now())"
            for m in metrics_list
        )
        sql = f"INSERT INTO resource_metrics VALUES {rows};"
        if not self._exec(sql):
            logger.warning("QuestDBWriter: INSERT 실패 (모니터링 계속)")
