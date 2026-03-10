"""
ClickHouse vs QuestDB Cold Read Benchmark — 측정 쿼리 정의

Reporter 실제 쿼리 기반 3개:
  Q1 — 단순 집계 (count, sum, round)
  Q3 — GROUP BY + ORDER BY (top pages, 높은 cardinality)
  Q5 — 서브쿼리 + CASE WHEN ilike + DISTINCT (revert 감지)

각 쿼리는 (start, end) 시간 범위를 받는다:
  - ClickHouse: event_time >= '{dt_str}' AND event_time < '{dt_str2}'
  - QuestDB:    timestamp >= '{iso_str}' AND timestamp < '{iso_str2}'
"""

from datetime import datetime, timezone


# ── 시간 포맷 변환 ──────────────────────────────────────────────────────────

def _ch_dt(unix_sec: int) -> str:
    """Unix seconds → ClickHouse DateTime 문자열 (UTC)."""
    return datetime.fromtimestamp(unix_sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _qdb_ts(unix_sec: int) -> str:
    """Unix seconds → QuestDB timestamp 문자열 (ISO 8601 UTC)."""
    return datetime.fromtimestamp(unix_sec, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


# ── Q1: 단순 집계 ───────────────────────────────────────────────────────────

def q1_clickhouse(t_start: int, t_end: int) -> str:
    """24h 구간 기본 통계: 총 편집 수, 활성 편집자, 봇 비율, 신규 문서 수."""
    s, e = _ch_dt(t_start), _ch_dt(t_end)
    return f"""\
SELECT
    count(1)                                              AS total_edits,
    count(DISTINCT user)                                  AS active_users,
    round(100.0 * sum(bot) / count(1), 1)                AS bot_ratio_pct,
    countIf(wiki_type = 'new')                            AS new_articles
FROM bench.events
WHERE event_time >= '{s}' AND event_time < '{e}'"""


def q1_questdb(t_start: int, t_end: int) -> str:
    s, e = _qdb_ts(t_start), _qdb_ts(t_end)
    return f"""\
SELECT
    count(1)                                                                  AS total_edits,
    count(DISTINCT "user")                                                    AS active_users,
    round(100.0 * sum(CASE WHEN bot = true THEN 1 ELSE 0 END) / count(1), 1) AS bot_ratio_pct,
    sum(CASE WHEN wiki_type = 'new' THEN 1 ELSE 0 END)                       AS new_articles
FROM bench_events
WHERE timestamp >= '{s}' AND timestamp < '{e}'"""


# ── Q3: GROUP BY TOP PAGES ─────────────────────────────────────────────────

def q3_clickhouse(t_start: int, t_end: int) -> str:
    """상위 편집 문서 20개: bot 제외, 실제 편집(edit)만, namespace=0."""
    s, e = _ch_dt(t_start), _ch_dt(t_end)
    return f"""\
SELECT
    if(wikidata_label != '', wikidata_label, title) AS label,
    title,
    server_name,
    count(1) AS edits
FROM bench.events
WHERE event_time >= '{s}' AND event_time < '{e}'
  AND namespace = 0
  AND bot = 0
  AND wiki_type = 'edit'
GROUP BY title, wikidata_label, server_name
ORDER BY edits DESC
LIMIT 20"""


def q3_questdb(t_start: int, t_end: int) -> str:
    s, e = _qdb_ts(t_start), _qdb_ts(t_end)
    return f"""\
SELECT
    CASE WHEN wikidata_label <> '' THEN wikidata_label ELSE title END AS label,
    title,
    server_name,
    count(1) AS edits
FROM bench_events
WHERE timestamp >= '{s}' AND timestamp < '{e}'
  AND namespace = 0
  AND bot = false
  AND wiki_type = 'edit'
GROUP BY title, wikidata_label, server_name
ORDER BY edits DESC
LIMIT 20"""


# ── Q5: 서브쿼리 + ilike (REVERT 감지) ─────────────────────────────────────

def q5_clickhouse(t_start: int, t_end: int) -> str:
    """되돌리기 비율 상위 5개 문서: comment ilike 필터 + 서브쿼리."""
    s, e = _ch_dt(t_start), _ch_dt(t_end)
    return f"""\
SELECT *
FROM (
    SELECT
        if(wikidata_label != '', wikidata_label, title) AS label,
        server_name,
        count(1) AS total_edits,
        countIf(
            comment ilike '%revert%' OR comment ilike '%undo%'
        ) AS reverts,
        round(
            100.0 * countIf(comment ilike '%revert%' OR comment ilike '%undo%') / count(1),
            1
        ) AS revert_rate_pct
    FROM bench.events
    WHERE event_time >= '{s}' AND event_time < '{e}'
      AND namespace = 0
    GROUP BY title, wikidata_label, server_name
)
WHERE reverts > 0
ORDER BY reverts DESC
LIMIT 5"""


def q5_questdb(t_start: int, t_end: int) -> str:
    s, e = _qdb_ts(t_start), _qdb_ts(t_end)
    return f"""\
SELECT * FROM (
    SELECT
        CASE WHEN wikidata_label <> '' THEN wikidata_label ELSE title END AS label,
        server_name,
        count(1) AS total_edits,
        sum(CASE WHEN comment ilike '%revert%' OR comment ilike '%undo%' THEN 1 ELSE 0 END) AS reverts,
        round(
            100.0 * sum(CASE WHEN comment ilike '%revert%' OR comment ilike '%undo%' THEN 1 ELSE 0 END) / count(1),
            1
        ) AS revert_rate_pct
    FROM bench_events
    WHERE timestamp >= '{s}' AND timestamp < '{e}'
      AND namespace = 0
    GROUP BY title, wikidata_label, server_name
) WHERE reverts > 0
ORDER BY reverts DESC
LIMIT 5"""


# ── 쿼리 레지스트리 ─────────────────────────────────────────────────────────

QUERIES = {
    "Q1": {"clickhouse": q1_clickhouse, "questdb": q1_questdb, "label": "집계(count/sum)"},
    "Q3": {"clickhouse": q3_clickhouse, "questdb": q3_questdb, "label": "GROUP BY TOP 20"},
    "Q5": {"clickhouse": q5_clickhouse, "questdb": q5_questdb, "label": "서브쿼리+ilike"},
}
