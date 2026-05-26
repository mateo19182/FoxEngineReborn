"""Postgres soft-deleted batches excluded from ClickHouse queries."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Batch


async def deleted_batch_sql_clause(session: AsyncSession) -> tuple[str, dict[str, Any]]:
    """Return a WHERE fragment excluding soft-deleted batch rows."""
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


PURGE_TABLES_DELETE_ORDER: tuple[str, ...] = (
    "leads",
    "lead_identities",
    "lead_tags",
    "lead_fingerprints",
)


async def batch_clickhouse_counts(ch: Any, batch_id: UUID) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in PURGE_TABLES_DELETE_ORDER:
        qr = await ch.query(
            f"SELECT count() FROM {table} WHERE batch_id = {{bid:UUID}}",
            parameters={"bid": batch_id},
        )
        out[table] = int(qr.first_row[0])
    return out


async def lightweight_delete_batch_rows(ch: Any, batch_id: UUID) -> None:
    """Issue lightweight DELETE FROM per insert-mutation-avoid-delete (not ALTER DELETE)."""
    for table in PURGE_TABLES_DELETE_ORDER:
        await ch.command(
            f"DELETE FROM {table} WHERE batch_id = {{bid:UUID}}",
            parameters={"bid": batch_id},
        )
