import json
import logging
import time
from datetime import datetime
from kafka import KafkaProducer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class KafkaSender:
    def __init__(self, kafka_broker: str, kafka_topic: str, dlq_topic: str):
        self.kafka_broker = kafka_broker
        self.kafka_topic = kafka_topic
        self.dlq_topic = dlq_topic
        self.producer = self._create_kafka_producer()

    def _create_kafka_producer(self):
        while True:
            try:
                producer = KafkaProducer(
                    bootstrap_servers=self.kafka_broker.split(","),
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    retries=5,
                )
                logging.info("✅ Kafka Producer에 성공적으로 연결되었습니다.")
                return producer
            except Exception as e:
                logging.error(f"❌ Kafka Producer 연결 실패: {e}, 5초 후 재시도...")
                time.sleep(5)

    def send_events(self, events: list):
        if not events:
            return

        futures = [
            (event, self.producer.send(self.kafka_topic, value=event))
            for event in events
        ]
        self.producer.flush()

        success, failed = 0, 0
        for event, future in futures:
            try:
                future.get(timeout=10)
                success += 1
            except Exception as e:
                self._send_to_dlq(event, str(e))
                failed += 1

        logging.info(
            f"{success}개의 이벤트를 '{self.kafka_topic}'으로 전송했습니다."
        )
        if failed:
            logging.warning(f"⚠️ {failed}개의 이벤트를 DLQ로 라우팅했습니다.")

    def _send_to_dlq(self, event: dict, error: str):
        dlq_message = {
            "original_event": event,
            "dlq_metadata": {
                "error": error,
                "failed_at": datetime.utcnow().isoformat(),
                "source_topic": self.kafka_topic,
                "retry_count": 0,
            },
        }
        try:
            self.producer.send(self.dlq_topic, value=dlq_message)
            self.producer.flush()
            logging.error(f"❌ DLQ로 이벤트 라우팅: {error}")
        except Exception as dlq_err:
            logging.critical(f"🚨 DLQ 전송도 실패: {dlq_err} | 원본 에러: {error}")
