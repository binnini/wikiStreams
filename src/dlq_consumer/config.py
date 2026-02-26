from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_broker: str = "localhost:9092"
    kafka_topic: str = "wikimedia.recentchange"
    kafka_dlq_topic: str = "wikimedia.recentchange.dlq"
    dlq_max_retries: int = 3
    dlq_consumer_group: str = "dlq-consumer-group"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
