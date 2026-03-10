import logging
import re
from typing import Optional

import httpx

from reporter.config import settings
from reporter.fetcher import ReportData

logger = logging.getLogger(__name__)

_RANKS = ["🥇", "🥈", "🥉", "4위", "5위"]
_WIKI_FLAGS: dict[str, str] = {
    "en.wikipedia.org": "🇺🇸",
    "ko.wikipedia.org": "🇰🇷",
    "ja.wikipedia.org": "🇯🇵",
    "de.wikipedia.org": "🇩🇪",
    "fr.wikipedia.org": "🇫🇷",
    "es.wikipedia.org": "🇪🇸",
    "zh.wikipedia.org": "🇨🇳",
    "ru.wikipedia.org": "🇷🇺",
    "ar.wikipedia.org": "🇸🇦",
    "pt.wikipedia.org": "🇧🇷",
    "it.wikipedia.org": "🇮🇹",
    "pl.wikipedia.org": "🇵🇱",
    "uk.wikipedia.org": "🇺🇦",
    "nl.wikipedia.org": "🇳🇱",
    "www.wikidata.org": "🌐",
}


def _wiki_flag(server_name: str) -> str:
    return _WIKI_FLAGS.get(server_name, "🌍")


def _upscale_wiki_thumb(url: str, width: int = 800) -> str:
    """Replace the size component in a Wikipedia thumbnail URL (e.g. 330px → 800px)."""
    return re.sub(r"/\d+px-", f"/{width}px-", url)


def _truncate(text: str, limit: int = 3000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _rank_badge(rank_change: Optional[int]) -> str:
    if rank_change is None:
        return " 🆕"
    if rank_change > 0:
        return f" ▲{rank_change}"
    if rank_change < 0:
        return f" ▼{abs(rank_change)}"
    return " →"


def _header(text: str) -> dict:
    return {
        "type": "header",
        "text": {"type": "plain_text", "text": _truncate(text, 150), "emoji": True},
    }


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": _truncate(text)}}


def _fields(*items: str) -> dict:
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": t} for t in items],
    }


def _divider() -> dict:
    return {"type": "divider"}


def _image_block(url: str, alt: str = "image") -> dict:
    return {"type": "image", "image_url": url, "alt_text": alt}


def _build_top5_blocks(data: ReportData, top5_analysis: str) -> list[dict]:
    blocks: list[dict] = [_header("📝 오늘의 Top 5 위키 문서")]

    if top5_analysis:
        blocks.append(_section(top5_analysis))

    for i, p in enumerate(data.top_pages[:5]):
        display = p.label or p.title
        badge = _rank_badge(p.rank_change)
        flag = _wiki_flag(p.server_name)
        lang = (
            p.server_name.split(".")[0].upper()
            if "." in p.server_name
            else p.server_name
        )

        signal_parts = []
        if p.is_spike:
            signal_parts.append(f"⚡ {p.spike_ratio_val}x")
        if p.crosswiki_count >= 2:
            signal_parts.append(f"🌍 {p.crosswiki_count}개 언어판")
        signal_line = ("  ·  " + "  ·  ".join(signal_parts)) if signal_parts else ""

        desc_part = f"\n> {p.description}" if p.description else ""
        title_line = f"*{_RANKS[i]}{badge}  {_truncate(display, 100)}*"

        if p.lang_editions:
            ed_parts = []
            for ed in p.lang_editions:
                ed_flag = _wiki_flag(ed.server_name)
                ed_lang = (
                    ed.server_name.split(".")[0].upper()
                    if "." in ed.server_name
                    else ed.server_name
                )
                ed_parts.append(f"{ed_flag} {ed_lang} {ed.edits:,}회")
            total = sum(ed.edits for ed in p.lang_editions)
            lang_str = "  ·  ".join(ed_parts) + f"  |  *합계 {total:,}회*"
            text = f"{title_line}\n<{p.url}|🔗 문서 보기>\n{lang_str}{signal_line}{desc_part}"
        else:
            text = (
                f"{title_line}\n<{p.url}|🔗 문서 보기>\n"
                f"{flag} {lang}  ·  *{p.edits:,}회* 편집{signal_line}"
                f"{desc_part}"
            )
        blocks.append(_section(text))

    if data.news_items:
        news_lines = [
            f"• <{n.link}|{_truncate(n.title, 80)}>"
            + (f" _— {n.source}_" if n.source else "")
            for n in data.news_items
        ]
        blocks.append(_section("📰 *관련 최신 뉴스*\n" + "\n".join(news_lines)))

    blocks.append(_divider())
    return blocks


