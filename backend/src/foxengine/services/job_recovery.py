"""Recover background jobs after worker restarts."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update

from foxengine.db.models import Job
from foxengine.db.session import get_session_factory

log = logging.getLogger(__name__)

TASK_NAME_BY_JOB_TYPE: dict[str, str] = {
    "ingest_file": "foxengine_ingest_file",
    "export": "foxengine_export",
    "bulk_tag": "foxengine_bulk_tag",
}

FOX_BACKGROUND_JOB_TYPES = tuple(TASK_NAME_BY_JOB_TYPE)


async def _defer_fox_job(job_type: str, job_id: UUID) -> None:
    from foxengine.tasks import foxengine_bulk_tag, foxengine_export, foxengine_ingest_file

    defer_by_type = {
        "ingest_file": foxengine_ingest_file.defer_async,
        "export": foxengine_export.defer_async,
        "bulk_tag": foxengine_bulk_tag.defer_async,
    }
    defer_fn = defer_by_type[job_type]
    await defer_fn(job_id=str(job_id))


async def retry_stalled_procrastinate_jobs(*, seconds_since_heartbeat: float = 30) -> int:
    from foxengine.tasks import pg_app

    stalled = list(
        await pg_app.job_manager.get_stalled_jobs(
            seconds_since_heartbeat=seconds_since_heartbeat,
        )
    )
    for job in stalled:
        await pg_app.job_manager.retry_job(job)
    if stalled:
        log.info("retried %s stalled procrastinate jobs", len(stalled))
    return len(stalled)


async def retry_doing_procrastinate_for_running_fox_jobs() -> int:
    """Retry procrastinate rows stuck in doing while the fox job is still running."""
    from foxengine.tasks import pg_app

    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(
            text(
                """
                SELECT pj.id
                FROM procrastinate_jobs AS pj
                INNER JOIN jobs AS j ON j.id::text = pj.args->>'job_id'
                WHERE pj.status = 'doing'
                  AND j.state = 'running'
                  AND j.finished_at IS NULL
                  AND j.type IN ('ingest_file', 'export', 'bulk_tag')
                """
            )
        )
        pg_ids = [int(row[0]) for row in res.fetchall()]

    now = datetime.now(UTC)
    for pg_id in pg_ids:
        await pg_app.job_manager.retry_job_by_id_async(job_id=pg_id, retry_at=now)
    if pg_ids:
        log.info("retried %s doing procrastinate jobs for running fox jobs", len(pg_ids))
    return len(pg_ids)


async def list_procrastinate_jobs_for_fox(
    session: Any,
    *,
    job_id: UUID,
    task_name: str,
) -> list[tuple[int, str]]:
    res = await session.execute(
        text(
            """
            SELECT id, status::text
            FROM procrastinate_jobs
            WHERE task_name = :task_name
              AND args->>'job_id' = :job_id
            ORDER BY id DESC
            """
        ),
        {"task_name": task_name, "job_id": str(job_id)},
    )
    return [(int(row[0]), str(row[1])) for row in res.fetchall()]


async def reconcile_orphaned_fox_jobs() -> int:
    factory = get_session_factory()
    from foxengine.tasks import pg_app

    requeued = 0
    retried_doing = 0

    async with factory() as session:
        res = await session.execute(
            select(Job).where(
                Job.state.in_(("running", "queued")),
                Job.finished_at.is_(None),
                Job.type.in_(FOX_BACKGROUND_JOB_TYPES),
            )
        )
        jobs = list(res.scalars().all())

    now = datetime.now(UTC)
    for job in jobs:
        task_name = TASK_NAME_BY_JOB_TYPE.get(job.type)
        if task_name is None:
            continue

        async with factory() as session:
            pg_jobs = await list_procrastinate_jobs_for_fox(
                session, job_id=job.id, task_name=task_name
            )

        if any(status == "todo" for _, status in pg_jobs):
            continue

        doing_ids = [pg_id for pg_id, status in pg_jobs if status == "doing"]
        if doing_ids:
            for pg_id in doing_ids:
                await pg_app.job_manager.retry_job_by_id_async(job_id=pg_id, retry_at=now)
            retried_doing += len(doing_ids)
            log.info(
                "retried %s doing procrastinate job(s) for fox job %s (%s)",
                len(doing_ids),
                job.id,
                job.type,
            )
            continue

        async with factory() as session:
            await session.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(state="queued", error=None)
            )
            await session.commit()

        await _defer_fox_job(job.type, job.id)
        requeued += 1
        log.info("re-queued orphaned fox job %s (%s)", job.id, job.type)

    if retried_doing:
        log.info("retried %s doing procrastinate jobs via reconcile", retried_doing)
    return requeued


async def recover_fox_job(job_id: UUID) -> str:
    """Recover one fox job. Returns a short action label for the API."""
    factory = get_session_factory()
    from foxengine.tasks import pg_app

    async with factory() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id))
        if job is None:
            return "not_found"
        if job.finished_at is not None or job.state not in ("running", "queued"):
            return "not_recoverable"
        task_name = TASK_NAME_BY_JOB_TYPE.get(job.type)
        if task_name is None:
            return "not_recoverable"
        pg_jobs = await list_procrastinate_jobs_for_fox(
            session, job_id=job.id, task_name=task_name
        )

    now = datetime.now(UTC)
    if any(status == "todo" for _, status in pg_jobs):
        return "already_queued"

    doing_ids = [pg_id for pg_id, status in pg_jobs if status == "doing"]
    if doing_ids:
        for pg_id in doing_ids:
            await pg_app.job_manager.retry_job_by_id_async(job_id=pg_id, retry_at=now)
        return "retried_doing"

    async with factory() as session:
        await session.execute(
            update(Job).where(Job.id == job_id).values(state="queued", error=None)
        )
        await session.commit()
    await _defer_fox_job(job.type, job_id)
    return "requeued"


async def run_worker_recovery() -> None:
    try:
        doing_retried = await retry_doing_procrastinate_for_running_fox_jobs()
        stalled = await retry_stalled_procrastinate_jobs(seconds_since_heartbeat=0)
        requeued = await reconcile_orphaned_fox_jobs()
        log.info(
            "worker recovery complete: doing_retried=%s stalled_retried=%s fox_requeued=%s",
            doing_retried,
            stalled,
            requeued,
        )
    except Exception:
        log.exception("worker recovery failed")
