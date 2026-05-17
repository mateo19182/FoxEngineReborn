CLICKHOUSE_SCHEMA_DDL = [
    """
CREATE TABLE IF NOT EXISTS leads (
    batch_id UUID,
    row_in_batch UInt32,
    ingest_ts DateTime DEFAULT now(),
    identity_key String,

    phone_norm String,
    phone_raw String,
    email_norm String,
    email_raw String,
    email_local String MATERIALIZED splitByChar('@', email_norm)[1],
    email_domain LowCardinality(String) MATERIALIZED splitByChar('@', email_norm)[2],
    username String,
    id_card String,

    full_name String,
    first_name String,
    last_name String,
    dob Nullable(Date),
    gender LowCardinality(String),
    address String,
    city LowCardinality(String),
    country LowCardinality(String),
    zip String,
    ip String,
    user_agent String,
    isp LowCardinality(String),
    phone_carrier LowCardinality(String),
    password String,
    password_hash String,
    last_seen Nullable(DateTime),

    extras Map(String, String),

    INDEX idx_phone_ngram phone_norm TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_email_ngram email_norm TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_username_ngram username TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_idcard_ngram id_card TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ingest_ts)
ORDER BY (batch_id, row_in_batch)
SETTINGS index_granularity = 8192;
""",
    """
CREATE TABLE IF NOT EXISTS lead_identities (
    identity_kind LowCardinality(String),
    identity_value String,
    batch_id UUID,
    row_in_batch UInt32,
    ingest_ts DateTime,

    INDEX idx_identity_value_ngram identity_value TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ingest_ts)
ORDER BY (identity_kind, identity_value, ingest_ts, batch_id, row_in_batch)
SETTINGS index_granularity = 8192;
""",
    """
CREATE TABLE IF NOT EXISTS lead_tags (
    tag_id UUID,
    batch_id UUID,
    row_in_batch UInt32,
    assigned_at DateTime DEFAULT now(),
    source LowCardinality(String) DEFAULT ''
)
ENGINE = ReplacingMergeTree(assigned_at)
PARTITION BY toYYYYMM(assigned_at)
ORDER BY (tag_id, batch_id, row_in_batch)
SETTINGS index_granularity = 8192;
""",
]
