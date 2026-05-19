"""Postgres soft-deleted batches excluded from ClickHouse queries."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Batch


async def deleted_batch_sql_clause(session: AsyncSession) -> tuple[str, dict[str, Any]]:
    """Return a WHERE fragment and parameters excluding soft-deleted batch rows."""
    deleted = (
        await session.execute(select(Batch.id).where(Batch.deleted_at.is_not(None)))
    ).scalars().all()
    if not deleted:
        return "", {}
    parts: list[str] = []
    params: dict[str, Any] = {}
    for i, bid in enumerate(deleted):
        k = f"bd_{i}"
        params[k] = str(bid)
        parts.append(f"toUUID({{{k}:String}})")
    return " AND batch_id NOT IN (" + ", ".join(parts) + ")", params


async def batch_clickhouse_counts(ch: Any, batch_id: UUID) -> dict[str, int]:
    tables = ("leads", "lead_identities", "lead_tags")
    out: dict[str, int] = {}
    for table in tables:
        qr = await ch.query(
            f"SELECT count() FROM {table} WHERE batch_id = {{bid:UUID}}",
            parameters={"bid": batch_id},
        )
        out[table] = int(qr.first_row[0])
    return out
