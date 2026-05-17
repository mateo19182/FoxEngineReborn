"""Run export jobs: stream ClickHouse rows to RustFS as CSV or JSONL."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import aioboto3
from sqlalchemy import select, update

from foxengine.audit_log import schedule_audit
from foxengine.clickhouse import get_ch_client
from foxengine.config import get_settings
from foxengine.db.models import Job
from foxengine.db.session import get_session_factory
from foxengine.services.job_queries import compile_leads_where

log = logging.getLogger(__name__)

CH_SETTINGS = {
    "max_execution_time": 3600,
    "max_result_rows": 10_000_000,
    "max_memory_usage": "8000000000",
}


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
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    state="failed",
                    finished_at=datetime.now(UTC),
                    error="missing dsl in checkpoint",
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
        where_sql, params = await compile_leads_where(session, dsl)

    row_cap = s.max_export_rows
    rl_raw = ck.get("row_limit")
    if isinstance(rl_raw, int) and rl_raw > 0:
        row_cap = min(row_cap, rl_raw)

    base = f"SELECT * FROM leads WHERE {where_sql} ORDER BY ingest_ts DESC"

    ch = await get_ch_client()
    total_written = 0
    columns: list[str] | None = None
    buf = io.StringIO()
    csv_writer: Any = None

    batch_size = 50_000
    offset = int(ck.get("resume_offset") or 0)

    if fmt == "csv":
        csv_writer = csv.writer(buf)

    while total_written < row_cap:
        lim = min(batch_size, row_cap - total_written)
        data_sql = f"{base} LIMIT {lim} OFFSET {offset}"
        qr = await ch.query(data_sql, parameters=params, settings=CH_SETTINGS)
        rows = list(qr.named_results())
        if not rows:
            break
        if fmt == "csv":
            assert csv_writer is not None
            if columns is None:
                columns = sorted(rows[0].keys())
                csv_writer.writerow(columns)
            for r in rows:
                d = dict(r)
                csv_writer.writerow([_fmt_csv_cell(d.get(c)) for c in columns])
        else:
            for r in rows:
                buf.write(
                    json.dumps(dict(r), ensure_ascii=False, default=_export_json_default)
                    + "\n"
                )
        total_written += len(rows)
        offset += len(rows)
        async with factory() as s2:
            await s2.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    processed_rows=total_written,
                    checkpoint={**ck, "dsl": dsl, "format": fmt, "resume_offset": offset},
                )
            )
            await s2.commit()
        if len(rows) < lim:
            break

    body = buf.getvalue().encode("utf-8")
    ext = "csv" if fmt == "csv" else "jsonl"
    key = f"exports/{job_id}/result.{ext}"

    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        await c.put_object(Bucket=s.s3_bucket_exports, Key=key, Body=body)

    async with factory() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                state="done",
                finished_at=datetime.now(UTC),
                processed_rows=total_written,
                result_uri=f"s3://{s.s3_bucket_exports}/{key}",
                checkpoint={**ck, "resume_offset": offset, "rows": total_written},
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
            details={"rows": total_written, "format": fmt, "uri": key},
            ip=None,
            user_agent=None,
        )


def _export_json_default(o: Any) -> Any:
    if isinstance(o, (bytes, bytearray)):
        return o.decode("utf-8", errors="replace")
    return str(o)


def _fmt_csv_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, default=_export_json_default)
    return str(v)
