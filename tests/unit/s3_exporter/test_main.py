"""
S3 Exporter 단위 테스트.

모든 외부 의존성(boto3, urllib, pyarrow)은 mock 처리.
"""

import io
import sys
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from botocore.exceptions import ClientError

import s3_exporter.main as exporter_module
from s3_exporter.main import (
    _fetch_hour_as_arrow,
    _next_run_utc,
    _s3_exists,
    _s3_key,
    export,
)


# ── _s3_key ──────────────────────────────────────────────────────────────────


def test_s3_key_format_default_prefix():
    """기본 prefix(events)로 Hive 파티셔닝 경로를 생성한다."""
    target = date(2026, 3, 10)
    with patch.object(exporter_module, "S3_PREFIX", "events"):
        key = _s3_key(target)
    assert key == "events/year=2026/month=03/day=10/events.parquet"


def test_s3_key_format_custom_prefix():
    """커스텀 prefix가 경로에 반영된다."""
    target = date(2026, 1, 5)
    with patch.object(exporter_module, "S3_PREFIX", "data/wiki"):
        key = _s3_key(target)
    assert key == "data/wiki/year=2026/month=01/day=05/events.parquet"


def test_s3_key_zero_padded():
    """월·일이 2자리로 0-패딩된다."""
    target = date(2026, 1, 1)
    with patch.object(exporter_module, "S3_PREFIX", "events"):
        key = _s3_key(target)
    assert "month=01" in key
    assert "day=01" in key


# ── _s3_exists ───────────────────────────────────────────────────────────────


def test_s3_exists_returns_true_when_object_found():
    """head_object가 성공(예외 없음)하면 True를 반환한다."""
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {}
    with patch.object(exporter_module, "S3_BUCKET", "my-bucket"):
        result = _s3_exists(mock_s3, "events/year=2026/month=03/day=10/events.parquet")
    assert result is True


def test_s3_exists_returns_false_on_404():
    """head_object가 404 ClientError를 던지면 False를 반환한다."""
    mock_s3 = MagicMock()
    error = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
    mock_s3.head_object.side_effect = error
    with patch.object(exporter_module, "S3_BUCKET", "my-bucket"):
        result = _s3_exists(mock_s3, "events/year=2026/month=03/day=10/events.parquet")
    assert result is False


def test_s3_exists_returns_false_on_nosuchkey():
    """head_object가 NoSuchKey ClientError를 던지면 False를 반환한다."""
    mock_s3 = MagicMock()
    error = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "No Such Key"}}, "HeadObject"
    )
    mock_s3.head_object.side_effect = error
    with patch.object(exporter_module, "S3_BUCKET", "my-bucket"):
        result = _s3_exists(mock_s3, "some/key")
    assert result is False


def test_s3_exists_reraises_other_client_errors():
    """403 등 다른 ClientError는 그대로 전파한다."""
    mock_s3 = MagicMock()
    error = ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")
    mock_s3.head_object.side_effect = error
    with patch.object(exporter_module, "S3_BUCKET", "my-bucket"):
        with pytest.raises(ClientError):
            _s3_exists(mock_s3, "some/key")


# ── _fetch_hour_as_arrow ─────────────────────────────────────────────────────


def _make_csv_bytes(rows: int = 2) -> bytes:
    """테스트용 CSV 바이트 생성 (헤더 + rows개 데이터행)."""
    header = "server_name,wiki_type,title,user,bot,namespace,minor,comment,wikidata_label,wikidata_description,timestamp\n"
    row = "enwiki,wikipedia,Test,user1,false,0,false,edit,,\n"
    # timestamp 컬럼 추가
    header = "server_name,wiki_type,title,user,bot,namespace,minor,comment,wikidata_label,wikidata_description,timestamp\n"
    row = "enwiki,wikipedia,Test,user1,false,0,false,edit,,,2026-03-10T00:30:00.000000Z\n"
    return (header + row * rows).encode()


def test_fetch_hour_returns_none_when_no_data():
    """QuestDB가 헤더만 반환(0행)하면 None을 반환한다."""
    empty_csv = b"col1,col2\n"  # 헤더만, 데이터행 0개
    mock_resp = MagicMock()
    mock_resp.read.return_value = empty_csv
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _fetch_hour_as_arrow(date(2026, 3, 10), 0)

    assert result is None


def test_fetch_hour_returns_arrow_table_with_data():
    """QuestDB가 데이터를 반환하면 pyarrow Table을 반환한다."""
    csv_bytes = _make_csv_bytes(rows=3)
    mock_resp = MagicMock()
    mock_resp.read.return_value = csv_bytes
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _fetch_hour_as_arrow(date(2026, 3, 10), 0)

    assert isinstance(result, pa.Table)
    assert len(result) == 3


