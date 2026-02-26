import logging

from config import settings
from consumer import DLQConsumer

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)


if __name__ == "__main__":
    consumer = DLQConsumer(
        kafka_broker=settings.kafka_broker,
        kafka_topic=settings.kafka_topic,
        dlq_topic=settings.kafka_dlq_topic,
        max_retries=settings.dlq_max_retries,
        consumer_group=settings.dlq_consumer_group,
    )
    consumer.run()
