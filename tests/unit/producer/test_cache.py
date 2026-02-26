import sqlite3
import pytest
from producer import cache
from producer.config import settings


def _insert_with_old_timestamp(
    db_path: str, q_id: str, seconds_ago: int, is_missing: int = 0
):
    """테스트용: 특정 시간 전에 저장된 것처럼 직접 timestamp를 조작해 삽입"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO wikidata_cache (q_id, label, description, timestamp, is_missing) "
        "VALUES (?, ?, ?, datetime('now', ? || ' seconds'), ?)",
        (q_id, "Old Label", "Old Desc", f"-{seconds_ago}", is_missing),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """
    임시 디렉토리에 테스트용 SQLite DB를 생성하고,
    cache 모듈이 이 DB를 사용하도록 설정(monkeypatch)하는 Fixture.
    """
    db_path = tmp_path / "test_cache.db"

    # cache 모듈이 사용하는 설정 객체의 database_path 속성을 테스트용 DB 경로로 교체
    # 주의: settings 객체 자체는 불변이 아니므로 속성을 직접 변경할 수 있습니다.
    monkeypatch.setattr(settings, "database_path", str(db_path))

    # DB 초기화 및 연결/커서 객체 반환
    cache.setup_database()
    yield
    cache.close_db_connection()


def test_setup_database(temp_db):
    # temp_db fixture가 실행되면 DB는 이미 설정된 상태
    # 연결 객체를 통해 테이블이 실제로 생성되었는지 확인
    # settings.database_path를 사용하여 연결
    conn = sqlite3.connect(settings.database_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='wikidata_cache'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_save_and_get_qids(temp_db):
    # Arrange
    qids_to_save = {
        "Q123": {"label": "Test Label 1", "description": "Test Desc 1"},
        "Q456": {"label": "Test Label 2", "description": "Test Desc 2"},
    }

    # Act
    cache.save_qids_to_cache(qids_to_save)

    # Assert
    # 1. 캐시에 있는 ID만 조회
    cached_data_1 = cache.get_qids_from_cache(["Q123"])
    assert cached_data_1 == {"Q123": qids_to_save["Q123"]}

    # 2. 캐시에 있는 여러 ID 조회
    cached_data_all = cache.get_qids_from_cache(["Q123", "Q456"])
    assert cached_data_all == qids_to_save


def test_get_non_existent_qids(temp_db):
    # Arrange: DB는 비어있는 상태

    # Act
    result = cache.get_qids_from_cache(["Q999", "Q888"])

    # Assert
    assert result == {}


def test_partial_cache_hit(temp_db):
    # Arrange
    qids_to_save = {"Q123": {"label": "Label 123", "description": "Desc 123"}}
    cache.save_qids_to_cache(qids_to_save)

    # Act
    # 캐시에 있는 Q123과 없는 Q999를 함께 조회
    result = cache.get_qids_from_cache(["Q123", "Q999"])

    # Assert
    assert result == qids_to_save  # 캐시에 있는 것만 반환되어야 함


def test_expired_entry_not_returned(temp_db, monkeypatch):
    # Arrange: TTL을 60초로 설정하고, 61초 전에 저장된 항목 삽입
    monkeypatch.setattr(settings, "cache_ttl_seconds", 60)
    _insert_with_old_timestamp(settings.database_path, "Q999", seconds_ago=61)

    # Act
    result = cache.get_qids_from_cache(["Q999"])

    # Assert: 만료됐으므로 캐시 미스
    assert result == {}


def test_valid_entry_within_ttl_returned(temp_db, monkeypatch):
    # Arrange: TTL을 60초로 설정하고, 정상 저장 (방금 저장 = 만료 안 됨)
    monkeypatch.setattr(settings, "cache_ttl_seconds", 60)
    cache.save_qids_to_cache(
        {"Q123": {"label": "Fresh Label", "description": "Fresh Desc"}}
    )

    # Act
    result = cache.get_qids_from_cache(["Q123"])

    # Assert
    assert result == {"Q123": {"label": "Fresh Label", "description": "Fresh Desc"}}


def test_mixed_expired_and_valid(temp_db, monkeypatch):
    # Arrange: TTL 60초, Q_expired는 만료, Q_fresh는 유효
    monkeypatch.setattr(settings, "cache_ttl_seconds", 60)
    _insert_with_old_timestamp(settings.database_path, "Q_expired", seconds_ago=61)
    cache.save_qids_to_cache({"Q_fresh": {"label": "Fresh", "description": "Desc"}})

    # Act
    result = cache.get_qids_from_cache(["Q_expired", "Q_fresh"])

    # Assert: 유효한 것만 반환
    assert "Q_fresh" in result
    assert "Q_expired" not in result


def test_missing_entry_expires_with_short_ttl(temp_db, monkeypatch):
    # Arrange: 정상 TTL=3600초, missing TTL=30초, 31초 전에 missing으로 저장
    monkeypatch.setattr(settings, "cache_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "cache_missing_ttl_seconds", 30)
    _insert_with_old_timestamp(
        settings.database_path, "Q_missing", seconds_ago=31, is_missing=1
    )

    # Act
    result = cache.get_qids_from_cache(["Q_missing"])

    # Assert: missing TTL 만료 → 캐시 미스
    assert result == {}


def test_missing_entry_returned_within_missing_ttl(temp_db, monkeypatch):
    # Arrange: missing TTL=3600초, 방금 저장
    monkeypatch.setattr(settings, "cache_missing_ttl_seconds", 3600)
    cache.save_qids_to_cache(
        {"Q_missing": {"label": "-", "description": "-", "is_missing": True}}
    )

    # Act
    result = cache.get_qids_from_cache(["Q_missing"])

    # Assert: TTL 내 → 캐시 히트
    assert "Q_missing" in result


def test_expired_count_logged(temp_db, monkeypatch, caplog):
    # Arrange: TTL=60초, 정상 항목과 만료 항목 혼재
    import logging

    monkeypatch.setattr(settings, "cache_ttl_seconds", 60)
    _insert_with_old_timestamp(settings.database_path, "Q_expired", seconds_ago=61)
    cache.save_qids_to_cache({"Q_fresh": {"label": "Fresh", "description": "Desc"}})

    # Act
    with caplog.at_level(logging.INFO):
        cache.get_qids_from_cache(["Q_expired", "Q_fresh"])

    # Assert: 로그에 TTL 만료 카운트 포함
    assert any("TTL 만료: 1개" in r.message for r in caplog.records)


def test_normal_entry_survives_past_missing_ttl(temp_db, monkeypatch):
    # Arrange: 정상 TTL=3600초, missing TTL=30초, 31초 전에 정상(is_missing=0)으로 저장
    monkeypatch.setattr(settings, "cache_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "cache_missing_ttl_seconds", 30)
    _insert_with_old_timestamp(
        settings.database_path, "Q_normal", seconds_ago=31, is_missing=0
    )

    # Act
    result = cache.get_qids_from_cache(["Q_normal"])

    # Assert: 정상 TTL 미만 → 캐시 히트
    assert "Q_normal" in result
