import sqlite3
import pytest
from producer import cache


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """
    임시 디렉토리에 테스트용 SQLite DB를 생성하고,
    cache 모듈이 이 DB를 사용하도록 설정(monkeypatch)하는 Fixture.
    """
    db_path = tmp_path / "test_cache.db"

    # cache 모듈의 전역 변수인 DATABASE_PATH를 테스트용 DB 경로로 교체
    monkeypatch.setattr(cache, "DATABASE_PATH", str(db_path))

    # DB 초기화 및 연결/커서 객체 반환
    cache.setup_database()
    yield
    cache.close_db_connection()


def test_setup_database(temp_db):
    # temp_db fixture가 실행되면 DB는 이미 설정된 상태
    # 연결 객체를 통해 테이블이 실제로 생성되었는지 확인
    conn = sqlite3.connect(cache.DATABASE_PATH)
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
