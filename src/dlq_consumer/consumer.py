import json
import logging
import time
from datetime import datetime, timezone
from kafka import KafkaConsumer, KafkaProducer


class DLQConsumer:
    def __init__(
        self,
        kafka_broker: str,
        kafka_topic: str,
        dlq_topic: str,
        max_retries: int,
        consumer_group: str,
    ):
        self.kafka_broker = kafka_broker
        self.kafka_topic = kafka_topic
        self.dlq_topic = dlq_topic
        self.max_retries = max_retries
        self.consumer_group = consumer_group
        self.consumer = self._create_consumer()
        self.producer = self._create_producer()

    def _create_consumer(self) -> KafkaConsumer:
        while True:
            try:
                consumer = KafkaConsumer(
                    self.dlq_topic,
                    bootstrap_servers=self.kafka_broker.split(","),
                    group_id=self.consumer_group,
                    value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                    auto_offset_reset="earliest",
                    enable_auto_commit=True,
                )
                logging.info("✅ KafkaConsumer 연결 성공")
                return consumer
            except Exception as e:
                logging.error(f"❌ KafkaConsumer 연결 실패: {e}, 5초 후 재시도...")
                time.sleep(5)

    def _create_producer(self) -> KafkaProducer:
        while True:
            try:
                producer = KafkaProducer(
                    bootstrap_servers=self.kafka_broker.split(","),
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    retries=5,
                )
                logging.info("✅ KafkaProducer 연결 성공")
                return producer
            except Exception as e:
                logging.error(f"❌ KafkaProducer 연결 실패: {e}, 5초 후 재시도...")
                time.sleep(5)

    def run(self):
        logging.info(f"DLQ Consumer 시작: {self.dlq_topic} 구독 중")
        for message in self.consumer:
            self._process_message(message.value)

    def _process_message(self, dlq_message: dict):
        try:
            retry_count = dlq_message["dlq_metadata"]["retry_count"]
            original_event = dlq_message["original_event"]
        except (KeyError, TypeError) as e:
            logging.error(f"잘못된 DLQ 메시지 형식: {e} | 메시지: {dlq_message}")
            return

        if retry_count >= self.max_retries:
            logging.critical(
                f"🚨 최대 재시도 초과 ({retry_count}/{self.max_retries}), 메시지 폐기: "
                f"{dlq_message['dlq_metadata']}"
            )
            return

        try:
            self.producer.send(self.kafka_topic, value=original_event).get(timeout=10)
            logging.info(
                f"✅ 재시도 성공 (retry_count={retry_count}): "
                f"'{self.kafka_topic}'으로 재전송"
            )
        except Exception as e:
            logging.warning(
                f"⚠️ 재시도 실패 (retry_count={retry_count}): {e}, DLQ 재큐잉"
            )
            self._requeue_to_dlq(dlq_message, retry_count + 1)

    def _requeue_to_dlq(self, dlq_message: dict, new_retry_count: int):
        updated_message = {
            "original_event": dlq_message["original_event"],
            "dlq_metadata": {
                **dlq_message["dlq_metadata"],
                "retry_count": new_retry_count,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        try:
            self.producer.send(self.dlq_topic, value=updated_message)
            self.producer.flush()
            logging.info(f"DLQ 재큐잉 완료 (retry_count={new_retry_count})")
        except Exception as e:
            logging.critical(f"🚨 DLQ 재큐잉도 실패: {e}")
