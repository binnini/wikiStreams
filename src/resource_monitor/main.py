"""Resource Monitor 메인 루프."""
import logging
import time
from datetime import datetime, timezone

from resource_monitor.alerter import Alerter
from resource_monitor.baseline import BaselineStore
from resource_monitor.collector import DockerStatsCollector, ContainerMetrics
from resource_monitor.config import settings
from resource_monitor.detector import detect

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_METRICS = ["cpu_pct", "mem_pct", "mem_mb", "block_io_mb"]


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
    alerter = Alerter(settings.discord_webhook_url, settings.alert_cooldown_seconds)
    collector = DockerStatsCollector()

    while True:
        now = datetime.now(tz=timezone.utc)
        hour = now.hour

        metrics_list = collector.collect_all(settings.targets)

        for m in metrics_list:
            _log_metrics(m, hour)

            for metric_name in _METRICS:
                value = getattr(m, metric_name)
                record = store.update(m.container, metric_name, hour, value)
                anomaly = detect(
                    record,
                    value,
                    threshold=settings.anomaly_threshold,
                    min_samples=settings.min_samples,
                )
                if anomaly:
                    logger.warning(
                        'level=warn msg="AnomalyDetected" container="%s" '
                        'metric="%s" value=%.4f ema=%.4f z_score=%.2f hour=%d',
                        anomaly.container,
                        anomaly.metric,
                        anomaly.current_value,
                        anomaly.ema,
                        anomaly.z_score,
                        anomaly.hour,
                    )
                    alerter.send(anomaly)

        time.sleep(settings.collect_interval_seconds)


if __name__ == "__main__":
    run()
