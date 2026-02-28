import logging
import httpx
from pydantic import ValidationError
from .cache import (
    get_qids_from_cache,
    save_qids_to_cache,
)
from .models import WikidataApiResponse

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class WikidataEnricher:
    def __init__(self):
        pass

    WIKIDATA_API_BATCH_SIZE = 50  # 익명 사용자 기준 Wikidata API 최대 ID 수

    def fetch_wikidata_info_in_bulk(self, q_ids: list) -> dict:
        if not q_ids:
            return {}

        results = {}
        chunks = [
            q_ids[i : i + self.WIKIDATA_API_BATCH_SIZE]
            for i in range(0, len(q_ids), self.WIKIDATA_API_BATCH_SIZE)
        ]
        for chunk in chunks:
            results.update(self._fetch_chunk(chunk))

        logging.info(f"Wikidata API로부터 총 {len(results)}개의 정보를 가져왔습니다.")
        return results

    def _fetch_chunk(self, q_ids: list) -> dict:
        api_endpoint = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "wbgetentities",
            "ids": "|".join(q_ids),
            "props": "labels|descriptions",
            "languages": "ko|en",
            "format": "json",
        }
        headers = {"User-Agent": "wikiStreams-producer/0.3"}
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(api_endpoint, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                try:
                    validated = WikidataApiResponse.model_validate(data)
                    entities = validated.entities
                except ValidationError as e:
                    logging.error(f"❌ Wikidata API 응답 스키마 불일치: {e}")
                    return {}
                results = {}
                for q_id, entity in entities.items():
                    is_missing = "missing" in entity
                    if is_missing:
                        label, desc = "", ""
                    else:
                        label = (
                            entity.get("labels", {}).get("ko", {}).get("value")
                            or entity.get("labels", {}).get("en", {}).get("value")
                            or ""
                        )
                        desc = (
                            entity.get("descriptions", {}).get("ko", {}).get("value")
                            or entity.get("descriptions", {}).get("en", {}).get("value")
                            or ""
                        )
                    results[q_id] = {
                        "label": label,
                        "description": desc,
                        "is_missing": is_missing,
                    }
                return results
        except httpx.HTTPError as e:
            logging.error(f"❌ Wikidata API 오류: {e}")
            return {}

    def enrich_events(self, events: list) -> list:
        if not events:
            return []

        q_ids_in_batch = {
            event.get("title")
            for event in events
            if event.get("title")
            and event["title"].startswith("Q")
            and event["title"][1:].isdigit()
        }

        all_qid_info = {}
        if q_ids_in_batch:
            cached_qids = get_qids_from_cache(list(q_ids_in_batch))
            qids_to_fetch = q_ids_in_batch - set(cached_qids.keys())

            newly_fetched_qids = {}
            if qids_to_fetch:
                newly_fetched_qids = self.fetch_wikidata_info_in_bulk(
                    list(qids_to_fetch)
                )
                if newly_fetched_qids:
                    save_qids_to_cache(newly_fetched_qids)

            all_qid_info = {**cached_qids, **newly_fetched_qids}

        for event in events:
            event["wikidata_label"] = None
            event["wikidata_description"] = None

            qid = event.get("title")
            if qid in all_qid_info:
                event["wikidata_label"] = all_qid_info[qid]["label"]
                event["wikidata_description"] = all_qid_info[qid]["description"]

        new_api_calls = len(all_qid_info) - len(cached_qids) if q_ids_in_batch else 0
        logging.info(
            f"정보 보강 후 {len(events)}개의 이벤트를 전송했습니다. (신규 API 호출: {new_api_calls}개)"
        )

        return events
