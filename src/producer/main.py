import os
import logging
import threading
import time

# 로컬 모듈 임포트
from .cache import setup_database, close_db_connection
from .collector import WikimediaCollector
from .enricher import WikidataEnricher
from .sender import KafkaSender

# --- 1. 설정값 불러오기 ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "wikimedia.recentchange")

# 마이크로 배치 설정
BATCH_SIZE = 500
BATCH_TIMEOUT_SECONDS = 10.0

def run_producer():
    """
    메인 프로듀서 함수: SSE 스트림에 연결하고 마이크로 배치로 메시지를 처리합니다.
    """
    setup_database()
    
    enricher = WikidataEnricher()
    sender = KafkaSender(KAFKA_BROKER, KAFKA_TOPIC)

    def process_batch(events: list):
        enriched_events = enricher.enrich_events(events)
        sender.send_events(enriched_events)

    collector = WikimediaCollector(BATCH_SIZE, BATCH_TIMEOUT_SECONDS)
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
