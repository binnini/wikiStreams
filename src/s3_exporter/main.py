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
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")  # 로컬 MinIO: http://minio:9000

EXPORT_DATE = os.getenv("EXPORT_DATE", "")  # YYYY-MM-DD, 미설정 시 전일


def _s3_key(target: date) -> str:
    """Hive 파티셔닝 경로 생성."""
    return (
        f"{S3_PREFIX}/"
        f"year={target.year:04d}/"
        f"month={target.month:02d}/"
        f"day={target.day:02d}/"
        f"events.parquet"
    )


def _make_s3_client():
    """boto3 S3 클라이언트 생성. S3_ENDPOINT_URL 설정 시 MinIO 등 로컬 호환 스토리지 사용."""
    kwargs = {"region_name": AWS_REGION}
    if S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


def _s3_exists(s3_client, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


_CONVERT_OPTIONS = pcsv.ConvertOptions(
    column_types={
        "bot": pa.bool_(),
        "minor": pa.bool_(),
        "namespace": pa.int32(),
    },
    null_values=["", "null", "NULL"],
    strings_can_be_null=True,
    timestamp_parsers=[],  # auto-detect 비활성화 → timestamp 컬럼을 string으로 읽음
)


def _fetch_hour_as_arrow(target: date, hour: int) -> pa.Table:
    """QuestDB /exp endpoint로 1시간치 데이터를 Arrow Table로 반환."""
    start = f"{target}T{hour:02d}:00:00.000000Z"
    end = f"{target}T{hour:02d}:59:59.999999Z"
    sql = (
        'SELECT server_name, wiki_type, title, "user", bot, namespace, minor, '
        "comment, wikidata_label, wikidata_description, timestamp "
        "FROM wikimedia_events "
        f"WHERE timestamp >= '{start}' AND timestamp <= '{end}'"
    )
    params = urllib.parse.urlencode({"query": sql})
    url = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exp?{params}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        csv_bytes = resp.read()

    row_count = max(0, csv_bytes.count(b"\n") - 1)
    if row_count == 0:
        return None

    table = pcsv.read_csv(io.BytesIO(csv_bytes), convert_options=_CONVERT_OPTIONS)

    # timestamp 컬럼을 timestamp[us, UTC]로 정규화
    # pyarrow 버전에 따라 auto-detect 결과가 string 또는 timestamp로 다름
    idx = table.schema.get_field_index("timestamp")
    ts_raw = table.column("timestamp")
    if pa.types.is_timestamp(ts_raw.type):
        ts_col = ts_raw.cast(pa.timestamp("us", tz="UTC"))
    else:
        ts_col = pc.strptime(ts_raw, format="%Y-%m-%dT%H:%M:%S.%fZ", unit="us")
        ts_col = pc.assume_timezone(ts_col, timezone="UTC")
    table = table.set_column(idx, "timestamp", ts_col)

    return table


def export(target: date, force: bool = False) -> None:
    """단일 날짜 데이터를 시간별 청크로 처리하여 S3에 Parquet으로 내보냅니다."""
    if not S3_BUCKET:
        logging.error("S3_BUCKET 환경변수 미설정 — 종료")
        sys.exit(1)

    s3 = _make_s3_client()
    key = _s3_key(target)

    if not force and _s3_exists(s3, key):
        logging.info("이미 존재함 (건너뜀): s3://%s/%s", S3_BUCKET, key)
        return

    # 1. 시간별 청크로 QuestDB 조회 → ParquetWriter에 순차 write
    buf = io.BytesIO()
    writer = None
    total_rows = 0

    logging.info("QuestDB 쿼리 시작: %s (시간별 24 청크)", target)
    for hour in range(24):
        table = _fetch_hour_as_arrow(target, hour)
        if table is None:
            continue
        if writer is None:
            writer = pq.ParquetWriter(buf, table.schema, compression="snappy")
        writer.write_table(table)
        total_rows += len(table)
        del table  # 즉시 메모리 해제

    if writer is None:
        logging.warning("데이터 없음 (%s) — 건너뜀 (TTL 만료 또는 수집 공백)", target)
        return
    writer.close()

    parquet_bytes = buf.getvalue()
    logging.info(
        "CSV 다운로드 + Parquet 변환 완료: %d rows / %d bytes (Snappy)",
        total_rows,
        len(parquet_bytes),
    )

    # 2. S3 업로드 (1회)
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
