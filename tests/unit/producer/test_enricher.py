import pytest
import httpx
from unittest.mock import MagicMock

# 테스트할 모듈 임포트
from producer.enricher import WikidataEnricher

# --- 테스트 케이스 데이터 ---

# 1. 캐시와 API를 모두 사용하는 시나리오
events_mixed = [
    {'title': 'Q123'}, {'title': 'NonQID'}, {'title': 'Q456'},
    {'title': 'Q123'}, {'title': 'Q789'}
]
mock_cache_response_mixed = {'Q123': {'label': 'Cache Label 123', 'description': 'Cache Desc 123'}}
mock_api_response_mixed = {
    "entities": {
        "Q456": {"labels": {"ko": {"value": "API Label 456"}}, "descriptions": {"en": {"value": "API Desc 456"}}},
        "Q789": {"labels": {"en": {"value": "API Label 789"}}, "descriptions": {"ko": {"value": "API Desc 789"}}}
    }
}
expected_mixed = [
    {'title': 'Q123', 'wikidata_label': 'Cache Label 123', 'wikidata_description': 'Cache Desc 123'},
    {'title': 'NonQID', 'wikidata_label': None, 'wikidata_description': None},
    {'title': 'Q456', 'wikidata_label': 'API Label 456', 'wikidata_description': 'API Desc 456'},
    {'title': 'Q123', 'wikidata_label': 'Cache Label 123', 'wikidata_description': 'Cache Desc 123'},
    {'title': 'Q789', 'wikidata_label': 'API Label 789', 'wikidata_description': 'API Desc 789'},
]

# 2. QID가 없는 시나리오
events_no_qids = [{'title': 'NonQID'}, {'title': 'AnotherText'}]
expected_no_qids = [
    {'title': 'NonQID', 'wikidata_label': None, 'wikidata_description': None},
    {'title': 'AnotherText', 'wikidata_label': None, 'wikidata_description': None},
]

# 3. API 에러 시나리오
events_api_error = [{'title': 'Q123'}]
expected_api_error = [{'title': 'Q123', 'wikidata_label': None, 'wikidata_description': None}]

# 4. 엣지 케이스: ko 레이블 없음
mock_api_no_ko_label = {"entities": {"Q1": {"labels": {"en": {"value": "English Label"}}}}}
expected_no_ko_label = [{'title': 'Q1', 'wikidata_label': 'English Label', 'wikidata_description': '-'}]

# 5. 엣지 케이스: ko/en 레이블 모두 없음
mock_api_no_valid_label = {"entities": {"Q1": {"labels": {"fr": {"value": "French Label"}}}}}
expected_no_valid_label = [{'title': 'Q1', 'wikidata_label': '-', 'wikidata_description': '-'}]

# 6. 엣지 케이스: labels 필드 없음
mock_api_no_labels_field = {"entities": {"Q1": {"descriptions": {"en": {"value": "English Desc"}}}}}
expected_no_labels_field = [{'title': 'Q1', 'wikidata_label': '-', 'wikidata_description': 'English Desc'}]

# --- 테스트 함수 ---

@pytest.fixture
def enricher():
    """WikidataEnricher 인스턴스를 생성하는 Fixture"""
    return WikidataEnricher()

@pytest.mark.parametrize("test_id, events, cache_return, api_response, api_error, expected_events", [
    pytest.param("cache_and_api", events_mixed, mock_cache_response_mixed, mock_api_response_mixed, None, expected_mixed, id="cache_and_api"),
    pytest.param("no_qids", events_no_qids, {}, None, None, expected_no_qids, id="no_qids"),
    pytest.param("api_error", events_api_error, {}, None, httpx.HTTPError("API error"), expected_api_error, id="api_error"),
    pytest.param("edge_case_no_ko_label", [{'title': 'Q1'}], {}, mock_api_no_ko_label, None, expected_no_ko_label, id="edge_case_no_ko_label"),
    pytest.param("edge_case_no_valid_label", [{'title': 'Q1'}], {}, mock_api_no_valid_label, None, expected_no_valid_label, id="edge_case_no_valid_label"),
    pytest.param("edge_case_no_labels_field", [{'title': 'Q1'}], {}, mock_api_no_labels_field, None, expected_no_labels_field, id="edge_case_no_labels_field"),
])
def test_enrich_scenarios(mocker, enricher, test_id, events, cache_return, api_response, api_error, expected_events):
    # --- Arrange ---
    mock_get_cache = mocker.patch('producer.enricher.get_qids_from_cache', return_value=cache_return)
    mock_save_cache = mocker.patch('producer.enricher.save_qids_to_cache')
    
    if api_error:
        mock_client_get = mocker.patch('httpx.Client.get', side_effect=api_error)
    else:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = api_response
        mock_client_get = mocker.patch('httpx.Client.get', return_value=mock_response)

    # --- Act ---
    result_events = enricher.enrich_events(events)

    # --- Assert ---
    assert result_events == expected_events

    qids_in_batch = {e['title'] for e in events if e['title'].startswith('Q') and e['title'][1:].isdigit()}
    if not qids_in_batch:
        mock_get_cache.assert_not_called()
    else:
        mock_get_cache.assert_called_once()
        # 순서에 상관없이 호출 인자 검증
        assert set(mock_get_cache.call_args[0][0]) == qids_in_batch

    qids_to_fetch = qids_in_batch - set(cache_return.keys())
    if not qids_to_fetch:
        mock_client_get.assert_not_called()
    else:
        mock_client_get.assert_called_once()

    if api_error or not qids_to_fetch or not api_response:
        mock_save_cache.assert_not_called()
    else:
        mock_save_cache.assert_called_once()
