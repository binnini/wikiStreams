import pytest
from unittest.mock import MagicMock, patch

from resource_monitor.collector import (
    DockerStatsCollector,
    _calc_cpu,
    _calc_mem,
    _calc_blkio,
    ContainerMetrics,
)


def _make_raw_stats(
    cpu_total=200_000_000,
    pre_cpu_total=100_000_000,
    sys_cpu=1_000_000_000,
    pre_sys_cpu=900_000_000,
    online_cpus=2,
    mem_usage=500 * 1024 * 1024,
    mem_limit=2048 * 1024 * 1024,
    cache=0,
    blkio_bytes=1024 * 1024,
):
    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": cpu_total},
            "system_cpu_usage": sys_cpu,
            "online_cpus": online_cpus,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": pre_cpu_total},
            "system_cpu_usage": pre_sys_cpu,
        },
        "memory_stats": {
            "usage": mem_usage,
            "limit": mem_limit,
            "stats": {"cache": cache},
        },
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"op": "Read", "value": blkio_bytes},
                {"op": "Write", "value": blkio_bytes},
            ]
        },
    }


def test_calc_cpu_basic():
    raw = _make_raw_stats(
        cpu_total=200_000_000,
        pre_cpu_total=100_000_000,
        sys_cpu=1_000_000_000,
        pre_sys_cpu=900_000_000,
        online_cpus=2,
    )
    # cpu_delta=1e8, sys_delta=1e8, num=2 → 200%
    assert _calc_cpu(raw) == pytest.approx(200.0)


def test_calc_cpu_zero_sys_delta():
    raw = _make_raw_stats(sys_cpu=1_000_000_000, pre_sys_cpu=1_000_000_000)
    assert _calc_cpu(raw) == 0.0


def test_calc_mem_basic():
    usage, limit = _calc_mem(
        _make_raw_stats(mem_usage=512 * 1024 * 1024, mem_limit=2048 * 1024 * 1024, cache=0)
    )
    assert usage == pytest.approx(512 * 1024 * 1024)
    assert limit == pytest.approx(2048 * 1024 * 1024)


def test_calc_mem_subtracts_cache():
    cache = 100 * 1024 * 1024
    usage, _ = _calc_mem(
        _make_raw_stats(mem_usage=600 * 1024 * 1024, mem_limit=2048 * 1024 * 1024, cache=cache)
    )
    assert usage == pytest.approx(500 * 1024 * 1024)


def test_calc_blkio_sums_entries():
    raw = _make_raw_stats(blkio_bytes=1024 * 1024)  # Read + Write = 2MB
    assert _calc_blkio(raw) == pytest.approx(2 * 1024 * 1024)


def test_calc_blkio_empty():
    raw = {"blkio_stats": {"io_service_bytes_recursive": []}}
    assert _calc_blkio(raw) == 0.0


def test_calc_blkio_none():
    raw = {"blkio_stats": {}}
    assert _calc_blkio(raw) == 0.0


@pytest.fixture
def collector(mocker):
    mocker.patch("resource_monitor.collector.docker.from_env")
    return DockerStatsCollector()


def test_collect_returns_metrics(collector, mocker):
    raw = _make_raw_stats()
    mock_container = MagicMock()
    mock_container.stats.return_value = raw
    collector._client.containers.get.return_value = mock_container

    result = collector.collect("producer")
    assert isinstance(result, ContainerMetrics)
    assert result.container == "producer"
    assert result.cpu_pct >= 0
    assert result.mem_mb > 0


def test_collect_returns_none_on_not_found(collector, mocker):
    import docker.errors

    collector._client.containers.get.side_effect = docker.errors.NotFound("not found")
    result = collector.collect("missing")
    assert result is None


def test_collect_returns_none_on_exception(collector):
    collector._client.containers.get.side_effect = RuntimeError("unexpected")
    result = collector.collect("producer")
    assert result is None


def test_block_io_delta(collector):
    raw1 = _make_raw_stats(blkio_bytes=1024 * 1024)   # 2 MB total
    raw2 = _make_raw_stats(blkio_bytes=2 * 1024 * 1024)  # 4 MB total → delta 2 MB

    mock_container = MagicMock()
    mock_container.stats.side_effect = [raw1, raw2]
    collector._client.containers.get.return_value = mock_container

    m1 = collector.collect("clickhouse")
    m2 = collector.collect("clickhouse")

    assert m1.block_io_mb == pytest.approx(0.0)   # 첫 번째: prev 없음 → 0
    assert m2.block_io_mb == pytest.approx(2.0)   # delta = 4 - 2 = 2 MB


def test_collect_all(collector, mocker):
    raw = _make_raw_stats()
    mock_container = MagicMock()
    mock_container.stats.return_value = raw
    collector._client.containers.get.return_value = mock_container

    results = collector.collect_all(["producer", "clickhouse"])
    assert len(results) == 2
    assert {r.container for r in results} == {"producer", "clickhouse"}
