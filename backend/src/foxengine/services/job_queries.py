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


def merged_profile_select(merged_sources_cap: int) -> str:
    """Aggregate expression list (inside SELECT ... FROM leads WHERE ... GROUP BY identity_key)."""
    return f"""
  identity_key,
  argMax(phone_norm, ingest_ts) AS phone_norm,
  argMax(phone_raw, ingest_ts) AS phone_raw,
  argMax(email_norm, ingest_ts) AS email_norm,
  argMax(email_raw, ingest_ts) AS email_raw,
  argMax(username, ingest_ts) AS username,
  argMax(id_card, ingest_ts) AS id_card,
  argMax(full_name, ingest_ts) AS full_name,
  argMax(first_name, ingest_ts) AS first_name,
  argMax(last_name, ingest_ts) AS last_name,
  argMax(dob, ingest_ts) AS dob,
  argMax(gender, ingest_ts) AS gender,
  argMax(address, ingest_ts) AS address,
  argMax(city, ingest_ts) AS city,
  argMax(country, ingest_ts) AS country,
  argMax(zip, ingest_ts) AS zip,
  argMax(ip, ingest_ts) AS ip,
  argMax(user_agent, ingest_ts) AS user_agent,
  argMax(isp, ingest_ts) AS isp,
  argMax(phone_carrier, ingest_ts) AS phone_carrier,
  argMax(password, ingest_ts) AS password,
  argMax(password_hash, ingest_ts) AS password_hash,
  argMax(last_seen, ingest_ts) AS last_seen,
  argMax(extras, ingest_ts) AS extras,
  arrayDistinct(arrayFlatten(groupArray(tag_ids))) AS tag_ids,
  max(ingest_ts) AS ingest_ts,
  argMax(batch_id, ingest_ts) AS batch_id,
  argMax(row_in_batch, ingest_ts) AS row_in_batch,
  count() AS _merged_row_count,
  arraySlice(
    groupArray(tuple(toString(batch_id), toString(row_in_batch), toString(ingest_ts))),
    1,
    {int(merged_sources_cap)}
  ) AS _merged_sources
""".strip()
