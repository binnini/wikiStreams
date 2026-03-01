"""Discord Embed 이상 알림 + 1시간 cooldown."""
import logging
import time
from typing import Optional

import httpx

from resource_monitor.detector import AnomalyResult

logger = logging.getLogger(__name__)

ORANGE = 0xFF6B35
_METRIC_LABELS = {
    "cpu_pct": "CPU 사용률",
    "mem_pct": "메모리 사용률",
    "mem_mb": "메모리 절댓값",
    "block_io_mb": "블록 I/O",
}
_METRIC_UNITS = {
    "cpu_pct": "%",
    "mem_pct": "%",
    "mem_mb": " MB",
    "block_io_mb": " MB/s",
}


class Alerter:
    def __init__(self, webhook_url: str, cooldown_seconds: int = 3600) -> None:
        self._webhook_url = webhook_url
        self._cooldown = cooldown_seconds
        # (container, metric) → last alert timestamp
        self._last_alert: dict[tuple[str, str], float] = {}

    def _is_cooled_down(self, container: str, metric: str) -> bool:
        key = (container, metric)
        last = self._last_alert.get(key)
        if last is None:
            return True
        return (time.monotonic() - last) >= self._cooldown

    def _mark_alerted(self, container: str, metric: str) -> None:
        self._last_alert[(container, metric)] = time.monotonic()

    def send(self, anomaly: AnomalyResult) -> None:
        if not self._webhook_url:
            logger.warning("DISCORD_WEBHOOK_URL 미설정 — 알림 전송 생략")
            return

        if not self._is_cooled_down(anomaly.container, anomaly.metric):
            logger.debug(
                "Cooldown active — skip alert container=%s metric=%s",
                anomaly.container,
                anomaly.metric,
            )
            return

        embed = self._build_embed(anomaly)
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(
                    self._webhook_url,
                    json={"embeds": [embed]},
                )
                resp.raise_for_status()
            self._mark_alerted(anomaly.container, anomaly.metric)
            logger.info(
                "Alert sent container=%s metric=%s z_score=%.2f",
                anomaly.container,
                anomaly.metric,
                anomaly.z_score,
            )
        except Exception as exc:
            logger.error("Discord alert failed: %s", exc)

    def _build_embed(self, a: AnomalyResult) -> dict:
        label = _METRIC_LABELS.get(a.metric, a.metric)
        unit = _METRIC_UNITS.get(a.metric, "")
        direction = "급증" if a.z_score > 0 else "급감"

        return {
            "title": f"⚠️ 리소스 이상 감지 — {a.container}",
            "color": ORANGE,
            "fields": [
                {"name": "컨테이너", "value": a.container, "inline": True},
                {"name": "메트릭", "value": label, "inline": True},
                {"name": "방향", "value": direction, "inline": True},
                {
                    "name": "현재값",
                    "value": f"{a.current_value:.2f}{unit}",
                    "inline": True,
                },
                {
                    "name": f"시간대 평균 ({a.hour:02d}시)",
                    "value": f"{a.ema:.2f}{unit}",
                    "inline": True,
                },
                {"name": "z-score", "value": f"{a.z_score:.2f}", "inline": True},
            ],
            "footer": {"text": "WikiStreams Resource Monitor"},
        }


def send_alert(
    anomaly: AnomalyResult,
    alerter: Optional["Alerter"] = None,
    webhook_url: str = "",
    cooldown_seconds: int = 3600,
) -> None:
    """편의 함수 — 테스트 주입용."""
    if alerter is None:
        alerter = Alerter(webhook_url, cooldown_seconds)
    alerter.send(anomaly)
