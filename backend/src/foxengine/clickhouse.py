from typing import Any

import clickhouse_connect

from foxengine.clickhouse_schema import CLICKHOUSE_SCHEMA_DDL
from foxengine.config import get_settings

_client: Any = None


async def get_ch_client() -> Any:
    global _client
    if _client is None:
        s = get_settings()
        bootstrap = await clickhouse_connect.get_async_client(
            host=s.clickhouse_host,
            port=s.clickhouse_port,
            username=s.clickhouse_user,
            password=s.clickhouse_password or "",
            database="default",
        )
        await bootstrap.command(f"CREATE DATABASE IF NOT EXISTS {s.clickhouse_database}")
        await bootstrap.close()
        _client = await clickhouse_connect.get_async_client(
            host=s.clickhouse_host,
            port=s.clickhouse_port,
            username=s.clickhouse_user,
            password=s.clickhouse_password or "",
            database=s.clickhouse_database,
        )
    return _client


async def ensure_clickhouse_schema() -> None:
    client = await get_ch_client()
    await _drop_legacy_schema_if_needed(client)
    for ddl in CLICKHOUSE_SCHEMA_DDL:
        await client.command(ddl)
    await _migrate_lead_tags_ingest_ts(client)


async def _migrate_lead_tags_ingest_ts(client: Any) -> None:
    exists = await client.query(
        "SELECT count() FROM system.tables "
        "WHERE database = currentDatabase() AND name = 'lead_tags'"
    )
    if int(exists.first_row[0]) == 0:
        return
    has_ingest_ts = await client.query(
        "SELECT count() FROM system.columns "
        "WHERE database = currentDatabase() AND table = 'lead_tags' AND name = 'ingest_ts'"
    )
    if int(has_ingest_ts.first_row[0]) > 0:
        return
    await client.command(
        """
CREATE TABLE lead_tags_new (
    tag_id UUID,
    batch_id UUID,
    row_in_batch UInt32,
    ingest_ts DateTime,
    assigned_at DateTime DEFAULT now(),
    source LowCardinality(String) DEFAULT ''
)
ENGINE = ReplacingMergeTree(assigned_at)
PARTITION BY toYYYYMM(assigned_at)
ORDER BY (tag_id, ingest_ts, batch_id, row_in_batch)
SETTINGS index_granularity = 8192
"""
    )
    await client.command(
        """
INSERT INTO lead_tags_new (tag_id, batch_id, row_in_batch, ingest_ts, assigned_at, source)
SELECT
    lt.tag_id,
    lt.batch_id,
    lt.row_in_batch,
    coalesce(l.ingest_ts, lt.assigned_at) AS ingest_ts,
    lt.assigned_at,
    lt.source
FROM lead_tags AS lt
LEFT JOIN leads AS l USING (batch_id, row_in_batch)
"""
    )
    await client.command("DROP TABLE lead_tags")
    await client.command("RENAME TABLE lead_tags_new TO lead_tags")


async def _drop_legacy_schema_if_needed(client: Any) -> None:
    legacy = await client.query(
        "SELECT count() FROM system.columns "
        "WHERE database = currentDatabase() AND table = 'leads' AND name = 'tag_ids'"
    )
    if int(legacy.first_row[0]) == 0:
        return
    await client.command("DROP TABLE IF EXISTS lead_tags")
    await client.command("DROP TABLE IF EXISTS lead_identities")
    await client.command("DROP TABLE IF EXISTS leads")
