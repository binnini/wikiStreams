CREATE DATABASE IF NOT EXISTS wikimedia;

-- Storage table: Wikipedia edit events (MergeTree)
CREATE TABLE IF NOT EXISTS wikimedia.events
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
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, server_name, wiki_type)
TTL event_time + INTERVAL 90 DAY;

-- Kafka engine table: subscribes to wikimedia.recentchange topic (via Redpanda)
-- Nullable fields handle optional producer output (minor, comment, wikidata_*)
CREATE TABLE IF NOT EXISTS wikimedia.kafka_raw
(
    timestamp            Int64,
    title                String,
    server_name          String,
    type                 String,
    namespace            Int32,
    user                 String,
    bot                  UInt8,
    minor                Nullable(UInt8),
    comment              Nullable(String),
    wikidata_label       Nullable(String),
    wikidata_description Nullable(String)
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list          = 'redpanda:9092',
    kafka_topic_list           = 'wikimedia.recentchange',
    kafka_group_name           = 'clickhouse-consumer',
    kafka_format               = 'JSONEachRow',
    kafka_skip_broken_messages = 1000;

-- Materialized View: streams kafka_raw → events
CREATE MATERIALIZED VIEW IF NOT EXISTS wikimedia.events_mv
TO wikimedia.events
AS
SELECT
    toDateTime(timestamp)            AS event_time,
    title,
    server_name,
    type                             AS wiki_type,
    namespace,
    user,
    bot,
    ifNull(minor, 0)                 AS minor,
    ifNull(comment, '')              AS comment,
    ifNull(wikidata_label, '')       AS wikidata_label,
    ifNull(wikidata_description, '') AS wikidata_description
FROM wikimedia.kafka_raw;
