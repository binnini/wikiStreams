import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote

import httpx

from reporter.config import settings

logger = logging.getLogger(__name__)

CLICKHOUSE_URL = f"http://{settings.clickhouse_host}:{settings.clickhouse_port}"
KST = timezone(timedelta(hours=9))
_WIKI_API_HEADERS = {"User-Agent": "WikiStreams/1.0 (https://github.com/wikistreams)"}


def wiki_url(server_name: str, title: str) -> str:
    path = quote(title.replace(" ", "_"), safe="")
    return f"https://{server_name}/wiki/{path}"


@dataclass
class OverallStats:
    total_edits: int = 0
    active_users: int = 0
    bot_ratio_pct: float = 0.0
    new_articles: int = 0


@dataclass
class TopPage:
    label: str = ""
    title: str = ""
    description: str = ""
    server_name: str = ""
    edits: int = 0
    url: str = ""
    thumbnail_url: str = ""
    rank_change: Optional[int] = None  # None=new entry, 0=same, +N=improved, -N=dropped
    # Enriched from spike/crosswiki data
    is_spike: bool = False
    spike_ratio_val: float = 0.0
    crosswiki_count: int = 0  # 0 = not cross-wiki


@dataclass
class SpikePage:
    label: str = ""
    title: str = ""
    server_name: str = ""
    edits_15m: int = 0
    spike_ratio: float = 0.0


@dataclass
class CrossWikiPage:
    title: str = ""
    wiki_count: int = 0
    total_edits: int = 0
    wikis: str = ""


@dataclass
class RevertPage:
    label: str = ""
    server_name: str = ""
    total_edits: int = 0
    reverts: int = 0
    revert_rate_pct: float = 0.0


@dataclass
class NewsItem:
    title: str = ""
    link: str = ""
    source: str = ""


@dataclass
class FeaturedArticle:
    title: str = ""
    description: str = ""
    extract: str = ""
    url: str = ""
    thumbnail_url: str = ""


@dataclass
class PeakHour:
    hour: int = -1
    edits: int = 0


@dataclass
class ReportData:
    stats: OverallStats = field(default_factory=OverallStats)
    top_pages: list[TopPage] = field(default_factory=list)
    spike_pages: list[SpikePage] = field(default_factory=list)
    crosswiki_pages: list[CrossWikiPage] = field(default_factory=list)
    revert_pages: list[RevertPage] = field(default_factory=list)
    news_items: list[NewsItem] = field(default_factory=list)
    featured_article: FeaturedArticle = field(default_factory=FeaturedArticle)
    peak_hour: PeakHour = field(default_factory=PeakHour)


def _query(sql: str) -> list[dict]:
    params = {"query": sql, "default_format": "JSONEachRow"}
    with httpx.Client(timeout=30) as client:
        resp = client.get(CLICKHOUSE_URL, params=params)
        resp.raise_for_status()
    rows = []
    for line in resp.text.strip().splitlines():
        if line:
            rows.append(json.loads(line))
    return rows


_RSS_EDITIONS = [
    "hl=ko&gl=KR&ceid=KR:ko",
    "hl=en&gl=US&ceid=US:en",
]


