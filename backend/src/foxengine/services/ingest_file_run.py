"""Background ingest from a file already stored in RustFS (JSONL or CSV)."""

from __future__ import annotations

import csv
import io
import json
import logging
import tempfile
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
from foxengine.services.ingest_resume import (
    checkpoint_int,
    ingest_needs_resume,
    load_seen_hashes_from_batch,
    max_row_in_batch,
)
from foxengine.services.ingest_rows import (
    CH_IDENTITY_INSERT_COLUMNS,
    CH_INSERT_COLUMNS,
    CH_TAG_INSERT_COLUMNS,
    RowOutcome,
    csv_row_to_raw,
    ingest_timestamp,
    materialize_identity_rows,
    materialize_lead_row,
    materialize_tag_rows,
)

log = logging.getLogger(__name__)
CH_INGEST_FLUSH_ROWS = 50_000
S3_DOWNLOAD_CHUNK_BYTES = 1024 * 1024


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
        manual_column_map = str(ck.get("column_map_source") or "") == "manual"
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

    resume_line_index = checkpoint_int(ck, "resume_line_index", default=-1)
    resume_csv_row = checkpoint_int(ck, "resume_csv_row", default=-1)
    accepted = checkpoint_int(ck, "accepted_rows")
    rejected = checkpoint_int(ck, "rejected_rows")
    dup = checkpoint_int(ck, "duplicate_rows")
    rib = checkpoint_int(ck, "rib")

    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        obj = await c.get_object(Bucket=s.s3_bucket_uploads, Key=s3_key)
        with tempfile.TemporaryFile() as tmp:
            stream = obj["Body"]
            while True:
                chunk = await stream.read(S3_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                tmp.write(chunk)
            tmp.seek(0)

            text_file = io.TextIOWrapper(tmp, encoding="utf-8", errors="replace", newline="")
            ch = await get_ch_client()
            if ingest_needs_resume(ck):
                async def _dedup_load_progress(loaded: int) -> None:
                    async with factory() as session:
                        await session.execute(
                            update(Job)
                            .where(Job.id == job_id)
                            .values(
                                checkpoint={
                                    **ck,
                                    "resume_phase": "loading_dedup",
                                    "dedup_keys_loaded": loaded,
                                }
                            )
                        )
                        await session.commit()

                seen_hashes = await load_seen_hashes_from_batch(
                    ch, batch.id, on_progress=_dedup_load_progress
                )
                rib = max(rib, await max_row_in_batch(ch, batch.id))
                ck = {**ck, "resume_phase": None, "dedup_keys_loaded": len(seen_hashes)}
                log.info(
                    "resuming ingest job %s at line %s csv_row %s rib %s dedup_keys=%s",
                    job_id,
                    resume_line_index,
                    resume_csv_row,
                    rib,
                    len(seen_hashes),
                )
            else:
                seen_hashes = set()

            ch_rows: list[list[Any]] = []
            identity_rows: list[list[Any]] = []
            tag_rows: list[list[Any]] = []
            rejections: list[tuple[int, str, str]] = []
            rejections_flush_at = 0
            last_line_index = resume_line_index
            last_csv_row = resume_csv_row
            ts = ingest_timestamp()

            async def persist_progress() -> None:
                nonlocal rejections_flush_at, ck
                processed = accepted + rejected + dup
                ck = {
                    **ck,
                    "rib": rib,
                    "accepted_rows": accepted,
                    "rejected_rows": rejected,
                    "duplicate_rows": dup,
                    "resume_line_index": last_line_index,
                    "resume_csv_row": last_csv_row,
                }
                async with factory() as session:
                    for line_no, reason, raw_line in rejections[rejections_flush_at:]:
                        session.add(
                            IngestRejection(
                                batch_id=batch.id,
                                line_no=line_no,
                                reason=reason,
                                raw_line=raw_line,
                            )
                        )
                    rejections_flush_at = len(rejections)
                    await session.execute(
                        update(Batch)
                        .where(Batch.id == batch.id)
                        .values(
                            accepted_rows=accepted,
                            rejected_rows=rejected,
                            duplicate_rows=dup,
                        )
                    )
                    await session.execute(
                        update(Job)
                        .where(Job.id == job_id)
                        .values(processed_rows=processed, checkpoint=ck)
                    )
                    await session.commit()

            async def flush_if_needed() -> None:
                if len(ch_rows) >= CH_INGEST_FLUSH_ROWS:
                    await _flush_clickhouse_rows(ch, ch_rows, identity_rows, tag_rows)
                    await persist_progress()

            if fmt == "jsonl":
                for i, raw_s in enumerate(text_file):
                    if i <= resume_line_index:
                        continue
                    line_no = i + 1
                    last_line_index = i
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
                        identity_rows,
                        tag_rows,
                        rejections,
                    )
                    await flush_if_needed()
            elif fmt == "csv":
                reader = csv.reader(text_file, delimiter=csv_delim)
                try:
                    header = [h.strip() for h in next(reader)]
                except StopIteration:
                    async with factory() as session:
                        await _fail_job(session, job_id, "empty csv")
                    return
                for j, cells in enumerate(reader):
                    if j <= resume_csv_row:
                        continue
                    line_no = j + 2
                    last_csv_row = j
                    raw = csv_row_to_raw(
                        header,
                        cells,
                        column_map_s,
                        allow_known_field_fallback=not manual_column_map,
                    )
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
                        identity_rows,
                        tag_rows,
                        rejections,
                    )
                    await flush_if_needed()
            elif fmt == "combo":
                for i, raw_s in enumerate(text_file):
                    if i <= resume_line_index:
                        continue
                    line_no = i + 1
                    last_line_index = i
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
                        identity_rows,
                        tag_rows,
                        rejections,
                    )
                    await flush_if_needed()
            else:
                async with factory() as session:
                    await _fail_job(session, job_id, f"unsupported format {fmt!r}")
                return

            if ch_rows:
                await _flush_clickhouse_rows(ch, ch_rows, identity_rows, tag_rows)
            await persist_progress()

    async with factory() as session:
        for line_no, reason, raw_line in rejections[rejections_flush_at:]:
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
                    "rib": rib,
                    "resume_line_index": last_line_index,
                    "resume_csv_row": last_csv_row,
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
    identity_rows: list[list[Any]],
    tag_rows: list[list[Any]],
    rejections: list[tuple[int, str, str]],
) -> tuple[int, int, int, int]:
    outcome, ch_row, reason, raw_line = materialize_lead_row(
        raw,
        batch_id=batch_id,
        row_in_batch=rib + 1,
        ingest_ts=ts,
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
    identity_rows.extend(materialize_identity_rows(ch_row))
    tag_rows.extend(
        materialize_tag_rows(
            tag_id_strs,
            ch_row,
            assigned_at=ts,
            source="ingest_file",
        )
    )
    return new_rib, accepted + 1, dup, rejected


async def _flush_clickhouse_rows(
    ch: Any,
    ch_rows: list[list[Any]],
    identity_rows: list[list[Any]],
    tag_rows: list[list[Any]],
) -> None:
    await ch.insert("leads", ch_rows, column_names=CH_INSERT_COLUMNS)
    await ch.insert(
        "lead_identities",
        identity_rows,
        column_names=CH_IDENTITY_INSERT_COLUMNS,
    )
    if tag_rows:
        await ch.insert("lead_tags", tag_rows, column_names=CH_TAG_INSERT_COLUMNS)
    ch_rows.clear()
    identity_rows.clear()
    tag_rows.clear()


async def _fail_job(session: Any, job_id: UUID, msg: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state="failed", finished_at=datetime.now(UTC), error=msg)
    )
    await session.commit()
