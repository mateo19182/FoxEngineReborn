"""Background ingest from a file already stored in RustFS (JSONL or CSV)."""

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

from foxengine.clickhouse import get_ch_client
from foxengine.config import get_settings
from foxengine.db.models import Batch, IngestRejection, Job
from foxengine.db.session import get_session_factory
from foxengine.services.ingest import resolve_tag_ids
from foxengine.services.ingest_rows import (
    CH_INSERT_COLUMNS,
    RowOutcome,
    csv_row_to_raw,
    ingest_timestamp,
    materialize_lead_row,
)

log = logging.getLogger(__name__)


async def run_ingest_file_job(job_id: UUID) -> None:
    s = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(Job).where(Job.id == job_id))
        job = res.scalar_one_or_none()
        if job is None or job.batch_id is None:
            log.error("ingest job missing: %s", job_id)
            return
        ck = dict(job.checkpoint or {})
        s3_key = ck.get("s3_key")
        fmt = str(ck.get("format", "jsonl")).lower()
        tag_names = [str(x) for x in (ck.get("tag_names") or []) if str(x).strip()]
        cm_raw = ck.get("column_map")
        column_map: dict[str, Any] = cm_raw if isinstance(cm_raw, dict) else {}
        column_map_s = {str(k): str(v) for k, v in column_map.items()}
        default_region = ck.get("default_phone_region")
        default_region_s = str(default_region).strip().upper() if default_region else None
        csv_delim = str(ck.get("csv_delimiter") or ",")
        if len(csv_delim) != 1:
            csv_delim = ","
        if not isinstance(s3_key, str) or not s3_key.strip():
            await _fail_job(session, job_id, "missing s3_key")
            return

        batch_res = await session.execute(select(Batch).where(Batch.id == job.batch_id))
        batch = batch_res.scalar_one_or_none()
        if batch is None:
            await _fail_job(session, job_id, "batch missing")
            return
        owner = batch.ingested_by
        if owner is None:
            await _fail_job(session, job_id, "batch owner missing")
            return

        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(state="running", started_at=datetime.now(UTC), error=None)
        )
        await session.commit()

        tag_ids = await resolve_tag_ids(session, tag_names, owner)
        tag_id_strs = [str(u) for u in tag_ids]
        await session.commit()

    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        obj = await c.get_object(Bucket=s.s3_bucket_uploads, Key=s3_key)
        body = await obj["Body"].read()

    text = body.decode("utf-8", errors="replace")
    ch_rows: list[list[Any]] = []
    rejections: list[tuple[int, str, str]] = []
    seen_hashes: set[str] = set()
    accepted = 0
    rejected = 0
    dup = 0
    rib = 0
    ts = ingest_timestamp()

    if fmt == "jsonl":
        for i, raw_s in enumerate(text.splitlines()):
            line_no = i + 1
            raw_s = raw_s.strip()
            if not raw_s or raw_s.startswith("#"):
                continue
            try:
                raw = json.loads(raw_s)
            except json.JSONDecodeError:
                rejections.append((line_no, "invalid json", raw_s[:8000]))
                rejected += 1
                continue
            if not isinstance(raw, dict):
                rejections.append((line_no, "json must be object", raw_s[:8000]))
                rejected += 1
                continue
            rib, accepted, dup, rejected = _append_row(
                raw,
                batch.id,
                rib,
                accepted,
                dup,
                rejected,
                line_no,
                tag_id_strs,
                seen_hashes,
                ts,
                default_region_s,
                ch_rows,
                rejections,
            )
    elif fmt == "csv":
        reader = csv.reader(io.StringIO(text), delimiter=csv_delim)
        all_rows = list(reader)
        if not all_rows:
            async with factory() as session:
                await _fail_job(session, job_id, "empty csv")
            return
        header = [h.strip() for h in all_rows[0]]
        for j, cells in enumerate(all_rows[1:]):
            line_no = j + 2
            raw = csv_row_to_raw(header, cells, column_map_s)
            rib, accepted, dup, rejected = _append_row(
                raw,
                batch.id,
                rib,
                accepted,
                dup,
                rejected,
                line_no,
                tag_id_strs,
                seen_hashes,
                ts,
                default_region_s,
                ch_rows,
                rejections,
            )
    elif fmt == "combo":
        for i, raw_s in enumerate(text.splitlines()):
            line_no = i + 1
            raw_s = raw_s.strip()
            if not raw_s or raw_s.startswith("#"):
                continue
            if ":" not in raw_s:
                rejections.append((line_no, "combo line needs colon", raw_s[:8000]))
                rejected += 1
                continue
            left, right = raw_s.split(":", 1)
            raw = {"email": left.strip(), "password": right.strip()}
            rib, accepted, dup, rejected = _append_row(
                raw,
                batch.id,
                rib,
                accepted,
                dup,
                rejected,
                line_no,
                tag_id_strs,
                seen_hashes,
                ts,
                default_region_s,
                ch_rows,
                rejections,
            )
    else:
        async with factory() as session:
            await _fail_job(session, job_id, f"unsupported format {fmt!r}")
        return

    ch = await get_ch_client()
    if ch_rows:
        await ch.insert("leads", ch_rows, column_names=CH_INSERT_COLUMNS)

    async with factory() as session:
        for line_no, reason, raw_line in rejections:
            session.add(
                IngestRejection(
                    batch_id=batch.id,
                    line_no=line_no,
                    reason=reason,
                    raw_line=raw_line,
                )
            )
        await session.execute(
            update(Batch)
            .where(Batch.id == batch.id)
            .values(accepted_rows=accepted, rejected_rows=rejected, duplicate_rows=dup)
        )
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                state="done",
                finished_at=datetime.now(UTC),
                processed_rows=accepted + rejected + dup,
                checkpoint={
                    **ck,
                    "accepted_rows": accepted,
                    "rejected_rows": rejected,
                    "duplicate_rows": dup,
                },
            )
        )
        await session.commit()


def _append_row(
    raw: dict[str, Any],
    batch_id: UUID,
    rib: int,
    accepted: int,
    dup: int,
    rejected: int,
    line_no: int,
    tag_id_strs: list[str],
    seen_hashes: set[str],
    ts: datetime,
    default_region: str | None,
    ch_rows: list[list[Any]],
    rejections: list[tuple[int, str, str]],
) -> tuple[int, int, int, int]:
    outcome, ch_row, reason, raw_line = materialize_lead_row(
        raw,
        batch_id=batch_id,
        row_in_batch=rib + 1,
        ingest_ts=ts,
        tag_id_strs=tag_id_strs,
        seen_hashes=seen_hashes,
        default_phone_region=default_region,
    )
    if outcome is RowOutcome.rejected:
        rejections.append((line_no, reason or "rejected", (raw_line or str(raw))[:8000]))
        return rib, accepted, dup, rejected + 1
    if outcome is RowOutcome.duplicate:
        return rib, accepted, dup + 1, rejected
    assert ch_row is not None
    new_rib = rib + 1
    ch_row[1] = new_rib
    ch_rows.append(ch_row)
    return new_rib, accepted + 1, dup, rejected


async def _fail_job(session: Any, job_id: UUID, msg: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state="failed", finished_at=datetime.now(UTC), error=msg)
    )
    await session.commit()
