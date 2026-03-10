#!/usr/bin/env python3
"""
ClickHouse vs QuestDB Cold Read Benchmark — 실행기

측정 조건:
  DB    : clickhouse (t4g.medium 시뮬레이션) vs questdb (t3.small 현재 설정)
  범위  : recent (마지막 1일) vs old (첫 번째 1일, 4~5일 전)
  쿼리  : Q1(집계) / Q3(GROUP BY) / Q5(서브쿼리+ilike)
  모드  : cold (캐시 초기화 후 측정) vs warm (캐시 적재 후 N회)
  반복  : N=10

캐시 초기화:
  ClickHouse — SYSTEM DROP MARK CACHE + SYSTEM DROP UNCOMPRESSED CACHE (HTTP)
  QuestDB    — sudo purge (macOS OS page cache 초기화, sudo 필요)

사용법:
    python benchmark/runner.py

    # 특정 DB만
    python benchmark/runner.py --db questdb

    # 빠른 테스트 (N=3)
    python benchmark/runner.py --n 3

결과:
    benchmark/results/cold_read_{YYYYMMDD_HHMMSS}.csv
"""

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from queries import QUERIES

# ── 접속 설정 ──────────────────────────────────────────────────────────────
CH_HTTP_URL = "http://localhost:28123"
QDB_REST_URL = "http://localhost:9000"

# ── 기본값 ─────────────────────────────────────────────────────────────────
N_RUNS = 10
SLO_THRESHOLD_S = 2.0  # SLO: 쿼리 응답 2초 이내


# ── DB 쿼리 실행 ───────────────────────────────────────────────────────────


def _run_clickhouse(sql: str) -> float:
    """ClickHouse HTTP API로 쿼리 실행 후 wall time(초) 반환."""
    url = f"{CH_HTTP_URL}/?query={urllib.parse.quote(sql)}"
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ClickHouse 쿼리 실패: {e.read().decode()[:300]}") from e
    return time.perf_counter() - t0


