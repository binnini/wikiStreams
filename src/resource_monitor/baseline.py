"""SQLite 기반 컨테이너 × 시간대별 EMA + Welford 분산 저장."""

import sqlite3
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class BaselineRecord:
    container: str
    metric: str
    hour: int
    ema: float
    variance: float  # Welford M2 / (count - 1) 로 계산된 분산
    count: int
    # Welford 알고리즘 내부 상태
    m2: float = 0.0


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS baseline (
    container TEXT NOT NULL,
    metric    TEXT NOT NULL,
    hour      INTEGER NOT NULL,
    ema       REAL NOT NULL DEFAULT 0,
    variance  REAL NOT NULL DEFAULT 0,
    count     INTEGER NOT NULL DEFAULT 0,
    m2        REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (container, metric, hour)
)
"""


class BaselineStore:
    """스레드 안전 SQLite 기반 Baseline 저장소."""

    def __init__(self, db_path: str, alpha: float = 0.1) -> None:
        self._db_path = db_path
        self._alpha = alpha
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, container: str, metric: str, hour: int) -> Optional[BaselineRecord]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM baseline WHERE container=? AND metric=? AND hour=?",
                (container, metric, hour),
            ).fetchone()
        if row is None:
            return None
        return BaselineRecord(
            container=row["container"],
            metric=row["metric"],
            hour=row["hour"],
            ema=row["ema"],
            variance=row["variance"],
            count=row["count"],
            m2=row["m2"],
        )

    def update(
        self, container: str, metric: str, hour: int, value: float
    ) -> BaselineRecord:
        """새 값으로 EMA와 Welford 분산을 업데이트하고 저장."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM baseline WHERE container=? AND metric=? AND hour=?",
                (container, metric, hour),
            ).fetchone()

            if row is None:
                # 첫 번째 샘플
                new_ema = value
                new_m2 = 0.0
                new_variance = 0.0
                new_count = 1
            else:
                old_ema = row["ema"]
                old_m2 = row["m2"]
                old_count = row["count"]

                new_count = old_count + 1
                # Welford online variance
                delta = value - old_ema
                new_ema = old_ema + self._alpha * delta
                delta2 = value - new_ema
                new_m2 = old_m2 + delta * delta2
                new_variance = new_m2 / (new_count - 1) if new_count > 1 else 0.0

            conn.execute(
                """
                INSERT INTO baseline (container, metric, hour, ema, variance, count, m2)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(container, metric, hour) DO UPDATE SET
                    ema=excluded.ema,
                    variance=excluded.variance,
                    count=excluded.count,
                    m2=excluded.m2
                """,
                (container, metric, hour, new_ema, new_variance, new_count, new_m2),
            )

        return BaselineRecord(
            container=container,
            metric=metric,
            hour=hour,
            ema=new_ema,
            variance=new_variance,
            count=new_count,
            m2=new_m2,
        )
