"""Queue ClickHouse purge jobs for deleted batches."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Batch, Job
from foxengine.deps import Principal
from foxengine.services.deleted_batches import batch_clickhouse_counts


async def schedule_batch_purge(
    session: AsyncSession,
    ch: Any,
    *,
    batch_id: UUID,
    batch: Batch,
    principal: Principal,
    request: Request | None,
    audit_fn: Any,
) -> str | None:
    """Return new purge job id, or None if nothing to purge / already pending / already purged."""
    if batch.purged_at is not None:
        return None

    pending = await session.scalar(
        select(Job.id).where(
            Job.batch_id == batch_id,
            Job.type == "batch_purge",
            Job.state.in_(("queued", "running")),
        )
    )
    if pending is not None:
        return str(pending)

    counts = await batch_clickhouse_counts(ch, batch_id)
    if not any(counts.values()):
        await session.execute(
            update(Batch).where(Batch.id == batch_id).values(purged_at=datetime.now(UTC))
        )
        return None

    job = Job(
        type="batch_purge",
        state="queued",
        batch_id=batch_id,
        owner_user_id=principal.user_id,
        checkpoint={"batch_id": str(batch_id)},
    )
    session.add(job)
    await session.flush()
    if request is not None:
        audit_fn(
            request,
            principal,
            "batch.purge.queued",
            target_kind="batch",
            target_id=str(batch_id),
            details={"job_id": str(job.id), "clickhouse_rows": counts},
        )
    return str(job.id)
