import pytest
from unittest.mock import MagicMock, patch, call
from producer.slo_writer import SloWriter


@pytest.fixture
def writer():
    return SloWriter("questdb", 9000)


# ── ensure_table ─────────────────────────────────────────────────────────────


def test_ensure_table_success_on_first_try(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", return_value=True)
    writer.ensure_table()
    mock_exec.assert_called_once()
    assert "CREATE TABLE" in mock_exec.call_args[0][0]


def test_ensure_table_retries_on_failure(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", side_effect=[False, False, True])
    writer.ensure_table(retries=5, delay=0)
    assert mock_exec.call_count == 3


def test_ensure_table_gives_up_after_max_retries(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", return_value=False)
    writer.ensure_table(retries=3, delay=0)
    assert mock_exec.call_count == 3


# ── write ─────────────────────────────────────────────────────────────────────


def test_write_builds_correct_insert_sql(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", return_value=True)
    writer.write(
        batch_sec=1.23,
        batch_size=100,
        valid=90,
        total_enriched=80,
        new_api_calls=20,
    )
    sql = mock_exec.call_args[0][0]
    assert "INSERT INTO producer_slo_metrics" in sql
    assert "1.23" in sql
    assert "100" in sql
    assert "90" in sql
    assert "80" in sql
    assert "20" in sql
    # cache_hit_rate_pct = (80-20)/80*100 = 75.0
    assert "75.0" in sql


def test_write_null_hit_rate_when_zero_enriched(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", return_value=True)
    writer.write(
        batch_sec=0.5,
        batch_size=10,
        valid=0,
        total_enriched=0,
        new_api_calls=0,
    )
    sql = mock_exec.call_args[0][0]
    assert "NULL" in sql


def test_write_continues_on_failure(writer, mocker):
    mocker.patch.object(writer, "_exec", return_value=False)
    # Should not raise
    writer.write(
        batch_sec=1.0,
        batch_size=50,
        valid=45,
        total_enriched=30,
        new_api_calls=5,
    )


# ── _exec ─────────────────────────────────────────────────────────────────────


def test_exec_returns_true_on_200(writer, mocker):
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: mock_resp
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.status = 200
    mocker.patch("urllib.request.urlopen", return_value=mock_resp)
    assert writer._exec("SELECT 1") is True


def test_exec_returns_false_on_exception(writer, mocker):
    mocker.patch("urllib.request.urlopen", side_effect=Exception("connection refused"))
    assert writer._exec("SELECT 1") is False