def test_fetch_hour_url_contains_correct_time_range():
    """URL에 시간 범위가 올바르게 포함된다."""
    empty_csv = b"col1\n"
    mock_resp = MagicMock()
    mock_resp.read.return_value = empty_csv
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    captured_urls = []

    def fake_urlopen(url, timeout):
        captured_urls.append(url)
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _fetch_hour_as_arrow(date(2026, 3, 10), 14)

    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert "14%3A00%3A00" in url or "14:00:00" in url  # URL-encoded or plain
    assert "14%3A59%3A59" in url or "14:59:59" in url


# ── export ───────────────────────────────────────────────────────────────────


def test_export_exits_when_s3_bucket_not_set():
    """S3_BUCKET이 비어있으면 sys.exit(1)을 호출한다."""
    with patch.object(exporter_module, "S3_BUCKET", ""):
        with pytest.raises(SystemExit) as exc_info:
            export(date(2026, 3, 10))
    assert exc_info.value.code == 1


def test_export_skips_if_file_exists_and_not_force(mocker):
    """force=False이고 S3에 파일이 이미 존재하면 업로드하지 않는다."""
    mock_s3 = MagicMock()
    mocker.patch.object(exporter_module, "S3_BUCKET", "my-bucket")
    mocker.patch.object(exporter_module, "_make_s3_client", return_value=mock_s3)
    mocker.patch.object(exporter_module, "_s3_exists", return_value=True)
    mock_fetch = mocker.patch.object(exporter_module, "_fetch_hour_as_arrow")

    export(date(2026, 3, 10), force=False)

    mock_fetch.assert_not_called()
    mock_s3.put_object.assert_not_called()


def test_export_force_overwrites_existing_file(mocker):
    """force=True이면 기존 파일이 있어도 재업로드한다."""
    mock_s3 = MagicMock()
    mocker.patch.object(exporter_module, "S3_BUCKET", "my-bucket")
    mocker.patch.object(exporter_module, "_make_s3_client", return_value=mock_s3)
    mocker.patch.object(exporter_module, "_s3_exists", return_value=True)

    # 한 시간치 데이터만 반환 (나머지는 None)
    dummy_table = pa.table(
        {
            "server_name": ["enwiki"],
            "wiki_type": ["wikipedia"],
            "title": ["Test"],
            "user": ["u"],
            "bot": [False],
            "namespace": pa.array([0], type=pa.int32()),
            "minor": [False],
            "comment": ["edit"],
            "wikidata_label": [None],
            "wikidata_description": [None],
            "timestamp": pa.array(
                [datetime(2026, 3, 10, 0, 30, tzinfo=timezone.utc)],
                type=pa.timestamp("us", tz="UTC"),
            ),
        }
    )
    mocker.patch.object(
        exporter_module,
        "_fetch_hour_as_arrow",
        side_effect=[dummy_table] + [None] * 23,
    )

    export(date(2026, 3, 10), force=True)

    mock_s3.put_object.assert_called_once()


def test_export_skips_when_all_hours_empty(mocker):
    """24시간 모두 데이터가 없으면 S3에 업로드하지 않는다."""
    mock_s3 = MagicMock()
    mocker.patch.object(exporter_module, "S3_BUCKET", "my-bucket")
    mocker.patch.object(exporter_module, "_make_s3_client", return_value=mock_s3)
    mocker.patch.object(exporter_module, "_s3_exists", return_value=False)
    mocker.patch.object(
        exporter_module, "_fetch_hour_as_arrow", return_value=None
    )

    export(date(2026, 3, 10), force=False)

    mock_s3.put_object.assert_not_called()


def test_export_uploads_parquet_with_correct_key(mocker):
    """데이터가 있으면 Hive 키 경로로 put_object를 호출한다."""
    mock_s3 = MagicMock()
    mocker.patch.object(exporter_module, "S3_BUCKET", "my-bucket")
    mocker.patch.object(exporter_module, "S3_PREFIX", "events")
    mocker.patch.object(exporter_module, "_make_s3_client", return_value=mock_s3)
    mocker.patch.object(exporter_module, "_s3_exists", return_value=False)

    dummy_table = pa.table(
        {
            "server_name": ["enwiki"],
            "wiki_type": ["wikipedia"],
            "title": ["Test"],
            "user": ["u"],
            "bot": [False],
            "namespace": pa.array([0], type=pa.int32()),
            "minor": [False],
            "comment": ["edit"],
            "wikidata_label": [None],
            "wikidata_description": [None],
            "timestamp": pa.array(
                [datetime(2026, 3, 10, 5, 0, tzinfo=timezone.utc)],
                type=pa.timestamp("us", tz="UTC"),
            ),
        }
    )
    # 5시간에만 데이터, 나머지는 None
    side_effects = [None] * 5 + [dummy_table] + [None] * 18
    mocker.patch.object(
        exporter_module, "_fetch_hour_as_arrow", side_effect=side_effects
    )

    export(date(2026, 3, 10), force=False)

    mock_s3.put_object.assert_called_once()
    call_kwargs = mock_s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "my-bucket"
    assert call_kwargs["Key"] == "events/year=2026/month=03/day=10/events.parquet"
    assert isinstance(call_kwargs["Body"], bytes)
    assert len(call_kwargs["Body"]) > 0


