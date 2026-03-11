from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 모니터링 대상 컨테이너 (쉼표 구분)
    monitor_targets: str = "producer,questdb,redpanda,questdb-consumer,reporter"

    # Slack Webhook URL (인프라 이상 알림 전용 — Reporter의 SLACK_WEBHOOK_URL과 별도)
    slack_alert_webhook_url: str = ""

    # 이상 감지 z-score 임계값 (warning)
    # 2.5 → 3.0: 정규분포 기준 이상 확률 1.2% → 0.3%로 낮춰 오발령 감소
    anomaly_threshold: float = 3.0

    # critical z-score 임계값 (이 이상이면 severity=critical)
    critical_z_score: float = 4.0

    # 절댓값 가드 — 이 값 미만이면 z-score가 높아도 알림 안 함 (false positive 방지)
    abs_threshold_cpu_pct: float = 20.0  # CPU 20% 미만은 무시
    abs_threshold_mem_pct: float = 70.0  # 메모리 70% 미만은 무시
    abs_threshold_block_io_mb: float = 50.0  # I/O 50 MB/s 미만은 무시

    # critical 절댓값 임계값 — 이 값 초과 시 z-score 무관하게 severity=critical
    critical_abs_cpu_pct: float = 50.0
    critical_abs_mem_pct: float = 85.0
    critical_abs_block_io_mb: float = 100.0

    # 최소 학습 샘플 수 (미만이면 감지 억제)
    # 수집 간격 10초 × 720 = 2시간분 데이터 → 베이스라인 안정화 후 감지 시작
    min_samples: int = 720

    # 같은 컨테이너·메트릭 재발송 억제 시간 (초)
    alert_cooldown_seconds: int = 3600

    # 수집 간격 (초)
    collect_interval_seconds: int = 10

    # EMA 평활 계수 (0 < alpha <= 1)
    ema_alpha: float = 0.1

    # SQLite 파일 경로
    baseline_db_path: str = "/data/resource_monitor_baseline.db"

    # 로그 레벨
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def targets(self) -> list[str]:
        return [t.strip() for t in self.monitor_targets.split(",") if t.strip()]


settings = Settings()
