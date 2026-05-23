"""Compile DSL to a ClickHouse WHERE clause plus parameters (shared by query and export)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.dsl.parser import parse_dsl
from foxengine.dsl.sql import CompiledLeadsQuery, compile_leads_query
from foxengine.services.deleted_batches import deleted_batch_sql_clause
from foxengine.services.tags_resolve import resolve_tag_predicates, walk_preds


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
    compiled = compile_leads_query(ast, tag_map)
    extra, extra_params = await deleted_batch_sql_clause(session)
    params = dict(compiled.parameters)
    params.update(extra_params)
    return CompiledLeadsQuery(
        leads_where=f"({compiled.leads_where}){extra}",
        parameters=params,
        tag_keys_select=compiled.tag_keys_select,
    )


def leads_count_sql(compiled: CompiledLeadsQuery) -> str:
    if compiled.tag_keys_select:
        return f"""
SELECT count()
FROM (
    {compiled.tag_keys_select}
) AS tagged
INNER JOIN leads AS l USING (batch_id, row_in_batch)
WHERE {compiled.leads_where}
""".strip()
    return f"SELECT count() FROM leads WHERE {compiled.leads_where}"


def leads_select_sql(compiled: CompiledLeadsQuery, *, limit: int, offset: int = 0) -> str:
    if compiled.tag_keys_select:
        from_clause = f"""
FROM (
    {compiled.tag_keys_select}
) AS tagged
INNER JOIN leads AS l USING (batch_id, row_in_batch)
""".strip()
        leads_ref = "l"
    else:
        from_clause = "FROM leads AS l"
        leads_ref = "l"

    return f"""
WITH selected AS (
    SELECT {leads_ref}.*
    {from_clause}
    WHERE {compiled.leads_where}
    ORDER BY {leads_ref}.ingest_ts DESC
    LIMIT {int(limit)} OFFSET {int(offset)}
)
SELECT
    l.*,
    ifNull(t.tag_ids, CAST([], 'Array(UUID)')) AS tag_ids
FROM selected AS l
LEFT ANY JOIN (
    SELECT
        batch_id,
        row_in_batch,
        groupUniqArray(tag_id) AS tag_ids
    FROM lead_tags
    WHERE (batch_id, row_in_batch) IN (SELECT batch_id, row_in_batch FROM selected)
    GROUP BY batch_id, row_in_batch
) AS t USING (batch_id, row_in_batch)
ORDER BY l.ingest_ts DESC
"""
