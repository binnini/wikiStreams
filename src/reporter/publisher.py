import logging
import re
from typing import Optional

import httpx

from reporter.config import settings
from reporter.fetcher import ReportData

logger = logging.getLogger(__name__)

BLURPLE = 0x5865F2
GOLD = 0xFFD700
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


def _truncate(text: str, limit: int = 1024) -> str:
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


def _build_top5_embed(data: ReportData, top5_analysis: str) -> dict:
    fields = []
    for i, p in enumerate(data.top_pages[:5]):
        display = p.label or p.title
        badge = _rank_badge(p.rank_change)
        flag = _wiki_flag(p.server_name)
        lang = (
            p.server_name.split(".")[0].upper()
            if "." in p.server_name
            else p.server_name
        )

        # Spike / cross-wiki badges
        signal_parts = []
        if p.is_spike:
            signal_parts.append(f"⚡ {p.spike_ratio_val}x")
        if p.crosswiki_count >= 2:
            signal_parts.append(f"🌍 {p.crosswiki_count}개 언어판")
        signal_line = ("  ·  " + "  ·  ".join(signal_parts)) if signal_parts else ""

        desc_part = f"\n> {p.description}" if p.description else ""

        if p.lang_editions:
            # Multi-language grouped: show each edition's edit count + total
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
            lang_str = "  ·  ".join(ed_parts) + f"  |  **합계 {total:,}회**"
            value = f"[🔗 문서 보기]({p.url})\n{lang_str}{signal_line}{desc_part}"
        else:
            value = (
                f"[🔗 문서 보기]({p.url})\n"
                f"{flag} {lang}  ·  **{p.edits:,}회** 편집{signal_line}"
                f"{desc_part}"
            )
        fields.append(
            {
                "name": _truncate(f"{_RANKS[i]}{badge}  {display}", 256),
                "value": _truncate(value, 1024),
                "inline": False,
            }
        )

    if data.news_items:
        news_lines = [
            f"• [{_truncate(n.title, 80)}]({n.link})"
            + (f" *— {n.source}*" if n.source else "")
            for n in data.news_items
        ]
        fields.append(
            {
                "name": "📰 관련 최신 뉴스",
                "value": _truncate("\n".join(news_lines), 1024),
                "inline": False,
            }
        )

    embed: dict = {
        "title": "📝 오늘의 Top 5 위키 문서",
        "description": _truncate(top5_analysis, 4096) if top5_analysis else None,
        "color": BLURPLE,
        "fields": fields,
    }
    # Remove None description to keep payload clean
    if embed["description"] is None:
        del embed["description"]

    if data.top_pages and data.top_pages[0].thumbnail_url:
        embed["thumbnail"] = {"url": data.top_pages[0].thumbnail_url}

    return embed


def _build_featured_embed(data: ReportData, featured_text: str) -> Optional[dict]:
    fa = data.featured_article
    if not fa.title:
        return None

    embed: dict = {
        "title": "📚 교양 코너 — Wikipedia 오늘의 특집 문서",
        "color": GOLD,
        "fields": [
            {
                "name": fa.title,
                "value": _truncate(featured_text or fa.extract or fa.description, 1024),
                "inline": False,
            }
        ],
        "footer": {
            "text": "Wikipedia · Featured Article of the Day · en.wikipedia.org 선정"
        },
    }
    if fa.url:
        embed["url"] = fa.url
    if fa.thumbnail_url:
        embed["thumbnail"] = {"url": fa.thumbnail_url}

    return embed


def publish_report(sections: dict[str, str], data: ReportData) -> None:
    date = sections.get("date", "")
    headline = _truncate(sections.get("headline", ""))
    top5_analysis = sections.get("top5_analysis", "")
    controversy = _truncate(sections.get("controversy", "특이사항 없음"))
    featured_text = sections.get("featured", "")

    # 숫자 브리핑 — Big Number 인라인 필드
    stats = data.stats
    numbers_fields: list[dict] = [
        {
            "name": "✏️ 총 편집 수",
            "value": f"**{stats.total_edits:,}**",
            "inline": True,
        },
        {
            "name": "👥 활성 편집자",
            "value": f"**{stats.active_users:,}**명",
            "inline": True,
        },
        {
            "name": "🤖 봇 편집 비율",
            "value": f"**{stats.bot_ratio_pct}%**",
            "inline": True,
        },
        {
            "name": "📄 신규 문서",
            "value": f"**{stats.new_articles:,}**개",
            "inline": True,
        },
    ]
    if data.peak_hour.hour >= 0:
        hour = data.peak_hour.hour
        period = "오전" if hour < 12 else "오후"
        display_hour = hour if hour <= 12 else hour - 12
        numbers_fields.append(
            {
                "name": "⏰ 편집 피크 시간대",
                "value": f"**{period} {display_hour}시** (KST) — {data.peak_hour.edits:,}건",
                "inline": True,
            }
        )

    # 논쟁/반달리즘 — revert_pages 구조화 필드
    revert_fields = [
        {
            "name": f"{_wiki_flag(p.server_name)} {p.label or '문서'}",
            "value": (
                f"되돌리기율 **{p.revert_rate_pct}%**"
                f"  ·  총 {p.total_edits}회 편집 중 **{p.reverts}회** 되돌림"
            ),
            "inline": False,
        }
        for p in data.revert_pages[:5]
    ]

    featured_embed = _build_featured_embed(data, featured_text)

    headline_embed: dict = {
        "title": f"Wikipedia 일일 트렌드 브리핑 — {date}",
        "description": headline,
        "color": BLURPLE,
        "footer": {"text": "WikiStreams · Powered by Claude Haiku"},
    }
    if data.top_pages and data.top_pages[0].thumbnail_url:
        headline_embed["image"] = {
            "url": _upscale_wiki_thumb(data.top_pages[0].thumbnail_url)
        }

    embeds = [
        headline_embed,
        {
            "title": "📊 숫자로 보는 위키백과 (최근 24시간)",
            "color": BLURPLE,
            "fields": numbers_fields,
        },
        _build_top5_embed(data, top5_analysis),
        {
            "title": "⚠️ 논쟁 및 반달리즘 (편집 분쟁) 주요 문서",
            "description": controversy,
            "color": BLURPLE,
            **({"fields": revert_fields} if revert_fields else {}),
        },
        *([] if featured_embed is None else [featured_embed]),
    ]

    payload = {"embeds": embeds}

    with httpx.Client(timeout=15) as client:
        resp = client.post(settings.discord_webhook_url, json=payload)
        resp.raise_for_status()

    logger.info("Discord report published for %s (%d embeds)", date, len(embeds))
