import json
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote

import httpx

from reporter.config import settings

logger = logging.getLogger(__name__)

QUESTDB_URL = f"http://{settings.questdb_host}:{settings.questdb_port}/exec"
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
class LangEdition:
    """One language edition of a Q-ID-grouped page."""

    server_name: str = ""
    edits: int = 0


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
    qid: Optional[str] = None  # Wikidata Q-ID (cross-language dedup key)
    # Populated when multiple language editions share the same Q-ID.
    # Contains ALL editions (index 0 = this representative page).
    # Empty when no cross-language grouping occurred.
    lang_editions: list[LangEdition] = field(default_factory=list)


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
    with httpx.Client(timeout=30) as client:
        resp = client.get(QUESTDB_URL, params={"query": sql, "fmt": "json"})
        resp.raise_for_status()
    data = resp.json()
    columns = [c["name"] for c in data.get("columns", [])]
    return [dict(zip(columns, row)) for row in data.get("dataset", [])]


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
        relevance = {
            word.lower() for kw in kws for word in kw.split() if len(word) >= 3
        }
        all_news.extend(_fetch_news(query, relevance_keywords=relevance, max_items=3))
    return all_news


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


def fetch_thumbnail(server_name: str, title: str) -> str:
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


def _fetch_qid(server_name: str, title: str) -> Optional[str]:
    """Fetch the Wikidata Q-ID for a page via the REST summary API.

    For Wikidata pages, the title itself is the Q-ID if it matches Q\\d+.
    For Wikipedia pages, the wikibase_item field in the summary response is used.
    Returns None on error or if no Q-ID is available.
    """
    if "wikidata" in server_name:
        return title if re.match(r"^Q\d+$", title) else None
    encoded = quote(title.replace(" ", "_"), safe="")
    url = f"https://{server_name}/api/rest_v1/page/summary/{encoded}"
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(url, headers=_WIKI_API_HEADERS)
            resp.raise_for_status()
        return resp.json().get("wikibase_item")
    except Exception as e:
        logger.warning("Q-ID fetch failed for '%s/%s': %s", server_name, title, e)
        return None


def _fetch_ko_description(qid: str) -> str:
    """Fetch the Korean short description for a Wikidata entity.

    Returns empty string on error or when no Korean description exists.
    """
    params = {
        "action": "wbgetentities",
        "ids": qid,
        "languages": "ko",
        "props": "descriptions",
        "format": "json",
    }
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(
                "https://www.wikidata.org/w/api.php",
                params=params,
                headers=_WIKI_API_HEADERS,
            )
            resp.raise_for_status()
        entity = resp.json().get("entities", {}).get(qid, {})
        return entity.get("descriptions", {}).get("ko", {}).get("value", "")
    except Exception as e:
        logger.warning("Korean description fetch failed for '%s': %s", qid, e)
        return ""


def _deduplicate_by_qid(pages: list[TopPage]) -> list[TopPage]:
    """Remove duplicate pages that share the same Wikidata Q-ID.

    Pages without a Q-ID are always kept (each gets a unique fallback key).
    When duplicates exist, the first occurrence (highest edit count) is kept as
    the representative. All editions (including the representative) are recorded
    in `representative.lang_editions` so publishers can show per-language edits
    and a total.
    """
    seen: dict[str, TopPage] = {}
    result = []
    for page in pages:
        key = page.qid if page.qid else f"_{page.server_name}/{page.title}"
        if key not in seen:
            seen[key] = page
            result.append(page)
        else:
            rep = seen[key]
            # First duplicate: seed lang_editions with the representative itself
            if not rep.lang_editions:
                rep.lang_editions.append(
                    LangEdition(server_name=rep.server_name, edits=rep.edits)
                )
            rep.lang_editions.append(
                LangEdition(server_name=page.server_name, edits=page.edits)
            )
    return result


