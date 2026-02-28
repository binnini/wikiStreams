from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, Optional


class WikimediaEvent(BaseModel):
    """Wikimedia Recent Change 이벤트 필수 필드 스키마.

    extra="allow"로 설정하여 정의되지 않은 필드는 그대로 통과시킨다.
    ClickHouse 등 하류 컨슈머가 필요로 하는 미정의 필드들을 보존하기 위함.
    """

    # 필수 필드
    title: str
    server_name: str
    type: str
    namespace: int
    timestamp: int
    user: str
    bot: bool

    # Enricher에서 추가되는 필드 (선택)
    wikidata_label: Optional[str] = None
    wikidata_description: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class WikidataApiResponse(BaseModel):
    """Wikidata API (wbgetentities) 응답 최상위 스키마.

    entities 키의 존재를 보장하며, 알 수 없는 추가 필드는 허용한다.
    """

    entities: Dict[str, Any]

    model_config = ConfigDict(extra="allow")