def _build_featured_blocks(data: ReportData, featured_text: str) -> list[dict]:
    fa = data.featured_article
    if not fa.title:
        return []

    blocks: list[dict] = [_header("📚 교양 코너 — Wikipedia 오늘의 특집 문서")]

    content = featured_text or fa.extract or fa.description or ""
    title_md = f"*<{fa.url}|{fa.title}>*" if fa.url else f"*{fa.title}*"
    blocks.append(_section(f"{title_md}\n{_truncate(content, 2800)}"))

    if fa.thumbnail_url:
        blocks.append(_image_block(fa.thumbnail_url, fa.title))

    return blocks


def publish_report(sections: dict[str, str], data: ReportData) -> None:
    date = sections.get("date", "")
    headline = _truncate(sections.get("headline", ""))
    top5_analysis = sections.get("top5_analysis", "")
    controversy = _truncate(sections.get("controversy", "특이사항 없음"))
    featured_text = sections.get("featured", "")

    thumbnail_url = data.top_pages[0].thumbnail_url if data.top_pages else None

    # 헤드라인 블록
    headline_blocks: list[dict] = [
        _header(f"Wikipedia 일일 트렌드 브리핑 — {date}"),
        _section(headline),
    ]
    if thumbnail_url:
        headline_blocks.append(
            _image_block(_upscale_wiki_thumb(thumbnail_url), "오늘의 1위 문서 썸네일")
        )
    headline_blocks.append(_divider())

    # 숫자 브리핑 블록
    stats = data.stats
    stat_items = [
        f"✏️ *총 편집 수*\n{stats.total_edits:,}",
        f"👥 *활성 편집자*\n{stats.active_users:,}명",
        f"🤖 *봇 편집 비율*\n{stats.bot_ratio_pct}%",
        f"📄 *신규 문서*\n{stats.new_articles:,}개",
    ]
    if data.peak_hour.hour >= 0:
        hour = data.peak_hour.hour
        period = "오전" if hour < 12 else "오후"
        display_hour = hour if hour <= 12 else hour - 12
        stat_items.append(
            f"⏰ *편집 피크 시간대*\n{period} {display_hour}시 (KST) — {data.peak_hour.edits:,}건"
        )
    stats_blocks: list[dict] = [
        _header("📊 숫자로 보는 위키백과 (최근 24시간)"),
        _fields(*stat_items),
        _divider(),
    ]

    # 논쟁/반달리즘 블록
    controversy_blocks: list[dict] = [
        _header("⚠️ 논쟁 및 반달리즘 (편집 분쟁) 주요 문서"),
        _section(controversy),
    ]
    for p in data.revert_pages[:5]:
        flag = _wiki_flag(p.server_name)
        text = (
            f"{flag} *{p.label or '문서'}*\n"
            f"되돌리기율 *{p.revert_rate_pct}%*  ·  "
            f"총 {p.total_edits}회 편집 중 *{p.reverts}회* 되돌림"
        )
        controversy_blocks.append(_section(text))
    controversy_blocks.append(_divider())

    blocks: list[dict] = []
    blocks += headline_blocks
    blocks += stats_blocks
    blocks += _build_top5_blocks(data, top5_analysis)
    blocks += controversy_blocks
    blocks += _build_featured_blocks(data, featured_text)

    payload = {
        "text": f"Wikipedia 일일 트렌드 브리핑 — {date}",
        "blocks": blocks,
    }

    with httpx.Client(timeout=15) as client:
        resp = client.post(settings.slack_webhook_url, json=payload)
        resp.raise_for_status()

    logger.info("Slack report published for %s (%d blocks)", date, len(blocks))
