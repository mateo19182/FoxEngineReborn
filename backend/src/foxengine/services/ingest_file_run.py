"""Background ingest from a file already stored in RustFS (JSONL or CSV)."""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import aioboto3
from sqlalchemy import delete, select, update

from foxengine.clickhouse import get_ch_client
from foxengine.config import get_settings
from foxengine.db.models import Batch, IngestRejection, Job
from foxengine.db.session import get_session_factory
from foxengine.services.deleted_batches import lightweight_delete_batch_rows
from foxengine.services.format_detect import LINE_VALUE_HEADER
from foxengine.services.ingest import resolve_tag_ids
from foxengine.services.ingest_rows import (
    RowOutcome,
    csv_row_to_raw,
    ingest_timestamp,
    json_object_to_raw,
    materialize_lead_row,
)
from foxengine.services.ingest_s3_stream import iter_utf8_lines, read_body_bytes
from foxengine.services.lead_fingerprints import (
    insert_prepared_leads,
    prepare_new_lead_inserts,
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
        await session.execute(delete(IngestRejection).where(IngestRejection.batch_id == batch.id))
        await session.commit()

        tag_ids = await resolve_tag_ids(session, tag_names, owner)
        tag_id_strs = [str(u) for u in tag_ids]
        await session.commit()

    pipeline = _IngestPipeline(
        job_id=job_id,
        batch_id=batch.id,
        tag_id_strs=tag_id_strs,
        column_map_s=column_map_s,
        manual_column_map=manual_column_map,
        default_region_s=default_region_s,
        flush_rows=s.ingest_flush_rows,
        progress_every=s.ingest_progress_every,
        s3_chunk_bytes=s.ingest_s3_read_chunk_bytes,
    )
    ch = await get_ch_client()
    await lightweight_delete_batch_rows(ch, batch.id)

    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        obj = await c.get_object(Bucket=s.s3_bucket_uploads, Key=s3_key)
        body = obj["Body"]
        if fmt == "jsonl":
            ok = await _ingest_jsonl(pipeline, ch, body, job_id, factory)
        elif fmt == "txt":
            ok = await _ingest_txt(pipeline, ch, body, job_id, factory)
        elif fmt == "csv":
            ok = await _ingest_csv(pipeline, ch, body, csv_delim, job_id, factory)
        elif fmt == "combo":
            ok = await _ingest_combo(pipeline, ch, body, job_id, factory)
        else:
            async with factory() as session:
                await _fail_job(session, job_id, f"unsupported format {fmt!r}")
            return
        if not ok:
            return

        if pipeline.pending_rows:
            await pipeline.flush(ch)
        if pipeline.rejections:
            await pipeline.flush_rejections()

    async with factory() as session:
        await session.execute(
            update(Batch)
            .where(Batch.id == batch.id)
            .values(
                accepted_rows=pipeline.accepted,
                rejected_rows=pipeline.rejected,
                duplicate_rows=pipeline.dup,
            )
        )
        await session.commit()
    async with factory() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                state="done",
                finished_at=datetime.now(UTC),
                processed_rows=pipeline.accepted + pipeline.rejected + pipeline.dup,
                checkpoint={
                    **ck,
                    "accepted_rows": pipeline.accepted,
                    "rejected_rows": pipeline.rejected,
                    "duplicate_rows": pipeline.dup,
                },
            )
        )
        await session.commit()


