"""Export job progress updates (Postgres) and ClickHouse query polling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import update

from foxengine.db.models import Job

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0


async def update_export_job_progress(
    factory: Any,
    job_id: UUID,
    *,
    processed_rows: int | None = None,
    total_rows: int | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> None:
    values: dict[str, Any] = {}
    if processed_rows is not None:
        values["processed_rows"] = processed_rows
    if total_rows is not None:
        values["total_rows"] = total_rows
    if checkpoint is not None:
        values["checkpoint"] = checkpoint
    if not values:
        return
    async with factory() as session:
        await session.execute(update(Job).where(Job.id == job_id).values(**values))
        await session.commit()


async def poll_clickhouse_export_rows(
    ch: Any,
    factory: Any,
    *,
    job_id: UUID,
    query_id: str,
    target_rows: int,
    base_checkpoint: dict[str, Any],
    stop: asyncio.Event,
) -> None:
    """Poll system.processes.read_rows while a server-side export INSERT runs."""
    while not stop.is_set():
        try:
            qr = await ch.query(
                """
                SELECT read_rows
                FROM system.processes
                WHERE query_id = {qid:String}
                ORDER BY read_rows DESC
                LIMIT 1
                """,
                parameters={"qid": query_id},
                settings={"max_execution_time": 5},
            )
            if qr.result_rows:
                read = min(int(qr.first_row[0]), target_rows)
                if read > 0:
                    await update_export_job_progress(
                        factory,
                        job_id,
                        processed_rows=read,
                        checkpoint={
                            **base_checkpoint,
                            "export_method": "ch_s3",
                            "export_phase": "ch_s3_write",
                        },
                    )
        except Exception:
            log.debug("export progress poll failed for %s", job_id, exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_S)
        except TimeoutError:
            pass
