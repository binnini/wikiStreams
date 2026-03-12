#!/usr/bin/env python3
"""
WikiStreams SLO 데이터 내보내기 스크립트

QuestDB와 Docker Stats에서 SLO 관련 데이터를 수집하여
분석용 CSV 파일로 저장합니다.

사용법 (EC2 서버에서):
    python3 scripts/export_slo_data.py
    python3 scripts/export_slo_data.py --days 3 --output-dir /tmp/slo

출력 파일:
    slo_throughput.csv          - P5: 분당 처리량 (1분 버킷)
    slo_enrichment_hourly.csv   - D2: 시간별 Wikidata 레이블 보강률
    slo_by_wiki.csv             - 위키별 이벤트 수 및 봇 비율
    slo_namespace.csv           - 네임스페이스별 분포
    slo_query_latency.csv       - P3: 쿼리 응답 레이턴시 (20회 측정)
    slo_batch_processing.csv    - P1: 배치 처리 시간 (producer_slo_metrics)
    slo_cache_hitrate.csv       - P7: 캐시 히트율 (producer_slo_metrics)
    slo_resources_snapshot.csv  - CAP1/CAP2: 현재 컨테이너 리소스
    slo_summary.txt             - 현재 SLO 달성 여부 요약
"""

import argparse
import csv
import json
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

QUESTDB_URL = "http://localhost:9000"


# ── QuestDB 헬퍼 ─────────────────────────────────────────────────────────────


def questdb_csv(sql: str, timeout: int = 60) -> str:
    """QuestDB /exp 엔드포인트로 CSV 직접 반환."""
    params = urllib.parse.urlencode({"query": sql})
    url = f"{QUESTDB_URL}/exp?{params}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def questdb_json(sql: str, timeout: int = 30) -> list[dict]:
    """QuestDB /exec 엔드포인트로 JSON rows 반환."""
    params = urllib.parse.urlencode({"query": sql, "fmt": "json"})
    url = f"{QUESTDB_URL}/exec?{params}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"QuestDB 오류: {body['error']}")
    columns = [col["name"] for col in body.get("columns", [])]
    return [dict(zip(columns, row)) for row in body.get("dataset", [])]


# ── Docker stats 헬퍼 ────────────────────────────────────────────────────────


def docker_stats_snapshot() -> list[dict]:
    """모든 컨테이너의 현재 리소스 사용량 조회."""
    try:
        result = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        rows = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                name, cpu, mem_usage, mem_pct = parts
                rows.append(
                    {
                        "container": name,
                        "cpu_pct": cpu.rstrip("%"),
                        "mem_usage": mem_usage,
                        "mem_pct": mem_pct.rstrip("%"),
                        "snapshot_time": datetime.now(timezone.utc).isoformat(),
                    }
                )
        return rows
    except Exception as e:
        print(f"  ⚠ docker stats 실패: {e}")
        return []


# ── 내보내기 함수들 ──────────────────────────────────────────────────────────


def export_throughput(output_dir: Path, days: int):
    """P5: 분당 처리량 (1분 버킷)."""
    print("📊 처리량 (P5) 내보내기...")
    sql = (
        f"SELECT timestamp, count() AS events_per_min "
        f"FROM wikimedia_events "
        f"WHERE timestamp > dateadd('d', -{days}, now()) "
        f"SAMPLE BY 1m ORDER BY timestamp"
    )
    csv_data = questdb_csv(sql)
    out = output_dir / "slo_throughput.csv"
    out.write_text(csv_data, encoding="utf-8")
    line_count = csv_data.count("\n") - 1
    print(f"  → {out} ({line_count:,}행)")


def export_enrichment_hourly(output_dir: Path, days: int):
    """D2: 시간별 Wikidata 레이블 보강률."""
    print("📊 레이블 보강률 (D2) 내보내기...")
    sql = (
        f"SELECT "
        f"  timestamp, "
        f"  count() AS total, "
        f"  sum(CASE WHEN wikidata_label <> '' THEN 1 ELSE 0 END) AS labeled, "
        f"  round(sum(CASE WHEN wikidata_label <> '' THEN 1 ELSE 0 END)"
        f"        * 100.0 / count(), 2) AS enrichment_rate_pct "
        f"FROM wikimedia_events "
        f"WHERE timestamp > dateadd('d', -{days}, now()) "
        f"  AND title LIKE 'Q%' "
        f"  AND server_name = 'www.wikidata.org' "
        f"SAMPLE BY 1h ORDER BY timestamp"
    )
    csv_data = questdb_csv(sql)
    out = output_dir / "slo_enrichment_hourly.csv"
    out.write_text(csv_data, encoding="utf-8")
    line_count = csv_data.count("\n") - 1
    print(f"  → {out} ({line_count:,}행)")