class _IngestPipeline:
    def __init__(
        self,
        *,
        job_id: UUID,
        batch_id: UUID,
        tag_id_strs: list[str],
        column_map_s: dict[str, str],
        manual_column_map: bool,
        default_region_s: str | None,
        flush_rows: int,
        progress_every: int,
        s3_chunk_bytes: int,
    ) -> None:
        self.job_id = job_id
        self.batch_id = batch_id
        self.tag_id_strs = tag_id_strs
        self.column_map_s = column_map_s
        self.manual_column_map = manual_column_map
        self.default_region_s = default_region_s
        self.flush_rows = flush_rows
        self.progress_every = progress_every
        self.s3_chunk_bytes = s3_chunk_bytes

        self.pending_rows: list[tuple[list[Any], str]] = []
        self.rejections: list[tuple[int, str, str]] = []
        self.seen_hashes: set[str] = set()
        self.accepted = 0
        self.rejected = 0
        self.dup = 0
        self.rib = 0
        self.ts = ingest_timestamp()
        self._next_progress_at = progress_every
        self._rejection_flush_rows = min(max(flush_rows, 1), 10_000)

    def processed_total(self) -> int:
        return self.accepted + len(self.pending_rows) + self.rejected + self.dup

    def append_raw(self, raw: dict[str, Any], line_no: int) -> None:
        self.dup, self.rejected = _append_row(
            raw,
            self.batch_id,
            self.dup,
            self.rejected,
            line_no,
            self.seen_hashes,
            self.ts,
            self.default_region_s,
            self.pending_rows,
            self.rejections,
        )

    def ingest_json_object(self, raw_obj: dict[str, Any], line_no: int) -> None:
        if self.column_map_s:
            mapped = json_object_to_raw(
                raw_obj,
                self.column_map_s,
                allow_known_field_fallback=not self.manual_column_map,
            )
        else:
            mapped = raw_obj
        self.append_raw(mapped, line_no)

    async def tick(self, ch: Any) -> None:
        needs_flush = len(self.pending_rows) >= self.flush_rows
        needs_rejection_flush = len(self.rejections) >= self._rejection_flush_rows
        total = self.processed_total()
        needs_progress = total >= self._next_progress_at
        if not needs_flush and not needs_rejection_flush and not needs_progress:
            return
        if needs_flush:
            await self.flush(ch)
        if needs_rejection_flush:
            await self.flush_rejections()
        if needs_progress:
            self._next_progress_at = total + self.progress_every
            await self.report_progress(total)

    async def flush(self, ch: Any) -> None:
        pending = self.pending_rows
        self.pending_rows = []
        prepared = await prepare_new_lead_inserts(
            ch,
            pending,
            batch_id=self.batch_id,
            next_row_in_batch=self.rib,
            tag_id_strs=self.tag_id_strs,
            assigned_at=self.ts,
            tag_source="ingest_file",
        )
        await insert_prepared_leads(ch, prepared)
        self.accepted += len(prepared.ch_rows)
        self.dup += prepared.duplicate_rows
        self.rib = prepared.next_row_in_batch

    async def flush_rejections(self) -> None:
        if not self.rejections:
            return
        rows = self.rejections
        self.rejections = []
        factory = get_session_factory()
        async with factory() as session:
            session.add_all(
                IngestRejection(
                    batch_id=self.batch_id,
                    line_no=line_no,
                    reason=reason,
                    raw_line=raw_line,
                )
                for line_no, reason, raw_line in rows
            )
            await session.commit()

    async def report_progress(self, processed: int) -> None:
        factory = get_session_factory()
        async with factory() as progress_session:
            await progress_session.execute(
                update(Job).where(Job.id == self.job_id).values(processed_rows=processed)
            )
            await progress_session.commit()


