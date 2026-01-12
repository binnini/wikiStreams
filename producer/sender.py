import os
import json
import logging
import time
from kafka import KafkaProducer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

class KafkaSender:
    def __init__(self, kafka_broker: str, kafka_topic: str):
        self.kafka_broker = kafka_broker
        self.kafka_topic = kafka_topic
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
        for event in events:
            self.producer.send(self.kafka_topic, value=event)
        self.producer.flush()
        logging.info(f"{len(events)}개의 이벤트를 Kafka 토픽 '{self.kafka_topic}'으로 전송했습니다.")