def _fetch_news(
    query: str,
    relevance_keywords: Optional[set[str]] = None,
    max_items: int = 2,
) -> list[NewsItem]:
    """Fetch news from Google News RSS.

    Tries Korean edition first; falls back to English if no results.

    Args:
        query: Search query string.
        relevance_keywords: If provided, only keep news whose headline contains
            at least one of these keywords (case-insensitive).
            Falls back to words of length >= 4 from query when None.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    if relevance_keywords is None:
        relevance_keywords = {w.lower() for w in query.split() if len(w) >= 4}

    encoded = quote(query)
    for i, edition in enumerate(_RSS_EDITIONS):
        rss_url = f"https://news.google.com/rss/search?q={encoded}&{edition}"
        # Korean edition: search query already provides relevance; skip keyword filter
        # English edition: apply keyword filter to avoid off-topic results
        apply_relevance = (i > 0) and bool(relevance_keywords)
        try:
            with httpx.Client(timeout=5, follow_redirects=True) as client:
                resp = client.get(rss_url)
                resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items: list[NewsItem] = []
            for item in root.findall(".//item"):
                if len(items) >= max_items:
                    break
                title_el = item.find("title")
                link_el = item.find("link")
                source_el = item.find("source")
                pubdate_el = item.find("pubDate")

                # 48h freshness filter
                if pubdate_el is not None and pubdate_el.text:
                    try:
                        pub_dt = parsedate_to_datetime(pubdate_el.text)
                        if pub_dt < cutoff:
                            continue
                    except Exception:
                        pass  # unparseable date: allow through

                link_url = ""
                if link_el is not None:
                    link_url = (link_el.text or link_el.get("href", "")).strip()
                if title_el is None or not link_url:
                    continue

                news_title = title_el.text or ""
                if apply_relevance and not any(
                    kw in news_title.lower() for kw in relevance_keywords  # type: ignore[union-attr]
                ):
                    continue

                items.append(
                    NewsItem(
                        title=news_title,
                        link=link_url,
                        source=source_el.text if source_el is not None else "",
                    )
                )

            if items:
                return items  # found results — no need for English fallback
        except Exception as e:
            logger.warning("News fetch failed for '%s' (%s): %s", query, edition, e)

    return []


def fetch_news_with_keywords(
    pages: list[TopPage], keywords_per_page: list[list[str]]
) -> list[NewsItem]:
    """Fetch news using Claude-extracted keywords for better relevance.

    Args:
        pages: Top pages to fetch news for (uses first 3).
        keywords_per_page: Claude-extracted keyword lists, one per page.
    """
    all_news: list[NewsItem] = []
    for i, page in enumerate(pages[:3]):
        kws = keywords_per_page[i] if i < len(keywords_per_page) else []
        if not kws:
            kws = [page.label or page.title]
        # Primary search query: join first two keywords
        query = " ".join(kws[:2])
        relevance = {kw.lower() for kw in kws if len(kw) >= 3}
        all_news.extend(_fetch_news(query, relevance_keywords=relevance))
    return all_news[:5]


def _fetch_featured_article(date: datetime) -> FeaturedArticle:
    y = date.strftime("%Y")
    m = date.strftime("%m")
    d = date.strftime("%d")
    url = f"https://en.wikipedia.org/api/rest_v1/feed/featured/{y}/{m}/{d}"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers=_WIKI_API_HEADERS)
            resp.raise_for_status()
        tfa = resp.json().get("tfa", {})
        if not tfa:
            return FeaturedArticle()
        return FeaturedArticle(
            title=tfa.get("title", ""),
            description=tfa.get("description", ""),
            extract=tfa.get("extract", "")[:600],
            url=tfa.get("content_urls", {}).get("desktop", {}).get("page", ""),
            thumbnail_url=tfa.get("thumbnail", {}).get("source", ""),
        )
    except Exception as e:
        logger.warning("Failed to fetch featured article: %s", e)
        return FeaturedArticle()


def _fetch_thumbnail(server_name: str, title: str) -> str:
    if "wikidata" in server_name:
        return ""
    encoded = quote(title.replace(" ", "_"), safe="")
    url = f"https://{server_name}/api/rest_v1/page/summary/{encoded}"
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(url, headers=_WIKI_API_HEADERS)
            resp.raise_for_status()
        return resp.json().get("thumbnail", {}).get("source", "")
    except Exception as e:
        logger.warning("Thumbnail fetch failed for '%s/%s': %s", server_name, title, e)
        return ""


def fetch_report_data() -> ReportData:
    data = ReportData()
    now_kst = datetime.now(KST)

    # 1. Overall stats (24h)
    time_filter = "event_time >= now() - INTERVAL 24 HOUR"
    try:
        rows = _query(
            f"SELECT count() AS value FROM wikimedia.events WHERE {time_filter}"
        )
        data.stats.total_edits = int(rows[0]["value"]) if rows else 0

        rows = _query(
            f"SELECT uniq(user) AS value FROM wikimedia.events WHERE {time_filter}"
        )
        data.stats.active_users = int(rows[0]["value"]) if rows else 0

        rows = _query(
            f"SELECT round(100.0 * countIf(bot = 1) / count(), 1) AS value "
            f"FROM wikimedia.events WHERE {time_filter}"
        )
        data.stats.bot_ratio_pct = float(rows[0]["value"]) if rows else 0.0

        rows = _query(
            f"SELECT count() AS value FROM wikimedia.events "
            f"WHERE wiki_type = 'new' AND {time_filter}"
        )
        data.stats.new_articles = int(rows[0]["value"]) if rows else 0
    except Exception as e:
        logger.error("Failed to fetch overall stats: %s", e)

    # 2. Top edited pages (bot excluded, actual edits only, 24h, top 10)
    try:
        rows = _query(
            f"SELECT if(wikidata_label != '', wikidata_label, title) AS label, "
            f"title, wikidata_description AS description, server_name, count() AS edits "
            f"FROM wikimedia.events "
            f"WHERE {time_filter} AND namespace = 0 AND bot = 0 AND wiki_type = 'edit' "
            f"GROUP BY title, wikidata_label, wikidata_description, server_name "
            f"ORDER BY edits DESC LIMIT 10"
        )
        data.top_pages = [
            TopPage(
                label=r["label"],
                title=r["title"],
                description=r.get("description", ""),
                server_name=r["server_name"],
                edits=int(r["edits"]),
                url=wiki_url(r["server_name"], r["title"]),
            )
            for r in rows
        ]
    except Exception as e:
        logger.error("Failed to fetch top pages: %s", e)

    # 3. Spike pages (recent 15m vs previous 60m)
    try:
        rows = _query(
            "SELECT if(wikidata_label NOT IN ('', '-'), wikidata_label, title) AS label, "
            "title, server_name, "
            "countIf(event_time > now() - INTERVAL 15 MINUTE) AS edits_15m, "
            "round(countIf(event_time > now() - INTERVAL 15 MINUTE) * 4.0 / "
            "(countIf(event_time BETWEEN now() - INTERVAL 75 MINUTE AND now() - INTERVAL 15 MINUTE) + 1), 1) AS spike_ratio "
            "FROM wikimedia.events "
            "WHERE event_time > now() - INTERVAL 75 MINUTE AND namespace = 0 "
            "GROUP BY title, wikidata_label, server_name "
            "HAVING edits_15m >= 3 "
            "ORDER BY spike_ratio DESC LIMIT 10"
        )
        data.spike_pages = [
            SpikePage(
                label=r["label"],
                title=r["title"],
                server_name=r["server_name"],
                edits_15m=int(r["edits_15m"]),
                spike_ratio=float(r["spike_ratio"]),
            )
            for r in rows
        ]
    except Exception as e:
        logger.error("Failed to fetch spike pages: %s", e)

    # 4. Cross-wiki trending (2+ wikis, recent 15m)
    try:
        rows = _query(
            "SELECT title, uniq(server_name) AS wiki_count, count() AS total_edits, "
            "arrayStringConcat(groupUniqArray(server_name), ', ') AS wikis "
            "FROM wikimedia.events "
            "WHERE event_time > now() - INTERVAL 15 MINUTE AND namespace = 0 "
            "GROUP BY title HAVING wiki_count >= 2 "
            "ORDER BY wiki_count DESC, total_edits DESC LIMIT 10"
        )
        data.crosswiki_pages = [
            CrossWikiPage(
                title=r["title"],
                wiki_count=int(r["wiki_count"]),
                total_edits=int(r["total_edits"]),
                wikis=r["wikis"],
            )
            for r in rows
        ]
    except Exception as e:
        logger.error("Failed to fetch cross-wiki pages: %s", e)

    # 5. Top reverted pages (24h, top 5)
    try:
        rows = _query(
            f"SELECT if(wikidata_label != '', wikidata_label, title) AS label, "
            f"server_name, count() AS total_edits, "
            f"countIf(comment ILIKE '%revert%' OR comment ILIKE '%undo%' OR startsWith(comment, 'Reverted')) AS reverts, "
            f"round(100.0 * countIf(comment ILIKE '%revert%' OR comment ILIKE '%undo%' OR startsWith(comment, 'Reverted')) / count(), 1) AS revert_rate_pct "
            f"FROM wikimedia.events "
            f"WHERE {time_filter} AND namespace = 0 "
            f"GROUP BY title, wikidata_label, server_name "
            f"HAVING reverts > 0 "
            f"ORDER BY reverts DESC LIMIT 5"
        )
        data.revert_pages = [
            RevertPage(
                label=r["label"],
                server_name=r["server_name"],
                total_edits=int(r["total_edits"]),
                reverts=int(r["reverts"]),
                revert_rate_pct=float(r["revert_rate_pct"]),
            )
            for r in rows
        ]
    except Exception as e:
        logger.error("Failed to fetch revert pages: %s", e)

    # 6. Peak edit hour (24h)
    try:
        rows = _query(
            "SELECT toHour(event_time) AS hour, count() AS edits "
            "FROM wikimedia.events "
            f"WHERE {time_filter} "
            "GROUP BY hour ORDER BY edits DESC LIMIT 1"
        )
        if rows:
            data.peak_hour = PeakHour(
                hour=int(rows[0]["hour"]), edits=int(rows[0]["edits"])
            )
    except Exception as e:
        logger.error("Failed to fetch peak hour: %s", e)

    # 7. Yesterday's top pages → rank_change for today's top 5
    if data.top_pages:
        try:
            rows = _query(
                "SELECT title, server_name "
                "FROM wikimedia.events "
                "WHERE event_time >= now() - INTERVAL 48 HOUR "
                "AND event_time < now() - INTERVAL 24 HOUR "
                "AND namespace = 0 AND bot = 0 "
                "GROUP BY title, wikidata_label, server_name "
                "ORDER BY count() DESC LIMIT 10"
            )
            yesterday_rank = {r["title"]: i + 1 for i, r in enumerate(rows)}
            for today_rank, page in enumerate(data.top_pages[:5], 1):
                prev = yesterday_rank.get(page.title)
                page.rank_change = None if prev is None else (prev - today_rank)
        except Exception as e:
            logger.error("Failed to fetch yesterday ranks: %s", e)

    # 8. Enrich top 5 pages with spike / cross-wiki metadata
    spike_map = {(p.title, p.server_name): p for p in data.spike_pages}
    crosswiki_map = {p.title: p for p in data.crosswiki_pages}
    for page in data.top_pages[:5]:
        spike = spike_map.get((page.title, page.server_name))
        if spike:
            page.is_spike = True
            page.spike_ratio_val = spike.spike_ratio
        cw = crosswiki_map.get(page.title)
        if cw:
            page.crosswiki_count = cw.wiki_count

    # 9. Thumbnail for #1 page
    if data.top_pages:
        data.top_pages[0].thumbnail_url = _fetch_thumbnail(
            data.top_pages[0].server_name, data.top_pages[0].title
        )

    # 10. Wikipedia Featured Article of the day
    data.featured_article = _fetch_featured_article(now_kst)

    logger.info(
        "Fetched: %d edits, %d top pages, %d spikes, %d cross-wiki, %d reverts, "
        "peak=%dh, featured='%s'",
        data.stats.total_edits,
        len(data.top_pages),
        len(data.spike_pages),
        len(data.crosswiki_pages),
        len(data.revert_pages),
        data.peak_hour.hour,
        data.featured_article.title,
    )
    return data
