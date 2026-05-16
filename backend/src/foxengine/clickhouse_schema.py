LEADS_DDL = """
CREATE TABLE IF NOT EXISTS leads (
    batch_id UUID,
    row_in_batch UInt64,
    ingest_ts DateTime DEFAULT now(),
    identity_key String,

    phone_norm String,
    phone_raw String,
    email_norm LowCardinality(String),
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
    tag_ids Array(UUID),

    INDEX idx_phone_ngram phone_norm TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_email_ngram email_norm TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_username_ngram username TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_idcard_ngram id_card TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_tags tag_ids TYPE bloom_filter() GRANULARITY 1
)
ENGINE = MergeTree
ORDER BY (identity_key, batch_id, row_in_batch)
PARTITION BY toYYYYMM(ingest_ts)
SETTINGS index_granularity = 8192;
"""
