"""Background purge: remove soft-deleted batch rows from ClickHouse via lightweight DELETE."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from foxengine.audit_log import schedule_audit
from foxengine.clickhouse import get_ch_client
from foxengine.db.models import Batch, Job
from foxengine.db.session import get_session_factory
from foxengine.services.deleted_batches import (
    batch_clickhouse_counts,
    lightweight_delete_batch_rows,
    mark_batch_visibility,
)

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
MAX_WAIT_S = 3600


async def _wait_for_zero_rows(ch: Any, batch_id: UUID) -> dict[str, int]:
    elapsed = 0.0
    counts = await batch_clickhouse_counts(ch, batch_id)
    while any(counts.values()) and elapsed < MAX_WAIT_S:
        await asyncio.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S
        counts = await batch_clickhouse_counts(ch, batch_id)
    return counts


async def run_batch_purge_job(job_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(Job).where(Job.id == job_id))
        job = res.scalar_one_or_none()
        if job is None:
            log.error("batch purge job missing: %s", job_id)
            return
        if job.type != "batch_purge":
            log.error("job %s is not batch_purge", job_id)
            return
        batch_id = job.batch_id
        if batch_id is None:
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    state="failed",
                    finished_at=datetime.now(UTC),
                    error="missing batch_id",
                )
            )
            await session.commit()
            return

        batch = await session.scalar(select(Batch).where(Batch.id == batch_id))
        if batch is None:
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    state="failed",
                    finished_at=datetime.now(UTC),
                    error="batch not found",
                )
            )
            await session.commit()
            return
        if batch.deleted_at is None:
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    state="failed",
                    finished_at=datetime.now(UTC),
                    error="batch is not soft-deleted",
                )
            )
            await session.commit()
            return

        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(state="running", started_at=datetime.now(UTC), error=None)
        )
        await session.commit()
        owner = job.owner_user_id
        already_purged = batch.purged_at is not None

    ch = await get_ch_client()
    try:
        await mark_batch_visibility(ch, batch_id, visible=False, reason="batch_purge")
        if not already_purged:
            await lightweight_delete_batch_rows(ch, batch_id)
            counts = await _wait_for_zero_rows(ch, batch_id)
            if any(counts.values()):
                raise TimeoutError(
                    f"ClickHouse rows remain after {MAX_WAIT_S}s: {counts}"
                )
    except Exception as e:
        log.exception("batch purge failed for batch %s", batch_id)
        async with factory() as session:
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    state="failed",
                    finished_at=datetime.now(UTC),
                    error=str(e)[:8000],
                )
            )
            await session.commit()
        if owner:
            schedule_audit(
                actor_id=owner,
                actor_kind="user",
                api_key_id=None,
                action="batch.purge.failed",
                target_kind="batch",
                target_id=str(batch_id),
                details={"job_id": str(job_id), "error": str(e)[:2000]},
                ip=None,
                user_agent=None,
            )
        raise

    now = datetime.now(UTC)
    async with factory() as session:
        await session.execute(
            update(Batch).where(Batch.id == batch_id).values(purged_at=now)
        )
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                state="done",
                finished_at=now,
                processed_rows=0,
                checkpoint={"batch_id": str(batch_id), "purged": True},
            )
        )
        await session.commit()

    if owner:
        schedule_audit(
            actor_id=owner,
            actor_kind="user",
            api_key_id=None,
            action="batch.purge.done",
            target_kind="batch",
            target_id=str(batch_id),
            details={"job_id": str(job_id)},
            ip=None,
            user_agent=None,
        )
