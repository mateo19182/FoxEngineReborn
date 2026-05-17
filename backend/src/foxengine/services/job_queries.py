"""Compile DSL to a ClickHouse WHERE clause plus parameters (shared by query and export)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Batch
from foxengine.dsl.parser import parse_dsl
from foxengine.dsl.sql import compile_expr
from foxengine.services.tags_resolve import resolve_tag_predicates, walk_preds


async def compile_leads_where(
    session: AsyncSession, dsl: str
) -> tuple[str, dict[str, Any]]:
    ast = parse_dsl(dsl)
    preds = walk_preds(ast)
    tag_map = await resolve_tag_predicates(session, preds)
    cw = compile_expr(ast, tag_map)
    deleted = (
        await session.execute(select(Batch.id).where(Batch.deleted_at.is_not(None)))
    ).scalars().all()
    extra = ""
    params = dict(cw.parameters)
    if deleted:
        parts: list[str] = []
        for i, bid in enumerate(deleted):
            k = f"bd_{i}"
            params[k] = str(bid)
            parts.append(f"toUUID({{{k}:String}})")
        extra = " AND batch_id NOT IN (" + ", ".join(parts) + ")"
    return f"({cw.sql}){extra}", params


def leads_select_sql(where_sql: str, *, limit: int, offset: int = 0) -> str:
    return f"""
WITH selected AS (
    SELECT *
    FROM leads
    WHERE {where_sql}
    ORDER BY ingest_ts DESC
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
