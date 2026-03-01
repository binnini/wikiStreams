import logging

import httpx

from reporter.config import settings

logger = logging.getLogger(__name__)

BLURPLE = 0x5865F2


def _truncate(text: str, limit: int = 1024) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def publish_report(sections: dict[str, str]) -> None:
    date = sections.get("date", "")
    headline = _truncate(sections.get("headline", ""))
    global_interest = _truncate(sections.get("global_interest", ""))
    top_edits = _truncate(sections.get("top_edits", ""))
    controversy = _truncate(sections.get("controversy", "특이사항 없음"))
    numbers = _truncate(sections.get("numbers", ""))

    embeds = [
        {
            "title": f"Wikipedia 일일 트렌드 브리핑 — {date}",
            "description": headline,
            "color": BLURPLE,
            "footer": {"text": "WikiStreams · Powered by Claude Haiku"},
        },
        {
            "title": "숫자 브리핑",
            "color": BLURPLE,
            "fields": [
                {"name": "📊 총 편집 수", "value": numbers, "inline": False},
            ],
        },
        {
            "title": "🌐 글로벌 관심사 & 트렌딩",
            "description": f"**글로벌 관심사**\n{global_interest}\n\n**핵심 편집 하이라이트**\n{top_edits}",
            "color": BLURPLE,
        },
        {
            "title": "⚠️ 논쟁/반달리즘 문서",
            "description": controversy,
            "color": BLURPLE,
        },
    ]

    payload = {"embeds": embeds}

    with httpx.Client(timeout=15) as client:
        resp = client.post(settings.discord_webhook_url, json=payload)
        resp.raise_for_status()

    logger.info("Discord report published for %s", date)
