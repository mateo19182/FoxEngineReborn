"""Queue batch_tag jobs to tag all leads in an ingest batch."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Batch, Job
from foxengine.deps import Principal


def can_manage_batch(principal: Principal, batch: Batch) -> bool:
    if "admin" in principal.roles:
        return True
    return batch.ingested_by is not None and batch.ingested_by == principal.user_id


async def assert_batch_taggable(
    session: AsyncSession,
    *,
    batch_id: UUID,
    batch: Batch,
) -> None:
    if batch.deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "batch deleted")
    if batch.purged_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "batch purged")
    if int(batch.accepted_rows) <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "batch has no accepted rows")

    ingest_active = await session.scalar(
        select(Job.id).where(
            Job.batch_id == batch_id,
            Job.type == "ingest_file",
            Job.state.in_(("queued", "running")),
        )
    )
    if ingest_active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "ingest still in progress")

    tag_active = await session.scalar(
        select(Job.id).where(
            Job.batch_id == batch_id,
            Job.type == "batch_tag",
            Job.state.in_(("queued", "running")),
        )
    )
    if tag_active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "batch tag job already running")


async def queue_batch_tag_job(
    session: AsyncSession,
    *,
    batch: Batch,
    tag_names: list[str],
    principal: Principal,
) -> Job:
    owner = batch.ingested_by if batch.ingested_by is not None else principal.user_id
    job = Job(
        id=uuid4(),
        type="batch_tag",
        state="queued",
        batch_id=batch.id,
        owner_user_id=principal.user_id,
        checkpoint={
            "tag_names": tag_names,
            "batch_id": str(batch.id),
            "owner_user_id": str(owner),
        },
    )
    session.add(job)
    await session.flush()
    return job
