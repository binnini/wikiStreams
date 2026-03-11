from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kafka Settings
    kafka_broker: str = "localhost:9092"
    kafka_topic: str = "wikimedia.recentchange"
    kafka_dlq_topic: str = "wikimedia.recentchange.dlq"

    # Cache Settings
    # 기본값은 기존과 동일하게 설정하되, 테스트나 로컬 개발 시 변경 가능하도록 함
    database_path: str = "/cache/wikidata_cache.db"
    cache_ttl_seconds: int = 2592000  # 정상 엔티티 (레이블 있음): 30일
    cache_missing_ttl_seconds: int = 10800  # "missing" 엔티티: 3시간
    cache_empty_label_ttl_seconds: int = 10800  # 정상 엔티티 (레이블 없음): 3시간

    # Collector Settings
    batch_size: int = 500
    batch_timeout_seconds: float = 10.0

    # DLQ Settings
    dlq_max_retries: int = 3

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 정의되지 않은 환경변수는 무시


# 전역 설정 객체 생성
settings = Settings()
