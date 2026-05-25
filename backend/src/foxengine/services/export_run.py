"""Run export jobs: ClickHouse → S3 (native) with keyset streaming fallback."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from foxengine.audit_log import schedule_audit
from foxengine.clickhouse import get_ch_client
from foxengine.config import get_settings
from foxengine.db.models import Job
from foxengine.db.session import get_session_factory
from foxengine.services.export_progress import (
    poll_clickhouse_export_rows,
    update_export_job_progress,
)
from foxengine.services.export_query import (
    ExportCursor,
    export_object_key,
    export_s3_url,
    normalize_export_columns,
)
from foxengine.services.export_s3 import ExportS3Writer
from foxengine.services.export_stream import export_streaming_to_s3, try_export_clickhouse_s3
from foxengine.services.job_queries import compile_leads_where, leads_count_sql

log = logging.getLogger(__name__)


def _export_checkpoint(
    ck: dict[str, Any],
    *,
    dsl: str,
    fmt: str,
    export_method: str | None = None,
    export_phase: str | None = None,
    processed_rows: int | None = None,
) -> dict[str, Any]:
    out = {**ck, "dsl": dsl, "format": fmt}
    if export_method is not None:
        out["export_method"] = export_method
    if export_phase is not None:
        out["export_phase"] = export_phase
    if processed_rows is not None:
        out["processed_rows"] = processed_rows
    return out


async def run_export_job(job_id: UUID) -> None:
    s = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(Job).where(Job.id == job_id))
        job = res.scalar_one_or_none()
        if job is None:
            log.error("export job missing: %s", job_id)
            return
        ck = dict(job.checkpoint or {})
        dsl = ck.get("dsl")
        fmt = ck.get("format", "csv")
        if not isinstance(dsl, str) or not dsl.strip():
            await _fail_job(session, job_id, "missing dsl in checkpoint")
            return
        if fmt not in ("csv", "jsonl"):
            await _fail_job(session, job_id, f"unsupported format: {fmt!r}")
            return
        columns_raw = ck.get("columns")
        try:
            columns = normalize_export_columns(
                columns_raw if isinstance(columns_raw, list) else None
            )
        except ValueError as e:
            await _fail_job(session, job_id, str(e))
            return

        owner = job.owner_user_id
        compiled = await compile_leads_where(session, dsl)

    row_cap = s.max_export_rows
    rl_raw = ck.get("row_limit")
    if isinstance(rl_raw, int) and rl_raw > 0:
        row_cap = min(row_cap, rl_raw)

    force_stream = ck.get("export_method") == "stream"
    upload_id = ck.get("s3_upload_id") if isinstance(ck.get("s3_upload_id"), str) else None
    resume_cursor = ExportCursor.from_checkpoint(ck.get("resume_cursor"))
    prior_rows = int(ck.get("processed_rows") or 0) if resume_cursor and upload_id else 0
    if resume_cursor is not None and not upload_id:
        resume_cursor = None
        prior_rows = 0

    ch = await get_ch_client()

    async with factory() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                state="running",
                started_at=datetime.now(UTC),
                error=None,
                processed_rows=prior_rows,
                checkpoint=_export_checkpoint(
                    ck, dsl=dsl, fmt=fmt, export_phase="counting"
                ),
            )
        )
        await session.commit()

    match_total = await _matching_row_total(ch, compiled, row_cap)
    target_rows = match_total

    await update_export_job_progress(
        factory,
        job_id,
        total_rows=target_rows,
        checkpoint=_export_checkpoint(ck, dsl=dsl, fmt=fmt, export_phase="exporting"),
    )

    key = export_object_key(job_id, fmt)
    s3_url = export_s3_url(s.s3_endpoint_url, s.s3_bucket_exports, key)
    result_uri = f"s3://{s.s3_bucket_exports}/{key}"

    total_written = prior_rows
    last_cursor = resume_cursor
    export_method = "stream" if force_stream else "ch_s3"

    try:
        if s.export_use_ch_s3 and not force_stream and resume_cursor is None:
            try:
                query_id = f"export-{job_id}"
                ch_ck = _export_checkpoint(
                    ck, dsl=dsl, fmt=fmt, export_method="ch_s3", export_phase="ch_s3_write"
                )
                await update_export_job_progress(factory, job_id, checkpoint=ch_ck)
                stop_poll = asyncio.Event()
                poll_task = asyncio.create_task(
                    poll_clickhouse_export_rows(
                        ch,
                        factory,
                        job_id=job_id,
                        query_id=query_id,
                        target_rows=target_rows,
                        base_checkpoint=ch_ck,
                        stop=stop_poll,
                    )
                )
                try:
                    await try_export_clickhouse_s3(
                        ch,
                        compiled=compiled,
                        s3_url=s3_url,
                        access_key=s.s3_access_key_id,
                        secret_key=s.s3_secret_access_key,
                        export_format=fmt,
                        row_cap=row_cap,
                        columns=columns,
                        query_id=query_id,
                    )
                finally:
                    stop_poll.set()
                    await poll_task
                total_written = target_rows
                export_method = "ch_s3"
                await update_export_job_progress(
                    factory,
                    job_id,
                    processed_rows=total_written,
                    checkpoint=_export_checkpoint(
                        ck, dsl=dsl, fmt=fmt, export_method="ch_s3"
                    ),
                )
            except Exception as e:
                log.warning(
                    "export job %s: ClickHouse s3() failed (%s), falling back to streaming",
                    job_id,
                    e,
                )
                export_method = "stream"

        if export_method == "stream":
            remaining = row_cap - prior_rows
            if remaining > 0:
                await update_export_job_progress(
                    factory,
                    job_id,
                    checkpoint=_export_checkpoint(
                        ck, dsl=dsl, fmt=fmt, export_method="stream", export_phase="streaming"
                    ),
                )
                prior_parts = ck.get("s3_parts") if isinstance(ck.get("s3_parts"), list) else None
                next_part = len(prior_parts) + 1 if prior_parts else 1
                async with ExportS3Writer(
                    endpoint_url=s.s3_endpoint_url,
                    access_key_id=s.s3_access_key_id,
                    secret_access_key=s.s3_secret_access_key,
                    region_name=s.s3_region,
                    bucket=s.s3_bucket_exports,
                    key=key,
                    part_size=s.export_s3_part_bytes,
                    upload_id=upload_id,
                    completed_parts=prior_parts,
                    next_part_number=next_part,
                    abort_on_exception=False,
                ) as writer:

                    async def on_batch(processed: int, cursor: ExportCursor | None) -> None:
                        nonlocal last_cursor
                        last_cursor = cursor
                        checkpoint = _export_checkpoint(
                            ck,
                            dsl=dsl,
                            fmt=fmt,
                            export_method="stream",
                            export_phase="streaming",
                            processed_rows=prior_rows + processed,
                        )
                        if cursor is not None:
                            checkpoint["resume_cursor"] = cursor.to_checkpoint()
                        if writer.upload_id is not None:
                            checkpoint["s3_upload_id"] = writer.upload_id
                        if writer.completed_parts:
                            checkpoint["s3_parts"] = writer.completed_parts
                        await update_export_job_progress(
                            factory,
                            job_id,
                            processed_rows=prior_rows + processed,
                            checkpoint=checkpoint,
                        )

                    batch_written, last_cursor = await export_streaming_to_s3(
                        ch,
                        compiled=compiled,
                        writer=writer,
                        export_format=fmt,
                        row_cap=remaining,
                        batch_size=s.export_batch_size,
                        cursor=resume_cursor,
                        columns=columns,
                        csv_include_header=resume_cursor is None,
                        on_batch=on_batch,
                    )
                    await writer.complete()
                total_written = min(row_cap, prior_rows + batch_written)
            else:
                total_written = prior_rows

    except Exception as e:
        log.exception("export job %s failed", job_id)
        async with factory() as session:
            checkpoint: dict[str, Any] = {
                **ck,
                "dsl": dsl,
                "format": fmt,
                "export_method": export_method,
                "processed_rows": total_written,
            }
            if last_cursor is not None:
                checkpoint["resume_cursor"] = last_cursor.to_checkpoint()
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    state="failed",
                    finished_at=datetime.now(UTC),
                    error=str(e)[:2000],
                    processed_rows=total_written,
                    checkpoint=checkpoint,
                )
            )
            await session.commit()
        return

    async with factory() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                state="done",
                finished_at=datetime.now(UTC),
                processed_rows=total_written,
                total_rows=total_written,
                result_uri=result_uri,
                checkpoint={
                    **ck,
                    "dsl": dsl,
                    "format": fmt,
                    "export_method": export_method,
                    "rows": total_written,
                },
            )
        )
        await session.commit()

    if owner:
        schedule_audit(
            actor_id=owner,
            actor_kind="user",
            api_key_id=None,
            action="export.done",
            target_kind="job",
            target_id=str(job_id),
            details={"rows": total_written, "format": fmt, "uri": key, "method": export_method},
            ip=None,
            user_agent=None,
        )


async def _matching_row_total(ch: Any, compiled: Any, row_cap: int) -> int:
    qr = await ch.query(
        leads_count_sql(compiled),
        parameters=compiled.parameters,
        settings={"max_execution_time": 3600, "max_memory_usage": "8000000000"},
    )
    return min(int(qr.first_row[0]), row_cap)


async def _fail_job(session: Any, job_id: UUID, error: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            state="failed",
            finished_at=datetime.now(UTC),
            error=error,
        )
    )
    await session.commit()