def test_export_uploaded_bytes_are_valid_parquet(mocker):
    """업로드된 바이트가 유효한 Parquet 파일이어야 한다."""
    mock_s3 = MagicMock()
    mocker.patch.object(exporter_module, "S3_BUCKET", "my-bucket")
    mocker.patch.object(exporter_module, "_make_s3_client", return_value=mock_s3)
    mocker.patch.object(exporter_module, "_s3_exists", return_value=False)

    dummy_table = pa.table(
        {
            "server_name": ["enwiki", "dewiki"],
            "wiki_type": ["wikipedia", "wikipedia"],
            "title": ["A", "B"],
            "user": ["u1", "u2"],
            "bot": [False, True],
            "namespace": pa.array([0, 0], type=pa.int32()),
            "minor": [False, False],
            "comment": ["c1", "c2"],
            "wikidata_label": [None, None],
            "wikidata_description": [None, None],
            "timestamp": pa.array(
                [
                    datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 3, 10, 0, 1, tzinfo=timezone.utc),
                ],
                type=pa.timestamp("us", tz="UTC"),
            ),
        }
    )
    mocker.patch.object(
        exporter_module,
        "_fetch_hour_as_arrow",
        side_effect=[dummy_table] + [None] * 23,
    )

    export(date(2026, 3, 10), force=False)

    parquet_bytes = mock_s3.put_object.call_args.kwargs["Body"]
    restored = pq.read_table(io.BytesIO(parquet_bytes))
    assert len(restored) == 2
    assert restored.schema.get_field_index("server_name") >= 0


def test_export_aggregates_multiple_hours(mocker):
    """여러 시간대의 데이터가 하나의 Parquet 파일로 합산된다."""
    mock_s3 = MagicMock()
    mocker.patch.object(exporter_module, "S3_BUCKET", "my-bucket")
    mocker.patch.object(exporter_module, "_make_s3_client", return_value=mock_s3)
    mocker.patch.object(exporter_module, "_s3_exists", return_value=False)

    def make_table(hour: int) -> pa.Table:
        return pa.table(
            {
                "server_name": ["enwiki"],
                "wiki_type": ["wikipedia"],
                "title": [f"T{hour}"],
                "user": ["u"],
                "bot": [False],
                "namespace": pa.array([0], type=pa.int32()),
                "minor": [False],
                "comment": ["c"],
                "wikidata_label": [None],
                "wikidata_description": [None],
                "timestamp": pa.array(
                    [datetime(2026, 3, 10, hour, 0, tzinfo=timezone.utc)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
            }
        )

    # 0시, 12시, 23시에 데이터 존재
    side_effects = []
    for h in range(24):
        side_effects.append(make_table(h) if h in (0, 12, 23) else None)

    mocker.patch.object(
        exporter_module, "_fetch_hour_as_arrow", side_effect=side_effects
    )

    export(date(2026, 3, 10), force=False)

    parquet_bytes = mock_s3.put_object.call_args.kwargs["Body"]
    restored = pq.read_table(io.BytesIO(parquet_bytes))
    assert len(restored) == 3  # 3시간치 합산


# ── _next_run_utc ────────────────────────────────────────────────────────────


def test_next_run_utc_is_in_future():
    """반환값은 항상 현재 시각보다 미래이다."""
    result = _next_run_utc()
    assert result > datetime.now(timezone.utc)


def test_next_run_utc_is_at_01_00():
    """반환값의 시각은 01:00:00 UTC이다."""
    result = _next_run_utc()
    assert result.hour == 1
    assert result.minute == 0
    assert result.second == 0


def test_next_run_utc_advances_to_next_day_when_past_01():
    """현재 시각이 01:00 이후라면 내일 01:00을 반환한다."""
    # 오늘 03:00 UTC 기준으로 고정
    fixed_now = datetime(2026, 3, 10, 3, 0, 0, tzinfo=timezone.utc)
    with patch("s3_exporter.main.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _next_run_utc()

    assert result.day == 11
    assert result.hour == 1


def test_next_run_utc_same_day_when_before_01():
    """현재 시각이 01:00 이전이라면 오늘 01:00을 반환한다."""
    fixed_now = datetime(2026, 3, 10, 0, 30, 0, tzinfo=timezone.utc)
    with patch("s3_exporter.main.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _next_run_utc()

    assert result.day == 10
    assert result.hour == 1
