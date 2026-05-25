"""Apply tags to every lead row in an ingest batch (post-ingest)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from foxengine.clickhouse import get_ch_client
from foxengine.db.models import Batch, Job
from foxengine.db.session import get_session_factory
from foxengine.services.ingest import resolve_tag_ids

log = logging.getLogger(__name__)


async def run_batch_tag_job(job_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(Job).where(Job.id == job_id))
        job = res.scalar_one_or_none()
        if job is None:
            log.error("batch_tag job missing: %s", job_id)
            return
        if job.type != "batch_tag":
            log.error("job %s is not batch_tag", job_id)
            return
        ck = dict(job.checkpoint or {})
        tag_names = [str(x) for x in (ck.get("tag_names") or []) if str(x).strip()]
        batch_id = job.batch_id
        owner_s = ck.get("owner_user_id")
        if batch_id is None:
            await _fail(session, job_id, "missing batch_id")
            return
        if not tag_names:
            await _fail(session, job_id, "missing tag_names")
            return
        if not isinstance(owner_s, str):
            await _fail(session, job_id, "missing owner_user_id")
            return
        owner = UUID(owner_s)

        batch = await session.scalar(select(Batch).where(Batch.id == batch_id))
        if batch is None:
            await _fail(session, job_id, "batch not found")
            return
        if batch.deleted_at is not None:
            await _fail(session, job_id, "batch deleted")
            return
        if batch.purged_at is not None:
            await _fail(session, job_id, "batch purged")
            return

        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(state="running", started_at=datetime.now(UTC), error=None)
        )
        await session.commit()

        tag_ids = await resolve_tag_ids(session, tag_names, owner)
        if not tag_ids:
            await _fail(session, job_id, "could not resolve tags")
            return
        await session.commit()

    ch = await get_ch_client()
    qr = await ch.query(
        "SELECT count() FROM leads WHERE batch_id = {bid:UUID}",
        parameters={"bid": batch_id},
    )
    lead_count = int(qr.first_row[0])
    if lead_count == 0:
        async with factory() as session:
            await _fail(session, job_id, "batch has no lead rows")
        return

    assigned_at = datetime.now(UTC).replace(tzinfo=None)
    source = f"batch_tag:{job_id}"
    for tag_id in tag_ids:
        await ch.command(
            """
            INSERT INTO lead_tags (tag_id, batch_id, row_in_batch, assigned_at, source)
            SELECT {tag_id:UUID}, batch_id, row_in_batch, {assigned_at:DateTime}, {source:String}
            FROM leads
            WHERE batch_id = {bid:UUID}
            """,
            parameters={
                "tag_id": tag_id,
                "bid": batch_id,
                "assigned_at": assigned_at,
                "source": source,
            },
        )

    async with factory() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                state="done",
                finished_at=datetime.now(UTC),
                processed_rows=lead_count,
                total_rows=lead_count,
                checkpoint={
                    **ck,
                    "tag_names": tag_names,
                    "tag_count": len(tag_ids),
                    "lead_rows": lead_count,
                },
            )
        )
        await session.commit()


async def _fail(session: Any, job_id: UUID, msg: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state="failed", finished_at=datetime.now(UTC), error=msg[:8000])
    )
    await session.commit()