def _run_questdb(sql: str) -> float:
    """QuestDB REST API로 쿼리 실행 후 wall time(초) 반환."""
    params = urllib.parse.urlencode({"query": sql, "fmt": "json"})
    url = f"{QDB_REST_URL}/exec?{params}"
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            body = json.loads(resp.read())
            if "error" in body:
                raise RuntimeError(f"QuestDB 쿼리 오류: {body['error']}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"QuestDB 쿼리 실패: {e.read().decode()[:300]}") from e
    return time.perf_counter() - t0


# ── 캐시 초기화 ────────────────────────────────────────────────────────────


def _flush_clickhouse_cache():
    """ClickHouse LRU 캐시 초기화 (mark cache + uncompressed cache). POST 필요."""
    for cmd in [
        "SYSTEM DROP MARK CACHE",
        "SYSTEM DROP UNCOMPRESSED CACHE",
    ]:
        req = urllib.request.Request(
            CH_HTTP_URL + "/",
            data=cmd.encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()


def _flush_os_page_cache() -> bool:
    """macOS OS page cache 초기화 (sudo purge). 실패 시 False 반환."""
    try:
        result = subprocess.run(
            ["sudo", "purge"],
            timeout=30,
            capture_output=True,
        )
        if result.returncode != 0:
            print(
                f"  [경고] sudo purge 실패 (returncode={result.returncode}): "
                f"{result.stderr.decode().strip()[:100]}",
                file=sys.stderr,
            )
            return False
        return True
    except FileNotFoundError:
        print(
            "  [경고] purge 명령어 없음 (macOS 전용). cold QuestDB 결과가 warm일 수 있음.",
            file=sys.stderr,
        )
        return False
    except subprocess.TimeoutExpired:
        print("  [경고] sudo purge 타임아웃.", file=sys.stderr)
        return False


# ── 퍼센타일 계산 ──────────────────────────────────────────────────────────


def _percentiles(times: list[float]) -> dict:
    sorted_t = sorted(times)
    n = len(sorted_t)
    return {
        "p50": sorted_t[int(n * 0.50)],
        "p95": sorted_t[int(n * 0.95)],
        "p99": sorted_t[min(int(n * 0.99), n - 1)],
        "mean": statistics.mean(times),
        "min": min(times),
        "max": max(times),
    }


# ── 단일 조건 측정 ─────────────────────────────────────────────────────────


def _measure(
    db: str,
    query_name: str,
    sql: str,
    mode: str,
    n: int,
    purge_ok: bool,
) -> dict:
    """
    한 (db × query × mode) 조합을 N회 측정.
    cold 모드: 각 실행 전에 캐시 플러시.
    warm 모드: 1회 웜업 후 N회 측정.
    """
    run_fn = _run_clickhouse if db == "clickhouse" else _run_questdb
    flush_fn = _flush_clickhouse_cache if db == "clickhouse" else _flush_os_page_cache

    if mode == "warm":
        # 웜업
        run_fn(sql)

    times = []
    for i in range(n):
        if mode == "cold":
            flushed = flush_fn()
            if not flushed and db == "questdb":
                print(f"  [주의] OS 캐시 미초기화 상태로 cold 측정 (run {i+1}/{n})")

        elapsed = run_fn(sql)
        times.append(elapsed)
        print(f"    {db} | {query_name} | {mode} | run {i+1:>2}/{n}: {elapsed:.3f}s")

    stats = _percentiles(times)
    slo_pass = stats["p95"] <= SLO_THRESHOLD_S
    return {
        "times": times,
        "stats": stats,
        "slo_pass": slo_pass,
    }


# ── 메인 ───────────────────────────────────────────────────────────────────


def run(dbs: list[str], n: int):
    # 메타 로드
    meta_path = Path(__file__).parent / "results" / "bench_meta.json"
    if not meta_path.exists():
        print(
            f"[오류] {meta_path} 없음. data_generator.py를 먼저 실행하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    meta = json.loads(meta_path.read_text())
    t_start: int = meta["t_start"]
    t_end: int = meta["t_end"]

    # 시간 범위 정의
    ranges = {
        "recent": (t_end - 86400, t_end),  # 마지막 1일
        "old": (t_start, t_start + 86400),  # 첫 번째 1일 (4~5일 전)
    }

    print("\n=== ClickHouse vs QuestDB Cold Read Benchmark ===")
    print(
        f"데이터 범위: {datetime.fromtimestamp(t_start, tz=timezone.utc).strftime('%Y-%m-%d')} "
        f"~ {datetime.fromtimestamp(t_end, tz=timezone.utc).strftime('%Y-%m-%d')}"
    )
    print(f"DB: {', '.join(dbs)} | 쿼리: Q1/Q3/Q5 | 반복: N={n}\n")

    # sudo purge 사용 가능 여부 사전 확인
    purge_ok = True
    if "questdb" in dbs:
        print("sudo purge 테스트 중...")
        purge_ok = _flush_os_page_cache()
        if purge_ok:
            print("  sudo purge 사용 가능 ✅")
        else:
            print("  sudo purge 불가 — cold QuestDB 결과는 참고용\n")

    # 결과 수집
    results = []

    for db in dbs:
        for range_name, (ts, te) in ranges.items():
            for query_name, query_def in QUERIES.items():
                sql_fn = query_def[db]
                sql = sql_fn(ts, te)
                label = query_def["label"]

                for mode in ("cold", "warm"):
                    print(
                        f"\n[{db.upper()}] {query_name}({label}) | {range_name} | {mode}"
                    )
                    result = _measure(db, query_name, sql, mode, n, purge_ok)
                    st = result["stats"]
                    slo = "✅" if result["slo_pass"] else "❌"
                    print(
                        f"  → p50={st['p50']:.3f}s  p95={st['p95']:.3f}s  "
                        f"p99={st['p99']:.3f}s  mean={st['mean']:.3f}s  "
                        f"SLO(p95≤{SLO_THRESHOLD_S}s) {slo}"
                    )

                    results.append(
                        {
                            "db": db,
                            "range": range_name,
                            "query": query_name,
                            "query_label": label,
                            "mode": mode,
                            "n": n,
                            "p50": round(st["p50"], 4),
                            "p95": round(st["p95"], 4),
                            "p99": round(st["p99"], 4),
                            "mean": round(st["mean"], 4),
                            "min": round(st["min"], 4),
                            "max": round(st["max"], 4),
                            "slo_pass": result["slo_pass"],
                            "raw_times": ",".join(f"{t:.4f}" for t in result["times"]),
                        }
                    )

    # CSV 저장
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = results_dir / f"cold_read_{ts_str}.csv"

    fieldnames = [
        "db",
        "range",
        "query",
        "query_label",
        "mode",
        "n",
        "p50",
        "p95",
        "p99",
        "mean",
        "min",
        "max",
        "slo_pass",
        "raw_times",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print("\n\n=== 결과 요약 (p95, SLO 2s) ===")
    print(
        f"{'DB':<12} {'Range':<8} {'Query':<4} {'Mode':<6} {'p50':>7} {'p95':>7} {'p99':>7} {'SLO'}"
    )
    print("-" * 65)
    for r in results:
        slo = "✅" if r["slo_pass"] else "❌"
        print(
            f"{r['db']:<12} {r['range']:<8} {r['query']:<4} {r['mode']:<6} "
            f"{r['p50']:>7.3f} {r['p95']:>7.3f} {r['p99']:>7.3f} {slo}"
        )

    print(f"\n결과 저장: {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ClickHouse vs QuestDB Cold Read 벤치마크"
    )
    parser.add_argument(
        "--db",
        choices=["both", "clickhouse", "questdb"],
        default="both",
        help="측정 대상 DB (기본: both)",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=N_RUNS,
        help=f"반복 횟수 (기본: {N_RUNS})",
    )
    args = parser.parse_args()

    db_list = ["clickhouse", "questdb"] if args.db == "both" else [args.db]
    run(db_list, args.n)