async def _ingest_jsonl(
    pipeline: _IngestPipeline,
    ch: Any,
    body: Any,
    job_id: UUID,
    factory: Any,
) -> bool:
    head_chunk = await body.read(4096)
    head = head_chunk.lstrip()
    if head.startswith(b"["):
        blob = await read_body_bytes(
            body,
            chunk_size=pipeline.s3_chunk_bytes,
            initial=head_chunk,
        )
        try:
            parsed = json.loads(blob.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            async with factory() as session:
                await _fail_job(session, job_id, f"invalid json array: {e}")
            return False
        if not isinstance(parsed, list):
            async with factory() as session:
                await _fail_job(session, job_id, "json root must be an array")
            return False
        for i, item in enumerate(parsed):
            line_no = i + 1
            if not isinstance(item, dict):
                pipeline.rejections.append((line_no, "json must be object", str(item)[:8000]))
                pipeline.rejected += 1
                await pipeline.tick(ch)
                continue
            row: dict[str, Any] = item
            pipeline.ingest_json_object(row, line_no)
            await pipeline.tick(ch)
        return True

    line_no = 0
    async for raw_s in iter_utf8_lines(
        body,
        chunk_size=pipeline.s3_chunk_bytes,
        initial=head_chunk,
    ):
        line_no += 1
        raw_s = raw_s.strip()
        if not raw_s or raw_s.startswith("#"):
            continue
        try:
            raw = json.loads(raw_s)
        except json.JSONDecodeError:
            pipeline.rejections.append((line_no, "invalid json", raw_s[:8000]))
            pipeline.rejected += 1
            await pipeline.tick(ch)
            continue
        if not isinstance(raw, dict):
            pipeline.rejections.append((line_no, "json must be object", raw_s[:8000]))
            pipeline.rejected += 1
            await pipeline.tick(ch)
            continue
        pipeline.ingest_json_object(raw, line_no)
        await pipeline.tick(ch)
    return True


async def _ingest_txt(
    pipeline: _IngestPipeline,
    ch: Any,
    body: Any,
    job_id: UUID,
    factory: Any,
) -> bool:
    del job_id, factory
    target_field = pipeline.column_map_s.get(LINE_VALUE_HEADER, "").strip()
    line_no = 0
    async for raw_s in iter_utf8_lines(body, chunk_size=pipeline.s3_chunk_bytes):
        line_no += 1
        raw_s = raw_s.strip()
        if not raw_s or raw_s.startswith("#"):
            continue
        if not target_field:
            pipeline.rejections.append((line_no, "txt line value not mapped", raw_s[:8000]))
            pipeline.rejected += 1
            await pipeline.tick(ch)
            continue
        pipeline.append_raw({target_field: raw_s}, line_no)
        await pipeline.tick(ch)
    return True


async def _ingest_csv(
    pipeline: _IngestPipeline,
    ch: Any,
    body: Any,
    csv_delim: str,
    job_id: UUID,
    factory: Any,
) -> bool:
    line_no = 0
    header: list[str] | None = None
    async for raw_s in iter_utf8_lines(body, chunk_size=pipeline.s3_chunk_bytes):
        line_no += 1
        if not raw_s.strip():
            continue
        row_cells = next(csv.reader([raw_s], delimiter=csv_delim))
        if header is None:
            header = [h.strip() for h in row_cells]
            continue
        data_line_no = line_no
        raw = csv_row_to_raw(
            header,
            row_cells,
            pipeline.column_map_s,
            allow_known_field_fallback=not pipeline.manual_column_map,
        )
        pipeline.append_raw(raw, data_line_no)
        await pipeline.tick(ch)
    if header is None:
        async with factory() as session:
            await _fail_job(session, job_id, "empty csv")
        return False
    return True


async def _ingest_combo(
    pipeline: _IngestPipeline,
    ch: Any,
    body: Any,
    job_id: UUID,
    factory: Any,
) -> bool:
    del job_id, factory
    line_no = 0
    async for raw_s in iter_utf8_lines(body, chunk_size=pipeline.s3_chunk_bytes):
        line_no += 1
        raw_s = raw_s.strip()
        if not raw_s or raw_s.startswith("#"):
            continue
        if ":" not in raw_s:
            pipeline.rejections.append((line_no, "combo line needs colon", raw_s[:8000]))
            pipeline.rejected += 1
            await pipeline.tick(ch)
            continue
        left, right = raw_s.split(":", 1)
        pipeline.append_raw(
            {"email": left.strip(), "password": right.strip()},
            line_no,
        )
        await pipeline.tick(ch)
    return True


def _append_row(
    raw: dict[str, Any],
    batch_id: UUID,
    dup: int,
    rejected: int,
    line_no: int,
    seen_hashes: set[str],
    ts: datetime,
    default_region: str | None,
    pending_rows: list[tuple[list[Any], str]],
    rejections: list[tuple[int, str, str]],
) -> tuple[int, int]:
    outcome, ch_row, row_hash, reason, raw_line = materialize_lead_row(
        raw,
        batch_id=batch_id,
        row_in_batch=0,
        ingest_ts=ts,
        seen_hashes=seen_hashes,
        default_phone_region=default_region,
    )
    if outcome is RowOutcome.rejected:
        rejections.append((line_no, reason or "rejected", (raw_line or str(raw))[:8000]))
        return dup, rejected + 1
    if outcome is RowOutcome.duplicate:
        return dup + 1, rejected
    assert ch_row is not None
    assert row_hash is not None
    pending_rows.append((ch_row, row_hash))
    return dup, rejected


async def _fail_job(session: Any, job_id: UUID, msg: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state="failed", finished_at=datetime.now(UTC), error=msg)
    )
    await session.commit()
