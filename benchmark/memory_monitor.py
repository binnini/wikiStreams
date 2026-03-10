#!/usr/bin/env python3
"""
RSS + CPU 시계열 모니터 (Kafka vs Redpanda 벤치마크용)

docker stats를 5초 간격으로 폴링하여 CSV로 저장한다.
load_generator.py와 병렬 실행하여 부하 구간별 메모리 패턴을 수집한다.

사용법:
    # 터미널 1: 부하 생성
    python benchmark/load_generator.py --broker localhost:29092 --label kafka

    # 터미널 2: 메모리 모니터링 (동시 실행)
    python benchmark/memory_monitor.py --container kafka-bench --label kafka

결과:
    benchmark/results/memory_{label}.csv
    컬럼: timestamp, elapsed_sec, label, container, rss_mib, cpu_pct
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def _parse_mem(mem_str: str) -> float:
    """'123.4MiB', '1.2GiB', '512kB' 등 → MiB 변환."""
    s = mem_str.strip()
    if s.endswith("GiB"):
        return float(s[:-3]) * 1024
    if s.endswith("MiB"):
        return float(s[:-3])
    if s.endswith("kB"):
        return float(s[:-2]) / 1024
    if s.endswith("MB"):
        return float(s[:-2])
    if s.endswith("GB"):
        return float(s[:-2]) * 1024
    return 0.0


def get_stats(container: str) -> dict | None:
    """docker stats --no-stream으로 컨테이너 RSS / CPU% 수집."""
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", container],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        data = json.loads(result.stdout.strip())

        # MemUsage: "123.4MiB / 800MiB"
        rss_mib = _parse_mem(data.get("MemUsage", "0MiB / 0").split(" / ")[0])

        # CPUPerc: "5.23%"
        cpu_pct = float(data.get("CPUPerc", "0%").rstrip("%") or 0)

        return {"rss_mib": round(rss_mib, 2), "cpu_pct": round(cpu_pct, 3)}

    except Exception as e:
        print(f"[WARN] docker stats 오류: {e}", file=sys.stderr)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="컨테이너 RSS/CPU 시계열 모니터")
    parser.add_argument("--container", required=True, help="모니터링할 컨테이너 이름")
    parser.add_argument("--label",     required=True, help="출력 파일 레이블 (kafka | redpanda)")
    parser.add_argument("--interval",  type=int, default=5,  help="폴링 간격(초) (기본: 5)")
    parser.add_argument("--duration",  type=int, default=0,
                        help="측정 종료 시간(초). 0이면 Ctrl+C까지 (기본: 0)")
    parser.add_argument("--output-dir", default="benchmark/results")
    args = parser.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    csv_path = Path(args.output_dir) / f"memory_{args.label}.csv"

    print(f"모니터링: {args.container}  간격: {args.interval}s  →  {csv_path}")
    print("종료: Ctrl+C\n")

    start_time = time.monotonic()

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "elapsed_sec", "label", "container", "rss_mib", "cpu_pct"])

        try:
            while True:
                elapsed = int(time.monotonic() - start_time)
                stats = get_stats(args.container)

                if stats:
                    ts = datetime.now().isoformat(timespec="seconds")
                    writer.writerow([ts, elapsed, args.label, args.container,
                                     stats["rss_mib"], stats["cpu_pct"]])
                    f.flush()
                    print(f"  {ts}  elapsed={elapsed:>5}s  "
                          f"RSS={stats['rss_mib']:>7.1f} MiB  CPU={stats['cpu_pct']:>6.2f}%")
                else:
                    print(f"  [{datetime.now().isoformat(timespec='seconds')}]"
                          f" 컨테이너 미응답 (아직 시작 중이거나 종료됨)")

                if args.duration > 0 and elapsed >= args.duration:
                    break

                time.sleep(args.interval)

        except KeyboardInterrupt:
            print("\n중지.")

    print(f"\n저장: {csv_path}")


if __name__ == "__main__":
    main()
