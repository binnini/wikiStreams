import math
import pytest
from resource_monitor.baseline import BaselineStore


@pytest.fixture
def store(tmp_path):
    return BaselineStore(str(tmp_path / "test.db"), alpha=0.1)


def test_first_update_returns_value(store):
    rec = store.update("producer", "cpu_pct", 10, 50.0)
    assert rec.count == 1
    assert rec.ema == 50.0
    assert rec.variance == 0.0


def test_get_returns_none_for_missing(store):
    assert store.get("producer", "cpu_pct", 0) is None


def test_get_returns_record_after_update(store):
    store.update("producer", "cpu_pct", 10, 50.0)
    rec = store.get("producer", "cpu_pct", 10)
    assert rec is not None
    assert rec.container == "producer"
    assert rec.metric == "cpu_pct"
    assert rec.hour == 10


def test_ema_converges(store):
    # 동일 값 반복 입력 → EMA가 해당 값으로 수렴
    for _ in range(100):
        rec = store.update("clickhouse", "mem_pct", 0, 80.0)
    assert abs(rec.ema - 80.0) < 1.0


def test_variance_grows_with_spread(store):
    # 분산된 값 → variance > 0
    for v in [10.0, 90.0, 10.0, 90.0, 50.0, 50.0]:
        rec = store.update("producer", "cpu_pct", 0, v)
    assert rec.variance > 0
    assert rec.count == 6


def test_different_containers_independent(store):
    store.update("producer", "cpu_pct", 0, 10.0)
    store.update("clickhouse", "cpu_pct", 0, 90.0)
    r1 = store.get("producer", "cpu_pct", 0)
    r2 = store.get("clickhouse", "cpu_pct", 0)
    assert r1.ema != r2.ema


def test_different_hours_independent(store):
    store.update("producer", "cpu_pct", 0, 10.0)
    store.update("producer", "cpu_pct", 12, 90.0)
    r0 = store.get("producer", "cpu_pct", 0)
    r12 = store.get("producer", "cpu_pct", 12)
    assert r0.ema < r12.ema


def test_persistence_across_instances(tmp_path):
    db = str(tmp_path / "persist.db")
    s1 = BaselineStore(db, alpha=0.1)
    s1.update("producer", "mem_mb", 3, 512.0)

    s2 = BaselineStore(db, alpha=0.1)
    rec = s2.get("producer", "mem_mb", 3)
    assert rec is not None
    assert rec.count == 1
    assert rec.ema == 512.0


def test_welford_variance_accuracy(store):
    # 알려진 분산 확인 — 값이 [0, 100]이면 분산 ≈ 2500 (표본 분산)
    for v in [0.0, 100.0] * 50:
        rec = store.update("producer", "cpu_pct", 0, v)
    assert abs(rec.variance - 2500.0) < 200  # 수렴 오차 허용
