import pytest
from resource_monitor.baseline import BaselineRecord
from resource_monitor.detector import detect, AnomalyResult


def _record(count=50, ema=50.0, variance=25.0, hour=10):
    return BaselineRecord(
        container="producer",
        metric="cpu_pct",
        hour=hour,
        ema=ema,
        variance=variance,
        count=count,
    )


def test_returns_none_when_below_min_samples():
    rec = _record(count=10)
    result = detect(rec, 999.0, threshold=2.5, min_samples=30)
    assert result is None


def test_returns_none_when_zero_variance():
    rec = _record(variance=0.0)
    result = detect(rec, 100.0, threshold=2.5, min_samples=30)
    assert result is None


def test_returns_none_when_z_score_within_threshold():
    # z = (55 - 50) / 5 = 1.0 < 2.5
    rec = _record(ema=50.0, variance=25.0)
    result = detect(rec, 55.0, threshold=2.5, min_samples=30)
    assert result is None


def test_detects_high_anomaly():
    # z = (70 - 50) / 5 = 4.0 > 2.5
    rec = _record(ema=50.0, variance=25.0)
    result = detect(rec, 70.0, threshold=2.5, min_samples=30)
    assert isinstance(result, AnomalyResult)
    assert result.z_score == pytest.approx(4.0)
    assert result.current_value == 70.0
    assert result.ema == 50.0


def test_detects_low_anomaly():
    # z = (30 - 50) / 5 = -4.0, abs > 2.5
    rec = _record(ema=50.0, variance=25.0)
    result = detect(rec, 30.0, threshold=2.5, min_samples=30)
    assert isinstance(result, AnomalyResult)
    assert result.z_score == pytest.approx(-4.0)


def test_anomaly_result_carries_metadata():
    rec = _record(ema=50.0, variance=25.0, hour=14)
    result = detect(rec, 70.0, threshold=2.5, min_samples=30)
    assert result.container == "producer"
    assert result.metric == "cpu_pct"
    assert result.hour == 14


def test_exact_threshold_is_not_anomaly():
    # z == threshold → not anomaly (strict >)
    rec = _record(ema=50.0, variance=25.0)
    # std = 5, threshold = 2.5 → value = 50 + 5 * 2.5 = 62.5
    result = detect(rec, 62.5, threshold=2.5, min_samples=30)
    assert result is None


def test_custom_threshold():
    rec = _record(ema=50.0, variance=25.0)
    # z = 2.0, threshold = 1.5 → anomaly
    result = detect(rec, 60.0, threshold=1.5, min_samples=30)
    assert result is not None
