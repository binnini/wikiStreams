import os
import json
import time
import logging
from wsgiref import headers
import httpx
from httpx_sse import connect_sse
from kafka import KafkaProducer

# 로깅 설정
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- 1. 설정값 불러오기 (환경 변수 사용) ---
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "wikimedia.recentchange")
WIKIMEDIA_URL = "https://stream.wikimedia.org/v2/stream/recentchange"


def create_kafka_producer():
    """
    Kafka Producer 인스턴스를 생성하고 연결을 시도합니다.
    연결에 실패하면 재시도합니다.
    """
    while True:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER.split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                retries=5,
                request_timeout_ms=30000,
            )
            logging.info("✅ Kafka Producer에 성공적으로 연결되었습니다.")
            return producer
        except Exception as e:
            logging.error(f"❌ Kafka Producer 연결에 실패했습니다: {e}")
            logging.info("5초 후 재시도합니다...")
            time.sleep(5)


def run_wiki_stream():
    """
    메인 함수: SSE 스트림에 연결하고 메시지를 Kafka로 전송합니다.
    """
    producer = create_kafka_producer()

    while True:  # 외부 루프: 연결 끊김 시 재시도를 위해 추가
        try:
            logging.info(f"Wikimedia SSE 스트림에 연결을 시도합니다: {WIKIMEDIA_URL}")
            # httpx 클라이언트 생성: 스트리밍이므로 timeout을 None으로 설정
            headers = {"User-Agent": "wikiStreams-project/0.1 (puding2564@gmail.com)"}
            with httpx.Client(timeout=None, headers=headers) as client:
                # SSE 연결
                with connect_sse(client, "GET", WIKIMEDIA_URL) as event_source:
                    logging.info("✅ Wikimedia SSE 스트림에 성공적으로 연결되었습니다.")
                    for sse in event_source.iter_sse():
                        # 데이터가 없는 이벤트(keep-alive 등)는 건너뜀
                        if not sse.data:
                            continue

                        try:
                            # JSON 데이터 파싱
                            data = json.loads(sse.data)

                            # --- Kafka로 데이터를 쏘는 지점 ---
                            producer.send(KAFKA_TOPIC, value=data)

                            # 현재 어떤 데이터가 전송되고 있는지 확인하기 위한 로그 (선택 사항)
                            if "title" in data:
                                logging.info(
                                    f"📨 메시지 전송됨: {data.get('meta', {}).get('domain', '')} - {data.get('title', '')}"
                                )

                        except json.JSONDecodeError:
                            logging.warning(
                                f"⚠️ 잘못된 JSON 데이터를 건너뜁니다: {sse.data}"
                            )
                        except Exception as e:
                            logging.error(f"메시지 처리 중 오류 발생: {e}")

        except httpx.HTTPError as e:
            # httpx 관련 네트워크/HTTP 오류 처리
            logging.error(f"❌ HTTPX 오류 발생: {e}")
            logging.info("10초 후 재연결을 시도합니다...")
            time.sleep(10)
        except Exception as e:
            # 그 외 예상치 못한 오류 처리
            logging.error(f"❌ 예상치 못한 오류 발생: {e}")
            logging.info("10초 후 재연결을 시도합니다...")
            time.sleep(10)


if __name__ == "__main__":
    run_wiki_stream()
