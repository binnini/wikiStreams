#!/usr/bin/env python3
"""
ClickHouse vs QuestDB Cold Read Benchmark — 데이터 생성기

합성 5일치 ~780만 건 (18 events/sec)을 ClickHouse와 QuestDB에 주입한다.

사용법:
    # 양쪽 DB 모두 주입 (기본)
    python benchmark/data_generator.py

    # ClickHouse만
    python benchmark/data_generator.py --target clickhouse

    # QuestDB만
    python benchmark/data_generator.py --target questdb

    # 빠른 테스트 (1일치만)
    python benchmark/data_generator.py --days 1

사전 조건:
    # ClickHouse 벤치마크 컨테이너 기동
    docker compose -f benchmark/docker-compose.bench.yml up -d

    # QuestDB는 기존 운영 컨테이너 사용 (포트 9009 ILP, 9000 REST)

결과:
    benchmark/results/bench_meta.json — 주입된 시간 범위 (runner.py가 참조)
"""

import argparse
import gzip
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── 접속 설정 ──────────────────────────────────────────────────────────────
CH_HTTP_URL = "http://localhost:28123"
QDB_REST_URL = "http://localhost:9000"

# ── 데이터 규모 ────────────────────────────────────────────────────────────
EVENTS_PER_SEC = 18
DAYS = 5
TOTAL_EVENTS = EVENTS_PER_SEC * 86400 * DAYS   # ~7,776,000
BATCH_SIZE = 10_000       # ClickHouse
QDB_BATCH_SIZE = 1_000    # QuestDB — mmap 메모리 압박 완화

# ── 합성 데이터 풀 ─────────────────────────────────────────────────────────
_SERVERS = [
    "en.wikipedia.org", "de.wikipedia.org", "fr.wikipedia.org",
    "es.wikipedia.org", "ja.wikipedia.org", "ru.wikipedia.org",
    "it.wikipedia.org", "zh.wikipedia.org", "pt.wikipedia.org",
    "www.wikidata.org",
]
_SERVER_WEIGHTS = [50, 10, 8, 7, 6, 5, 4, 3, 3, 4]

_WIKI_TYPES = ["edit", "new", "categorize"]
_WIKI_TYPE_WEIGHTS = [80, 15, 5]

_NAMESPACES = [0, 1, 4, 14]
_NS_WEIGHTS = [85, 5, 5, 5]

_HUMAN_USERS = [f"User_{i:04d}" for i in range(500)]
_BOT_USERS = [f"Bot_{i:03d}" for i in range(100)]

# 500개 타이틀 — 앞 50개는 인기 페이지(더 자주 편집됨)
_TITLES_POPULAR = [f"Popular_Page_{i:03d}" for i in range(50)]
_TITLES_LONG_TAIL = [f"Page_{i:04d}" for i in range(450)]
_TITLES = _TITLES_POPULAR + _TITLES_LONG_TAIL
_TITLE_WEIGHTS = [10] * 50 + [1] * 450  # 인기 페이지 10배 확률

_COMMENTS = (
    [""] * 60
    + ["Reverted edits by user"] * 8
    + ["Undid revision"] * 7
    + ["/* section */ minor edit"] * 10
    + ["Added content"] * 8
    + ["Fixed typo"] * 7
)

# Wikidata 레이블: 30% 페이지에만 존재
_WD_LABELS = {
    f"Popular_Page_{i:03d}": f"Wikidata Label {i}"
    for i in range(30)
}
_WD_DESCS = {
    f"Popular_Page_{i:03d}": f"Short description for entity {i}"
    for i in range(20)
}


