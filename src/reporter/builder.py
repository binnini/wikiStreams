import json
import logging
import re
from datetime import datetime, timezone, timedelta

import anthropic

from reporter.config import settings
from reporter.fetcher import ReportData
from reporter.prompts import SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def _build_context(data: ReportData, report_date: str) -> str:
    lines = [f"[{report_date} Wikipedia 편집 데이터 요약]", ""]

    lines.append("## 전체 통계 (최근 24시간)")
    lines.append(f"- 총 편집 수: {data.stats.total_edits:,}건")
    lines.append(f"- 활성 편집자: {data.stats.active_users:,}명")
    lines.append(f"- 봇 편집 비율: {data.stats.bot_ratio_pct}%")
    lines.append(f"- 신규 문서 생성: {data.stats.new_articles:,}건")
    if data.peak_hour.hour >= 0:
        lines.append(
            f"- 편집 피크 시간대: {data.peak_hour.hour}시 KST ({data.peak_hour.edits:,}건)"
        )
    lines.append("")

    if data.top_pages:
        lines.append("## 편집량 상위 문서 후보 (봇 제외, 실제 편집만, 24시간)")
        for i, p in enumerate(data.top_pages):
            desc = f" — {p.description}" if p.description else " [설명 없음]"
            badges = []
            if p.is_spike:
                badges.append(f"⚡스파이크 {p.spike_ratio_val}x")
            if p.crosswiki_count >= 2:
                badges.append(f"🌍다국어 {p.crosswiki_count}개 언어판")
            badge_str = f" [{', '.join(badges)}]" if badges else ""
            lines.append(
                f"[{i}] {p.label} ({p.server_name}, {p.edits}회){badge_str}{desc}"
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


def build_report(data: ReportData) -> tuple[dict[str, str], list[list[str]]]:
    """Build the daily report using Claude.

    Selects 5 thematically diverse top pages (via selected_indices) from the
    full candidate list, then generates section text and news keywords.

    Returns:
        sections: Dict of section name → text content for Discord embeds.
        news_keywords: List of keyword lists (one per top-3 selected page) for news searching.
    """
    report_date = datetime.now(KST).strftime("%Y년 %m월 %d일")
    context = _build_context(data, report_date)

    missing_desc_indices = [i for i, p in enumerate(data.top_pages) if not p.description]
    user_message = build_user_message(context, missing_desc_indices)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        parsed = json.loads(json_match.group())
    else:
        parsed = {
            "selected_indices": [],
            "headline": raw,
            "top5_analysis": "",
            "controversy": "",
            "numbers": "",
            "featured": "",
            "news_keywords": [],
        }

    # Apply Claude-generated descriptions for candidates missing one
    descriptions = parsed.pop("descriptions", {})
    if isinstance(descriptions, dict):
        for idx_str, desc in descriptions.items():
            try:
                idx = int(idx_str)
                if 0 <= idx < len(data.top_pages) and not data.top_pages[idx].description and desc:
                    data.top_pages[idx].description = str(desc)
            except (ValueError, TypeError):
                pass

    # Apply LLM-selected topic diversity: filter top_pages to chosen indices
    selected = parsed.pop("selected_indices", [])
    if isinstance(selected, list):
        valid = [
            i for i in selected if isinstance(i, int) and 0 <= i < len(data.top_pages)
        ][:5]
        if valid:
            data.top_pages = [data.top_pages[i] for i in valid]
            logger.info("LLM selected indices: %s", valid)
        else:
            data.top_pages = data.top_pages[:5]
    else:
        data.top_pages = data.top_pages[:5]

    # Separate news_keywords (list[list[str]]) from text sections (dict[str, str])
    news_keywords: list[list[str]] = parsed.pop("news_keywords", [])
    if not isinstance(news_keywords, list):
        news_keywords = []

    sections: dict[str, str] = {k: str(v) for k, v in parsed.items()}
    sections["date"] = report_date

    logger.info(
        "Report built for %s — keywords: %s",
        report_date,
        news_keywords,
    )
    return sections, news_keywords
