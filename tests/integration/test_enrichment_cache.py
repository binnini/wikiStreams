import pytest
import sqlite3
import os
from unittest.mock import patch, MagicMock
from producer.enricher import WikidataEnricher
from producer.cache import setup_database, close_db_connection

# 임시 DB 경로를 주입하기 위한 Fixture
@pytest.fixture
def mock_db_path(tmp_path):
    # 임시 디렉토리에 DB 파일 경로 생성
    db_file = tmp_path / "test_wikidata_cache.db"
    
    # producer.cache 모듈의 DATABASE_PATH 변수를 패치
    with patch("producer.cache.DATABASE_PATH", str(db_file)):
        setup_database() # 테이블 생성
        yield str(db_file)
        close_db_connection()

@pytest.fixture
def enricher():
    return WikidataEnricher()

def test_enrichment_caches_api_results(mock_db_path, enricher):
    """
    Enricher가 외부 API 결과를 캐시하고, 이후 요청에서는 API 호출 없이 캐시를 사용하는지 검증합니다.
    """
    # 테스트 데이터
    q_id = "Q42"
    event = {"title": q_id, "id": 12345}
    
    # Mock API Response
    mock_api_response = {
        "entities": {
            q_id: {
                "labels": {"ko": {"value": "더글러스 애덤스"}, "en": {"value": "Douglas Adams"}},
                "descriptions": {"ko": {"value": "영국 소설가"}, "en": {"value": "English author"}}
            }
        }
    }

    # 1. 첫 번째 호출 (Cache Miss -> API Call)
    # httpx.Client.get 메서드를 모킹
    with patch("httpx.Client.get") as mock_get:
        # 모의 응답 설정
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_api_response
        mock_get.return_value = mock_resp

        # 실행
        enriched_events = enricher.enrich_events([event.copy()])

        # 검증
        assert enriched_events[0]["wikidata_label"] == "더글러스 애덤스"
        assert enriched_events[0]["wikidata_description"] == "영국 소설가"
        
        # API가 한 번 호출되었는지 확인
        mock_get.assert_called_once()
        print("\n[Test] 첫 번째 호출: API가 정상적으로 호출되었습니다.")

    # 2. 두 번째 호출 (Cache Hit -> No API Call)
    with patch("httpx.Client.get") as mock_get:
        # 실행 (동일한 이벤트)
        enriched_events_2 = enricher.enrich_events([event.copy()])

        # 검증 (데이터는 여전히 정확해야 함)
        assert enriched_events_2[0]["wikidata_label"] == "더글러스 애덤스"
        assert enriched_events_2[0]["wikidata_description"] == "영국 소설가"

        # API가 호출되지 않았는지 확인 (0번 호출)
        mock_get.assert_not_called()
        print("[Test] 두 번째 호출: API 호출 없이 캐시에서 데이터를 가져왔습니다.")

