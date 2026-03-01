import logging
from datetime import datetime, timezone, timedelta

import anthropic

from reporter.config import settings
from reporter.fetcher import ReportData

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

SYSTEM_PROMPT = """당신은 한국어 Wikipedia 트렌드 뉴스 에디터입니다.
매일 위키미디어 편집 데이터를 분석해 간결하고 읽기 쉬운 한국어 뉴스 브리핑을 작성합니다.

작성 원칙:
- 제공된 데이터에만 근거하여 작성하고, 데이터에 없는 사실을 추측하거나 창작하지 마세요.
- 문서가 트렌딩인 '이유'를 추론하여 설명하세요 (단순히 "편집이 많았다"가 아닌, 어떤 사건·맥락과 연관됐는지).
- 다국어 동시 트렌딩은 글로벌 관심도의 증거이므로 반드시 강조하세요.
- 각 섹션은 2-3문장으로 간결하게 작성합니다.
- 숫자는 항상 구체적으로 인용하세요 (예: "약 200만 건", "상위 5개 중 3개가 영어판")."""


def _build_context(data: ReportData, report_date: str) -> str:
    lines = [f"[{report_date} Wikipedia 편집 데이터 요약]", ""]

    lines.append("## 전체 통계 (최근 24시간)")
    lines.append(f"- 총 편집 수: {data.stats.total_edits:,}건")
    lines.append(f"- 활성 편집자: {data.stats.active_users:,}명")
    lines.append(f"- 봇 편집 비율: {data.stats.bot_ratio_pct}%")
    lines.append(f"- 신규 문서 생성: {data.stats.new_articles:,}건")
    if data.peak_hour.hour >= 0:
        lines.append(f"- 편집 피크 시간대: {data.peak_hour.hour}시 KST ({data.peak_hour.edits:,}건)")
    lines.append("")

    if data.top_pages:
        lines.append("## 편집량 상위 문서 (봇 제외, 24시간)")
        for i, p in enumerate(data.top_pages[:5], 1):
            desc = f" — {p.description}" if p.description else ""
            lines.append(f"{i}. {p.label} ({p.server_name}, {p.edits}회 편집){desc}")
        lines.append("")

    if data.spike_pages:
        lines.append("## 실시간 급등 문서 (최근 15분 스파이크)")
        for p in data.spike_pages[:5]:
            lines.append(
                f"- {p.label} ({p.server_name}): spike_ratio={p.spike_ratio}x, 15분간 {p.edits_15m}회 편집"
            )
        lines.append("")

    if data.crosswiki_pages:
        lines.append("## 다국어 동시 트렌딩 (최근 15분)")
        for p in data.crosswiki_pages[:5]:
            lines.append(
                f"- {p.title}: {p.wiki_count}개 언어판 동시 편집 ({p.total_edits}회) — {p.wikis}"
            )
        lines.append("")

    if data.revert_pages:
        lines.append("## 논쟁/반달리즘 문서 (되돌리기 상위, 24시간)")
        for p in data.revert_pages:
            lines.append(
                f"- {p.label} ({p.server_name}): {p.reverts}회 되돌리기 / 전체 {p.total_edits}회 ({p.revert_rate_pct}%)"
            )
        lines.append("")

    fa = data.featured_article
    if fa.title:
        lines.append("## Wikipedia 오늘의 특집 문서 (영문 원문)")
        lines.append(f"- 제목: {fa.title}")
        if fa.description:
            lines.append(f"- 설명: {fa.description}")
        if fa.extract:
            lines.append(f"- 요약: {fa.extract}")
        lines.append("")

    return "\n".join(lines)


def build_report(data: ReportData) -> dict[str, str]:
    report_date = datetime.now(KST).strftime("%Y년 %m월 %d일")
    context = _build_context(data, report_date)

    user_message = f"""{context}

위 데이터를 바탕으로 다음 6개 섹션으로 한국어 뉴스 브리핑을 작성해주세요.
각 섹션은 JSON 키로 반환하되, 아래 형식을 정확히 따르세요.

섹션 구성:
1. headline: 오늘 가장 주목할 Wikipedia 동향 1-2개를 선정해 2-3문장으로 요약. 왜 오늘 이 문서들이 주목받는지 맥락을 포함하세요.
2. global_interest: 다국어 동시 트렌딩 문서 중심의 글로벌 관심사 분석 (2-3문장). 몇 개 언어판에서 동시에 편집됐는지 숫자를 포함하세요.
3. top_edits: 편집량 1-2위 문서의 하이라이트 (2-3문장). 단순 나열이 아닌 "왜 오늘 이 문서인가"에 초점을 맞추세요.
4. controversy: 되돌리기(revert) 상위 문서의 현황과 의미 (2-3문장). 데이터가 없으면 "특이사항 없음"
5. numbers: 오늘의 핵심 수치 요약 — 총 편집 수, 활성 편집자, 봇 비율, 신규 문서, 피크 시간대를 자연스러운 한 문단으로 서술하세요.
6. featured: 오늘의 Wikipedia 특집 문서 소개 — 제목을 한국어로 번역하고, 어떤 내용인지, 왜 주목할 만한지 2-3문장. 데이터 없으면 "특집 문서 정보 없음"

반드시 아래 형식으로 응답하세요 (JSON):
{{
  "headline": "...",
  "global_interest": "...",
  "top_edits": "...",
  "controversy": "...",
  "numbers": "...",
  "featured": "..."
}}"""

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    import json
    import re

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        sections = json.loads(json_match.group())
    else:
        sections = {
            "headline": raw,
            "global_interest": "",
            "top_edits": "",
            "controversy": "",
            "numbers": "",
            "featured": "",
        }

    sections["date"] = report_date
    logger.info("Report built for %s", report_date)
    return sections
