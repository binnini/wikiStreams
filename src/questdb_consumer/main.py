import json
import logging
import os
import socket
import time
import urllib.request
import urllib.parse

from kafka import KafkaConsumer

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "host.docker.internal:19092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "wikimedia.recentchange")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "questdb-consumer")
QUESTDB_HOST = os.getenv("QUESTDB_HOST", "questdb-staging")
QUESTDB_ILP_PORT = int(os.getenv("QUESTDB_ILP_PORT", "9009"))
QUESTDB_REST_PORT = int(os.getenv("QUESTDB_REST_PORT", "9000"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
BATCH_TIMEOUT_MS = int(os.getenv("BATCH_TIMEOUT_MS", "5000"))

_SKIP_TYPES = {"log"}
_SKIP_DOMAINS = {"canary"}

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS wikimedia_events (
    server_name SYMBOL,
    wiki_type   SYMBOL,
    title       STRING,
    user        STRING,
    bot         BOOLEAN,
    namespace   INT,
    minor       BOOLEAN,
    comment     STRING,
    wikidata_label       STRING,
    wikidata_description STRING,
    timestamp   TIMESTAMP
) timestamp(timestamp) PARTITION BY DAY TTL 5d;\
"""


def _ensure_table():
    """QuestDB REST API로 wikimedia_events 테이블을 TTL 5d로 생성 (없을 때만)."""
    base_url = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec"
    params = urllib.parse.urlencode({"query": _CREATE_TABLE_SQL})
    url = f"{base_url}?{params}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = json.loads(resp.read())
                if "error" in body:
                    logging.warning("테이블 생성 응답 오류: %s", body["error"])
                else:
                    logging.info("wikimedia_events 테이블 확인/생성 완료 (TTL 5d)")
                return
        except Exception as e:
            logging.warning("테이블 초기화 실패 (시도 %d/5): %s", attempt + 1, e)
            time.sleep(3)
    logging.error("wikimedia_events 테이블 초기화 실패 — ILP auto-create로 폴백")


def _should_skip(event: dict) -> bool:
    if event.get("type") in _SKIP_TYPES:
        return True
    if event.get("meta", {}).get("domain") in _SKIP_DOMAINS:
        return True
    return False


def _tag(v: str) -> str:
    """ILP tag value 이스케이프: 쉼표·등호·공백 앞에 역슬래시."""
    return str(v).replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def _str(v: str) -> str:
    """ILP string field 이스케이프: 역슬래시·따옴표·개행 처리."""
    return (
        str(v)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "")
        .replace("\r", "")
    )


def event_to_ilp(event: dict) -> str | None:
    try:
        server_name = _tag(event.get("server_name", "unknown"))
        wiki_type = _tag(event.get("type", "unknown"))

        title = _str(event.get("title", ""))
        user = _str(event.get("user", ""))
        bot = "t" if event.get("bot") else "f"
        namespace = int(event.get("namespace", 0))
        minor = "t" if event.get("minor") else "f"
        comment = _str((event.get("comment") or "")[:500])
        wikidata_label = _str(event.get("wikidata_label") or "")
        wikidata_description = _str((event.get("wikidata_description") or "")[:200])
        timestamp_ns = int(event.get("timestamp", time.time())) * 1_000_000_000

        return (
            f"wikimedia_events,server_name={server_name},wiki_type={wiki_type} "
            f'title="{title}",user="{user}",bot={bot},'
            f"namespace={namespace}i,minor={minor},"
            f'comment="{comment}",wikidata_label="{wikidata_label}",'
            f'wikidata_description="{wikidata_description}" '
            f"{timestamp_ns}\n"
        )
    except Exception as e:
        logging.warning("ILP 변환 실패: %s | title=%s", e, event.get("title"))
        return None


def run():
    _ensure_table()

    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="latest",
    )
    logging.info(
        "QuestDB Consumer 시작: broker=%s topic=%s questdb=%s:%d",
        KAFKA_BROKER,
        KAFKA_TOPIC,
        QUESTDB_HOST,
        QUESTDB_ILP_PORT,
    )

    while True:
        sock = None
        try:
            sock = socket.create_connection(
                (QUESTDB_HOST, QUESTDB_ILP_PORT), timeout=10
            )
            logging.info("QuestDB ILP 연결: %s:%d", QUESTDB_HOST, QUESTDB_ILP_PORT)

            while True:
                records = consumer.poll(
                    timeout_ms=BATCH_TIMEOUT_MS, max_records=BATCH_SIZE
                )
                batch = []

                for msgs in records.values():
                    for msg in msgs:
                        try:
                            event = json.loads(msg.value.decode("utf-8"))
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue
                        if not isinstance(event, dict) or _should_skip(event):
                            continue
                        line = event_to_ilp(event)
                        if line:
                            batch.append(line)

                if batch:
                    sock.sendall("".join(batch).encode("utf-8"))
                    logging.info("batch_sent count=%d", len(batch))

        except Exception as e:
            logging.error("오류: %s | 5초 후 재시도", e)
            time.sleep(5)
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass


if __name__ == "__main__":
    run()
