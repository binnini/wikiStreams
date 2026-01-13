import sqlite3
import threading
import logging
from .config import settings

# 스레드 간에 SQLite 연결을 안전하게 공유하기 위해 Thread-local 데이터 사용
local = threading.local()


def get_db_connection():
    """
    현재 스레드에 대한 데이터베이스 연결을 가져오거나 생성합니다.
    """
    db = getattr(local, "_db", None)
    if db is None:
        try:
            # check_same_thread=False는 이 예제처럼 간단한 스레딩 모델에서
            # 단일 스레드가 연결을 생성하고 사용을 보장할 때 허용됩니다.
            db = sqlite3.connect(settings.database_path, check_same_thread=False)
            db.row_factory = sqlite3.Row  # 결과를 딕셔너리처럼 접근 가능하게 함
            local._db = db
            logging.info(f"새로운 SQLite 연결을 생성했습니다. (Path: {settings.database_path})")
        except sqlite3.Error as e:
            logging.error(f"SQLite 연결 생성 실패: {e}")
            return None
    return db


def close_db_connection(exception=None):
    """
    현재 스레드의 데이터베이스 연결을 닫습니다.
    """
    db = getattr(local, "_db", None)
    if db is not None:
        db.close()
        local._db = None
        logging.info("SQLite 연결을 닫았습니다.")


def setup_database():
    """
    데이터베이스와 캐시 테이블이 존재하는지 확인하고, 없으면 생성합니다.
    """
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS wikidata_cache (
                    q_id TEXT PRIMARY KEY,
                    label TEXT,
                    description TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
            logging.info("✅ Wikidata 캐시 테이블이 성공적으로 준비되었습니다.")
        except sqlite3.Error as e:
            logging.error(f"캐시 테이블 생성 실패: {e}")


def get_qids_from_cache(q_ids: list) -> dict:
    """
    주어진 Q-ID 리스트에 대해 캐시에서 정보를 조회합니다.
    """
    if not q_ids:
        return {}

    conn = get_db_connection()
    if not conn:
        return {}

    found_qids = {}
    try:
        placeholders = ", ".join("?" for _ in q_ids)
        query = f"SELECT q_id, label, description FROM wikidata_cache WHERE q_id IN ({placeholders})"

        cursor = conn.cursor()
        cursor.execute(query, q_ids)
        rows = cursor.fetchall()

        for row in rows:
            found_qids[row["q_id"]] = {
                "label": row["label"],
                "description": row["description"],
            }
        logging.info(f"캐시에서 {len(found_qids)}/{len(q_ids)}개의 Q-ID를 찾았습니다.")
    except sqlite3.Error as e:
        logging.error(f"캐시 조회 실패: {e}")

    return found_qids


def save_qids_to_cache(qids_data: dict):
    """
    여러 Q-ID 정보를 캐시에 저장합니다. (Upsert 방식)
    """
    if not qids_data:
        return

    conn = get_db_connection()
    if not conn:
        return

    to_save = [
        (q_id, data["label"], data["description"]) for q_id, data in qids_data.items()
    ]

    try:
        cursor = conn.cursor()
        cursor.executemany(
            "INSERT OR REPLACE INTO wikidata_cache (q_id, label, description) VALUES (?, ?, ?)",
            to_save,
        )
        conn.commit()
        logging.info(f"{len(to_save)}개의 Q-ID를 캐시에 저장/업데이트했습니다.")
    except sqlite3.Error as e:
        logging.error(f"캐시 저장 실패: {e}")
