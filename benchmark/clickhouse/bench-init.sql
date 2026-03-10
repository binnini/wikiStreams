-- ClickHouse 벤치마크 테이블
-- 스키마: wikimedia.events와 동일, 파티션을 DAY 단위로 세분화 (cold read 실험용)

CREATE DATABASE IF NOT EXISTS bench;

CREATE TABLE IF NOT EXISTS bench.events
(
    event_time           DateTime         CODEC(Delta, ZSTD),
    title                String,
    server_name          LowCardinality(String),
    wiki_type            LowCardinality(String),
    namespace            Int32,
    user                 String,
    bot                  UInt8,
    minor                UInt8,
    comment              String,
    wikidata_label       String,
    wikidata_description String
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(event_time)
ORDER BY (event_time, server_name, wiki_type);
