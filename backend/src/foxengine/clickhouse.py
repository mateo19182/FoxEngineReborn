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
