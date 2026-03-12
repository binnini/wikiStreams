"""Resource Monitor 메인 루프."""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from resource_monitor.alerter import Alerter
from resource_monitor.baseline import BaselineStore
from resource_monitor.collector import DockerStatsCollector, ContainerMetrics
from resource_monitor.config import settings
from resource_monitor.detector import detect
from resource_monitor.questdb_writer import QuestDBWriter

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_METRICS = ["cpu_pct", "mem_pct", "block_io_mb"]

# 메트릭별 (절댓값 가드, critical 절댓값) 임계값
_ABS_THRESHOLDS: dict[str, tuple[float, float]] = {
    "cpu_pct": (settings.abs_threshold_cpu_pct, settings.critical_abs_cpu_pct),
    "mem_pct": (settings.abs_threshold_mem_pct, settings.critical_abs_mem_pct),
    "block_io_mb": (
        settings.abs_threshold_block_io_mb,
        settings.critical_abs_block_io_mb,
    ),
}


def _log_metrics(m: ContainerMetrics, hour: int) -> None:
    logger.info(
        'level=info msg="DockerStats" target_container="%s" '
        "cpu_pct=%.2f mem_pct=%.2f mem_mb=%.2f block_io_mb=%.4f hour=%d",
        m.container,
        m.cpu_pct,
        m.mem_pct,
        m.mem_mb,
        m.block_io_mb,
        hour,
    )


def run() -> None:
    logger.info("Resource Monitor started. Targets: %s", settings.targets)

    store = BaselineStore(settings.baseline_db_path, alpha=settings.ema_alpha)
    alerter = Alerter(settings.slack_alert_webhook_url, settings.alert_cooldown_seconds)
    collector = DockerStatsCollector()
    qdb_writer = QuestDBWriter(settings.questdb_host, settings.questdb_rest_port)
    qdb_writer.ensure_table()

    while True:
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        hour = now.hour

        metrics_list = collector.collect_all(settings.targets)

        qdb_writer.write(metrics_list)

        for m in metrics_list:
            _log_metrics(m, hour)

            for metric_name in _METRICS:
                value = getattr(m, metric_name)
                record = store.update(m.container, metric_name, hour, value)
                abs_thr, crit_abs_thr = _ABS_THRESHOLDS.get(metric_name, (None, None))
                anomaly = detect(
                    record,
                    value,
                    threshold=settings.anomaly_threshold,
                    min_samples=settings.min_samples,
                    abs_threshold=abs_thr,
                    critical_z_score=settings.critical_z_score,
                    critical_abs_threshold=crit_abs_thr,
                )
                if anomaly:
                    logger.warning(
                        'level=warn msg="AnomalyDetected" container="%s" '
                        'metric="%s" value=%.4f ema=%.4f z_score=%.2f hour=%d severity="%s"',
                        anomaly.container,
                        anomaly.metric,
                        anomaly.current_value,
                        anomaly.ema,
                        anomaly.z_score,
                        anomaly.hour,
                        anomaly.severity,
                    )
                    alerter.send(anomaly)

        time.sleep(settings.collect_interval_seconds)


if __name__ == "__main__":
    run()
