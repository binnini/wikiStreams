from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # QuestDB Settings
    questdb_host: str = "questdb"
    questdb_port: int = 9000

    # API Keys
    anthropic_api_key: str = ""
    discord_webhook_url: str = ""

    # Prompt style ('default' or 'doro')
    prompt_style: str = "default"
    # prompt_style: str = "doro"

    # Report storage — YYYY-MM-DD.json files saved here
    report_storage_dir: str = "/app/reports"

    # Schedule
    report_hour_kst: int = 9

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
