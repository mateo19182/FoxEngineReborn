"""Procrastinate application and background tasks (import side effects register tasks)."""

from __future__ import annotations

import logging
from uuid import UUID

from procrastinate import App
from procrastinate.psycopg_connector import PsycopgConnector

from foxengine.config import get_settings

log = logging.getLogger(__name__)

_pg_connector: PsycopgConnector | None = None


def _connector() -> PsycopgConnector:
    global _pg_connector
    if _pg_connector is None:
        _pg_connector = PsycopgConnector(conninfo=get_settings().database_url_sync)
    return _pg_connector


pg_app = App(connector=_connector())


@pg_app.periodic(cron="*/10 * * * *")
@pg_app.task(queueing_lock="retry_stalled_jobs", pass_context=True)
async def retry_stalled_jobs_task(context, timestamp: int) -> None:
    from foxengine.services.job_recovery import retry_stalled_procrastinate_jobs

    await retry_stalled_procrastinate_jobs()


async def _fail_job_state(job_id: UUID, msg: str) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import update

    from foxengine.db.models import Job
    from foxengine.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(state="failed", finished_at=datetime.now(UTC), error=msg[:8000])
        )
        await session.commit()


@pg_app.task(name="foxengine_export")
async def foxengine_export(job_id: str) -> None:
    from foxengine.services.export_run import run_export_job

    jid = UUID(job_id)
    try:
        await run_export_job(jid)
    except Exception as e:
        log.exception("export job failed")
        await _fail_job_state(jid, str(e))
        raise


@pg_app.task(name="foxengine_ingest_file")
async def foxengine_ingest_file(job_id: str) -> None:
    from foxengine.services.ingest_file_run import run_ingest_file_job

    jid = UUID(job_id)
    try:
        await run_ingest_file_job(jid)
    except Exception as e:
        log.exception("ingest file job failed")
        await _fail_job_state(jid, str(e))
        raise


@pg_app.task(name="foxengine_bulk_tag")
async def foxengine_bulk_tag(job_id: str) -> None:
    from foxengine.services.bulk_tag_run import run_bulk_tag_job

    jid = UUID(job_id)
    try:
        await run_bulk_tag_job(jid)
    except Exception as e:
        log.exception("bulk tag job failed")
        await _fail_job_state(jid, str(e))
        raise