def fetch_report_data() -> ReportData:
    data = ReportData()
    now_kst = datetime.now(KST)

    # 1. Overall stats (24h)
    time_filter = "timestamp >= dateadd('d',-1,now())"
    try:
        rows = _query(
            f"SELECT count(1) AS value FROM wikimedia_events WHERE {time_filter}"
        )
        data.stats.total_edits = int(rows[0]["value"]) if rows else 0

        rows = _query(
            f"SELECT count(DISTINCT \"user\") AS value FROM wikimedia_events WHERE {time_filter}"
        )
        data.stats.active_users = int(rows[0]["value"]) if rows else 0

        rows = _query(
            f"SELECT round(100.0 * sum(CASE WHEN bot = true THEN 1 ELSE 0 END) / count(1), 1) AS value "
            f"FROM wikimedia_events WHERE {time_filter}"
        )
        data.stats.bot_ratio_pct = float(rows[0]["value"]) if rows else 0.0

        rows = _query(
            f"SELECT count(1) AS value FROM wikimedia_events "
            f"WHERE wiki_type = 'new' AND {time_filter}"
        )
        data.stats.new_articles = int(rows[0]["value"]) if rows else 0
    except Exception as e:
        logger.error("Failed to fetch overall stats: %s", e)

    # 2. Top edited pages (bot excluded, actual edits only, 24h, top 20)
    try:
        rows = _query(
            f"SELECT CASE WHEN wikidata_label <> '' THEN wikidata_label ELSE title END AS label, "
            f"title, wikidata_description AS description, server_name, count(1) AS edits "
            f"FROM wikimedia_events "
            f"WHERE {time_filter} AND namespace = 0 AND bot = false AND wiki_type = 'edit' "
            f"GROUP BY title, wikidata_label, wikidata_description, server_name "
            f"ORDER BY edits DESC LIMIT 20"
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

    # 2b. Fetch Wikidata Q-IDs in parallel for cross-language deduplication
    if data.top_pages:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(_fetch_qid, p.server_name, p.title): p
                for p in data.top_pages
            }
            for f in as_completed(futures):
                futures[f].qid = f.result()
        data.top_pages = _deduplicate_by_qid(data.top_pages)
        logger.info("After Q-ID dedup: %d unique topic candidates", len(data.top_pages))

    # 2c. Fetch Korean descriptions in parallel for pages with empty description
    pages_needing_desc = [p for p in data.top_pages if not p.description and p.qid]
    if pages_needing_desc:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(_fetch_ko_description, p.qid): p
                for p in pages_needing_desc
            }
            for f in as_completed(futures):
                desc = f.result()
                if desc:
                    futures[f].description = desc

    # 3. Spike pages (recent 15m vs previous 60m)
    try:
        rows = _query(
            "SELECT * FROM ("
            "SELECT CASE WHEN wikidata_label NOT IN ('', '-') THEN wikidata_label ELSE title END AS label, "
            "title, server_name, "
            "sum(CASE WHEN timestamp > dateadd('m',-15,now()) THEN 1 ELSE 0 END) AS edits_15m, "
            "round(cast(sum(CASE WHEN timestamp > dateadd('m',-15,now()) THEN 1 ELSE 0 END) as double) * 4.0 / "
            "(sum(CASE WHEN timestamp BETWEEN dateadd('m',-75,now()) AND dateadd('m',-15,now()) THEN 1 ELSE 0 END) + 1), 1) AS spike_ratio "
            "FROM wikimedia_events "
            "WHERE timestamp > dateadd('m',-75,now()) AND namespace = 0 "
            "GROUP BY title, wikidata_label, server_name"
            ") WHERE edits_15m >= 3 "
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
            "SELECT * FROM ("
            "SELECT title, count(DISTINCT server_name) AS wiki_count, count(1) AS total_edits, '' AS wikis "
            "FROM wikimedia_events "
            "WHERE timestamp > dateadd('m',-15,now()) AND namespace = 0 "
            "GROUP BY title"
            ") WHERE wiki_count >= 2 "
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
            f"SELECT * FROM ("
            f"SELECT CASE WHEN wikidata_label <> '' THEN wikidata_label ELSE title END AS label, "
            f"server_name, count(1) AS total_edits, "
            f"sum(CASE WHEN comment ilike '%revert%' OR comment ilike '%undo%' OR comment LIKE 'Reverted%' THEN 1 ELSE 0 END) AS reverts, "
            f"round(100.0 * sum(CASE WHEN comment ilike '%revert%' OR comment ilike '%undo%' OR comment LIKE 'Reverted%' THEN 1 ELSE 0 END) / count(1), 1) AS revert_rate_pct "
            f"FROM wikimedia_events "
            f"WHERE {time_filter} AND namespace = 0 "
            f"GROUP BY title, wikidata_label, server_name"
            f") WHERE reverts > 0 "
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
            "SELECT extract(hour from timestamp) AS hour, count(1) AS edits "
            "FROM wikimedia_events "
            f"WHERE {time_filter} "
            "GROUP BY hour ORDER BY edits DESC LIMIT 1"
        )
        if rows:
            data.peak_hour = PeakHour(
                hour=int(rows[0]["hour"]), edits=int(rows[0]["edits"])
            )
    except Exception as e:
        logger.error("Failed to fetch peak hour: %s", e)

    # 7. Yesterday's top pages → rank_change for all candidates
    if data.top_pages:
        try:
            rows = _query(
                "SELECT title, server_name "
                "FROM wikimedia_events "
                "WHERE timestamp >= dateadd('h',-48,now()) "
                "AND timestamp < dateadd('d',-1,now()) "
                "AND namespace = 0 AND bot = false "
                "GROUP BY title, wikidata_label, server_name "
                "ORDER BY count(1) DESC LIMIT 10"
            )
            yesterday_rank = {r["title"]: i + 1 for i, r in enumerate(rows)}
            for today_rank, page in enumerate(data.top_pages, 1):
                prev = yesterday_rank.get(page.title)
                page.rank_change = None if prev is None else (prev - today_rank)
        except Exception as e:
            logger.error("Failed to fetch yesterday ranks: %s", e)

    # 8. Enrich all candidate pages with spike / cross-wiki metadata
    spike_map = {(p.title, p.server_name): p for p in data.spike_pages}
    crosswiki_map = {p.title: p for p in data.crosswiki_pages}
    for page in data.top_pages:
        spike = spike_map.get((page.title, page.server_name))
        if spike:
            page.is_spike = True
            page.spike_ratio_val = spike.spike_ratio
        cw = crosswiki_map.get(page.title)
        if cw:
            page.crosswiki_count = cw.wiki_count

    # 9. Wikipedia Featured Article of the day
    data.featured_article = _fetch_featured_article(now_kst)

    logger.info(
        "Fetched: %d edits, %d top candidates, %d spikes, %d cross-wiki, %d reverts, "
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
