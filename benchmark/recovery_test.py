#!/usr/bin/env python3
"""
재시작 복구 시간 벤치마크: Kafka vs Redpanda

측정 항목:
  docker restart → 컨슈머가 첫 메시지 수신까지 걸린 시간(gap_sec)

SLI-D1 연결:
  데이터 신선도 SLO = 30s.
  - Kafka:    JVM 재시작 20~40s → SLO 위반 가능
  - Redpanda: Rust 재시작 2~5s  → SLO 충분한 여유

사용법:
    python benchmark/recovery_test.py \\
        --broker localhost:29092 --container kafka-bench --label kafka

    python benchmark/recovery_test.py \\
        --broker localhost:29093 --container redpanda-bench --label redpanda

결과:
    benchmark/results/recovery_{label}.csv
    컬럼: label, run, gap_sec, slo_30s_pass
"""

import argparse
import csv
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

TOPIC = "bench.recovery"
DEFAULT_RUNS = 5
WARMUP_SEC = 5          # 재시작 전 기존 메시지 drain
MAX_WAIT_SEC = 120      # 복구 대기 최대 시간
BETWEEN_RUNS_SEC = 15   # 런 간 안정화 대기


def _ensure_topic(broker: str) -> None:
    admin = KafkaAdminClient(bootstrap_servers=[broker], request_timeout_ms=15_000)
    try:
        admin.create_topics([NewTopic(TOPIC, num_partitions=1, replication_factor=1)])
    except TopicAlreadyExistsError:
        pass
    finally:
        admin.close()


def _producer_loop(broker: str, stop_event: threading.Event) -> None:
    """브로커가 올라올 때까지 재연결을 반복하며 메시지를 계속 전송한다.
    future.get() 대신 flush() + 콜백 방식으로 블로킹 타임아웃 이슈를 회피.
    """
    seq = 0
    while not stop_event.is_set():
        try:
            producer = KafkaProducer(
                bootstrap_servers=[broker],
                acks="all",
                linger_ms=0,
                batch_size=1,
                request_timeout_ms=30_000,
                max_block_ms=10_000,
            )
            while not stop_event.is_set():
                payload = json.dumps({"seq": seq, "ts": time.time()}).encode()
                producer.send(TOPIC, value=payload)
                producer.flush(timeout=10)  # 콜백 방식 — 내부적으로 전송 완료까지 대기
                seq += 1
                time.sleep(0.2)
            producer.close()
            return
        except Exception:
            time.sleep(1)


def measure_one_run(broker: str, container: str) -> float:
    """
    1회 복구 시간 측정.
    Returns: gap_sec (restart → 첫 메시지 수신)
    """
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=[broker],
        group_id=f"bench-recovery-{time.time_ns()}",
        auto_offset_reset="latest",
        enable_auto_commit=True,
        # consumer_timeout_ms 미설정: next() 사용 안 함, poll() 방식 사용
    )

    # 워밍업: 기존 메시지 drain
    deadline = time.monotonic() + WARMUP_SEC
    while time.monotonic() < deadline:
        consumer.poll(timeout_ms=500)

    # 컨테이너 재시작
    restart_time = time.monotonic()
    print(f"    {container} 재시작...", end="", flush=True)
    result = subprocess.run(
        ["docker", "restart", container],
        capture_output=True, timeout=60,
    )
    if result.returncode != 0:
        print(f" 실패: {result.stderr.decode().strip()}")
        consumer.close()
        return float("nan")
    print(" 완료", flush=True)

    # 재시작 직후 프로듀서 스레드 가동 (브로커가 올라오면 자동 재연결)
    stop_event = threading.Event()
    producer_thread = threading.Thread(
        target=_producer_loop,
        args=(broker, stop_event),
        daemon=True,
    )
    producer_thread.start()

    # 첫 메시지 수신 대기 (poll() 방식 — 재연결 후에도 계속 동작)
    first_msg_time = None
    deadline = time.monotonic() + MAX_WAIT_SEC

    while time.monotonic() < deadline:
        records = consumer.poll(timeout_ms=1_000)
        if records:
            first_msg_time = time.monotonic()
            break

    stop_event.set()
    consumer.close()

    if first_msg_time is None:
        print(f"    [WARN] {MAX_WAIT_SEC}s 내 메시지 수신 없음")
        return float("nan")

    return first_msg_time - restart_time


def main() -> None:
    parser = argparse.ArgumentParser(description="브로커 재시작 복구 시간 벤치마크")
    parser.add_argument("--broker",    required=True, help="Bootstrap server (host:port)")
    parser.add_argument("--container", required=True, help="재시작할 컨테이너 이름")
    parser.add_argument("--label",     required=True, help="출력 파일 레이블 (kafka | redpanda)")
    parser.add_argument("--runs",      type=int, default=DEFAULT_RUNS, help=f"반복 횟수 (기본: {DEFAULT_RUNS})")
    parser.add_argument("--output-dir", default="benchmark/results")
    args = parser.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    csv_path = Path(args.output_dir) / f"recovery_{args.label}.csv"

    print(f"\n=== 재시작 복구 벤치마크: {args.label} ===")
    print(f"컨테이너: {args.container}  브로커: {args.broker}  런: {args.runs}회\n")

    # 브로커 준비 대기 + 토픽 생성
    print("브로커 연결 대기 중", end="", flush=True)
    for _ in range(20):
        try:
            _ensure_topic(args.broker)
            print(" 완료\n")
            break
        except Exception:
            print(".", end="", flush=True)
            time.sleep(3)
    else:
        print("\n[ERROR] 브로커 연결 실패")
        return

    gaps: list[float] = []

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["label", "run", "gap_sec", "slo_30s_pass"])

        for i in range(1, args.runs + 1):
            print(f"  Run {i}/{args.runs}")
            if i > 1:
                print(f"    {BETWEEN_RUNS_SEC}초 안정화 대기...")
                time.sleep(BETWEEN_RUNS_SEC)

            gap = measure_one_run(args.broker, args.container)
            gaps.append(gap)

            slo_pass = not (gap != gap) and gap <= 30.0  # NaN 처리 포함
            writer.writerow([args.label, i, round(gap, 2) if gap == gap else "NaN", slo_pass])
            f.flush()

            status = "✅" if slo_pass else "❌"
            gap_str = f"{gap:.2f}s" if gap == gap else "NaN"
            print(f"    복구 gap: {gap_str}  SLO(30s): {status}\n")

    # 요약
    valid = [g for g in gaps if g == g]  # NaN 제외
    if valid:
        avg = sum(valid) / len(valid)
        max_gap = max(valid)
        slo_ok = sum(g <= 30 for g in valid)
        print(f"=== 결과: {args.label} ===")
        print(f"  avg={avg:.2f}s  max={max_gap:.2f}s  "
              f"SLO(30s) 통과={slo_ok}/{len(valid)}")

    print(f"\n저장: {csv_path}")


if __name__ == "__main__":
    main()
