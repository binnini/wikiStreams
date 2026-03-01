import json
import logging
import time

import httpx
from httpx_sse import connect_sse

logger = logging.getLogger(__name__)

WIKIMEDIA_URL = "https://stream.wikimedia.org/v2/stream/recentchange"
_RETRY_BASE_DELAY = 2.0  # 초기 재연결 대기 시간 (초)
_RETRY_MAX_DELAY = 60.0  # 최대 재연결 대기 시간 (초)


# 테스트 환경에서 무한 루프를 제어하기 위한 예외
class StopCollector(Exception):
    pass


class WikimediaCollector:
    def __init__(self, batch_size: int, batch_timeout_seconds: float):
        self.batch_size = batch_size
        self.batch_timeout_seconds = batch_timeout_seconds
        self.event_buffer = []
        self.last_processed_time = time.time()
        self.callback = None

    def set_callback(self, callback_func):
        self.callback = callback_func

    def _process_buffer(self):
        if self.event_buffer and self.callback:
            try:
                # 버퍼의 복사본을 콜백에 전달합니다.
                self.callback(self.event_buffer[:])
            finally:
                self.event_buffer.clear()
        self.last_processed_time = time.time()

    def run(self):
        retry_delay = _RETRY_BASE_DELAY
        while True:
            try:
                headers = {"User-Agent": "wikiStreams-project/0.3"}
                with httpx.Client(timeout=None, headers=headers) as client:
                    with connect_sse(client, "GET", WIKIMEDIA_URL) as event_source:
                        logger.info(
                            "✅ Wikimedia SSE 스트림에 성공적으로 연결되었습니다."
                        )
                        retry_delay = _RETRY_BASE_DELAY  # 연결 성공 시 초기화
                        for sse in event_source.iter_sse():
                            if not sse.data:
                                if self.event_buffer and (
                                    time.time() - self.last_processed_time
                                    >= self.batch_timeout_seconds
                                ):
                                    self._process_buffer()
                                continue

                            try:
                                event_data = json.loads(sse.data)
                                self.event_buffer.append(event_data)
                            except json.JSONDecodeError:
                                logger.warning(
                                    "⚠️ 잘못된 JSON 데이터를 건너뜀: %s", sse.data
                                )
                                continue

                            if len(self.event_buffer) >= self.batch_size:
                                self._process_buffer()

            except httpx.HTTPError as e:
                logger.error(
                    "❌ HTTPX 오류 발생: %s — %.0f초 후 재연결 시도...", e, retry_delay
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, _RETRY_MAX_DELAY)
            except (KeyboardInterrupt, StopCollector):
                raise
            except Exception as e:
                logger.error(
                    "❌ 예상치 못한 오류 발생: %s (TYPE: %s) — %.0f초 후 재연결...",
                    e,
                    type(e).__name__,
                    retry_delay,
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, _RETRY_MAX_DELAY)
