import os
import json
import logging
import httpx
from httpx_sse import connect_sse
import time

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
WIKIMEDIA_URL = "https://stream.wikimedia.org/v2/stream/recentchange"

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
        while True:
            try:
                headers = {"User-Agent": "wikiStreams-project/0.3"}
                with httpx.Client(timeout=None, headers=headers) as client:
                    with connect_sse(client, "GET", WIKIMEDIA_URL) as event_source:
                        logging.info("✅ Wikimedia SSE 스트림에 성공적으로 연결되었습니다.")
                        for sse in event_source.iter_sse():
                            if not sse.data:
                                current_time = time.time()
                                if self.event_buffer and (
                                    current_time - self.last_processed_time
                                    >= self.batch_timeout_seconds
                                ):
                                    self._process_buffer()
                                continue

                            try:
                                event_data = json.loads(sse.data)
                                self.event_buffer.append(event_data)
                            except json.JSONDecodeError:
                                logging.warning(
                                    f"⚠️ 잘못된 JSON 데이터를 건너뜀: {sse.data}"
                                )
                                continue

                            if len(self.event_buffer) >= self.batch_size:
                                self._process_buffer()

            except httpx.HTTPError as e:
                logging.error(f"❌ HTTPX 오류 발생: {e}, 10초 후 재연결 시도...")
                time.sleep(10)
            except (KeyboardInterrupt, StopCollector):
                # 프로그램 종료 또는 테스트 종료를 위한 예외는 다시 발생시켜 루프를 중단합니다.
                raise
            except Exception as e:
                logging.error(f"❌ 예상치 못한 오류 발생: {e}, TYPE: {type(e)}")
                time.sleep(10)
