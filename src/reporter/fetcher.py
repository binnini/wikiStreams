import logging
from dataclasses import dataclass, field

import httpx

from reporter.config import settings

logger = logging.getLogger(__name__)

CLICKHOUSE_URL = f"http://{settings.clickhouse_host}:{settings.clickhouse_port}"


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


@dataclass
class SpikePage:
    label: str = ""
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
class ReportData:
    stats: OverallStats = field(default_factory=OverallStats)
    top_pages: list[TopPage] = field(default_factory=list)
    spike_pages: list[SpikePage] = field(default_factory=list)
    crosswiki_pages: list[CrossWikiPage] = field(default_factory=list)
    revert_pages: list[RevertPage] = field(default_factory=list)


def _query(sql: str) -> list[dict]:
    params = {"query": sql, "default_format": "JSONEachRow"}
    with httpx.Client(timeout=30) as client:
        resp = client.get(CLICKHOUSE_URL, params=params)
        resp.raise_for_status()
    rows = []
    for line in resp.text.strip().splitlines():
        if line:
            import json
            rows.append(json.loads(line))
    return rows


def fetch_report_data() -> ReportData:
    data = ReportData()

    # 1. Overall stats (24h)
    time_filter = "event_time >= now() - INTERVAL 24 HOUR"
    try:
        rows = _query(f"SELECT count() AS value FROM wikimedia.events WHERE {time_filter}")
        data.stats.total_edits = int(rows[0]["value"]) if rows else 0

        rows = _query(f"SELECT uniq(user) AS value FROM wikimedia.events WHERE {time_filter}")
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

    # 2. Top edited pages (bot excluded, 24h, top 10)
    try:
        rows = _query(
            f"SELECT if(wikidata_label != '', wikidata_label, title) AS label, "
            f"title, wikidata_description AS description, server_name, count() AS edits "
            f"FROM wikimedia.events "
            f"WHERE {time_filter} AND namespace = 0 AND bot = 0 "
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
            )
            for r in rows
        ]
    except Exception as e:
        logger.error("Failed to fetch top pages: %s", e)

    # 3. Spike pages (recent 15m vs previous 60m)
    try:
        rows = _query(
            "SELECT if(wikidata_label NOT IN ('', '-'), wikidata_label, title) AS label, "
            "server_name, "
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

    logger.info(
        "Fetched report data: %d edits, %d top pages, %d spikes, %d cross-wiki, %d reverts",
        data.stats.total_edits,
        len(data.top_pages),
        len(data.spike_pages),
        len(data.crosswiki_pages),
        len(data.revert_pages),
    )
    return data
