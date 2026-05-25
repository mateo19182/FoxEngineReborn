"""Compile DSL to a ClickHouse WHERE clause plus parameters (shared by query and export)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.dsl.parser import parse_dsl
from foxengine.dsl.sql import CompiledLeadsQuery, compile_leads_query
from foxengine.services.deleted_batches import deleted_batch_sql_clause
from foxengine.services.tags_resolve import (
    resolve_tag_predicates,
    validate_tag_references,
    walk_preds,
)


async def compile_leads_where(session: AsyncSession, dsl: str) -> CompiledLeadsQuery:
    if not dsl.strip():
        extra, extra_params = await deleted_batch_sql_clause(session)
        return CompiledLeadsQuery(
            leads_where=f"(1 = 1){extra}",
            parameters=dict(extra_params),
            tag_keys_select=None,
        )

    ast = parse_dsl(dsl)
    preds = walk_preds(ast)
    tag_map = await resolve_tag_predicates(session, preds)
    await validate_tag_references(session, ast, tag_map)
    compiled = compile_leads_query(ast, tag_map)
    extra, extra_params = await deleted_batch_sql_clause(session)
    params = dict(compiled.parameters)
    params.update(extra_params)
    return CompiledLeadsQuery(
        leads_where=f"({compiled.leads_where}){extra}",
        parameters=params,
        tag_keys_select=compiled.tag_keys_select,
    )


def _tag_count_on_keys_only(leads_where: str) -> bool:
    """True when every predicate applies to batch_id / keys (no lead column filters)."""
    if "lead_identities" in leads_where or "lead_tags" in leads_where:
        return False
    lead_columns = (
        "email_",
        "phone_",
        "full_name",
        "first_name",
        "last_name",
        "username",
        "id_card",
        "dob ",
        "gender",
        "address",
        "city",
        "country",
        "zip",
        "ip",
        "user_agent",
        "isp",
        "phone_carrier",
        "password",
        "last_seen",
        "extras",
    )
    return not any(col in leads_where for col in lead_columns)


def leads_count_sql(compiled: CompiledLeadsQuery) -> str:
    if compiled.tag_keys_select:
        if _tag_count_on_keys_only(compiled.leads_where):
            return f"""
SELECT count()
FROM (
    {compiled.tag_keys_select}
) AS tagged
WHERE {compiled.leads_where}
""".strip()
        return f"""
SELECT count()
FROM (
    {compiled.tag_keys_select}
) AS tagged
INNER JOIN leads AS l USING (batch_id, row_in_batch)
WHERE {compiled.leads_where}
""".strip()
    return f"SELECT count() FROM leads WHERE {compiled.leads_where}"


_LEADS_EXCEPT = "batch_id, row_in_batch, extras"


def leads_select_sql(compiled: CompiledLeadsQuery, *, limit: int, offset: int = 0) -> str:
    """Lead rows for one page. Tag UUIDs are loaded separately (bounded by limit)."""
    lim = int(limit)
    off = int(offset)
    if compiled.tag_keys_select:
        # Sort/limit on ingest_ts before reading wide columns (extras Map blows memory).
        return f"""
WITH sorted_keys AS (
    SELECT l.batch_id AS batch_id, l.row_in_batch AS row_in_batch
    FROM leads AS l
    WHERE (l.batch_id, l.row_in_batch) IN (
        SELECT batch_id, row_in_batch FROM (
            {compiled.tag_keys_select}
        )
    )
    AND ({compiled.leads_where})
    ORDER BY l.ingest_ts DESC
    LIMIT {lim} OFFSET {off}
)
SELECT
    l.batch_id AS batch_id,
    l.row_in_batch AS row_in_batch,
    l.* EXCEPT ({_LEADS_EXCEPT})
FROM leads AS l
WHERE (l.batch_id, l.row_in_batch) IN (
    SELECT batch_id, row_in_batch FROM sorted_keys
)
ORDER BY l.ingest_ts DESC
""".strip()

    return f"""
SELECT
    l.batch_id AS batch_id,
    l.row_in_batch AS row_in_batch,
    l.* EXCEPT ({_LEADS_EXCEPT})
FROM leads AS l
WHERE {compiled.leads_where}
ORDER BY l.ingest_ts DESC
LIMIT {lim} OFFSET {off}
""".strip()


def _lead_row_key(row: dict[str, Any]) -> tuple[str, int]:
    return (str(row["batch_id"]), int(row["row_in_batch"]))


async def fetch_lead_tag_ids(
    ch: Any,
    keys: list[tuple[str, int]],
    *,
    settings: dict[str, Any] | None = None,
) -> dict[tuple[str, int], list[Any]]:
    """groupUniqArray(tag_id) for explicit (batch_id, row_in_batch) keys only."""
    unique = list(dict.fromkeys(keys))
    if not unique:
        return {}

    out: dict[tuple[str, int], list[Any]] = {}
    chunk_size = 5_000
    for i in range(0, len(unique), chunk_size):
        chunk = unique[i : i + chunk_size]
        qr = await ch.query(
            "SELECT batch_id, row_in_batch, groupUniqArray(tag_id) AS tag_ids "
            "FROM lead_tags "
            "WHERE (batch_id, row_in_batch) IN {keys:Array(Tuple(UUID, UInt32))} "
            "GROUP BY batch_id, row_in_batch",
            parameters={"keys": chunk},
            settings=settings or {},
        )
        for batch_id, row_in_batch, tag_ids in qr.result_rows:
            out[(str(batch_id), int(row_in_batch))] = list(tag_ids)
    return out


def attach_tag_ids(
    rows: list[dict[str, Any]], tag_ids_by_key: dict[tuple[str, int], list[Any]]
) -> None:
    for row in rows:
        row["tag_ids"] = tag_ids_by_key.get(_lead_row_key(row), [])
