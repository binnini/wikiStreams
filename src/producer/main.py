import logging
import threading
import time

from pydantic import ValidationError

# 로컬 모듈 임포트
from .config import settings
from .cache import setup_database, close_db_connection
from .collector import WikimediaCollector
from .enricher import WikidataEnricher
from .models import WikimediaEvent
from .sender import KafkaSender

# --- 1. 설정값 불러오기 ---
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def run_producer():
    """
    메인 프로듀서 함수: SSE 스트림에 연결하고 마이크로 배치로 메시지를 처리합니다.
    """
    setup_database()

    enricher = WikidataEnricher()
    sender = KafkaSender(
        settings.kafka_broker, settings.kafka_topic, settings.kafka_dlq_topic
    )

    def process_batch(events: list):
        t0 = time.perf_counter()
        batch_size = len(events)

        valid_events = []
        for event in events:
            try:
                WikimediaEvent.model_validate(event)
                valid_events.append(event)
            except ValidationError as e:
                logging.warning(f"⚠️ 스키마 검증 실패, DLQ로 격리: {e}")
                sender.send_to_dlq(event, f"Schema validation error: {e}")

        enriched_events = enricher.enrich_events(valid_events)
        sender.send_events(enriched_events)

        elapsed = time.perf_counter() - t0
        logging.info(
            "batch_processing_seconds=%.3f batch_size=%d valid=%d",
            elapsed,
            batch_size,
            len(valid_events),
        )

    collector = WikimediaCollector(settings.batch_size, settings.batch_timeout_seconds)
    collector.set_callback(process_batch)
    collector.run()


if __name__ == "__main__":
    main_thread = threading.Thread(target=run_producer)
    main_thread.daemon = True
    main_thread.start()

    try:
        while main_thread.is_alive():
            main_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        logging.info("프로그램 종료 요청을 받았습니다. 정리 작업을 수행합니다.")
    finally:
        close_db_connection()
        logging.info("프로그램을 종료합니다.")
