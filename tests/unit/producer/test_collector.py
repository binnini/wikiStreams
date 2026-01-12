import json
import httpx
import pytest
from unittest.mock import MagicMock

# 테스트할 모듈 및 테스트용 예외 임포트
from producer.collector import WikimediaCollector, StopCollector

# --- 테스트 케이스 데이터 ---

# 1. 배치 크기(2) 도달 시나리오
event_data_1 = {'id': 1, 'title': 'Test1'}
event_data_2 = {'id': 2, 'title': 'Test2'}
sse_batch_size = [
    MagicMock(data=json.dumps(event_data_1)),
    MagicMock(data=json.dumps(event_data_2))
]

# 2. 타임아웃 시나리오
event_data_timeout = {'id': 10, 'title': 'TimeoutTest1'}
sse_timeout = [MagicMock(data=json.dumps(event_data_timeout))]

# 3. JSON 에러 시나리오
event_data_valid_1 = {'id': 1, 'title': 'Valid1'}
event_data_valid_2 = {'id': 2, 'title': 'Valid2'}
sse_json_error = [
    MagicMock(data='invalid json'),
    MagicMock(data=json.dumps(event_data_valid_1)),
    MagicMock(data=json.dumps(event_data_valid_2))
]

# 4. 재연결 시나리오
sse_reconnect = [
    MagicMock(data=json.dumps(event_data_1)),
    MagicMock(data=json.dumps(event_data_2))
]

# --- 테스트 함수 ---

@pytest.fixture
def collector():
    """테스트용 WikimediaCollector 인스턴스를 생성하는 Fixture"""
    collector = WikimediaCollector(batch_size=2, batch_timeout_seconds=0.1)
    mock_callback = MagicMock()
    collector.set_callback(mock_callback)
    return collector, mock_callback

@pytest.mark.parametrize("test_id, sse_events, time_side_effect, expected_callback_arg, reconnect_side_effect", [
    pytest.param("by_batch_size", sse_batch_size, None, [event_data_1, event_data_2], None, id="by_batch_size"),
    pytest.param("by_timeout", sse_timeout, [0.0, 0.2], [event_data_timeout], None, id="by_timeout"),
    pytest.param("with_json_error", sse_json_error, None, [event_data_valid_1, event_data_valid_2], None, id="with_json_error"),
    pytest.param("on_reconnect", sse_reconnect, None, [event_data_1, event_data_2], [httpx.HTTPError("Connection error")], id="on_reconnect"),
])
def test_collector_scenarios(mocker, collector, test_id, sse_events, time_side_effect, expected_callback_arg, reconnect_side_effect):
    # --- Arrange ---
    collector_instance, mock_callback = collector
    collector_instance.last_processed_time = 0.0

    mocker.patch('producer.collector.httpx.Client')
    mock_connect_sse = mocker.patch('producer.collector.connect_sse')
    mocker.patch('producer.collector.time.sleep', return_value=None)
    
    if time_side_effect:
        mocker.patch('producer.collector.time.time', side_effect=time_side_effect)

    # 무한 스트림 제너레이터
    def stream_generator(events):
        for event in events:
            yield event
        while True:
            yield MagicMock(data='')

    # 재연결 시나리오 설정
    if reconnect_side_effect:
        success_stream = MagicMock(__enter__=MagicMock(return_value=MagicMock(iter_sse=MagicMock(return_value=stream_generator(sse_events)))))
        mock_connect_sse.side_effect = reconnect_side_effect + [success_stream]
    else:
        mock_event_source = mock_connect_sse.return_value.__enter__.return_value
        mock_event_source.iter_sse.return_value = stream_generator(sse_events)

    mock_callback.side_effect = StopCollector

    # --- Act & Assert ---
    with pytest.raises(StopCollector):
        collector_instance.run()

    mock_callback.assert_called_once_with(expected_callback_arg)
    assert len(collector_instance.event_buffer) == 0
    if reconnect_side_effect:
        assert mock_connect_sse.call_count == len(reconnect_side_effect) + 1

