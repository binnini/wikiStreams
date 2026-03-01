from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ClickHouse Settings
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 8123

    # API Keys
    anthropic_api_key: str = ""
    discord_webhook_url: str = ""

    # Prompt style ('default' or 'doro')
    prompt_style: str = "default"

    # Schedule
    report_hour_kst: int = 9

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
