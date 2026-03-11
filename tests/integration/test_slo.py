"""
SLO 검증 테스트

배포 후 실제 운영 시스템이 SLO를 만족하는지 확인합니다.
로컬 또는 EC2에서 서비스가 실행 중인 상태에서 실행하세요.

실행:
    # SLO 테스트만
    PYTHONPATH=src pytest tests/integration/test_slo.py -v -m slo

    # 전체 통합 테스트
    PYTHONPATH=src pytest tests/integration/ -v -m integration

SLO 목표 (docs/SLO.md 기준):
    A2: QuestDB 쿼리 성공률 ≥ 99%
    P3: 쿼리 응답 p99 ≤ 200ms
    P5: 처리량 ≥ 800 events/min (최근 5분 기준)
    D1: 데이터 lag ≤ 30s
    D2: Wikidata 레이블 보강률 ≥ 80%
    CAP1: QuestDB 메모리 ≤ 80% (mem_limit 1100m 기준)
    CAP2: Producer CPU ≤ 70%
"""

import json
import subprocess
import time
import urllib.parse
import urllib.request

import pytest

QUESTDB_URL = "http://localhost:9000"
MEM_LIMIT_MIB = 1100  # docker-compose.yml questdb mem_limit


# ── 헬퍼 ────────────────────────────────────────────────────────────────────


def _query(sql: str, timeout: int = 10) -> list[dict]:
    """QuestDB REST API 쿼리 실행 → rows 반환."""
    params = urllib.parse.urlencode({"query": sql, "fmt": "json"})
    url = f"{QUESTDB_URL}/exec?{params}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"QuestDB 오류: {body['error']}")
    columns = [col["name"] for col in body.get("columns", [])]
    return [dict(zip(columns, row)) for row in body.get("dataset", [])]


def _percentile(data: list[float], p: float) -> float:
    sorted_data = sorted(data)
    idx = min(int(len(sorted_data) * p / 100), len(sorted_data) - 1)
    return sorted_data[idx]


def _docker_mem_mib(container: str) -> float | None:
    """docker stats로 컨테이너 RSS(MiB) 조회."""
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        usage = result.stdout.strip().split(" / ")[0]
        if usage.endswith("GiB"):
            return float(usage[:-3]) * 1024
        if usage.endswith("MiB"):
            return float(usage[:-3])
        return None
    except Exception:
        return None


def _docker_cpu_pct(container: str) -> float | None:
    """docker stats로 컨테이너 CPU% 조회."""
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}", container],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return float(result.stdout.strip().rstrip("%"))
    except Exception:
        return None


# ── SLO 테스트 ───────────────────────────────────────────────────────────────


