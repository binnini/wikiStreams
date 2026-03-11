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


# ── 절댓값 가드 ────────────────────────────────────────────────────────────────


def test_abs_threshold_suppresses_low_value():
    # z = (70 - 50) / 5 = 4.0 > 2.5 이지만 현재값(3.0) < abs_threshold(20.0) → None
    rec = _record(ema=0.5, variance=0.04)  # std=0.2, ema=0.5
    # value=3.0, z=(3.0-0.5)/0.2=12.5 → 높은 z지만 abs_threshold=20.0 미만
    result = detect(rec, 3.0, threshold=2.5, min_samples=30, abs_threshold=20.0)
    assert result is None


def test_abs_threshold_allows_high_value():
    # 현재값(70.0) >= abs_threshold(20.0) → 정상 감지
    rec = _record(ema=50.0, variance=25.0)
    result = detect(rec, 70.0, threshold=2.5, min_samples=30, abs_threshold=20.0)
    assert result is not None


def test_no_abs_threshold_behaves_as_before():
    # abs_threshold=None → 기존 동작 유지
    rec = _record(ema=0.5, variance=0.04)
    result = detect(rec, 3.0, threshold=2.5, min_samples=30, abs_threshold=None)
    assert result is not None


# ── severity 분리 ───────────────────────────────────────────────────────────────


def test_severity_warning_when_z_below_critical():
    # z = 4.0, critical_z_score = 4.5 → warning
    rec = _record(ema=50.0, variance=25.0)
    result = detect(rec, 70.0, threshold=2.5, min_samples=30, critical_z_score=4.5)
    assert result is not None
    assert result.severity == "warning"


def test_severity_critical_when_z_exceeds_critical_z():
    # z = (90 - 50) / 5 = 8.0 > critical_z_score=4.0 → critical
    rec = _record(ema=50.0, variance=25.0)
    result = detect(rec, 90.0, threshold=2.5, min_samples=30, critical_z_score=4.0)
    assert result is not None
    assert result.severity == "critical"


def test_severity_critical_when_value_exceeds_critical_abs():
    # z = 4.0 (warning 수준), 하지만 현재값(85.0) > critical_abs(80.0) → critical
    rec = _record(ema=50.0, variance=25.0)
    result = detect(
        rec,
        70.0,
        threshold=2.5,
        min_samples=30,
        critical_z_score=5.0,  # z=4.0은 이 미만
        critical_abs_threshold=60.0,  # 현재값 70.0 > 60.0
    )
    assert result is not None
    assert result.severity == "critical"


def test_severity_warning_when_value_below_critical_abs():
    # z = 4.0, 현재값(70.0) < critical_abs(80.0), z도 critical_z(5.0) 미만 → warning
    rec = _record(ema=50.0, variance=25.0)
    result = detect(
        rec,
        70.0,
        threshold=2.5,
        min_samples=30,
        critical_z_score=5.0,
        critical_abs_threshold=80.0,
    )
    assert result is not None
    assert result.severity == "warning"


def test_default_severity_is_warning():
    rec = _record(ema=50.0, variance=25.0)
    result = detect(rec, 70.0, threshold=2.5, min_samples=30)
    assert result is not None
    assert result.severity == "warning"
