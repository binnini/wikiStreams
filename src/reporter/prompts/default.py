"""Default prompt strings for the WikiStreams daily reporter (Claude calls)."""

SYSTEM_PROMPT = """당신은 한국어 Wikipedia 트렌드 뉴스 에디터입니다.
매일 위키미디어 편집 데이터를 분석해 간결하고 읽기 쉬운 한국어 뉴스 브리핑을 작성합니다.

작성 원칙:
- 제공된 데이터에만 근거하여 작성하고, 데이터에 없는 사실을 추측하거나 창작하지 마세요.
- 문서가 트렌딩인 '이유'를 추론하여 설명하세요 (단순히 "편집이 많았다"가 아닌, 어떤 사건·맥락과 연관됐는지).
- 다국어 동시 트렌딩은 글로벌 관심도의 증거이므로 반드시 강조하세요.
- 각 섹션은 2-3문장으로 간결하게 작성합니다.
- 숫자는 항상 구체적으로 인용하세요 (예: "약 200만 건", "상위 5개 중 3개가 영어판")."""


def build_user_message(context: str, missing_desc_indices: list[int]) -> str:
    """Build the full user message for the daily report Claude call.

    Args:
        context: Pre-built data summary string from _build_context().
        missing_desc_indices: Candidate page indices that lack a Korean description.
                              Claude will be asked to fill these in.
    """
    if missing_desc_indices:
        desc_instruction = (
            f"7. descriptions: 인덱스 {missing_desc_indices} 항목에 대해 반드시 "
            f"짧은 한국어 설명(20자 이내)을 작성하세요. "
            f"문서 제목·서버명을 바탕으로 추론하세요. "
            f'형식: {{"인덱스": "설명텍스트"}} — {len(missing_desc_indices)}개 모두 포함 필수.'
        )
        schema_entries = ", ".join(f'"{i}": "..."' for i in missing_desc_indices)
        desc_schema = f',\n  "descriptions": {{{schema_entries}}}'
    else:
        desc_instruction = (
            "7. descriptions: 모든 후보에 설명이 있으므로 빈 객체 {} 반환."
        )
        desc_schema = ',\n  "descriptions": {}'

    return f"""{context}

위 데이터를 바탕으로 JSON 응답을 작성해주세요.

--- 사전 처리 (내부용, 표시 안 됨) ---
후보 목록([0], [1], ...)에서 주제가 서로 다른 5개의 인덱스를 먼저 고르세요.
선택 기준:
- 같은 사건/인물에 관한 문서는 1개만 선택
- ⚡스파이크 · 🌍다국어 트렌딩이 있으면 우선 고려
- 정치/스포츠/과학/문화 등 분야 다양성 선호
- 선택 순서는 편집량 내림차순 유지 (편집 수가 많은 문서를 앞에)
- 후보가 5개 미만이면 전체 선택
고른 인덱스는 JSON의 "selected_indices" 키에 담아주세요.

--- 브리핑 작성 (선택한 5개 문서 기준) ---
1. headline: 오늘 가장 주목할 Wikipedia 동향 1-2개를 선정해 2-3문장으로 요약. 왜 오늘 이 문서들이 주목받는지 맥락을 포함하세요.
2. top5_analysis: 선택된 5개 문서들의 통합 분석 (2-3문장). 스파이크·다국어 문서를 강조하고, "왜 오늘 이 문서인가"에 초점을 맞추세요.
3. controversy: 되돌리기(revert)가 집중된 주제·분야의 공통 맥락 (1-2문장, 도입부). 개별 문서명과 수치는 언급하지 마세요 — 문서별 통계는 별도로 표시됩니다. 어떤 유형의 주제(정치·행정·문화 등)에서 편집 분쟁이 발생하고 있는지 설명하세요. 데이터가 없으면 "특이사항 없음"
4. numbers: 오늘의 핵심 수치 요약 — 총 편집 수, 활성 편집자, 봇 비율, 신규 문서, 피크 시간대를 자연스러운 한 문단으로 서술하세요.
5. featured: 오늘의 Wikipedia 특집 문서 소개 — 제목을 한국어로 번역하고, 어떤 내용인지, 왜 주목할 만한지 2-3문장. 데이터 없으면 "특집 문서 정보 없음"
6. news_keywords: 선택한 5개 문서 중 앞의 3개에 대한 Google 뉴스 검색용 핵심 키워드.
   - 고유명사(인물명, 국가명, 사건명)만 1-3개씩 추출하세요.
   - 검색 효율을 위해 문서 원어(영어/한국어 등) 기준으로 작성하세요.
{desc_instruction}

반드시 아래 형식으로 응답하세요 (JSON):
{{
  "selected_indices": [i1, i2, i3, i4, i5],
  "headline": "...",
  "top5_analysis": "...",
  "controversy": "...",
  "numbers": "...",
  "featured": "...",
  "news_keywords": [["키워드1A", "키워드1B"], ["키워드2A"], ["키워드3A", "키워드3B"]]{desc_schema}
}}"""
