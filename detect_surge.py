import requests
import json
import pandas as pd
import argparse
from textwrap import dedent


def get_wikidata_labels_in_bulk(q_ids: list) -> dict:
    """
    여러 개의 Q-ID 리스트를 받아 위키데이터 API에 한 번의 요청으로
    이름(Label)과 설명(Description)을 가져옵니다.

    Args:
        q_ids (list): 조회할 Q-ID 문자열의 리스트.

    Returns:
        dict: Q-ID를 키로, 이름과 설명을 값으로 갖는 딕셔너리.
              예: {"Q123": {"label": "이름", "description": "설명"}}
    """
    if not q_ids:
        return {}

    api_endpoint = "https://www.wikidata.org/w/api.php"
    # 여러 ID를 파이프(|)로 연결하여 전달
    ids_string = "|".join(q_ids)

    params = {
        "action": "wbgetentities",
        "ids": ids_string,
        "props": "labels|descriptions",
        "languages": "ko|en",
        "format": "json",
    }
    headers = {"User-Agent": "wikiStreams-analysis-script/0.2"}

    try:
        response = requests.get(api_endpoint, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        results = {}
        entities = data.get("entities", {})
        for q_id, entity in entities.items():
            label_ko = entity.get("labels", {}).get("ko", {}).get("value")
            label_en = entity.get("labels", {}).get("en", {}).get("value")
            label = label_ko or label_en or "-"

            desc_ko = entity.get("descriptions", {}).get("ko", {}).get("value")
            desc_en = entity.get("descriptions", {}).get("en", {}).get("value")
            description = desc_ko or desc_en or "-"

            results[q_id] = {"label": label, "description": description}
        return results

    except requests.exceptions.RequestException as e:
        print(f"\n[Wikidata API 오류] {e}")
        return {}


def detect_and_enrich_surge_trends(
    recent_hours: int, previous_hours: int, min_edits: int
):
    """
    급상승 트렌드를 분석하고, Q-ID 항목에 대한 정보를 위키데이터에서 가져와 সমৃদ্ধ하게 만듭니다.
    """
    url = "http://localhost:8082/druid/v2/sql"
    sql_query = f"""
    WITH
    RecentChanges AS (
      SELECT "title", "server_name", COUNT(*) AS RecentCount
      FROM "wikimedia.recentchange"
      WHERE "__time" BETWEEN CURRENT_TIMESTAMP - INTERVAL '{recent_hours}' HOUR AND CURRENT_TIMESTAMP
        AND "bot" = FALSE AND "type" IN ('edit', 'new')
        AND "namespace" IN (0, 4, 6, 14) AND "minor" = FALSE
      GROUP BY 1, 2
    ),
    PreviousChanges AS (
      SELECT "title", "server_name", COUNT(*) AS PreviousCount
      FROM "wikimedia.recentchange"
      WHERE "__time" BETWEEN CURRENT_TIMESTAMP - INTERVAL '{recent_hours + previous_hours}' HOUR AND CURRENT_TIMESTAMP - INTERVAL '{recent_hours}' HOUR
        AND "bot" = FALSE AND "type" IN ('edit', 'new')
        AND "namespace" IN (0, 4, 6, 14) AND "minor" = FALSE
      GROUP BY 1, 2
    )
    SELECT
      r.title, r.server_name, r.RecentCount,
      COALESCE(p.PreviousCount, 0) AS PreviousCount,
      r.RecentCount * 1.0 / GREATEST(p.PreviousCount, 1) AS SurgeRatio
    FROM RecentChanges r
    LEFT JOIN PreviousChanges p ON r.title = p.title AND r.server_name = p.server_name
    WHERE r.RecentCount >= {min_edits}
    ORDER BY SurgeRatio DESC, RecentCount DESC
    LIMIT 20
    """

    payload = {"query": dedent(sql_query), "context": {"sqlTimeZone": "Asia/Seoul"}}
    headers = {"Content-Type": "application/json"}

    print(
        f"Druid에 쿼리를 전송합니다 (최근 {recent_hours}시간 vs 이전 {previous_hours}시간)..."
    )
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        data = response.json()

        if not data:
            print("분석할 데이터가 없습니다.")
            return

        df = pd.DataFrame(data)

        # --- Q-ID 정보 통합 ---
        q_ids = [
            title
            for title in df["title"]
            if title.startswith("Q") and title[1:].isdigit()
        ]
        if q_ids:
            print(f"Wikidata에서 {len(q_ids)}개 항목의 정보를 조회합니다...")
            wikidata_info = get_wikidata_labels_in_bulk(q_ids)
            # map 함수를 사용하여 정보를 새로운 컬럼에 추가
            df["Label"] = df["title"].map(
                lambda x: wikidata_info.get(x, {}).get("label", "-")
            )
            df["Description"] = df["title"].map(
                lambda x: wikidata_info.get(x, {}).get("description", "-")
            )
        else:
            df["Label"] = "-"
            df["Description"] = "-"

        # --- 결과 출력 ---
        # 보기 좋게 컬럼 순서 조정
        df = df[
            [
                "title",
                "Label",
                "Description",
                "server_name",
                "RecentCount",
                "PreviousCount",
                "SurgeRatio",
            ]
        ]
        print("\n--- 편집 급상승 트렌드 분석 결과 (통합) ---")
        pd.options.display.float_format = "{:.2f}".format
        # 터미널 너비에 맞게 출력 조정
        pd.set_option("display.width", 1000)
        pd.set_option("display.max_colwidth", 40)
        print(df)
        print("---------------------------------------------")

    except requests.exceptions.RequestException as e:
        print(f"오류가 발생했습니다: {e}")
        if response is not None:
            print(f"서버 응답: {response.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="편집 급상승 트렌드를 분석하고 Q-ID 정보를 통합하여 보여줍니다."
    )
    # ... (이하 인자 파싱 부분은 이전과 동일)
    parser.add_argument("--recent-hours", type=int, default=1)
    parser.add_argument("--previous-hours", type=int, default=1)
    parser.add_argument("--min-edits", type=int, default=10)
    args = parser.parse_args()
    detect_and_enrich_surge_trends(
        args.recent_hours, args.previous_hours, args.min_edits
    )
