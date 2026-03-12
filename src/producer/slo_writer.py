import logging
import time
import urllib.parse
import urllib.request

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS producer_slo_metrics (
    batch_processing_seconds DOUBLE,
    batch_size               INT,
    valid                    INT,
    total_enriched           INT,
    new_api_calls            INT,
    cache_hit_rate_pct       DOUBLE,
    ts                       TIMESTAMP
) timestamp(ts) PARTITION BY DAY TTL 7d;
""".strip()


class SloWriter:
    """배치 처리 완료 시 SLO 지표를 QuestDB REST API로 기록한다."""

    def __init__(self, host: str, port: int):
        self._base_url = f"http://{host}:{port}"

    def _exec(self, sql: str) -> bool:
        """QuestDB /exec 엔드포인트에 SQL 실행. 실패 시 False 반환."""
        try:
            params = urllib.parse.urlencode({"query": sql})
            url = f"{self._base_url}/exec?{params}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logging.warning("SloWriter QuestDB 요청 실패: %s", e)
            return False

    def ensure_table(self, retries: int = 5, delay: float = 3.0) -> None:
        """테이블이 없으면 생성한다. QuestDB 기동 전 호출 시 재시도."""
        for attempt in range(1, retries + 1):
            if self._exec(_CREATE_TABLE_SQL):
                logging.info("SloWriter: producer_slo_metrics 테이블 준비 완료")
                return
            logging.warning(
                "SloWriter: 테이블 생성 실패 (%d/%d), %.0fs 후 재시도...",
                attempt,
                retries,
                delay,
            )
            time.sleep(delay)
        logging.warning("SloWriter: 테이블 생성 최종 실패 — SLO 지표 기록 불가")

    def write(
        self,
        batch_sec: float,
        batch_size: int,
        valid: int,
        total_enriched: int,
        new_api_calls: int,
    ) -> None:
        """배치 1건의 SLO 지표를 QuestDB에 INSERT한다. 실패해도 파이프라인은 계속된다."""
        if total_enriched > 0:
            hit_rate_sql = str(
                round((total_enriched - new_api_calls) / total_enriched * 100, 2)
            )
        else:
            hit_rate_sql = "NULL"

        sql = (
            f"INSERT INTO producer_slo_metrics VALUES ("
            f"{batch_sec}, {batch_size}, {valid}, "
            f"{total_enriched}, {new_api_calls}, {hit_rate_sql}, now()"
            f");"
        )
        if not self._exec(sql):
            logging.warning("SloWriter: SLO 지표 INSERT 실패 (파이프라인 계속)")
