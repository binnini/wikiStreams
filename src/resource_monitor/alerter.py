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

# 컨테이너 + 메트릭 조합별 점검 runbook
# key: (container, metric), 컨테이너명 부분 일치(in) 검사
_RUNBOOK: dict[tuple[str, str], list[str]] = {
    ("questdb", "mem_pct"): [
        "`docker stats questdb --no-stream`",
        "`docker logs questdb --tail 30`",
        "메모리가 지속 증가 중이라면 page cache drift — TTL 만료 대기 또는 컨테이너 재시작 검토",
    ],
    ("questdb", "cpu_pct"): [
        "`docker stats questdb --no-stream`",
        "`docker logs questdb --tail 30`",
    ],
    ("questdb", "block_io_mb"): [
        "`docker stats questdb --no-stream`",
        "`docker logs questdb --tail 30`",
        "파티션 merge 또는 대량 쿼리 여부 확인",
    ],
    ("producer", "cpu_pct"): [
        "`docker logs producer --tail 50`",
        "`docker stats producer --no-stream`",
        "Wikidata API 병목 또는 배치 처리 지연 가능성",
    ],
    ("producer", "block_io_mb"): [
        "`docker logs producer --tail 30`",
        "SQLite 캐시 쓰기 폭증 가능성 — wikidata_cache.db 크기 확인",
    ],
    ("redpanda", "cpu_pct"): [
        "`docker stats redpanda --no-stream`",
        "`docker logs redpanda --tail 30`",
    ],
    ("redpanda", "mem_pct"): [
        "`docker stats redpanda --no-stream`",
        "`docker logs redpanda --tail 30`",
    ],
}
_DEFAULT_RUNBOOK = [
    "`docker stats --no-stream`",
    "`docker compose logs --tail 50`",
]


def _get_runbook(container: str, metric: str) -> list[str]:
    """컨테이너명 부분 일치로 runbook 조회."""
    for (c, m), steps in _RUNBOOK.items():
        if c in container and m == metric:
            return steps
    return _DEFAULT_RUNBOOK


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
                "Alert sent container=%s metric=%s z_score=%.2f severity=%s",
                anomaly.container,
                anomaly.metric,
                anomaly.z_score,
                anomaly.severity,
            )
        except Exception as exc:
            logger.error("Slack alert failed: %s", exc)

    def _build_payload(self, a: AnomalyResult) -> dict:
        label = _METRIC_LABELS.get(a.metric, a.metric)
        unit = _METRIC_UNITS.get(a.metric, "")
        direction = "급증" if a.z_score > 0 else "급감"

        is_critical = a.severity == "critical"
        header_emoji = "🚨" if is_critical else "⚠️"
        header_text = (
            f"🚨 리소스 위험 — {a.container} 즉시 확인 필요"
            if is_critical
            else f"⚠️ 리소스 이상 감지 — {a.container}"
        )

        runbook_steps = _get_runbook(a.container, a.metric)
        runbook_text = "\n".join(f"• {step}" for step in runbook_steps)

        return {
            "text": header_text,
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": header_text,
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
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*📋 점검 명령어*\n{runbook_text}",
                    },
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
