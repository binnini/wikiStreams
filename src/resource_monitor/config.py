from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 모니터링 대상 컨테이너 (쉼표 구분)
    monitor_targets: str = "producer,clickhouse"

    # Discord Webhook URL (리소스 이상 알림 전용 — Reporter의 DISCORD_WEBHOOK_URL과 별도)
    resource_monitor_discord_webhook_url: str = ""

    # 이상 감지 z-score 임계값
    anomaly_threshold: float = 2.5

    # 최소 학습 샘플 수 (미만이면 감지 억제)
    # 수집 간격 10초 × 360 = 1시간분 데이터 → 24개 버킷 전체 활성화까지 약 1일 소요
    min_samples: int = 360

    # 같은 컨테이너·메트릭 재발송 억제 시간 (초, 기본 15분)
    alert_cooldown_seconds: int = 900

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
