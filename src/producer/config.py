from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kafka Settings
    kafka_broker: str = "localhost:9092"
    kafka_topic: str = "wikimedia.recentchange"

    # Cache Settings
    # 기본값은 기존과 동일하게 설정하되, 테스트나 로컬 개발 시 변경 가능하도록 함
    database_path: str = "/cache/wikidata_cache.db"

    # Collector Settings
    batch_size: int = 500
    batch_timeout_seconds: float = 10.0

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 정의되지 않은 환경변수는 무시


# 전역 설정 객체 생성
settings = Settings()