# ── QuestDB 테이블 생성 ────────────────────────────────────────────────────
_QDB_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS bench_events (
    server_name SYMBOL,
    wiki_type   SYMBOL,
    title       STRING,
    "user"      STRING,
    bot         BOOLEAN,
    namespace   INT,
    minor       BOOLEAN,
    comment     STRING,
    wikidata_label       STRING,
    wikidata_description STRING,
    timestamp   TIMESTAMP
) timestamp(timestamp) PARTITION BY DAY;\
"""


def _qdb_create_table():
    params = urllib.parse.urlencode({"query": _QDB_CREATE_SQL})
    url = f"{QDB_REST_URL}/exec?{params}"
    for attempt in range(10):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = json.loads(resp.read())
                if "error" in body:
                    print(f"  QuestDB 테이블 생성 오류: {body['error']}", file=sys.stderr)
                else:
                    print("  QuestDB bench_events 테이블 준비 완료")
                return
        except Exception as e:
            print(f"  QuestDB 연결 재시도 ({attempt+1}/10): {e}", file=sys.stderr)
            time.sleep(3)
    raise RuntimeError("QuestDB REST API 연결 실패")


# ── ClickHouse 초기화 확인 ─────────────────────────────────────────────────
def _ch_ping():
    for attempt in range(20):
        try:
            with urllib.request.urlopen(f"{CH_HTTP_URL}/ping", timeout=5) as resp:
                if resp.status == 200:
                    print("  ClickHouse bench 컨테이너 준비 완료")
                    return
        except Exception:
            pass
        print(f"  ClickHouse 연결 대기 ({attempt+1}/20)...", file=sys.stderr)
        time.sleep(3)
    raise RuntimeError("ClickHouse bench 컨테이너 연결 실패 (docker compose up 확인)")


# ── 이벤트 생성 ────────────────────────────────────────────────────────────
def _make_event(rng: random.Random, ts: int) -> dict:
    title = rng.choices(_TITLES, weights=_TITLE_WEIGHTS)[0]
    is_bot = rng.random() < 0.20
    user = rng.choice(_BOT_USERS if is_bot else _HUMAN_USERS)
    return {
        "server_name": rng.choices(_SERVERS, weights=_SERVER_WEIGHTS)[0],
        "wiki_type": rng.choices(_WIKI_TYPES, weights=_WIKI_TYPE_WEIGHTS)[0],
        "title": title,
        "user": user,
        "bot": is_bot,
        "namespace": rng.choices(_NAMESPACES, weights=_NS_WEIGHTS)[0],
        "minor": rng.random() < 0.15,
        "comment": rng.choice(_COMMENTS),
        "wikidata_label": _WD_LABELS.get(title, ""),
        "wikidata_description": _WD_DESCS.get(title, ""),
        "ts": ts,  # Unix seconds
    }


# ── ILP 포맷 (QuestDB) ─────────────────────────────────────────────────────
def _tag(v: str) -> str:
    return v.replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def _str(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")


def _to_ilp(evt: dict) -> str:
    ts_ns = evt["ts"] * 1_000_000_000
    bot = "t" if evt["bot"] else "f"
    minor = "t" if evt["minor"] else "f"
    return (
        f"bench_events,server_name={_tag(evt['server_name'])},wiki_type={_tag(evt['wiki_type'])} "
        f'title="{_str(evt["title"])}",'
        f'user="{_str(evt["user"])}",'
        f"bot={bot},"
        f"namespace={evt['namespace']}i,"
        f"minor={minor},"
        f'comment="{_str(evt["comment"])}",'
        f'wikidata_label="{_str(evt["wikidata_label"])}",'
        f'wikidata_description="{_str(evt["wikidata_description"])}" '
        f"{ts_ns}\n"
    )


# ── JSON 포맷 (ClickHouse) ─────────────────────────────────────────────────
def _to_ch_json(evt: dict) -> str:
    dt = datetime.fromtimestamp(evt["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return json.dumps({
        "event_time": dt,
        "title": evt["title"],
        "server_name": evt["server_name"],
        "wiki_type": evt["wiki_type"],
        "namespace": evt["namespace"],
        "user": evt["user"],
        "bot": 1 if evt["bot"] else 0,
        "minor": 1 if evt["minor"] else 0,
        "comment": evt["comment"],
        "wikidata_label": evt["wikidata_label"],
        "wikidata_description": evt["wikidata_description"],
    }, ensure_ascii=False)


# ── ClickHouse 배치 INSERT ─────────────────────────────────────────────────
def _ch_insert(rows: list[str]):
    body = "\n".join(rows).encode("utf-8")
    compressed = gzip.compress(body, compresslevel=1)
    url = f"{CH_HTTP_URL}/?query=INSERT+INTO+bench.events+FORMAT+JSONEachRow"
    req = urllib.request.Request(
        url,
        data=compressed,
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ClickHouse INSERT 실패: {e.read().decode()[:200]}") from e


# ── QuestDB 배치 ILP (HTTP /write — TCP 9009 미노출 시 대안) ───────────────
def _qdb_ilp_http(lines: list[str], retries: int = 5):
    """QuestDB HTTP ILP endpoint (POST /write) — 포트 9000 사용."""
    body = "".join(lines).encode("utf-8")
    url = f"{QDB_REST_URL}/write"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "text/plain"},
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp.read()
            return
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"QuestDB ILP HTTP 실패: {e.read().decode()[:200]}") from e
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"\n  [QuestDB] ILP 재시도 ({attempt+1}/{retries}): {e} — {wait}s 대기", file=sys.stderr)
                time.sleep(wait)
            else:
                raise RuntimeError(f"QuestDB ILP 최종 실패: {e}") from e


# ── 메인 ───────────────────────────────────────────────────────────────────
def generate(target: str, days: int):
    total = EVENTS_PER_SEC * 86400 * days
    rng = random.Random(42)  # 재현 가능성

    t_end = int(time.time())
    t_start = t_end - days * 86400

    print(f"\n데이터 범위: {datetime.fromtimestamp(t_start, tz=timezone.utc).isoformat()} "
          f"~ {datetime.fromtimestamp(t_end, tz=timezone.utc).isoformat()}")
    print(f"총 이벤트: {total:,}건 ({days}일 × 18 events/sec)")

    do_ch = target in ("both", "clickhouse")
    do_qdb = target in ("both", "questdb")

    if do_ch:
        print("\n[ClickHouse] 연결 확인...")
        _ch_ping()

    if do_qdb:
        print("\n[QuestDB] 테이블 준비...")
        _qdb_create_table()

    # 균등 분포 타임스탬프 생성 (1초 단위로 18건씩)
    timestamps = []
    for sec in range(t_start, t_end):
        timestamps.extend([sec] * EVENTS_PER_SEC)

    # 순서 셔플 (랜덤 도착 시뮬레이션)
    rng.shuffle(timestamps)
    timestamps = timestamps[:total]

    ch_batch: list[str] = []
    qdb_batch: list[str] = []
    inserted = 0
    t0 = time.time()

    for ts in timestamps:
        evt = _make_event(rng, ts)

        if do_ch:
            ch_batch.append(_to_ch_json(evt))
        if do_qdb:
            qdb_batch.append(_to_ilp(evt))

        inserted += 1

        if do_qdb and len(qdb_batch) >= QDB_BATCH_SIZE:
            _qdb_ilp_http(qdb_batch)
            qdb_batch.clear()

        if inserted % BATCH_SIZE == 0:
            if do_ch:
                _ch_insert(ch_batch)
                ch_batch.clear()

            elapsed = time.time() - t0
            pct = 100 * inserted / total
            rps = inserted / elapsed
            eta = (total - inserted) / rps if rps > 0 else 0
            print(
                f"  {pct:5.1f}% | {inserted:>8,}/{total:,} "
                f"| {rps:,.0f} rows/s | ETA {eta:.0f}s",
                end="\r",
            )

    # 남은 배치 플러시
    if ch_batch and do_ch:
        _ch_insert(ch_batch)
    if qdb_batch and do_qdb:
        _qdb_ilp_http(qdb_batch)
        time.sleep(2)  # ILP 버퍼 플러시 대기

    elapsed = time.time() - t0
    print(f"\n\n완료: {inserted:,}건 주입, {elapsed:.1f}초 ({inserted/elapsed:,.0f} rows/s)")

    # 메타 저장
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    meta = {
        "t_start": t_start,
        "t_end": t_end,
        "days": days,
        "row_count": inserted,
        "target": target,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = results_dir / "bench_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"메타 저장: {meta_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ClickHouse vs QuestDB 벤치마크 데이터 생성기")
    parser.add_argument(
        "--target",
        choices=["both", "clickhouse", "questdb"],
        default="both",
        help="데이터 주입 대상 (기본: both)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DAYS,
        help=f"생성할 일수 (기본: {DAYS})",
    )
    args = parser.parse_args()
    generate(args.target, args.days)
