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


def detect(
    record: BaselineRecord,
    current_value: float,
    threshold: float = 2.5,
    min_samples: int = 30,
) -> AnomalyResult | None:
    """이상 감지. 조건 미충족 시 None 반환."""
    if record.count < min_samples:
        return None

    std = math.sqrt(record.variance) if record.variance > 0 else 0.0
    if std == 0:
        return None

    z_score = (current_value - record.ema) / std
    if abs(z_score) <= threshold:
        return None

    return AnomalyResult(
        container=record.container,
        metric=record.metric,
        current_value=current_value,
        ema=record.ema,
        z_score=z_score,
        hour=record.hour,
    )
