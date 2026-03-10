"""Slack Block Kit 이상 알림 + cooldown."""

import logging
import time
from typing import Optional

import httpx

from resource_monitor.detector import AnomalyResult

logger = logging.getLogger(__name__)

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
            logger.warning("SLACK_ALERT_WEBHOOK_URL 미설정 — 알림 전송 생략")
            return

        if not self._is_cooled_down(anomaly.container, anomaly.metric):
            logger.debug(
                "Cooldown active — skip alert container=%s metric=%s",
                anomaly.container,
                anomaly.metric,
            )
            return

        payload = self._build_payload(anomaly)
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(self._webhook_url, json=payload)
                resp.raise_for_status()
            self._mark_alerted(anomaly.container, anomaly.metric)
            logger.info(
                "Alert sent container=%s metric=%s z_score=%.2f",
                anomaly.container,
                anomaly.metric,
                anomaly.z_score,
            )
        except Exception as exc:
            logger.error("Slack alert failed: %s", exc)

    def _build_payload(self, a: AnomalyResult) -> dict:
        label = _METRIC_LABELS.get(a.metric, a.metric)
        unit = _METRIC_UNITS.get(a.metric, "")
        direction = "급증" if a.z_score > 0 else "급감"

        return {
            "text": f"⚠️ 리소스 이상 감지 — {a.container}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"⚠️ 리소스 이상 감지 — {a.container}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*컨테이너*\n{a.container}"},
                        {"type": "mrkdwn", "text": f"*메트릭*\n{label}"},
                        {"type": "mrkdwn", "text": f"*방향*\n{direction}"},
                        {"type": "mrkdwn", "text": f"*현재값*\n{a.current_value:.2f}{unit}"},
                        {"type": "mrkdwn", "text": f"*시간대 평균 ({a.hour:02d}시)*\n{a.ema:.2f}{unit}"},
                        {"type": "mrkdwn", "text": f"*z-score*\n{a.z_score:.2f}"},
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "WikiStreams Resource Monitor"}
                    ],
                },
            ],
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
