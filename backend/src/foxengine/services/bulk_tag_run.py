"""Bulk-apply tags to leads matched by identity columns from a CSV in RustFS."""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import aioboto3
from sqlalchemy import select, update

from foxengine.clickhouse import get_ch_client
from foxengine.config import get_settings
from foxengine.db.models import Job
from foxengine.db.session import get_session_factory
from foxengine.services.identity import (
    has_any_identity,
    identity_key,
    normalize_email,
    normalize_phone,
)
from foxengine.services.ingest import resolve_tag_ids
from foxengine.services.ingest_rows import CH_TAG_INSERT_COLUMNS

log = logging.getLogger(__name__)


async def run_bulk_tag_job(job_id: UUID) -> None:
    s = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(Job).where(Job.id == job_id))
        job = res.scalar_one_or_none()
        if job is None:
            log.error("bulk_tag job missing: %s", job_id)
            return
        ck = dict(job.checkpoint or {})
        s3_key = ck.get("s3_key")
        tag_names = [str(x) for x in (ck.get("tag_names") or []) if str(x).strip()]
        owner_s = ck.get("owner_user_id")
        if not isinstance(s3_key, str) or not s3_key.strip():
            await _fail(session, job_id, "missing s3_key")
            return
        if not tag_names:
            await _fail(session, job_id, "missing tag_names")
            return
        if not isinstance(owner_s, str):
            await _fail(session, job_id, "missing owner_user_id")
            return
        owner = UUID(owner_s)

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
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        async with factory() as session:
            await _fail(session, job_id, "csv has no header")
        return

    fields_lower = {f.strip().lower(): f for f in reader.fieldnames}

    def pick(row: dict[str, str | None], *names: str) -> str:
        for n in names:
            col = fields_lower.get(n.lower())
            if col and row.get(col):
                return str(row[col]).strip()
        return ""

    keys_from_csv: list[str] = []
    for row in reader:
        email = pick(row, "email", "email_norm")
        phone = pick(row, "phone", "phone_norm", "phone_raw")
        username = pick(row, "username")
        id_card = pick(row, "id_card", "id")
        pn, _ = normalize_phone(phone or None)
        en, _ = normalize_email(email or None)
        u = username.strip()
        ic = id_card.strip()
        if not has_any_identity(pn, en, u, ic):
            continue
        ik = identity_key(pn, en, u, ic)
        if ik:
            keys_from_csv.append(ik)

    unique_keys = list(dict.fromkeys(keys_from_csv))
    ch = await get_ch_client()
    existing: set[str] = set()
    matched_rows: dict[tuple[str, int], datetime] = {}
    chunk_size = 10_000
    for i in range(0, len(unique_keys), chunk_size):
        chunk = unique_keys[i : i + chunk_size]
        q = (
            "SELECT li.identity_value, li.batch_id, li.row_in_batch, l.ingest_ts "
            "FROM lead_identities AS li "
            "INNER JOIN leads AS l USING (batch_id, row_in_batch) "
            "WHERE li.identity_kind = 'identity_key' "
            "AND has({keys:Array(String)}, li.identity_value)"
        )
        qr = await ch.query(q, parameters={"keys": chunk})
        for row in qr.result_rows:
            existing.add(str(row[0]))
            matched_rows[(str(row[1]), int(row[2]))] = row[3]

    assigned_at = datetime.now(UTC).replace(tzinfo=None)
    tag_rows = [
        [str(tag_id), batch_id, row_in_batch, ingest_ts, assigned_at, f"bulk_tag:{job_id}"]
        for (batch_id, row_in_batch), ingest_ts in matched_rows.items()
        for tag_id in tag_ids
    ]
    if tag_rows:
        await ch.insert(
            "lead_tags",
            tag_rows,
            column_names=CH_TAG_INSERT_COLUMNS,
        )

    unmatched_keys = [k for k in unique_keys if k not in existing]
    unmatched_body = ("identity_key\n" + "\n".join(unmatched_keys) + "\n").encode("utf-8")
    ukey = f"exports/{job_id}/unmatched.csv"
    up_session = aioboto3.Session()
    async with up_session.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        await c.put_object(Bucket=s.s3_bucket_exports, Key=ukey, Body=unmatched_body)

    async with factory() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                state="done",
                finished_at=datetime.now(UTC),
                processed_rows=len(unique_keys),
                result_uri=f"s3://{s.s3_bucket_exports}/{ukey}",
                checkpoint={
                    **ck,
                    "matched_rows": len(matched_rows),
                    "unmatched_rows": len(unmatched_keys),
                    "unmatched_key": ukey,
                },
            )
        )
        await session.commit()


async def _fail(session: Any, job_id: UUID, msg: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state="failed", finished_at=datetime.now(UTC), error=msg)
    )
    await session.commit()