def export_by_wiki(output_dir: Path, days: int):
    """위키별 이벤트 수, 봇 비율."""
    print("📊 위키별 통계 내보내기...")
    sql = (
        f"SELECT "
        f"  server_name, "
        f"  count() AS total_events, "
        f"  sum(CASE WHEN bot THEN 1 ELSE 0 END) AS bot_events, "
        f"  round(sum(CASE WHEN bot THEN 1 ELSE 0 END) * 100.0 / count(), 2) AS bot_pct "
        f"FROM wikimedia_events "
        f"WHERE timestamp > dateadd('d', -{days}, now()) "
        f"ORDER BY total_events DESC"
    )
    csv_data = questdb_csv(sql)
    out = output_dir / "slo_by_wiki.csv"
    out.write_text(csv_data, encoding="utf-8")
    line_count = csv_data.count("\n") - 1
    print(f"  → {out} ({line_count:,}행)")


def export_namespace(output_dir: Path, days: int):
    """네임스페이스별 이벤트 분포."""
    print("📊 네임스페이스 분포 내보내기...")
    sql = (
        f"SELECT "
        f"  namespace, "
        f"  count() AS total_events, "
        f"  sum(CASE WHEN bot THEN 1 ELSE 0 END) AS bot_events, "
        f"  round(sum(CASE WHEN bot THEN 1 ELSE 0 END) * 100.0 / count(), 2) AS bot_pct "
        f"FROM wikimedia_events "
        f"WHERE timestamp > dateadd('d', -{days}, now()) "
        f"ORDER BY total_events DESC"
    )
    csv_data = questdb_csv(sql)
    out = output_dir / "slo_namespace.csv"
    out.write_text(csv_data, encoding="utf-8")
    line_count = csv_data.count("\n") - 1
    print(f"  → {out} ({line_count:,}행)")


def export_query_latency(output_dir: Path):
    """P3: 쿼리 레이턴시 (20회 측정)."""
    print("📊 쿼리 레이턴시 (P3) 측정 중...")
    sql = (
        "SELECT count(1) AS total, "
        "sum(CASE WHEN bot = true THEN 1 ELSE 0 END) AS bot_count "
        "FROM wikimedia_events "
        "WHERE timestamp > dateadd('d', -1, now())"
    )
    # 콜드 캐시 스파이크 제거용 워밍업
    try:
        questdb_json(sql)
    except Exception:
        pass

    n = 20
    rows = []
    for i in range(n):
        t0 = time.perf_counter()
        try:
            questdb_json(sql)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            rows.append(
                {"trial": i + 1, "latency_ms": round(elapsed_ms, 2), "status": "ok"}
            )
        except Exception as e:
            rows.append({"trial": i + 1, "latency_ms": None, "status": f"error: {e}"})

    out = output_dir / "slo_query_latency.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["trial", "latency_ms", "status"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  → {out} (n={n})")


def export_batch_processing(output_dir: Path, days: int):
    """P1: 배치 처리 시간 (producer_slo_metrics 테이블)."""
    print("📊 배치 처리 시간 (P1) 내보내기...")
    sql = (
        f"SELECT ts, batch_processing_seconds, batch_size, valid "
        f"FROM producer_slo_metrics "
        f"WHERE ts > dateadd('d', -{days}, now()) "
        f"ORDER BY ts"
    )
    try:
        csv_data = questdb_csv(sql)
        out = output_dir / "slo_batch_processing.csv"
        out.write_text(csv_data, encoding="utf-8")
        line_count = csv_data.count("\n") - 1
        print(f"  → {out} ({line_count:,}건)")
    except Exception as e:
        print(f"  ⚠ 조회 실패: {e}")


