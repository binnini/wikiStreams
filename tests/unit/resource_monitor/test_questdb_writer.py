from unittest.mock import MagicMock

import pytest

from resource_monitor.collector import ContainerMetrics
from resource_monitor.questdb_writer import QuestDBWriter


@pytest.fixture
def writer():
    return QuestDBWriter("questdb", 9000)


def _make_metrics(container="producer", cpu=5.0, mem=30.0, mem_mb=150.0, bio=0.1):
    return ContainerMetrics(
        container=container,
        cpu_pct=cpu,
        mem_pct=mem,
        mem_mb=mem_mb,
        block_io_mb=bio,
    )


# ── ensure_table ─────────────────────────────────────────────────────────────


def test_ensure_table_success_on_first_try(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", return_value=True)
    writer.ensure_table()
    mock_exec.assert_called_once()
    assert "CREATE TABLE" in mock_exec.call_args[0][0]
    assert "resource_metrics" in mock_exec.call_args[0][0]


def test_ensure_table_retries_on_failure(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", side_effect=[False, False, True])
    writer.ensure_table(retries=5, delay=0)
    assert mock_exec.call_count == 3


def test_ensure_table_gives_up_after_max_retries(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", return_value=False)
    writer.ensure_table(retries=3, delay=0)
    assert mock_exec.call_count == 3


# ── write ─────────────────────────────────────────────────────────────────────


def test_write_empty_list_does_nothing(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec")
    writer.write([])
    mock_exec.assert_not_called()


def test_write_single_metric_builds_correct_sql(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", return_value=True)
    m = _make_metrics(container="producer", cpu=12.5, mem=45.0, mem_mb=200.0, bio=0.5)
    writer.write([m])
    sql = mock_exec.call_args[0][0]
    assert "INSERT INTO resource_metrics" in sql
    assert "'producer'" in sql
    assert "12.5" in sql
    assert "45.0" in sql
    assert "200.0" in sql
    assert "0.5" in sql


def test_write_multiple_metrics_single_insert(writer, mocker):
    mock_exec = mocker.patch.object(writer, "_exec", return_value=True)
    metrics = [
        _make_metrics("producer"),
        _make_metrics("questdb"),
        _make_metrics("redpanda"),
    ]
    writer.write(metrics)
    mock_exec.assert_called_once()
    sql = mock_exec.call_args[0][0]
    assert "'producer'" in sql
    assert "'questdb'" in sql
    assert "'redpanda'" in sql


def test_write_continues_on_failure(writer, mocker):
    mocker.patch.object(writer, "_exec", return_value=False)
    # Should not raise
    writer.write([_make_metrics()])


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
