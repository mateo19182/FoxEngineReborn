"""Postgres soft-deleted batches excluded from ClickHouse queries."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Batch


async def deleted_batch_sql_clause(session: AsyncSession) -> tuple[str, dict[str, Any]]:
    """Return a WHERE fragment excluding hidden and soft-deleted batch rows.

    Batches without a visibility row are treated as visible for compatibility with
    data ingested before `batch_visibility` existed. New ingest jobs write
    visible=0 before loading rows and visible=1 only after a successful commit.
    """
    deleted = (
        await session.execute(select(Batch.id).where(Batch.deleted_at.is_not(None)))
    ).scalars().all()
    clauses = [
        """
batch_id NOT IN (
    SELECT batch_id
    FROM batch_visibility
    GROUP BY batch_id
    HAVING argMax(visible, version) = 0
)""".strip()
    ]
    if not deleted:
        return " AND " + " AND ".join(clauses), {}
    parts: list[str] = []
    params: dict[str, Any] = {}
    for i, bid in enumerate(deleted):
        k = f"bd_{i}"
        params[k] = str(bid)
        parts.append(f"toUUID({{{k}:String}})")
    clauses.append("batch_id NOT IN (" + ", ".join(parts) + ")")
    return " AND " + " AND ".join(clauses), params


PURGE_TABLES_DELETE_ORDER: tuple[str, ...] = ("leads", "lead_identities", "lead_tags")


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


async def mark_batch_visibility(
    ch: Any,
    batch_id: UUID,
    *,
    visible: bool,
    reason: str,
) -> None:
    await ch.insert(
        "batch_visibility",
        [[str(batch_id), 1 if visible else 0, reason[:128]]],
        column_names=["batch_id", "visible", "reason"],
    )