def export_cache_hitrate(output_dir: Path, days: int):
    """P7: 캐시 히트율 (producer_slo_metrics 테이블)."""
    print("📊 캐시 히트율 (P7) 내보내기...")
    sql = (
        f"SELECT ts, total_enriched, new_api_calls, cache_hit_rate_pct "
        f"FROM producer_slo_metrics "
        f"WHERE ts > dateadd('d', -{days}, now()) "
        f"ORDER BY ts"
    )
    try:
        csv_data = questdb_csv(sql)
        out = output_dir / "slo_cache_hitrate.csv"
        out.write_text(csv_data, encoding="utf-8")
        line_count = csv_data.count("\n") - 1
        print(f"  → {out} ({line_count:,}건)")
    except Exception as e:
        print(f"  ⚠ 조회 실패: {e}")


def export_resources(output_dir: Path):
    """CAP1/CAP2: 현재 컨테이너 리소스 스냅샷."""
    print("📊 리소스 사용량 (CAP1/CAP2) 스냅샷...")
    rows = docker_stats_snapshot()
    out = output_dir / "slo_resources_snapshot.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "container",
                "cpu_pct",
                "mem_usage",
                "mem_pct",
                "snapshot_time",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"  → {out} ({len(rows)}개 컨테이너)")


def export_summary(output_dir: Path, days: int):
    """현재 SLO 달성 여부 요약."""
    print("📋 SLO 요약 생성...")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"WikiStreams SLO 요약 — {now_str}",
        f"분석 기간: 최근 {days}일",
        "=" * 60,
    ]

    # P1: 배치 처리 시간
    try:
        rows = questdb_json(
            "SELECT max(batch_processing_seconds) AS max_sec, "
            "avg(batch_processing_seconds) AS avg_sec "
            "FROM producer_slo_metrics "
            "WHERE ts > dateadd('m', -30, now())"
        )
        if rows and rows[0]["max_sec"] is not None:
            max_sec = float(rows[0]["max_sec"])
            avg_sec = float(rows[0]["avg_sec"])
            status = "✅" if max_sec <= 5 else "❌"
            lines.append(
                f"[P1]  배치 처리 시간   max={max_sec:.2f}s avg={avg_sec:.2f}s  {status} (목표 ≤5s)"
            )
        else:
            lines.append("[P1]  배치 처리 시간   데이터 없음")
    except Exception as e:
        lines.append(f"[P1]  배치 처리 시간   조회 실패 ({e})")

    # P5: 처리량
    try:
        rows = questdb_json(
            "SELECT count() AS cnt FROM wikimedia_events "
            "WHERE timestamp > dateadd('m', -5, now())"
        )
        cnt = int(rows[0]["cnt"]) if rows else 0
        epm = cnt / 5
        status = "✅" if epm >= 800 else "❌"
        lines.append(
            f"[P5]  처리량           {epm:8.0f} events/min  {status} (목표 ≥800)"
        )
    except Exception as e:
        lines.append(f"[P5]  처리량           조회 실패 ({e})")

    # P7: 캐시 히트율
    try:
        rows = questdb_json(
            "SELECT avg(cache_hit_rate_pct) AS avg_hit "
            "FROM producer_slo_metrics "
            "WHERE ts > dateadd('h', -1, now())"
        )
        if rows and rows[0]["avg_hit"] is not None:
            hit = float(rows[0]["avg_hit"])
            status = "✅" if hit >= 80 else "❌"
            lines.append(
                f"[P7]  캐시 히트율     {hit:8.1f} %           {status} (목표 ≥80%)"
            )
        else:
            lines.append("[P7]  캐시 히트율     데이터 없음")
    except Exception as e:
        lines.append(f"[P7]  캐시 히트율     조회 실패 ({e})")

    # D1: 데이터 신선도
    try:
        rows = questdb_json("SELECT max(timestamp) AS latest FROM wikimedia_events")
        if rows and rows[0]["latest"]:
            ts_str = (
                rows[0]["latest"].replace("Z", "+00:00").replace("T", " ")[:26]
                + "+00:00"
            )
            latest = datetime.fromisoformat(ts_str)
            lag = (datetime.now(timezone.utc) - latest).total_seconds()
            status = "✅" if lag <= 30 else "❌"
            lines.append(
                f"[D1]  데이터 lag       {lag:8.1f} s           {status} (목표 ≤30s)"
            )
    except Exception as e:
        lines.append(f"[D1]  데이터 lag       조회 실패 ({e})")

    # D2: 보강률
    try:
        rows = questdb_json(
            "SELECT count() AS total, "
            "sum(CASE WHEN wikidata_label <> '' THEN 1 ELSE 0 END) AS labeled "
            "FROM wikimedia_events "
            "WHERE timestamp > dateadd('h', -24, now()) "
            "  AND title LIKE 'Q%' AND server_name = 'www.wikidata.org'"
        )
        total = int(rows[0]["total"]) if rows else 0
        labeled = int(rows[0]["labeled"]) if rows else 0
        if total >= 100:
            rate = labeled / total * 100
            status = "✅" if rate >= 80 else "❌"
            lines.append(
                f"[D2]  레이블 보강률    {rate:8.1f} %           {status} (목표 ≥80%, {labeled}/{total}건)"
            )
        else:
            lines.append(f"[D2]  레이블 보강률    데이터 부족 ({total}건 < 100건)")
    except Exception as e:
        lines.append(f"[D2]  레이블 보강률    조회 실패 ({e})")

    # P3: 쿼리 레이턴시
    try:
        sql = "SELECT count(1) FROM wikimedia_events WHERE timestamp > dateadd('d', -1, now())"
        questdb_json(sql)  # 워밍업
        latencies = []
        for _ in range(10):
            t0 = time.perf_counter()
            questdb_json(sql)
            latencies.append((time.perf_counter() - t0) * 1000)
        p50 = sorted(latencies)[4]
        p99 = sorted(latencies)[-1]
        status = "✅" if p99 <= 200 else "❌"
        lines.append(
            f"[P3]  쿼리 레이턴시   p50={p50:.1f}ms p99={p99:.1f}ms  {status} (목표 p99≤200ms)"
        )
    except Exception as e:
        lines.append(f"[P3]  쿼리 레이턴시   조회 실패 ({e})")

    # CAP1/CAP2: 리소스
    stats = docker_stats_snapshot()
    qdb = next(
        (
            r
            for r in stats
            if "questdb" in r["container"] and "consumer" not in r["container"]
        ),
        None,
    )
    if qdb:
        mem_pct = float(qdb["mem_pct"])
        status = "✅" if mem_pct <= 80 else "❌"
        lines.append(
            f"[CAP1] QDB 메모리     {qdb['mem_usage']:>20s}  {status}"
            f" ({mem_pct:.1f}%, 목표 ≤880MiB)"
        )

    prod = next((r for r in stats if r["container"] == "producer"), None)
    if prod:
        cpu_pct = float(prod["cpu_pct"])
        status = "✅" if cpu_pct <= 70 else "❌"
        lines.append(
            f"[CAP2] Producer CPU  {cpu_pct:8.2f} %           {status} (목표 ≤70%)"
        )

    summary_text = "\n".join(lines)
    out = output_dir / "slo_summary.txt"
    out.write_text(summary_text + "\n", encoding="utf-8")
    print(summary_text)
    print(f"\n  → {out} 저장")


