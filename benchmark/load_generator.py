#!/usr/bin/env python3
"""
Send Latency Benchmark: Kafka vs Redpanda

Producer → Broker ACK 왕복 지연(send latency)을 측정한다.
측정 지표: p50 / p95 / p99 / p999 (ms), 처리율(msg/sec)

사용법:
    pip install -r benchmark/requirements.txt

    # Kafka 벤치마크 (기본 30분 × 3구간)
    python benchmark/load_generator.py --broker localhost:29092 --label kafka

    # Redpanda 벤치마크
    python benchmark/load_generator.py --broker localhost:29093 --label redpanda

    # 빠른 테스트 (60초)
    python benchmark/load_generator.py --broker localhost:29092 --label kafka --duration 60

결과: benchmark/results/latency_{label}.csv
"""

import argparse
import csv
import json
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path

from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

TOPIC = "bench.latency"
DEFAULT_RATES = [18, 50, 200]   # msg/sec
DEFAULT_DURATION = 1800         # 30분


def _make_payload(seq: int) -> bytes:
    """WikimediaEvent와 유사한 합성 페이로드."""
    return json.dumps({
        "title": f"Test_Page_{seq % 10_000}",
        "server_name": "en.wikipedia.org",
        "type": "edit",
        "namespace": 0,
        "timestamp": int(time.time()),
        "user": f"user_{seq % 100}",
        "bot": False,
        "seq": seq,
    }).encode()


def _ensure_topic(broker: str) -> None:
    admin = KafkaAdminClient(bootstrap_servers=[broker], request_timeout_ms=10_000)
    try:
        admin.create_topics([NewTopic(TOPIC, num_partitions=1, replication_factor=1)])
        print(f"  토픽 생성: {TOPIC}")
    except TopicAlreadyExistsError:
        pass
    finally:
        admin.close()


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return float("nan")
    sorted_data = sorted(data)
    idx = min(int(len(sorted_data) * p / 100), len(sorted_data) - 1)
    return sorted_data[idx]


def run_rate(broker: str, rate: int, duration_sec: int) -> list[float]:
    """
    고정 rate(msg/sec)로 duration_sec 동안 메시지를 전송하고,
    각 메시지의 produce → ACK 지연(ms) 리스트를 반환한다.
    """
    latencies: list[float] = []
    pending: dict[int, float] = {}  # seq → send_time
    lock = threading.Lock()

    def make_callback(seq_id: int):
        def on_send_success(_metadata):
            recv_time = time.perf_counter()
            with lock:
                send_time = pending.pop(seq_id, None)
            if send_time is not None:
                latencies.append((recv_time - send_time) * 1000)
        return on_send_success

    producer = KafkaProducer(
        bootstrap_servers=[broker],
        acks="all",
        linger_ms=0,        # 배치 지연 없음 — 단건 latency 측정
        batch_size=1,       # 배치 비활성화
        request_timeout_ms=30_000,
        max_block_ms=30_000,
    )

    interval = 1.0 / rate
    seq = 0
    start = time.monotonic()
    print(f"  {rate} msg/sec × {duration_sec}s 측정 중...", flush=True)

    while time.monotonic() - start < duration_sec:
        tick = time.perf_counter()
        with lock:
            pending[seq] = tick

        producer.send(
            TOPIC,
            key=str(seq).encode(),
            value=_make_payload(seq),
        ).add_callback(make_callback(seq)).add_errback(
            lambda e: None  # 오류 무시 (통계에서 제외)
        )

        seq += 1

        # 레이트 제어: 구간 잔여 시간만큼 sleep
        elapsed = time.perf_counter() - tick
        wait = interval - elapsed
        if wait > 0:
            time.sleep(wait)

    producer.flush(timeout=30)
    producer.close()
    return latencies


def main() -> None:
    parser = argparse.ArgumentParser(description="Kafka/Redpanda send latency 벤치마크")
    parser.add_argument("--broker", required=True, help="Bootstrap server (host:port)")
    parser.add_argument("--label", required=True, help="출력 파일 레이블 (kafka | redpanda)")
    parser.add_argument("--rates", nargs="+", type=int, default=DEFAULT_RATES,
                        help=f"측정 처리율 목록 (기본: {DEFAULT_RATES})")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"구간당 측정 시간(초) (기본: {DEFAULT_DURATION})")
    parser.add_argument("--output-dir", default="benchmark/results")
    args = parser.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    csv_path = Path(args.output_dir) / f"latency_{args.label}.csv"

    print(f"\n=== Send Latency Benchmark: {args.label} ({args.broker}) ===")
    print(f"레이트: {args.rates} msg/sec | 구간: {args.duration}s | 시작: {datetime.now():%Y-%m-%d %H:%M:%S}\n")

    # 브로커 준비 대기
    print("브로커 연결 대기 중", end="", flush=True)
    for _ in range(30):
        try:
            _ensure_topic(args.broker)
            print(" 완료\n")
            break
        except Exception:
            print(".", end="", flush=True)
            time.sleep(2)
    else:
        print("\n[ERROR] 60초 내 브로커 연결 실패")
        return

    summary_rows = []

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["label", "rate", "count", "p50_ms", "p95_ms", "p99_ms", "p999_ms", "mean_ms"])

        for rate in args.rates:
            latencies = run_rate(args.broker, rate, args.duration)
            if not latencies:
                print(f"  [WARN] {rate} msg/sec — 수집된 데이터 없음")
                continue

            row = {
                "label":    args.label,
                "rate":     rate,
                "count":    len(latencies),
                "p50_ms":   round(_percentile(latencies, 50),   3),
                "p95_ms":   round(_percentile(latencies, 95),   3),
                "p99_ms":   round(_percentile(latencies, 99),   3),
                "p999_ms":  round(_percentile(latencies, 99.9), 3),
                "mean_ms":  round(statistics.mean(latencies),   3),
            }
            writer.writerow(list(row.values()))
            f.flush()
            summary_rows.append(row)

            print(f"\n  [{args.label}] {rate} msg/sec — {len(latencies):,}건")
            print(f"    p50={row['p50_ms']}ms  p95={row['p95_ms']}ms  "
                  f"p99={row['p99_ms']}ms  p999={row['p999_ms']}ms")

    print(f"\n결과 저장: {csv_path}")
    print("\n=== 요약 ===")
    print(f"{'Rate':>8} {'Count':>8} {'p50':>8} {'p95':>8} {'p99':>8} {'p999':>9}")
    for row in summary_rows:
        print(f"{row['rate']:>8} {row['count']:>8} {row['p50_ms']:>8} "
              f"{row['p95_ms']:>8} {row['p99_ms']:>8} {row['p999_ms']:>9}")


if __name__ == "__main__":
    main()
