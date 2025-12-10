import os
import json
import time
import logging
import httpx
import threading
from httpx_sse import connect_sse
from kafka import KafkaProducer

# 로컬 모듈 임포트
from cache import (
    setup_database,
    get_qids_from_cache,
    save_qids_to_cache,
    close_db_connection,
)

# --- 1. 설정값 불러오기 ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "wikimedia.recentchange")
WIKIMEDIA_URL = "https://stream.wikimedia.org/v2/stream/recentchange"

# 마이크로 배치 설정
BATCH_SIZE = 500
BATCH_TIMEOUT_SECONDS = 10.0


def create_kafka_producer():
    # ... (이전과 동일)
    while True:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER.split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                retries=5,
            )
            logging.info("✅ Kafka Producer에 성공적으로 연결되었습니다.")
            return producer
        except Exception as e:
            logging.error(f"❌ Kafka Producer 연결 실패: {e}, 5초 후 재시도...")
            time.sleep(5)


def fetch_wikidata_info_in_bulk(q_ids: list) -> dict:
    # ... (이전과 동일)
    if not q_ids:
        return {}
    api_endpoint = "https://www.wikidata.org/w/api.php"
    ids_string = "|".join(q_ids)
    params = {
        "action": "wbgetentities",
        "ids": ids_string,
        "props": "labels|descriptions",
        "languages": "ko|en",
        "format": "json",
    }
    headers = {"User-Agent": "wikiStreams-producer/0.3"}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(api_endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            results = {}
            entities = data.get("entities", {})
            for q_id, entity in entities.items():
                label = (
                    entity.get("labels", {}).get("ko", {}).get("value")
                    or entity.get("labels", {}).get("en", {}).get("value")
                    or "-"
                )
                desc = (
                    entity.get("descriptions", {}).get("ko", {}).get("value")
                    or entity.get("descriptions", {}).get("en", {}).get("value")
                    or "-"
                )
                results[q_id] = {"label": label, "description": desc}
            logging.info(f"Wikidata API로부터 {len(results)}개의 정보를 가져왔습니다.")
            return results
    except httpx.HTTPError as e:
        logging.error(f"❌ Wikidata API 오류: {e}")
        return {}


def process_events_in_batch(events: list, producer: KafkaProducer):
    """
    이벤트 배치를 받아 Q-ID 보강 및 Kafka 전송을 처리합니다.
    모든 이벤트에 wikidata_label, wikidata_description 필드를 보장합니다.
    """
    if not events:
        return

    q_ids_in_batch = {
        event.get("title")
        for event in events
        if event.get("title")
        and event["title"].startswith("Q")
        and event["title"][1:].isdigit()
    }

    all_qid_info = {}
    if q_ids_in_batch:
        cached_qids = get_qids_from_cache(list(q_ids_in_batch))
        qids_to_fetch = q_ids_in_batch - set(cached_qids.keys())

        newly_fetched_qids = {}
        if qids_to_fetch:
            newly_fetched_qids = fetch_wikidata_info_in_bulk(list(qids_to_fetch))
            if newly_fetched_qids:
                save_qids_to_cache(newly_fetched_qids)

        all_qid_info = {**cached_qids, **newly_fetched_qids}

    # 모든 이벤트에 정보 보강 후 Kafka로 전송
    for event in events:
        # 스키마 통일성을 위해 기본값(None) 설정
        event["wikidata_label"] = None
        event["wikidata_description"] = None

        qid = event.get("title")
        if qid in all_qid_info:
            event["wikidata_label"] = all_qid_info[qid]["label"]
            event["wikidata_description"] = all_qid_info[qid]["description"]

        # 디버깅 로그는 잠시 주석 처리하거나 필요시 활성화
        # logging.info(f"KAFKA SENDING: {json.dumps(event, ensure_ascii=False))}")
        producer.send(KAFKA_TOPIC, value=event)

    new_api_calls = len(all_qid_info) - len(cached_qids) if q_ids_in_batch else 0
    logging.info(
        f"정보 보강 후 {len(events)}개의 이벤트를 전송했습니다. (신규 API 호출: {new_api_calls}개)"
    )


def run_producer():
    """
    메인 프로듀서 함수: SSE 스트림에 연결하고 마이크로 배치로 메시지를 처리합니다.
    """
    producer = create_kafka_producer()
    setup_database()

    event_buffer = []
    last_processed_time = time.time()

    while True:
        try:
            headers = {"User-Agent": "wikiStreams-project/0.3"}
            with httpx.Client(timeout=None, headers=headers) as client:
                with connect_sse(client, "GET", WIKIMEDIA_URL) as event_source:
                    logging.info("✅ Wikimedia SSE 스트림에 성공적으로 연결되었습니다.")
                    for sse in event_source.iter_sse():
                        if not sse.data:
                            # 타임아웃만으로 배치를 처리하기 위한 로직
                            current_time = time.time()
                            if event_buffer and (
                                current_time - last_processed_time
                                >= BATCH_TIMEOUT_SECONDS
                            ):
                                process_events_in_batch(event_buffer, producer)
                                event_buffer.clear()
                                last_processed_time = current_time
                            continue

                        try:
                            event_data = json.loads(sse.data)
                            event_buffer.append(event_data)
                        except json.JSONDecodeError:
                            logging.warning(
                                f"⚠️ 잘못된 JSON 데이터를 건너뜁니다: {sse.data}"
                            )
                            continue

                        current_time = time.time()
                        if len(event_buffer) >= BATCH_SIZE:
                            process_events_in_batch(event_buffer, producer)
                            event_buffer.clear()
                            last_processed_time = current_time

        except httpx.HTTPError as e:
            logging.error(f"❌ HTTPX 오류 발생: {e}, 10초 후 재연결 시도...")
            time.sleep(10)
        except Exception as e:
            logging.error(f"❌ 예상치 못한 오류 발생: {e}, 10초 후 재연결 시도...")
            time.sleep(10)
        finally:
            if event_buffer:
                logging.info("연결 종료 전, 남아있는 버퍼를 처리합니다.")
                process_events_in_batch(event_buffer, producer)
                event_buffer.clear()


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