# ── 메인 ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="WikiStreams SLO 데이터 내보내기")
    parser.add_argument(
        "--days",
        type=int,
        default=5,
        help="분석 기간(일). QuestDB TTL=5일이므로 최대 5 (기본값: 5)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="slo_export",
        help="출력 디렉터리 (기본값: ./slo_export)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    days = min(args.days, 5)  # QuestDB TTL=5일

    print("\n🚀 WikiStreams SLO 데이터 내보내기 시작")
    print(f"   기간: 최근 {days}일")
    print(f"   출력: {output_dir.resolve()}\n")

    # QuestDB 기반 (wikimedia_events)
    export_throughput(output_dir, days)
    export_enrichment_hourly(output_dir, days)
    export_by_wiki(output_dir, days)
    export_namespace(output_dir, days)
    export_query_latency(output_dir)

    # QuestDB 기반 (producer_slo_metrics)
    export_batch_processing(output_dir, days)
    export_cache_hitrate(output_dir, days)

    # Docker stats 스냅샷
    export_resources(output_dir)

    # 요약
    print()
    export_summary(output_dir, days)

    print("\n✅ 완료! 파일 목록:")
    for f in sorted(output_dir.iterdir()):
        size_kb = f.stat().st_size / 1024
        print(f"   {f.name:45s} {size_kb:7.1f} KB")


if __name__ == "__main__":
    main()