@pytest.mark.slo
@pytest.mark.integration
class TestSLO:

    def test_slo_a2_questdb_availability(self):
        """
        SLO-A2: QuestDB 쿼리 성공률 ≥ 99%
        10회 쿼리 시도 후 성공률을 측정합니다.
        """
        total = 10
        success = 0
        for _ in range(total):
            try:
                _query("SELECT count(1) FROM wikimedia_events")
                success += 1
            except Exception:
                pass

        success_rate = success / total * 100
        assert success_rate >= 99.0, (
            f"SLO-A2 위반: QuestDB 쿼리 성공률 {success_rate:.1f}% < 99% "
            f"({success}/{total} 성공)"
        )

    def test_slo_p3_query_latency(self):
        """
        SLO-P3: QuestDB 쿼리 응답 p99 ≤ 200ms
        Reporter 실제 쿼리 패턴으로 10회 측정합니다.
        """
        sql = (
            "SELECT count(1) AS total, "
            "sum(CASE WHEN bot = true THEN 1 ELSE 0 END) AS bot_count "
            "FROM wikimedia_events "
            "WHERE timestamp > dateadd('d', -1, now())"
        )
        # 첫 쿼리 콜드 캐시 스파이크 제거용 워밍업
        try:
            _query(sql)
        except Exception:
            pass

        latencies_ms = []
        n = 10
        for _ in range(n):
            t0 = time.perf_counter()
            _query(sql)
            latencies_ms.append((time.perf_counter() - t0) * 1000)

        p99 = _percentile(latencies_ms, 99)
        p50 = _percentile(latencies_ms, 50)
        assert p99 <= 200.0, (
            f"SLO-P3 위반: 쿼리 응답 p99={p99:.1f}ms > 200ms "
            f"(p50={p50:.1f}ms, n={n})"
        )

    def test_slo_p5_throughput(self):
        """
        SLO-P5: 처리량 ≥ 800 events/min (최근 5분 기준)
        Wikimedia 스트림이 활성 상태여야 합니다.
        """
        rows = _query(
            "SELECT count(1) AS cnt FROM wikimedia_events "
            "WHERE timestamp > dateadd('m', -5, now())"
        )
        count_5min = int(rows[0]["cnt"]) if rows else 0
        events_per_min = count_5min / 5

        assert events_per_min >= 800, (
            f"SLO-P5 위반: 처리량 {events_per_min:.0f} events/min < 800/min "
            f"(최근 5분 {count_5min}건)"
        )

    def test_slo_d1_data_freshness(self):
        """
        SLO-D1: 데이터 신선도 lag ≤ 30s
        QuestDB 최신 이벤트 타임스탬프와 현재 시각의 차이를 측정합니다.
        """
        rows = _query("SELECT max(timestamp) AS latest FROM wikimedia_events")
        if not rows or rows[0]["latest"] is None:
            pytest.skip("wikimedia_events 테이블에 데이터 없음")

        latest_str = rows[0]["latest"]
        # QuestDB timestamp 형식: "2026-03-10T12:34:56.000000Z"
        from datetime import datetime, timezone

        latest_dt = datetime.fromisoformat(
            latest_str.replace("Z", "+00:00").replace("T", " ")[:26] + "+00:00"
        )
        now_utc = datetime.now(timezone.utc)
        lag_s = (now_utc - latest_dt).total_seconds()

        assert lag_s <= 30.0, (
            f"SLO-D1 위반: 데이터 lag {lag_s:.1f}s > 30s "
            f"(최신 이벤트: {latest_str})"
        )

    def test_slo_d2_label_enrichment(self):
        """
        SLO-D2: Wikidata 레이블 보강률 ≥ 80%
        wikidata.org 이벤트(Q-ID 타이틀) 중 레이블이 있는 비율을 측정합니다.
        """
        rows = _query(
            "SELECT "
            "  count(1) AS total, "
            "  sum(CASE WHEN wikidata_label <> '' THEN 1 ELSE 0 END) AS labeled "
            "FROM wikimedia_events "
            "WHERE timestamp > dateadd('h', -24, now()) "
            "  AND title LIKE 'Q%' "
            "  AND server_name = 'www.wikidata.org'"
        )
        if not rows:
            pytest.skip("wikidata.org 이벤트 없음")

        total = int(rows[0]["total"])
        labeled = int(rows[0]["labeled"])

        if total < 100:
            pytest.skip(f"wikidata.org Q-ID 이벤트 부족 ({total}건 < 100건)")

        enrichment_rate = labeled / total * 100
        assert enrichment_rate >= 80.0, (
            f"SLO-D2 위반: 레이블 보강률 {enrichment_rate:.1f}% < 80% "
            f"({labeled}/{total}건)"
        )

    def test_slo_cap1_questdb_memory(self):
        """
        SLO-CAP1: QuestDB 메모리 ≤ 80% (mem_limit 1100m 기준 = 880 MiB)
        docker stats으로 실시간 RSS를 확인합니다.
        """
        rss_mib = _docker_mem_mib("questdb")
        if rss_mib is None:
            pytest.skip("docker stats 조회 실패 (Docker 미실행 또는 컨테이너 없음)")

        threshold_mib = MEM_LIMIT_MIB * 0.80  # 880 MiB
        assert rss_mib <= threshold_mib, (
            f"SLO-CAP1 위반: QuestDB RSS {rss_mib:.0f} MiB > "
            f"{threshold_mib:.0f} MiB (mem_limit {MEM_LIMIT_MIB}m의 80%)"
        )

    def test_slo_cap2_producer_cpu(self):
        """
        SLO-CAP2: Producer CPU ≤ 70%
        docker stats으로 실시간 CPU 사용률을 확인합니다.
        """
        cpu_pct = _docker_cpu_pct("producer")
        if cpu_pct is None:
            pytest.skip("docker stats 조회 실패 (Docker 미실행 또는 컨테이너 없음)")

        assert cpu_pct <= 70.0, f"SLO-CAP2 위반: Producer CPU {cpu_pct:.1f}% > 70%"
