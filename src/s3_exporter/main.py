"""
S3 Datalake Exporter — WikiStreams

QuestDB wikimedia_events 전일 데이터를 Parquet(Snappy)으로 변환하여 S3에 저장합니다.

저장 경로:
    s3://{S3_BUCKET}/{S3_PREFIX}/year=YYYY/month=MM/day=DD/events.parquet

실행 방법:
    # 데몬 모드 (매일 01:00 UTC 자동 실행)
    docker compose --profile s3 up -d s3-exporter

    # 수동 일회성 실행 (전일)
    docker exec s3-exporter python main.py --once

    # 특정 날짜 백필
    docker exec -e EXPORT_DATE=2026-03-01 s3-exporter python main.py --once

    # 이미 존재하는 파일 강제 덮어쓰기
    docker exec s3-exporter python main.py --once --force

과거 데이터 조회 (DuckDB):
    duckdb -c "SELECT server_name, count(*) FROM read_parquet('s3://bucket/events/**/*.parquet') GROUP BY 1"
"""

import io
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import boto3
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - [s3-exporter] - %(message)s",
)

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "questdb")
QUESTDB_REST_PORT = int(os.getenv("QUESTDB_REST_PORT", "9000"))

S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_PREFIX = os.getenv("S3_PREFIX", "events")
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")

EXPORT_DATE = os.getenv("EXPORT_DATE", "")  # YYYY-MM-DD, 미설정 시 전일

# Parquet 스키마 (QuestDB wikimedia_events 테이블과 일치)
_SCHEMA = pa.schema([
    ("server_name", pa.string()),
    ("wiki_type", pa.string()),
    ("title", pa.string()),
    ("user", pa.string()),
    ("bot", pa.bool_()),
    ("namespace", pa.int32()),
    ("minor", pa.bool_()),
    ("comment", pa.string()),
    ("wikidata_label", pa.string()),
    ("wikidata_description", pa.string()),
    ("timestamp", pa.timestamp("us", tz="UTC")),
])


def _s3_key(target: date) -> str:
    """Hive 파티셔닝 경로 생성."""
    return (
        f"{S3_PREFIX}/"
        f"year={target.year:04d}/"
        f"month={target.month:02d}/"
        f"day={target.day:02d}/"
        f"events.parquet"
    )


def _s3_exists(s3_client, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def _fetch_csv(target: date) -> bytes:
    """QuestDB /exp endpoint로 하루치 CSV 다운로드 (스트리밍)."""
    start = f"{target}T00:00:00.000000Z"
    end = f"{target + timedelta(days=1)}T00:00:00.000000Z"
    sql = (
        'SELECT server_name, wiki_type, title, "user", bot, namespace, minor, '
        "comment, wikidata_label, wikidata_description, timestamp "
        "FROM wikimedia_events "
        f"WHERE timestamp >= '{start}' AND timestamp < '{end}'"
    )
    params = urllib.parse.urlencode({"query": sql})
    url = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exp?{params}"
    logging.info("QuestDB 쿼리 시작: %s", target)
    with urllib.request.urlopen(url, timeout=300) as resp:
        data = resp.read()
    return data


def _csv_to_parquet(csv_bytes: bytes) -> bytes:
    """CSV bytes → Parquet bytes (Snappy 압축)."""
    convert_options = pcsv.ConvertOptions(
        column_types={
            "bot": pa.bool_(),
            "minor": pa.bool_(),
            "namespace": pa.int32(),
        },
        null_values=["", "null", "NULL"],
        strings_can_be_null=True,
        timestamp_parsers=[],  # auto-detect 비활성화 → timestamp 컬럼을 string으로 읽음
    )
    table = pcsv.read_csv(io.BytesIO(csv_bytes), convert_options=convert_options)

    # "2026-03-10T14:10:05.000000Z" → timestamp[us, UTC]
    idx = table.schema.get_field_index("timestamp")
    ts_col = pc.strptime(table.column("timestamp"), format="%Y-%m-%dT%H:%M:%S.%fZ", unit="us")
    ts_col = pc.assume_timezone(ts_col, timezone="UTC")
    table = table.set_column(idx, "timestamp", ts_col)

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy", schema=_SCHEMA)
    return buf.getvalue()


def export(target: date, force: bool = False) -> None:
    """단일 날짜 데이터를 S3에 Parquet으로 내보냅니다."""
    if not S3_BUCKET:
        logging.error("S3_BUCKET 환경변수 미설정 — 종료")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=AWS_REGION)
    key = _s3_key(target)

    if not force and _s3_exists(s3, key):
        logging.info("이미 존재함 (건너뜀): s3://%s/%s", S3_BUCKET, key)
        return

    # 1. QuestDB에서 CSV 다운로드
    csv_bytes = _fetch_csv(target)
    row_count = max(0, csv_bytes.count(b"\n") - 1)  # 헤더 제외
    logging.info("CSV 다운로드 완료: %d rows / %d bytes", row_count, len(csv_bytes))

    if row_count == 0:
        logging.warning("데이터 없음 (%s) — 건너뜀 (TTL 만료 또는 수집 공백)", target)
        return

    # 2. Parquet 변환
    parquet_bytes = _csv_to_parquet(csv_bytes)
    ratio = len(csv_bytes) / max(len(parquet_bytes), 1)
    logging.info(
        "Parquet 변환 완료: %d bytes (%.1fx 압축, Snappy)",
        len(parquet_bytes),
        ratio,
    )

    # 3. S3 업로드
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=parquet_bytes)
    logging.info("업로드 완료: s3://%s/%s", S3_BUCKET, key)


def _next_run_utc() -> datetime:
    """다음 01:00 UTC 계산."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=1, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


def main() -> None:
    once = "--once" in sys.argv
    force = "--force" in sys.argv

    if EXPORT_DATE:
        target = date.fromisoformat(EXPORT_DATE)
    else:
        target = date.today() - timedelta(days=1)

    if once:
        export(target, force=force)
        return

    # 데몬 모드: 매일 01:00 UTC 실행
    logging.info("데몬 모드 시작 (매일 01:00 UTC 자동 실행)")
    while True:
        next_run = _next_run_utc()
        sleep_sec = (next_run - datetime.now(timezone.utc)).total_seconds()
        logging.info(
            "다음 실행: %s UTC (%.0f초 후)",
            next_run.strftime("%Y-%m-%d %H:%M"),
            sleep_sec,
        )
        time.sleep(sleep_sec)
        export(date.today() - timedelta(days=1), force=False)


if __name__ == "__main__":
    main()
