"""z-score 기반 이상 감지."""

import math
from dataclasses import dataclass

from resource_monitor.baseline import BaselineRecord


@dataclass
class AnomalyResult:
    container: str
    metric: str
    current_value: float
    ema: float
    z_score: float
    hour: int
    severity: str = "warning"  # "warning" | "critical"


def detect(
    record: BaselineRecord,
    current_value: float,
    threshold: float = 2.5,
    min_samples: int = 30,
    abs_threshold: float | None = None,
    critical_z_score: float = 4.0,
    critical_abs_threshold: float | None = None,
) -> AnomalyResult | None:
    """이상 감지. 조건 미충족 시 None 반환.

    Args:
        abs_threshold: 절댓값 가드 — 현재값이 이 미만이면 z-score 무관하게 무시.
        critical_z_score: 이 이상이면 severity=critical.
        critical_abs_threshold: 현재값이 이 초과면 z-score 무관하게 severity=critical.
    """
    if record.count < min_samples:
        return None

    std = math.sqrt(record.variance) if record.variance > 0 else 0.0
    if std == 0:
        return None

    z_score = (current_value - record.ema) / std
    if abs(z_score) <= threshold:
        return None

    # 절댓값 가드: 현재값이 임계 미만이면 노이즈로 판단
    if abs_threshold is not None and current_value < abs_threshold:
        return None

    # severity 판정
    is_critical_z = abs(z_score) > critical_z_score
    is_critical_abs = (
        critical_abs_threshold is not None and current_value > critical_abs_threshold
    )
    severity = "critical" if (is_critical_z or is_critical_abs) else "warning"

    return AnomalyResult(
        container=record.container,
        metric=record.metric,
        current_value=current_value,
        ema=record.ema,
        z_score=z_score,
        hour=record.hour,
        severity=severity,
    )
